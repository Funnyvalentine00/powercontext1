# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Physical-page Sources captured from one offline PDF document."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING
from urllib.parse import quote

from pydantic import BaseModel, JsonValue
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)

if TYPE_CHECKING:
    from powercontext.builtin.runtime import MemoryEntryRecord, ScopedMemoryApplication

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"

_TERM = re.compile(r"[a-z]+|\d+")
_QUERY_STOPWORDS = frozenset([
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "during",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "more",
    "most",
    "much",
    "no",
    "not",
    "of",
    "on",
    "only",
    "or",
    "other",
    "our",
    "over",
    "please",
    "should",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "this",
    "those",
    "to",
    "under",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
])
_BM25_K1 = 1.2
_BM25_B = 0.3
_PASSAGE_SIZE = 64
_PASSAGE_STRIDE = 32
_PHRASE_WEIGHT = 0.3
_TITLE_WEIGHT = 0.5
_SECTION_PRIOR = 0.3
_SECTION_PRIOR_OVERRIDES: dict[str, float] = {"md&a": 0.1, "front": 0.45, "income": 0.5, "balance": 0.5, "cashflow": 0.5}
_PAGE_COVERAGE_WEIGHT = 0.4
_NEIGHBOR_WEIGHT = 0.5
_SECTION_NEIGHBORS = 1
_FRONT_MATTER_WEIGHT = 0.7
_HEADING_LINES = 3
_HEADING_MIN_LENGTH = 8
_BOILERPLATE_MIN_PAGES = 3
_BOILERPLATE_SHARE = 0.25
_MAX_ERROR_DETAIL = 200
_PDF_SOURCE_ID = re.compile(r"pdf:(?P<document>[^:]*):(?P<digest>[0-9a-f]{64}):(?P<page>\d+)\Z")
_DOCUMENT_SEGMENT = re.compile(r"(?:\d{4}|\d+[kq])\Z", re.IGNORECASE)
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

