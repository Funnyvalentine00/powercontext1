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

"""Pi session branch history captured as one immutable Source per visible event."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import rfc8785
from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_VERSION = 3
PI_CHECKPOINT_VERSION = 1
_SESSION_RECORD_TYPE = "session"
_MISSING_IDENTIFIER = "unknown"


class PiSessionInput(BaseModel):
    """Complete offline Pi session bytes and the branch leaf to follow."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch with its complete input record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured Source holding exactly one Pi session event."""

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSourceAdapter:
    """Resolve and read the event-level Sources of one Pi session branch."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one Pi session event as the standard textual evidence object."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        metadata: dict[str, JsonValue] = {
            "session_id": source.session_id,
            "event_id": source.event_id,
            "parent_id": source.parent_id,
            "event_type": source.event_type,
            "role": source.role,
        }
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata=metadata,
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    projections=(PiEventTextEvidenceProjection(),),
)


class _PiSession:
    """One validated session archive with the events of the selected branch."""

    def __init__(
        self,
        session_id: str,
        nodes: dict[str, dict[str, JsonValue]],
        events: tuple[PiEventInput, ...],
    ) -> None:
        self.session_id = session_id
        self.nodes = nodes
        self.events = events


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse and validate the selected branch before returning any event."""

    return _parse_session(value).events


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the delimiter-safe identity of one event Source."""

    for field, part in (("session_id", session_id), ("event_id", event_id)):
        if not isinstance(part, str) or not part:
            raise ValueError(f"{field} must be a non-empty string")
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"Pi event source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def _parse_session(value: PiSessionInput) -> _PiSession:
    records = _read_records(value.content)
    session_id = records[0]["id"]
    nodes = _index_nodes(records[1:])
    leaf_id = value.leaf_id
    if leaf_id is None and nodes:
        leaf_id = next(reversed(nodes))
    if leaf_id is None:
        return _PiSession(session_id, nodes, ())
    if leaf_id not in nodes:
        raise ValueError("Pi session leaf does not identify a record in this session")
    events = tuple(
        event for event in (_parse_event(session_id, node) for node in _ancestor_chain(nodes, leaf_id)) if event
    )
    return _PiSession(session_id, nodes, events)


def _read_records(content: bytes) -> tuple[dict[str, JsonValue], ...]:
    if not isinstance(content, bytes):
        raise ValueError("Pi session content must be bytes")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be strictly UTF-8 encoded") from error
    records: list[dict[str, JsonValue]] = []
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi session content must be newline-delimited JSON") from error
        if not isinstance(record, dict):
            raise ValueError("Pi session records must be JSON objects")
        records.append(record)
    if not records or records[0].get("type") != _SESSION_RECORD_TYPE:
        raise ValueError("Pi session content must start with a session header")
    version = records[0].get("version")
    if isinstance(version, bool) or version != PI_SESSION_VERSION:
        raise ValueError(f"Pi session header must declare version {PI_SESSION_VERSION}")
    session_id = records[0].get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Pi session header must declare a non-empty id")
    return tuple(records)


def _index_nodes(records: tuple[dict[str, JsonValue], ...]) -> dict[str, dict[str, JsonValue]]:
    nodes: dict[str, dict[str, JsonValue]] = {}
    for record in records:
        node_id = record.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("Pi session records must declare a non-empty id")
        if node_id in nodes:
            raise ValueError("Pi session record ids must be unique")
        parent_id = record.get("parentId")
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in nodes):
            raise ValueError("Pi session parent must be empty or reference an earlier record")
        nodes[node_id] = record
    return nodes


def _ancestor_chain(nodes: dict[str, dict[str, JsonValue]], leaf_id: str) -> tuple[dict[str, JsonValue], ...]:
    chain: list[dict[str, JsonValue]] = []
    cursor: str | None = leaf_id
    while cursor is not None:
        node = nodes[cursor]
        chain.append(node)
        parent_id = node.get("parentId")
        cursor = parent_id if isinstance(parent_id, str) else None
    chain.reverse()
    return tuple(chain)


def _parse_event(session_id: str, node: dict[str, JsonValue]) -> PiEventInput | None:
    event_type = node.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None
    if event_type == "message":
        visible = _message_body(node)
    elif event_type == "custom_message":
        visible = ("custom", _text_of(node.get("content")))
    elif event_type in {"compaction", "branch_summary"}:
        summary = node.get("summary")
        visible = (event_type, summary if isinstance(summary, str) else "")
    else:
        return None
    if visible is None or not visible[1]:
        return None
    role, body = visible
    parent_id = node.get("parentId")
    return PiEventInput(
        session_id=session_id,
        event_id=node["id"],
        parent_id=parent_id if isinstance(parent_id, str) else None,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=node,
    )


def _message_body(node: dict[str, JsonValue]) -> tuple[str, str] | None:
    message = node.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    if not isinstance(role, str) or not role:
        return None
    if role == "toolResult":
        header = f"[tool_result {_identifier(message.get('toolName'))} {_identifier(message.get('toolCallId'))}]"
        text = _text_of(message.get("content"))
        return role, f"{header} {text}" if text else header
    if role == "bashExecution":
        command = message.get("command")
        output = message.get("output")
        parts = [f"$ {command}"] if isinstance(command, str) and command else []
        if isinstance(output, str) and output:
            parts.append(output)
        return role, "\n".join(parts)
    return role, _text_of(message.get("content"))


def _text_of(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "toolCall":
            name = _identifier(block.get("name"))
            call_id = _identifier(block.get("id"))
            parts.append(f"[tool_call {name} {call_id}] {_canonical_arguments(block.get('arguments'))}")
    return "\n".join(parts)


def _canonical_arguments(value: JsonValue) -> str:
    return json.dumps({} if value is None else value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identifier(value: JsonValue) -> str:
    return value if isinstance(value, str) and value else _MISSING_IDENTIFIER


class PiSessionConnector:
    """Import one selected Pi branch incrementally behind a durable checkpoint."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        archive = _parse_session(PiSessionInput(content=self._content(), leaf_id=self.leaf_id))
        imported = _imported_events(session.checkpoint)
        if imported is not None and imported[0] != archive.session_id:
            raise ValueError("Pi session id does not match the committed checkpoint")
        known = {} if imported is None else imported[1]
        for event_id, digest in known.items():
            record = archive.nodes.get(event_id)
            if record is not None and digest != _record_digest(record):
                raise ValueError(f"Pi event {event_id!r} was rewritten after it was imported")
        events = archive.events
        checkpoint = dict(known)
        for event in events:
            if event.event_id in known:
                continue
            outcome = await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            if outcome.status is ConnectorSubmissionStatus.ACCEPTED:
                checkpoint[event.event_id] = _record_digest(event.record)
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"version": PI_CHECKPOINT_VERSION, "session_id": archive.session_id, "events": checkpoint},
        )

    def _content(self) -> bytes:
        try:
            return self.path.read_bytes()
        except OSError as error:
            raise ValueError("Pi session file must be readable") from error


def _imported_events(checkpoint: JsonValue | None) -> tuple[str, dict[str, str]] | None:
    if checkpoint is None:
        return None
    if not isinstance(checkpoint, dict) or checkpoint.get("version") != PI_CHECKPOINT_VERSION:
        raise ValueError("Pi checkpoint must be a versioned session checkpoint")
    session_id = checkpoint.get("session_id")
    events = checkpoint.get("events")
    if not isinstance(session_id, str) or not session_id or not isinstance(events, dict):
        raise ValueError("Pi checkpoint must declare a session id and its imported events")
    imported: dict[str, str] = {}
    for event_id, digest in events.items():
        if not isinstance(digest, str):
            raise ValueError("Pi checkpoint must store one record digest per imported event")
        imported[event_id] = digest
    return session_id, imported


def _record_digest(record: dict[str, JsonValue]) -> str:
    return f"sha256:{hashlib.sha256(rfc8785.dumps(record)).hexdigest()}"


__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
