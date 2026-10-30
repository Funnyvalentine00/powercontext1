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

"""HTTP cross-encoder reranking for coarse Memory search candidates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision, _validate_bounds
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score coarse Memory candidates through an external HTTP reranking service.

    The service accepts at most ``batch_size`` candidates per request, so the pool is split
    into batches that keep the original global rank of every candidate. Scores from all
    batches are then merged into one global selection, which lets a later batch outrank an
    earlier one while the selected ranks still anchor to the original Memory hits.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if batch_size < 1:
            raise ValueError("rerank batch_size must be at least one")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate once by rank and return the global top ``limit`` ranks."""

        _validate_bounds(len(candidates), limit)
        scored: list[tuple[float, int]] = []
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            first_rank = start + 1
            batch_scores = await self._score(query, batch, first_rank)
            scored.extend(zip(batch_scores, range(first_rank, first_rank + len(batch)), strict=True))
            requests += 1
        selected = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for _score, rank in selected),
            usage=InferenceUsage(requests=requests),
        )

    async def _score(self, query: str, batch: Sequence[MemoryHit], first_rank: int) -> tuple[float, ...]:
        """Send one batch request and return its scores ordered by global rank."""

        payload = {
            "query": query,
            "candidates": [
                {"rank": rank, "text": candidate.text}
                for rank, candidate in enumerate(batch, start=first_rank)
            ],
        }
        response = await self._client.post(self._endpoint, json=payload)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as error:
            raise ValueError("reranker response was not valid JSON") from error
        return _validated_batch_scores(body, first_rank=first_rank, count=len(batch))


def _validated_batch_scores(body: object, *, first_rank: int, count: int) -> tuple[float, ...]:
    """Validate one response against the exact ranks this batch requested."""

    expected = range(first_rank, first_rank + count)
    if not isinstance(body, Mapping) or set(body) != {"scores"}:
        raise ValueError("reranker response must contain exactly the scores field")  # noqa: TRY003
    rows = body["scores"]
    if not isinstance(rows, list):
        raise ValueError("reranker scores must be a list")  # noqa: TRY003
    observed: dict[int, float] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"rank", "score"}:
            raise ValueError("reranker score must contain exactly rank and score")  # noqa: TRY003
        rank = row["rank"]
        score = row["score"]
        if type(rank) is not int or rank not in expected:
            raise ValueError("reranker score rank is outside the requested batch")  # noqa: TRY003
        if rank in observed:
            raise ValueError(f"reranker score rank was returned twice: {rank}")  # noqa: TRY003
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("reranker score must be a finite number")  # noqa: TRY003
        observed[rank] = float(score)
    if len(observed) != count:
        raise ValueError("reranker scores did not cover the requested batch")  # noqa: TRY003
    return tuple(observed[rank] for rank in expected)


__all__ = ["HTTPMemoryReranker"]
