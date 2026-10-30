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

"""Propagate Source availability to the Memory and Topic Memory that depend on it.

Every Scope owns one dependency graph. A caller registers the exact references it
already captured, and withdrawal or restoration of a Source is then evaluated layer
by layer against each node's ``all``/``any`` policy. Deactivation only changes use
eligibility: the registered body and every historical citation stay readable through
``audit`` while ``generation`` refuses unavailable content.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.topic_memory import TopicMemory
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODE_ID_LENGTH,
    SOURCE_LIFECYCLE_NODES_TABLE,
)
from powercontext.builtin.sources import validate_scope_id
from powercontext.builtin.statistics import ModelUsagePurpose
from powercontext.errors import PowerContextError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.context import BuiltinSources
    from powercontext.builtin.runtime.application import BuiltinRuntime

SourceLifecycleFamily = Literal["source", "memory", "topic"]
SourceLifecyclePolicy = Literal["all", "any"]
SourceLifecyclePurpose = Literal["generation", "audit"]

_POLICIES = frozenset({"all", "any"})
_PURPOSES = frozenset({"generation", "audit"})
_REGISTRATION_REASON = "source lifecycle registration"
_FAMILY_SOURCE = "source"
_FAMILY_MEMORY = "memory"
_FAMILY_TOPIC = "topic"


class SourceLifecycleError(ValueError):
    """Raised when a lifecycle registration, event, or read violates the contract."""


class SourceLifecycleEvent(BaseModel):
    """One validated Source availability transition with its own monotonic sequence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    node_id: str = Field(min_length=1)
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str = Field(min_length=1)

    @field_validator("node_id", "reason")
    @classmethod
    def _require_visible_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain visible characters")
        return value


@dataclass(frozen=True, slots=True)
class _LifecycleNode:
    """One registered node and its persisted derived availability."""

    node_id: str
    family: SourceLifecycleFamily
    reference: dict[str, Any]
    parents: tuple[str, ...]
    policy: SourceLifecyclePolicy
    revision: int
    available: bool
    sequence: int


class SourceLifecycleStore:
    """Persist node bindings, derived availability, and applied events per Scope."""

    def __init__(self, database: AsyncDatabase) -> None:
        self._database = database

    async def nodes(self, scope_id: str) -> tuple[_LifecycleNode, ...]:
        async with self._database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(SOURCE_LIFECYCLE_NODES_TABLE).where(SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id)
                )
            ).mappings()
            return tuple(_node_from_row(row) for row in rows)

    async def insert_node(self, scope_id: str, node: _LifecycleNode, /) -> None:
        async with self._database.transaction() as connection:
            await connection.execute(insert(SOURCE_LIFECYCLE_NODES_TABLE).values(_node_values(scope_id, node)))

    async def apply(
        self,
        scope_id: str,
        *,
        changes: Mapping[str, bool],
        source: _LifecycleNode,
        event: SourceLifecycleEvent,
    ) -> None:
        """Write the derived states and the applied event in one transaction."""

        async with self._database.transaction() as connection:
            for node_id, available in changes.items():
                await connection.execute(
                    update(SOURCE_LIFECYCLE_NODES_TABLE)
                    .where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                        SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                    )
                    .values(available=available)
                )
            await connection.execute(
                update(SOURCE_LIFECYCLE_NODES_TABLE)
                .where(
                    SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                    SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == source.node_id,
                )
                .values(sequence=event.sequence)
            )
            await connection.execute(
                insert(SOURCE_LIFECYCLE_EVENTS_TABLE).values(
                    scope_id=scope_id,
                    node_id=source.node_id,
                    sequence=event.sequence,
                    revision=event.revision,
                    available=event.available,
                    reason=event.reason,
                    applied_at=datetime.now(UTC),
                )
            )


