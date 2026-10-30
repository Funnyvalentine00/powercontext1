"""证据边界：子问题拆分、证据选择与缺口判定。

本项目「可核验」的核心在这里：结论只能来自证据块，覆盖不足必须如实标成缺口。
接口已定好，阈值与判定规则见 docs/DESIGN.md 任务 3。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import textutil

MIN_SCORE = 0.30
MIN_EVIDENCE = 2
MIN_DOCUMENTS = 2
TOP_K_PER_ASPECT = 4

_ASPECT_SPLIT = re.compile(r"[，；。？！]+")


@dataclass
class EvidenceItem:
    ref: str
    chunk_id: str
    doc_id: str
    doc_title: str
    seq: int
    text: str
    sha256: str
    score: float

    def as_mapping(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "seq": self.seq,
            "sha256": self.sha256,
            "score": self.score,
        }


@dataclass
class AspectResult:
    """一个子问题的检索结果。

    status 取值必须限定为：supported / insufficient / single_doc / missing。
    """

    aspect: str
    status: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)

    @property
    def documents(self) -> list[str]:
        return list(dict.fromkeys(item.doc_id for item in self.evidence))


@dataclass
class Gap:
    aspect: str
    kind: str
    detail: str
    missing_terms: list[str] = field(default_factory=list)

    def as_mapping(self) -> dict[str, object]:
        return {
            "aspect": self.aspect,
            "kind": self.kind,
            "detail": self.detail,
            "missing_terms": self.missing_terms,
        }


class EvidenceBook:
    """全局证据编号簿：同一个 chunk 在报告里始终使用同一个 [En] 编号。"""

    def __init__(self) -> None:
        self._order: list[EvidenceItem] = []
        # chunk_id -> 已登记证据，保证同一块跨子问题复用同一编号。
        self._index: dict[str, EvidenceItem] = {}

    def register(self, chunk: dict[str, object], score: float) -> EvidenceItem:
        """已存在的 chunk 复用编号并更新最高分，否则追加 En。"""
        chunk_id = str(chunk["chunk_id"])
        existing = self._index.get(chunk_id)
        if existing is not None:
            if score > existing.score:
                existing.score = score
            return existing

        item = EvidenceItem(
            ref=f"E{len(self._order) + 1}",
            chunk_id=chunk_id,
            doc_id=str(chunk["doc_id"]),
            doc_title=str(chunk["doc_title"]),
            seq=int(chunk["seq"]),
            text=str(chunk["text"]),
            sha256=str(chunk["sha256"]),
            score=float(score),
        )
        self._order.append(item)
        self._index[chunk_id] = item
        return item

    @property
    def items(self) -> list[EvidenceItem]:
        return list(self._order)


def split_aspects(question: str, aspects: list[str] | None = None) -> list[str]:
    """优先用显式 aspects；否则按中文标点拆分，拆不出就整体作为一个子问题。"""
    if aspects:
        explicit = [aspect.strip() for aspect in aspects if aspect and aspect.strip()]
        if explicit:
            return explicit
    text = question.strip()
    if not text:
        return []
    parts = [part.strip() for part in _ASPECT_SPLIT.split(text) if part.strip()]
    return parts or [text]


def select_for_aspect(
    aspect: str,
    candidates: list[dict[str, object]],
    book: EvidenceBook,
) -> AspectResult:
    """对每个子问题打分、取前 K 条证据，并判定 status。"""
    aspect_tokens = textutil.tokens(aspect)
    corpus_tokens: set[str] = set()
    scored: list[tuple[float, dict[str, object]]] = []
    for candidate in candidates:
        text = str(candidate["text"])
        corpus_tokens |= textutil.tokens(text)
        value = textutil.score(aspect_tokens, text)
        if value >= MIN_SCORE:
            scored.append((value, candidate))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1]["chunk_id"])))

    evidence = [book.register(candidate, value) for value, candidate in scored[:TOP_K_PER_ASPECT]]
    documents = {item.doc_id for item in evidence}
    if not evidence:
        status = "missing"
    elif len(evidence) < MIN_EVIDENCE:
        status = "insufficient"
    elif len(documents) < MIN_DOCUMENTS:
        status = "single_doc"
    else:
        status = "supported"

    # 候选块来自查询词的 LIKE 检索：在这些块里都没出现的词，即语料未覆盖的词。
    missing_terms = sorted(token for token in aspect_tokens if token not in corpus_tokens)
    return AspectResult(aspect=aspect, status=status, evidence=evidence, missing_terms=missing_terms)


def detect_gaps(results: list[AspectResult]) -> list[Gap]:
    """把非 supported 的子问题转成缺口，缺口类型取 missing/insufficient/single_doc。"""
    gaps: list[Gap] = []
    for result in results:
        if result.status == "supported":
            continue
        if result.status == "missing":
            detail = f"没有匹配分 ≥ {MIN_SCORE:.2f} 的证据"
        elif result.status == "insufficient":
            detail = f"仅 {len(result.evidence)} 条证据，少于 {MIN_EVIDENCE} 条"
        else:
            detail = f"证据来自 {len(result.documents)} 篇文献，少于 {MIN_DOCUMENTS} 篇"
        gaps.append(
            Gap(
                aspect=result.aspect,
                kind=result.status,
                detail=detail,
                missing_terms=list(result.missing_terms),
            )
        )
    return gaps


def coverage_ratio(results: list[AspectResult]) -> float:
    """supported 子问题占比，保留 4 位小数。"""
    if not results:
        return 0.0
    supported = sum(1 for result in results if result.status == "supported")
    return round(supported / len(results), 4)
