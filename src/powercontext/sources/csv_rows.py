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

"""Row-level Sources captured from one offline CSV document."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)

CSV_ROW_SOURCE_NAME = "csv-row"


class CSVDocumentInput(BaseModel):
    """Complete offline CSV bytes addressed by a caller-stable document identity."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed CSV record with its header order preserved."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """Captured Source holding exactly one CSV row."""

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSourceAdapter:
    """Resolve and read the row-level Sources of one CSV document."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        _validate_primary_key(value.primary_key)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Expose one CSV row as the standard textual evidence object."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row: dict[str, JsonValue] = {
            column: value for column, value in zip(source.columns, source.values, strict=True)
        }
        metadata: dict[str, JsonValue] = {
            "document_id": source.document_id,
            "primary_key": source.primary_key,
            "primary_key_value": source.primary_key_value,
            "columns": list(source.columns),
            "row": row,
        }
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata=metadata,
        )


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    CSV_ROW_SOURCE_ADAPTER,
    projections=(CSVRowTextEvidenceProjection(),),
)


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate every record before returning any row."""

    _validate_document_id(value.document_id)
    _validate_primary_key(value.primary_key)
    records = _read_records(value.content)
    if not records:
        raise ValueError("CSV document must contain a header record")
    columns = tuple(records[0])
    _validate_header(columns, value.primary_key)
    primary_key_index = columns.index(value.primary_key)

    rows: list[CSVRowInput] = []
    seen: set[str] = set()
    for record in records[1:]:
        if not record:
            continue
        if len(record) != len(columns):
            raise ValueError("CSV record width does not match the header width")
        primary_key_value = record[primary_key_index]
        _validate_primary_key_value(primary_key_value)
        if primary_key_value in seen:
            raise ValueError("CSV primary key values must be unique within a document")
        seen.add(primary_key_value)
        csv_row_source_id(value.document_id, primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=primary_key_value,
                columns=columns,
                values=tuple(record),
            )
        )
    return tuple(rows)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the delimiter-safe identity of one row Source."""

    _validate_document_id(document_id)
    _validate_primary_key_value(primary_key_value)
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"CSV row source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def _read_records(content: bytes) -> list[list[str]]:
    if not isinstance(content, bytes):
        raise ValueError("CSV content must be bytes")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be strictly UTF-8 encoded") from error
    try:
        return list(csv.reader(io.StringIO(decoded, newline=""), strict=True))
    except csv.Error as error:
        raise ValueError("CSV content is malformed") from error


def _validate_header(columns: tuple[str, ...], primary_key: str) -> None:
    for column in columns:
        if not column or not column.strip():
            raise ValueError("CSV header fields must be non-empty and non-blank")
    if len(set(columns)) != len(columns):
        raise ValueError("CSV header fields must be unique")
    if primary_key not in columns:
        raise ValueError("CSV primary key must exactly match one header field")


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id must be a non-empty string")
    if document_id != document_id.strip():
        raise ValueError("document_id must not contain leading or trailing whitespace")


def _validate_primary_key(primary_key: str) -> None:
    if not isinstance(primary_key, str) or not primary_key:
        raise ValueError("primary_key must be a non-empty string")


def _validate_primary_key_value(primary_key_value: str) -> None:
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        raise ValueError("CSV primary key values must not be empty or blank")


__all__ = [
    "CSV_ROW_SOURCE_ADAPTER",
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowSourceAdapter",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]