class ScopedSourceLifecycle:
    """Register the dependency graph of one Scope and apply Source transitions to it."""

    def __init__(self, runtime: BuiltinRuntime, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = validate_scope_id(scope_id)

    def _store(self) -> SourceLifecycleStore:
        store = self._runtime._lifecycle_store
        if store is None:
            raise SourceLifecycleError("Source lifecycle is not configured for this Runtime")
        return store

    async def register_source(self, node_id: str, source_ref: SourceRef, /, revision: int) -> None:
        target = _node_id(node_id)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("register_source requires a captured SourceRef")
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("revision must be a positive integer")
        nodes = await self._nodes()
        existing = nodes.get(target)
        if existing is not None:
            if (
                existing.family == _FAMILY_SOURCE
                and existing.reference == source_ref.model_dump(mode="json")
                and existing.revision == revision
            ):
                return
            raise SourceLifecycleError(f"node {target!r} is already registered with a different binding")
        await self._require_source(source_ref)
        await self._store().insert_node(
            self.scope_id,
            _LifecycleNode(
                node_id=target,
                family=_FAMILY_SOURCE,
                reference=source_ref.model_dump(mode="json"),
                parents=(),
                policy="all",
                revision=revision,
                available=True,
                sequence=0,
            ),
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        parents: Sequence[str],
        policy: str = "all",
    ) -> None:
        target = _node_id(node_id)
        citation = _citation(citation)
        binding = _binding(policy)
        nodes = await self._nodes()
        bound_parents = _parents(parents, nodes, target)
        reference = citation.model_dump(mode="json")
        existing = nodes.get(target)
        if existing is not None:
            if (
                existing.family == _FAMILY_MEMORY
                and existing.reference == reference
                and existing.parents == bound_parents
                and existing.policy == binding
            ):
                return
            raise SourceLifecycleError(f"node {target!r} is already registered with a different binding")
        await self._require_memory(citation)
        available = _combine(_evaluate(nodes), bound_parents, binding)
        await self._set_memory_state(((citation, available),), _REGISTRATION_REASON)
        await self._store().insert_node(
            self.scope_id,
            _LifecycleNode(
                node_id=target,
                family=_FAMILY_MEMORY,
                reference=reference,
                parents=bound_parents,
                policy=binding,
                revision=0,
                available=available,
                sequence=0,
            ),
        )

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        /,
        parents: Sequence[str],
        policy: str = "all",
    ) -> None:
        target = _node_id(node_id)
        reference_ref = _topic_ref(artifact_ref)
        binding = _binding(policy)
        nodes = await self._nodes()
        bound_parents = _parents(parents, nodes, target)
        reference = reference_ref.model_dump(mode="json")
        existing = nodes.get(target)
        if existing is not None:
            if (
                existing.family == _FAMILY_TOPIC
                and existing.reference == reference
                and existing.parents == bound_parents
                and existing.policy == binding
            ):
                return
            raise SourceLifecycleError(f"node {target!r} is already registered with a different binding")
        await self._require_topic(reference_ref)
        available = _combine(_evaluate(nodes), bound_parents, binding)
        await self._store().insert_node(
            self.scope_id,
            _LifecycleNode(
                node_id=target,
                family=_FAMILY_TOPIC,
                reference=reference,
                parents=bound_parents,
                policy=binding,
                revision=reference_ref.revision,
                available=available,
                sequence=0,
            ),
        )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Apply one Source event and return every currently available node id, sorted."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("apply requires a SourceLifecycleEvent")
        nodes = await self._nodes()
        source = nodes.get(event.node_id)
        if source is None or source.family != _FAMILY_SOURCE:
            raise SourceLifecycleError(f"event targets unknown Source {event.node_id!r}")
        if source.revision != event.revision:
            raise SourceLifecycleError(
                f"event revision {event.revision} does not match registered revision {source.revision}"
            )
        if event.sequence < source.sequence:
            raise SourceLifecycleError(f"event sequence {event.sequence} is lower than {source.sequence}")
        if event.sequence == source.sequence:
            if event.available != source.available:
                raise SourceLifecycleError(
                    f"event sequence {event.sequence} was already applied with a different outcome"
                )
            return _available_ids(_evaluate(nodes))

        states = _evaluate(nodes, overrides={source.node_id: event.available})
        changes = {
            node_id: available for node_id, available in states.items() if available != nodes[node_id].available
        }
        memory_changes = tuple(
            (MemoryCitation.model_validate(nodes[node_id].reference), states[node_id])
            for node_id in sorted(changes)
            if nodes[node_id].family == _FAMILY_MEMORY
        )
        # Native Memory writes commit one revision at a time, so a failure leaves the
        # stored lifecycle state untouched; retrying the same event re-applies only
        # the remaining transitions because every write is itself idempotent.
        await self._set_memory_state(memory_changes, event.reason)
        await self._store().apply(self.scope_id, changes=changes, source=source, event=event)
        return _available_ids(states)

    async def resolve(
        self,
        node_id: str,
        /,
        *,
        purpose: str = "generation",
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        """Return the registered reference, refusing unavailable content for generation."""

        if purpose not in _PURPOSES:
            raise SourceLifecycleError(f"unknown resolve purpose {purpose!r}")
        node = (await self._nodes()).get(node_id)
        if node is None:
            raise SourceLifecycleError(f"node {node_id!r} is not registered")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError(f"node {node_id!r} is unavailable for generation")
        return _reference(node)

    async def unavailable_topic_refs(self) -> frozenset[tuple[str, int]]:
        """Return the Topic revisions that currently must stay out of search and Context."""

        store = self._runtime._lifecycle_store
        if store is None:
            return frozenset()
        return frozenset(
            (str(node.reference["artifact_id"]), int(node.reference["revision"]))
            for node in (await self._nodes()).values()
            if node.family == _FAMILY_TOPIC and not node.available
        )

    async def _nodes(self) -> dict[str, _LifecycleNode]:
        return {node.node_id: node for node in await self._store().nodes(self.scope_id)}

    async def _require_source(self, source_ref: SourceRef) -> None:
        async with self._runtime._context(self.scope_id) as context:
            sources: BuiltinSources = context.sources
            try:
                members = await sources.list()
            except PowerContextError as error:
                raise SourceLifecycleError("Source catalog is not readable") from error
            if not any(sources.catalog.as_ref(source) == source_ref for source in members):
                raise SourceLifecycleError(f"Source {source_ref.source_id!r} is absent from the Scope catalog")

    async def _require_memory(self, citation: MemoryCitation) -> None:
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            if citation.memory_ref.artifact_id != context.artifacts.memory_artifact_id:
                raise SourceLifecycleError("Memory citation does not belong to this Scope's Memory")
            try:
                await service.revision(citation.memory_ref)
                await service.validate_citation(citation)
            except PowerContextError as error:
                raise SourceLifecycleError("Memory citation is not readable") from error

    async def _require_topic(self, reference: ArtifactRef) -> None:
        records = self._runtime.records.for_scope(self.scope_id)
        try:
            await records.get_artifact_revision(TopicMemory.family, reference.artifact_id, reference.revision)
        except PowerContextError as error:
            raise SourceLifecycleError("Topic Memory revision is not readable") from error

    async def _set_memory_state(
        self,
        changes: Sequence[tuple[MemoryCitation, bool]],
        reason: str | None,
    ) -> None:
        """Deactivate or restore the exact registered entries of the current Memory head."""

        if not changes:
            return
        async with self._runtime._context(
            self.scope_id,
            embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING,
        ) as context:
            service = context.artifacts.memory
            async with self._runtime._locked(self.scope_id):
                for citation, available in changes:
                    current = await service.head(context.artifacts.memory_artifact_id)
                    entry = next(
                        (item for item in await service.entries(current) if item.entry_id == citation.entry_id),
                        None,
                    )
                    if entry is None or entry.entry_version_id != citation.entry_version_id:
                        raise SourceLifecycleError(
                            f"Memory entry {citation.entry_id!r} no longer matches the current Memory head"
                        )
                    if available:
                        await service.reactivate(current, entries=(entry,), reason=reason)
                    else:
                        await service.forget(current, entries=(entry,), reason=reason)


class SourceLifecycleApplication:
    """Select the lifecycle service for one Scope."""

    def __init__(self, runtime: BuiltinRuntime) -> None:
        self._runtime = runtime

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, scope_id)