_SECTION_HEADINGS: dict[str, tuple[str, ...]] = {
    "income": (
        "consolidated statements of income",
        "consolidated statement of income",
        "statements of operations",
        "statement of operations",
        "consolidated statements of operations",
        "statement of earnings",
        "statements of earnings",
    ),
    "balance": (
        "consolidated balance sheets",
        "consolidated balance sheet",
        "balance sheet",
        "balance sheets",
        "statements of financial position",
        "statement of financial position",
    ),
    "cashflow": (
        "consolidated statements of cash flows",
        "consolidated statement of cash flows",
        "statements of cash flows",
        "statement of cash flows",
    ),
    "md&a": (
        "results of operations",
        "management's discussion and analysis",
        "md&a",
        "liquidity and capital resources",
        "performance by business segment",
    ),
    "business": (
        "item 1. business",
        "item 1 business",
        "description of business",
        "products and services",
        "geographic operations",
        "geographic",
    ),
    "legal": ("legal proceedings", "commitments and contingencies", "contingencies", "litigation"),
    "acquisition": (
        "acquisitions and divestitures",
        "acquisitions",
        "business combinations",
        "divestiture",
        "divestitures",
    ),
    "tax": ("income taxes", "effective tax rate"),
    "segment": ("business segment", "segment information", "summary of business segment data", "segments"),
    "restructuring": ("restructuring",),
    "debt": ("long-term debt", "debt", "borrowings", "notes payable"),
    "customer": ("customers", "concentration", "major customers"),
}
_SECTION_TERMS: dict[str, tuple[str, ...]] = {
    "income": (
        "income statement",
        "income statements",
        "revenue",
        "revenues",
        "margin",
        "profit",
        "profitability",
        "sales",
        "operating income",
        "operating margin",
        "gross margin",
        "net income",
        "earnings",
        "eps",
        "earnings per share",
        "cost",
        "costs",
        "expense",
        "expenses",
        "ebitda",
        "depreciation",
        "amortization",
        "income",
        "loss",
        "impairment",
        "capital intensive",
        "capital-intensive",
        "asset intensive",
    ),
    "balance": (
        "balance sheet",
        "balance sheets",
        "liability",
        "liabilities",
        "asset",
        "assets",
        "quick ratio",
        "current ratio",
        "working capital",
        "liquidity",
        "stockholders",
        "shareholders",
        "equity",
        "inventory",
        "receivables",
        "goodwill",
        "capital intensive",
        "capital-intensive",
        "asset intensive",
    ),
    "cashflow": (
        "cash flow",
        "cash flows",
        "capital expenditure",
        "capital expenditures",
        "capex",
        "operating activities",
        "investing activities",
        "financing activities",
        "free cash flow",
        "capital intensive",
        "capital-intensive",
        "asset intensive",
    ),
    "md&a": (
        "drove",
        "drive",
        "change",
        "changed",
        "increase",
        "decrease",
        "decline",
        "improve",
        "improving",
        "declined",
        "growth",
        "grew",
        "compared",
        "comparison",
        "trend",
        "deteriorat",
        "factor",
    ),
    "business": (
        "industry",
        "industries",
        "products",
        "services",
        "product",
        "service",
        "customer",
        "customers",
        "geograph",
        "geographies",
        "geography",
        "geographic",
        "region",
        "regions",
        "worldwide",
        "segment",
        "segments",
        "operate",
        "operates",
        "operations",
        "business",
    ),
    "legal": (
        "legal",
        "litigation",
        "lawsuit",
        "lawsuits",
        "proceeding",
        "proceedings",
        "claim",
        "claims",
        "battle",
        "battles",
        "contingenc",
        "regulatory",
        "investigation",
        "investigations",
        "dispute",
        "disputes",
    ),
    "acquisition": (
        "acquisition",
        "acquisitions",
        "acquire",
        "acquired",
        "m&a",
        "merger",
        "mergers",
        "divestiture",
        "divest",
        "divested",
    ),
    "tax": ("tax", "taxes", "tax rate", "effective tax rate"),
    "segment": ("segment", "segments", "business unit", "business units"),
    "restructuring": ("restructuring", "restructure", "severance"),
    "debt": ("debt", "borrowings", "credit facility", "leverage", "maturities"),
    "customer": ("customer", "customers", "concentration", "distributor", "distributors", "retailer", "retailers"),
}
_SECTION_ANYWHERE = frozenset({"legal", "acquisition", "tax", "restructuring", "segment", "customer", "debt"})
_PRODUCT_TERMS = ("product", "products", "service", "services", "category", "categories")


class PDFDocumentInput(BaseModel):
    """Complete offline PDF bytes addressed by a caller-stable document identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical PDF page with its document digest and 1-based page position."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """Captured Source holding exactly one physical PDF page."""

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSourceAdapter:
    """Resolve and read the page-level Sources of one PDF document."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one PDF page as the standard textual evidence object."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        metadata: dict[str, JsonValue] = {
            "document_id": source.document_id,
            "document_sha256": source.document_sha256,
            "page_number": source.page_number,
        }
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata=metadata,
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    version=PDF_PAGE_SOURCE_VERSION,
    projections=(PDFPageTextEvidenceProjection(),),
)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse and validate every physical page before returning any page."""

    _validate_document_id(value.document_id)
    if not isinstance(value.content, bytes) or not value.content:
        raise ValueError("PDF content must be a non-empty byte string")
    digest = hashlib.sha256(value.content).hexdigest()
    texts = _extract_page_texts(value.content)
    return tuple(
        PDFPageInput(
            document_id=value.document_id,
            document_sha256=digest,
            page_number=page_number,
            text=text,
        )
        for page_number, text in enumerate(texts, start=1)
    )


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the delimiter-safe identity of one physical page Source."""

    _validate_document_id(document_id)
    if not isinstance(document_sha256, str) or not document_sha256.strip():
        raise ValueError("document_sha256 must be a non-empty string")
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be a positive integer")
    source_id = (
        f"pdf:{quote(document_id, safe='')}:{quote(document_sha256, safe='')}:{page_number}"
    )
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"PDF page source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


