"""PowerContext HTTP API 薄客户端（仅标准库）。"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class PowerContextError(RuntimeError):
    """PowerContext 调用失败，携带 HTTP 状态码。"""

    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class PowerContextClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0, token: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8311")).rstrip("/")
        self.timeout = timeout
        self.token = token if token is not None else os.environ.get("POWERCONTEXT_TOKEN")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise PowerContextError(
                f"{method} {path} failed with HTTP {error.code}: {detail[:800]}",
                status=error.code,
                body=detail,
            ) from error
        except URLError as error:
            raise PowerContextError(f"{method} {url} unreachable: {error.reason}") from error

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload=payload)

    def health_live(self) -> bool:
        try:
            self.get("/health/live")
            return True
        except PowerContextError:
            return False

    def health_ready(self) -> bool:
        try:
            ready = self.get("/health/ready")
        except PowerContextError:
            return False
        status = ready.get("status") if isinstance(ready, dict) else None
        return status == "ready"

    def ensure_scope(self, key: str, title: str, summary: str) -> str:
        payload = {"title": title, "summary": summary, "idempotency_key": key}
        try:
            descriptor = self.post("/v1/scopes", payload)
            return descriptor["scope_id"]
        except PowerContextError as error:
            if error.status != 409:
                raise
        page = self.get("/v1/scopes", {"query": title, "query_field": "title", "limit": 50})
        for item in page.get("items", []):
            if item.get("title") == title:
                return item["scope_id"]
        raise PowerContextError("scope already exists but cannot be resolved")

    def capture_source(self, scope_id: str, source_id: str, content: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            "/v1/sources/content",
            {"scope_id": scope_id, "source_id": source_id, "content": content, "metadata": metadata},
        )

    def get_source(self, scope_id: str, source_id: str) -> dict[str, Any]:
        return self.get(f"/v1/scopes/{scope_id}/sources/content/{source_id}")

    def list_sources(self, scope_id: str, limit: int = 100) -> dict[str, Any]:
        return self.get(f"/v1/scopes/{scope_id}/sources", {"limit": limit})

    def prepare_context(self, scope_id: str, query: str, max_bytes: int = 8000) -> dict[str, Any]:
        return self.post("/v1/context/prepare", {"scope_id": scope_id, "query": query, "max_bytes": max_bytes})

    def remember(self, scope_id: str, kind: str, text: str, reason: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        return self.post("/v1/memory/remember", payload)

    def list_memory_entries(self, scope_id: str) -> dict[str, Any]:
        return self.post("/v1/memory/entries/list", {"scope_id": scope_id})

    def create_contract(self, scope_id: str, source_id: str, contract: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            "/v1/work/contracts/create",
            {"scope_id": scope_id, "source_id": source_id, "contract": contract},
        )

    def record_outcome(self, scope_id: str, source_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            "/v1/work/outcomes/record",
            {"scope_id": scope_id, "source_id": source_id, "outcome": outcome},
        )