def _node_id(value: object) -> str:
    if not isinstance(value, str):
        raise SourceLifecycleError("node_id must be text")
    if not value.strip():
        raise SourceLifecycleError("node_id must contain visible characters")
    if len(value) > SOURCE_LIFECYCLE_NODE_ID_LENGTH:
        raise SourceLifecycleError(f"node_id must not exceed {SOURCE_LIFECYCLE_NODE_ID_LENGTH} characters")
    return value


def _binding(value: object) -> SourceLifecyclePolicy:
    if not isinstance(value, str) or value not in _POLICIES:
        raise SourceLifecycleError("policy must be 'all' or 'any'")
    return value  # type: ignore[return-value]


def _parents(
    value: Sequence[str],
    nodes: Mapping[str, _LifecycleNode],
    node_id: str,
) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SourceLifecycleError("parents must be a sequence of node ids")
    parents = tuple(_node_id(parent) for parent in value)
    if not parents:
        raise SourceLifecycleError("a derived node requires at least one parent")
    if len(set(parents)) != len(parents):
        raise SourceLifecycleError("parents must not repeat")
    if node_id in parents:
        raise SourceLifecycleError("a node cannot depend on itself")
    for parent in parents:
        if parent not in nodes:
            raise SourceLifecycleError(f"parent {parent!r} must be registered first")
    return parents