async def search_pdf_pages(
    memory: ScopedMemoryApplication,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` exact page citations ranked against ``question``."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not isinstance(question, str) or not question.strip():
        return ()
    entries = await _page_entries(memory)
    if not entries:
        return ()
    ranking = _rank_pages(entries, question)
    return tuple(entries[index].citation for index in ranking[:limit])


async def _page_entries(memory: ScopedMemoryApplication) -> tuple[MemoryEntryRecord, ...]:
    """Load the searchable page entries of the scoped Memory in physical page order."""

    page = await memory.list()
    if page.memory_ref is None:
        return ()
    records = [(_page_position(record), record) for record in page.entries if record.entry.text.strip()]
    records.sort(key=lambda item: item[0])
    return tuple(record for _position, record in records)


def _page_position(record: MemoryEntryRecord) -> tuple[str, int]:
    """Recover the document and physical page a stored entry was captured from."""

    for reference in record.entry.sources:
        if reference.source_type != PDF_PAGE_SOURCE_NAME:
            continue
        match = _PDF_SOURCE_ID.fullmatch(reference.source_id)
        if match is not None:
            return match.group("document"), int(match.group("page"))
    return "", 0


def _rank_pages(entries: Sequence[MemoryEntryRecord], question: str) -> tuple[int, ...]:
    """Rank pages by the best matching passage plus their financial section."""

    query_terms = _query_terms(question)
    if not query_terms:
        return ()
    cleaned = _clean_texts(tuple(record.entry.text for record in entries))
    bodies = tuple(tuple(_terms(text)) for text in cleaned)
    headings = tuple(_heading_terms(text) for text in cleaned)
    documents = tuple(_page_position(record)[0] for record in entries)
    labels = _page_sections(cleaned, documents)

    unique_terms = tuple(dict.fromkeys(query_terms))
    frequency = Counter()
    for body in bodies:
        frequency.update(set(body))
    total = len(bodies)
    inverse_frequency = {
        term: math.log(1.0 + (total - count + 0.5) / (count + 0.5)) for term, count in frequency.items()
    }
    query_weight = {term: inverse_frequency.get(term, math.log(1.0 + (total + 0.5) / 0.5)) for term in unique_terms}
    weight_mass = sum(query_weight.values()) or 1.0
    adjacent = frozenset(zip(query_terms, query_terms[1:]))
    requested = _requested_sections(question)
    document_terms: dict[str, set[str]] = {}
    for document, body in zip(documents, bodies, strict=True):
        document_terms.setdefault(document, set()).update(body)
    document_coverage = {
        document: sum(weight for term, weight in query_weight.items() if term in terms) / weight_mass
        for document, terms in document_terms.items()
    }
    mentioned = frozenset(document for document in document_terms if _document_mentioned(question, document))
    document_presence: Counter[str] = Counter()
    for terms in document_terms.values():
        document_presence.update(terms)
    exclusive: dict[str, float] = {}
    for document, terms in document_terms.items():
        mass = sum(
            weight
            for term, weight in query_weight.items()
            if term in terms and document_presence[term] == 1
        )
        if mass:
            exclusive[document] = mass
    if mentioned:
        selected = mentioned
    elif exclusive:
        selected = frozenset({max(exclusive, key=lambda document: exclusive[document])})
    else:
        selected = frozenset(
            {max(document_coverage, key=lambda document: document_coverage[document], default="")}
        )

    scored: list[tuple[float, int]] = []
    for index, body in enumerate(bodies):
        if documents[index] not in selected:
            continue
        score = _passage_score(body, query_weight, adjacent)
        body_terms = set(body)
        page_coverage = sum(query_weight[term] for term in unique_terms if term in body_terms) / weight_mass
        score += _PAGE_COVERAGE_WEIGHT * page_coverage * weight_mass
        if headings[index]:
            heading_counts = Counter(headings[index])
            heading_coverage = sum(query_weight[term] for term in unique_terms if heading_counts[term]) / weight_mass
            score += _TITLE_WEIGHT * heading_coverage * weight_mass
        if requested:
            match = max(
                (
                    _SECTION_PRIOR_OVERRIDES.get(name, _SECTION_PRIOR) * weight
                    for name, weight in labels[index].items()
                    if name in requested
                ),
                default=0.0,
            )
            score += weight_mass * match
        scored.append((score, index))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(index for _score, index in scored)


def _passage_score(
    body: tuple[str, ...],
    query_weight: dict[str, float],
    adjacent: frozenset[tuple[str, str]],
) -> float:
    """Return the strongest windowed match, so short passages are not diluted."""

    best = 0.0
    passages = _passages(body)
    average = (sum(len(passage) for passage in passages) / len(passages)) or 1.0
    for passage in passages:
        counts = Counter(passage)
        length = len(passage)
        score = 0.0
        for term, weight in query_weight.items():
            hits = counts.get(term, 0)
            if not hits:
                continue
            saturation = hits + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * length / average)
            score += weight * hits * (_BM25_K1 + 1.0) / saturation
        if adjacent:
            score += _PHRASE_WEIGHT * sum(1 for pair in zip(passage, passage[1:]) if pair in adjacent)
        if score > best:
            best = score
    return best


def _passages(body: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if len(body) <= _PASSAGE_SIZE:
        return (body,)
    return tuple(
        body[start : start + _PASSAGE_SIZE] for start in range(0, len(body) - _PASSAGE_SIZE + 1, _PASSAGE_STRIDE)
    )


def _clean_texts(texts: tuple[str, ...]) -> tuple[str, ...]:
    """Drop lines repeated across pages so running headers cannot match queries."""

    occurrences = Counter()
    for text in texts:
        occurrences.update({" ".join(line.casefold().split()) for line in text.splitlines()})
    threshold = max(_BOILERPLATE_MIN_PAGES, len(texts) * _BOILERPLATE_SHARE)
    repeated = {line for line, count in occurrences.items() if count > threshold}
    return tuple(
        "\n".join(line for line in text.splitlines() if " ".join(line.casefold().split()) not in repeated)
        for text in texts
    )


def _heading_lines(text: str) -> list[str]:
    """Take the opening title lines, ignoring fragmented running headers."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [line for line in lines if len(line) > _HEADING_MIN_LENGTH][:_HEADING_LINES]


def _heading_terms(text: str) -> tuple[str, ...]:
    return tuple(_terms("\n".join(_heading_lines(text))))


def _page_sections(
    texts: tuple[str, ...],
    documents: tuple[str, ...],
) -> tuple[dict[str, float], ...]:
    """Label each page by the financial section it opens or continues."""

    headings = [_heading_text(text) for text in texts]
    front_ends: dict[str, int] = {}
    for index, (document, heading) in enumerate(zip(documents, headings, strict=True)):
        if "item 7" in heading or "item 8" in heading:
            front_ends.setdefault(document, index)
    labels: list[dict[str, float]] = []
    for index, (document, text, heading) in enumerate(zip(documents, texts, headings, strict=True)):
        whole = " ".join(text.casefold().split())
        found: dict[str, float] = {}
        for name, patterns in _SECTION_HEADINGS.items():
            haystack = whole if name in _SECTION_ANYWHERE else heading
            if any(pattern in haystack for pattern in patterns):
                found[name] = 1.0
        if index < front_ends.get(document, len(texts)):
            found.setdefault("front", _FRONT_MATTER_WEIGHT)
        labels.append(found)
    propagated: list[dict[str, float]] = []
    for index, found in enumerate(labels):
        weights = dict(found)
        for neighbour in range(max(0, index - _SECTION_NEIGHBORS), min(len(labels), index + _SECTION_NEIGHBORS + 1)):
            if neighbour == index:
                continue
            for name in labels[neighbour]:
                weights.setdefault(name, _NEIGHBOR_WEIGHT)
        propagated.append(weights)
    return tuple(propagated)


def _heading_text(text: str) -> str:
    return " ".join(_heading_lines(text)).casefold()


def _document_mentioned(question: str, document: str) -> bool:
    """Return whether the question names the company a document belongs to."""

    company = _document_company(document)
    if not company or (len(company) < 3 and not any(char.isdigit() for char in company)):
        return False
    return company in _question_phrases(question)


def _document_company(document: str) -> str:
    """Reduce a document id to the company segment that precedes its filing period."""

    parts = [part for part in document.split("_") if part]
    for index, part in enumerate(parts):
        if part.isdigit() or _DOCUMENT_SEGMENT.fullmatch(part) or re.search(r"\d{4}", part):
            parts = parts[:index]
            break
    return _NON_ALPHANUMERIC.sub("", "_".join(parts).casefold())


def _question_phrases(question: str) -> frozenset[str]:
    """Collect the question's words and short adjacent word joins, without spaces."""

    tokens = [token for token in _NON_ALPHANUMERIC.split(question.casefold()) if token]
    phrases = set(tokens)
    for width in (2, 3):
        for start in range(len(tokens) - width + 1):
            phrases.add("".join(tokens[start : start + width]))
    return frozenset(phrases)


def _requested_sections(question: str) -> frozenset[str]:
    """Map metric vocabulary in a question to the sections that report it."""

    folded = question.casefold()
    requested: set[str] = set()
    for name, triggers in _SECTION_TERMS.items():
        if any(_mentions(folded, trigger) for trigger in triggers):
            requested.add(name)
    if "tax rate" in folded:
        requested.add("income")
    if any(_mentions(folded, trigger) for trigger in _PRODUCT_TERMS):
        requested.update(("segment", "business"))
    if "business" in requested:
        requested.add("front")
    return frozenset(requested)


def _mentions(folded: str, trigger: str) -> bool:
    if trigger.isalnum() and len(trigger) <= 3:
        return re.search(rf"\b{re.escape(trigger)}\b", folded) is not None
    return trigger in folded


def _query_terms(question: str) -> list[str]:
    return [
        term
        for term in _terms(question)
        if term not in _QUERY_STOPWORDS and (len(term) > 1 or term.isdigit())
    ]


def _terms(text: str) -> list[str]:
    return [_stem(term) for term in _TERM.findall(text.casefold())]


def _stem(term: str) -> str:
    """Fold common English suffixes and long-word endings so related forms meet."""

    if term.endswith("ies") and len(term) > 4:
        return f"{term[:-3]}y"
    if term.endswith(("ses", "xes", "zes", "ches", "shes")) and len(term) > 4:
        return term[:-2]
    if term.endswith("s") and len(term) > 3 and not term.endswith(("ss", "us", "is")):
        term = term[:-1]
    if term.isalpha() and len(term) > 6:
        return term[:6]
    return term


def _extract_page_texts(content: bytes) -> tuple[str, ...]:
    """Extract every physical page in order, failing before any page is returned."""

    try:
        reader = PdfReader(io.BytesIO(content))
        pages = tuple(reader.pages)
    except Exception as error:
        raise ValueError(f"PDF document must be a readable PDF file: {_detail(error)}") from error
    if not pages:
        raise ValueError("PDF document must contain at least one page")
    texts: list[str] = []
    for page in pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception as error:
            raise ValueError(f"PDF page text must be extractable: {_detail(error)}") from error
    return tuple(texts)


def _detail(error: Exception) -> str:
    message = " ".join(str(error).split())
    return message[:_MAX_ERROR_DETAIL]


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty, non-blank string")


__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDF_PAGE_SOURCE_VERSION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
