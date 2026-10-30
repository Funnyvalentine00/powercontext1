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

"""Coalesce concurrent embedding calls and cache successful vectors.

The wrapper keeps one request pipeline per model instance: texts registered inside
the same coalescing window are de-duplicated into provider batches of at most
``max_batch_size``, calls that arrive while a batch is executing reuse that batch,
and successful vectors feed a bounded LRU cache. Provider work always runs in a
background task owned by the wrapper, so cancelling one caller never interrupts
a batch that other callers wait on.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

_DEFAULT_MAX_BATCH_SIZE = 64
_DEFAULT_COALESCE_MS = 5.0
_DEFAULT_CACHE_SIZE = 1024


@dataclass(slots=True)
class _Batch:
    """One provider request shared by every caller that waits on its texts."""

    texts: tuple[str, ...]
    future: asyncio.Future[EmbeddingResult]


class CoalescingEmbeddingModel:
    """Share in-progress embedding work across calls and cache successful vectors.

    ``max_batch_size`` bounds the de-duplicated texts of one provider request,
    ``coalesce_ms`` sets the window that collects concurrent callers (``0`` merges
    everything registered during the current event-loop iteration), and ``cache_size``
    bounds the cross-call LRU cache (``0`` disables caching without disabling sharing).
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE,
        coalesce_ms: float = _DEFAULT_COALESCE_MS,
        cache_size: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be at least one")  # noqa: TRY003
        if coalesce_ms < 0:
            raise ValueError("coalesce_ms must not be negative")  # noqa: TRY003
        if cache_size < 0:
            raise ValueError("cache_size must not be negative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_delay = coalesce_ms / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._pending: dict[str, asyncio.Future[_Batch]] = {}
        self._inflight: dict[str, _Batch] = {}
        self._flush_handle: asyncio.TimerHandle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Embed texts in caller order, sharing and caching provider work."""

        if not texts:
            return EmbeddingResult(vectors=())
        loop = asyncio.get_running_loop()
        self._loop = loop
        vectors: dict[str, EmbeddingVector] = {}
        distinct = dict.fromkeys(texts)
        batches: dict[int, _Batch] = {}
        assignments: list[asyncio.Future[_Batch]] = []
        for text in distinct:
            cached = self._cached(text)
            if cached is not None:
                vectors[text] = cached
                continue
            batch = self._inflight.get(text)
            if batch is not None:
                batches.setdefault(id(batch), batch)
                continue
            waiter = self._pending.get(text)
            if waiter is None:
                waiter = loop.create_future()
                self._pending[text] = waiter
            assignments.append(waiter)
        if self._pending:
            self._schedule_flush(loop)
        for waiter in assignments:
            batch = await asyncio.shield(waiter)
            batches.setdefault(id(batch), batch)
        wanted = set(distinct)
        requests = 0
        input_tokens: int | None = None
        output_tokens: int | None = None
        for batch in batches.values():
            result = await asyncio.shield(batch.future)
            usage = result.usage
            requests += usage.requests
            input_tokens = _add_tokens(input_tokens, usage.input_tokens)
            output_tokens = _add_tokens(output_tokens, usage.output_tokens)
            for text, vector in zip(batch.texts, result.vectors, strict=True):
                if text in wanted:
                    vectors[text] = vector
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=requests,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )

    def _cached(self, text: str) -> EmbeddingVector | None:
        if text not in self._cache:
            return None
        self._cache.move_to_end(text)
        return self._cache[text]

    def _schedule_flush(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._flush_handle is not None:
            return
        self._flush_handle = loop.call_later(self._coalesce_delay, self._start_flush)

    def _start_flush(self) -> None:
        """Freeze the current window into batches and start executing them."""

        self._flush_handle = None
        pending, self._pending = self._pending, {}
        loop = self._loop
        if not pending or loop is None:
            return
        entries = tuple(pending.items())
        batches: list[_Batch] = []
        for start in range(0, len(entries), self._max_batch_size):
            chunk = entries[start : start + self._max_batch_size]
            batch = _Batch(tuple(text for text, _ in chunk), loop.create_future())
            for text, waiter in chunk:
                self._inflight[text] = batch
                if not waiter.done():
                    waiter.set_result(batch)
            batches.append(batch)
        task = loop.create_task(self._execute(tuple(batches)))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _execute(self, batches: tuple[_Batch, ...]) -> None:
        """Run every batch of one window, isolating each batch's failure."""

        for index, batch in enumerate(batches):
            try:
                result = await self._model.embed(batch.texts)
                self._validate(batch, result)
            except asyncio.CancelledError:
                for remaining in batches[index:]:
                    self._release(remaining)
                    remaining.future.cancel()
                raise
            except Exception as error:
                self._release(batch)
                batch.future.set_exception(error)
            else:
                self._store(batch, result)

    @staticmethod
    def _validate(batch: _Batch, result: EmbeddingResult) -> None:
        if len(result.vectors) != len(batch.texts):
            raise ValueError(  # noqa: TRY003
                f"provider returned {len(result.vectors)} vectors for {len(batch.texts)} texts"
            )

    def _store(self, batch: _Batch, result: EmbeddingResult) -> None:
        if self._cache_size:
            for text, vector in zip(batch.texts, result.vectors, strict=True):
                self._cache[text] = vector
                self._cache.move_to_end(text)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        self._release(batch)
        if not batch.future.done():
            batch.future.set_result(result)

    def _release(self, batch: _Batch) -> None:
        for text in batch.texts:
            if self._inflight.get(text) is batch:
                del self._inflight[text]


def _add_tokens(total: int | None, value: int | None) -> int | None:
    if value is None:
        return total
    return value if total is None else total + value


__all__ = ["CoalescingEmbeddingModel"]