def _citation(value: object) -> MemoryCitation:
    if isinstance(value, MemoryCitation):
        return value
    try:
        return MemoryCitation.model_validate(value)
    except ValidationError as error:
        raise SourceLifecycleError("registration requires a readable MemoryCitation") from error


def _topic_ref(value: object) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        reference = value
    else:
        try:
            reference = ArtifactRef.model_validate(value)
        except ValidationError as error:
            raise SourceLifecycleError("registration requires a readable Topic Memory ArtifactRef") from error
    if reference.family != TopicMemory.family:
        raise SourceLifecycleError("registration requires a Topic Memory ArtifactRef")
    return reference


def _combine(states: Mapping[str, bool], parents: Sequence[str], policy: SourceLifecyclePolicy) -> bool:
    supports = [states[parent] for parent in parents]
    return all(supports) if policy == "all" else any(supports)


def _evaluate(
    nodes: Mapping[str, _LifecycleNode],
    overrides: Mapping[str, bool] | None = None,
) -> dict[str, bool]:
    """Evaluate every node's availability, resolving parents before dependants."""

    memo: dict[str, bool] = {}

    def value(node_id: str) -> bool:
        if node_id in memo:
            return memo[node_id]
        node = nodes[node_id]
        if overrides is not None and node_id in overrides:
            resolved = overrides[node_id]
        elif node.family == _FAMILY_SOURCE:
            resolved = node.available
        else:
            resolved = _combine({parent: value(parent) for parent in node.parents}, node.parents, node.policy)
        memo[node_id] = resolved
        return resolved

    return {node_id: value(node_id) for node_id in nodes}


def _available_ids(states: Mapping[str, bool]) -> list[str]:
    return sorted(node_id for node_id, available in states.items() if available)


def _reference(node: _LifecycleNode) -> SourceRef | MemoryCitation | ArtifactRef:
    if node.family == _FAMILY_SOURCE:
        return SourceRef.model_validate(node.reference)
    if node.family == _FAMILY_MEMORY:
        return MemoryCitation.model_validate(node.reference)
    return ArtifactRef.model_validate(node.reference)


def _node_values(scope_id: str, node: _LifecycleNode) -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "node_id": node.node_id,
        "family": node.family,
        "reference": json.dumps(node.reference, sort_keys=True, separators=(",", ":")),
        "parents": json.dumps(list(node.parents), separators=(",", ":")),
        "policy": node.policy,
        "revision": node.revision,
        "available": node.available,
        "sequence": node.sequence,
    }


def _node_from_row(row: Mapping[Any, Any]) -> _LifecycleNode:
    return _LifecycleNode(
        node_id=str(row["node_id"]),
        family=row["family"],
        reference=json.loads(row["reference"]),
        parents=tuple(json.loads(row["parents"])),
        policy=row["policy"],
        revision=int(row["revision"]),
        available=bool(row["available"]),
        sequence=int(row["sequence"]),
    )


__all__ = [
    "ScopedSourceLifecycle",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
    "SourceLifecycleStore",
]
