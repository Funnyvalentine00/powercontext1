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

"""Versioned Context Packs and prefix-reuse deltas for prepared context transfer.

A Context Pack is the prepared context split into deterministic, UTF-8-safe byte chunks
with a content-addressed digest. A delta reuses a prefix of a pack the receiver already
holds and appends the target's remaining chunks, so only the changed tail crosses the wire.
Both wire forms are self-describing JSON: every field, the digest and the byte count are
validated on decode, and a receiver rebuilds the target pack from serialized data alone.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from powercontext.errors import PowerContextError

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512
_DIGEST_PREFIX = "sha256:"
_HEX_DIGITS = frozenset("0123456789abcdef")
_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(PowerContextError, ValueError):
    """Raised when a Context Pack or a Context Pack delta violates the wire protocol."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete prepared context as ordered, validated byte chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: Iterable[bytes]) -> ContextPack:
        """Build a pack from chunks, deriving its digest and exact wire byte count."""

        chunks = _validated_items(items)
        unsigned = _unsigned_pack(chunks)
        digest = _digest_of(unsigned)
        payload = {**unsigned, "digest": digest}
        byte_count = _stable_byte_count(payload)
        return cls(items=chunks, digest=digest, byte_count=byte_count)

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Split content into deterministic, valid UTF-8 chunks of at most ``chunk_bytes``."""

        return cls.build(_chunk_text(content, chunk_bytes))

    def to_bytes(self) -> bytes:
        """Serialize to canonical JSON, including the digest and byte count."""

        return _canonical(
            {
                "schema": PACK_SCHEMA,
                "items": _encode_items(self.items),
                "digest": self.digest,
                "byte_count": self.byte_count,
            }
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> ContextPack:
        """Decode and fully verify a serialized pack."""

        document = _decode_document(payload, _PACK_FIELDS, "pack")
        if document["schema"] != PACK_SCHEMA:
            raise ContextPackError("context pack schema is not recognized")
        chunks = _decode_items(document["items"])
        digest = _validated_digest(document["digest"], "digest")
        byte_count = _validated_count(document["byte_count"], "byte_count")
        expected = _digest_of(_unsigned_pack(chunks))
        if digest != expected:
            raise ContextPackError("context pack digest does not match its items")
        if byte_count != len(payload):
            raise ContextPackError("context pack byte_count does not match its wire bytes")
        return cls(items=chunks, digest=digest, byte_count=byte_count)

    def content(self) -> str:
        """Reassemble the original content from the chunks."""

        return b"".join(self.items).decode("utf-8")


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A receiver-held pack prefix plus the target chunks that follow it."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Reuse the longest common chunk prefix and carry the target's suffix."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta operands must be Context Packs")
        prefix = 0
        for held, wanted in zip(base.items, target.items, strict=False):
            if held != wanted:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @property
    def byte_count(self) -> int:
        """Exact wire size of this delta, including every protocol field."""

        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serialize to canonical JSON; the byte count is derived, never written."""

        return _canonical(
            {
                "schema": DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": _encode_items(self.appended),
            }
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> ContextPackDelta:
        """Decode and fully verify a serialized delta."""

        document = _decode_document(payload, _DELTA_FIELDS, "delta")
        if document["schema"] != DELTA_SCHEMA:
            raise ContextPackError("context pack delta schema is not recognized")
        base_digest = _validated_digest(document["base_digest"], "base_digest")
        target_digest = _validated_digest(document["target_digest"], "target_digest")
        prefix = document["prefix_items"]
        if type(prefix) is not int or prefix < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = _decode_items(document["appended"])
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix,
            appended=appended,
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Verify a delta against the held pack and return the rebuilt target pack."""

    if not isinstance(base, ContextPack):
        raise ContextPackError("delta receiver requires a Context Pack base")
    if not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta receiver requires a Context Pack delta")
    if delta.base_digest != base.digest:
        raise ContextPackError("delta base digest does not match the held pack")
    if type(delta.prefix_items) is not int or delta.prefix_items < 0 or delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix_items is outside the held pack")
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("rebuilt target digest does not match the delta")
    return target


def _chunk_text(content: str, chunk_bytes: int) -> tuple[bytes, ...]:
    """Split text greedily by complete UTF-8 characters so every chunk stays valid."""

    if type(chunk_bytes) is not int or chunk_bytes <= 0:
        raise ContextPackError("chunk_bytes must be a positive integer")
    if not isinstance(content, str):
        raise ContextPackError("context content must be text")
    chunks: list[bytes] = []
    pending: list[str] = []
    pending_bytes = 0
    for character in content:
        character_bytes = len(character.encode("utf-8"))
        if character_bytes > chunk_bytes:
            raise ContextPackError("chunk_bytes is smaller than one UTF-8 character")
        if pending_bytes + character_bytes > chunk_bytes:
            chunks.append("".join(pending).encode("utf-8"))
            pending = []
            pending_bytes = 0
        pending.append(character)
        pending_bytes += character_bytes
    if pending:
        chunks.append("".join(pending).encode("utf-8"))
    return tuple(chunks)


def _validated_items(items: Iterable[bytes]) -> tuple[bytes, ...]:
    if isinstance(items, (bytes, bytearray, str)) or not isinstance(items, Iterable):
        raise ContextPackError("pack items must be an iterable of byte chunks")
    chunks: list[bytes] = []
    for item in items:
        if not isinstance(item, bytes):
            raise ContextPackError("pack items must be bytes")
        chunks.append(item)
    return tuple(chunks)


def _unsigned_pack(items: tuple[bytes, ...]) -> dict[str, Any]:
    return {"schema": PACK_SCHEMA, "items": _encode_items(items)}


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("items must be a list of Base64 strings")
    decoded: list[bytes] = []
    for item in value:
        if not isinstance(item, str):
            raise ContextPackError("items must be a list of Base64 strings")
        try:
            raw = base64.b64decode(item.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError) as error:
            raise ContextPackError("items must be valid Base64") from error
        decoded.append(raw)
    return tuple(decoded)


def _decode_document(payload: bytes, fields: frozenset[str], kind: str) -> dict[str, Any]:
    if not isinstance(payload, bytes):
        raise ContextPackError(f"context {kind} wire form must be bytes")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ContextPackError(f"context {kind} wire form must be UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ContextPackError(f"context {kind} wire form must be a JSON object")
    if set(document) != fields:
        raise ContextPackError(f"context {kind} wire form has unexpected fields")
    return document


def _validated_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        raise ContextPackError(f"{field} must be a sha256 digest")
    hex_part = value[len(_DIGEST_PREFIX) :]
    if len(hex_part) != 64 or not set(hex_part) <= _HEX_DIGITS:
        raise ContextPackError(f"{field} must be a sha256 digest")
    return value


def _validated_count(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ContextPackError(f"{field} must be a non-negative integer")
    return value


def _digest_of(unsigned: dict[str, Any]) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _stable_byte_count(document: dict[str, Any]) -> int:
    """Find the byte count that makes ``len(to_bytes())`` equal the field itself."""

    byte_count = 0
    while True:
        size = len(_canonical({**document, "byte_count": byte_count}))
        if size == byte_count:
            return byte_count
        byte_count = size


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
