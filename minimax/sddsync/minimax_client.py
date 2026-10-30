"""MiniMax 接入层：官方 API / 编码助手会话 / 确定性 Mock 三种模式。"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://api.minimax.cn/v1"
DEFAULT_MODEL = "MiniMax-M3.1-Flash"
# 无 API Key 时复用“编码助手会话”产出的补丁：模型仍是 MiniMax-M3.1-Flash，
# 会话过程见 docs/minimax-development-log.md，补丁按上下文 sha256 精确匹配。
ASSISTANT_SESSION_BASE_URL = "in-repo://minimax-assistant-session"
PATCH_INDEX_PATH = "patches/index.json"

# Mock 模式下的目标实现：只取一种优惠，满足规格 R2 与 R1。
_MOCK_FIXED_SOURCE = '''"""退款计费样例：按规格 R2 只取一种优惠。"""

from dataclasses import dataclass

MEMBER_DISCOUNT_FACTOR = 0.80
THRESHOLD_AMOUNT = 100.00
THRESHOLD_DISCOUNT = 10.00


@dataclass(frozen=True)
class Order:
    paid_amount: float
    member: bool
    shipped: bool = False


def _member_price(paid_amount: float) -> float:
    return round(paid_amount * MEMBER_DISCOUNT_FACTOR, 2)


def _threshold_price(paid_amount: float) -> float:
    if paid_amount < THRESHOLD_AMOUNT:
        return paid_amount
    return round(paid_amount - THRESHOLD_DISCOUNT, 2)


def compute_refund(order: Order) -> float:
    """按规格计算应退金额。"""
    candidates = [order.paid_amount]
    if order.member:
        candidates.append(_member_price(order.paid_amount))
    if order.paid_amount >= THRESHOLD_AMOUNT:
        candidates.append(_threshold_price(order.paid_amount))
    return round(min(candidates), 2)
'''


class MiniMaxError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatResult:
    text: str
    mode: str
    model: str
    base_url: str
    log_path: str
    latency_ms: int


class _BaseClient:
    mode = "base"

    def __init__(self, root: Path, model: str, base_url: str) -> None:
        self.root = root
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.log_dir = root / "logs" / "minimax"

    def _write_log(self, record: dict[str, Any]) -> str:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / "calls.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return str(log_path)

    def chat(self, messages: list[dict[str, str]], purpose: str) -> ChatResult:
        raise NotImplementedError


class MockClient(_BaseClient):
    """确定性 Mock：返回预置 unified diff，日志中显式标记 mode=mock。"""

    mode = "mock"

    def __init__(self, root: Path, model: str, base_url: str, buggy_source: str) -> None:
        super().__init__(root, model, base_url)
        self.buggy_source = buggy_source

    def _patch(self) -> str:
        diff = difflib.unified_diff(
            self.buggy_source.splitlines(),
            _MOCK_FIXED_SOURCE.splitlines(),
            fromfile="a/src/refund.py",
            tofile="b/src/refund.py",
            lineterm="",
        )
        return "\n".join(diff) + "\n"

    def chat(self, messages: list[dict[str, str]], purpose: str) -> ChatResult:
        started = time.monotonic()
        if purpose == "propose_patch":
            text = self._patch()
        else:
            text = "(mock) 无额外内容。"
        latency_ms = int((time.monotonic() - started) * 1000)
        log_path = self._write_log(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "mode": self.mode,
                "purpose": purpose,
                "model": self.model,
                "base_url": self.base_url,
                "messages": messages,
                "response_text": text,
                "latency_ms": latency_ms,
            }
        )
        return ChatResult(text, self.mode, self.model, self.base_url, log_path, latency_ms)


class AssistantSessionClient(_BaseClient):
    """复用 MiniMax 编码助手会话产出的补丁。

    补丁按“任务上下文 sha256”在 patches/index.json 中精确匹配：规格一旦变更，
    上下文摘要随之改变，旧补丁不再命中，必须重新由 MiniMax 生成。
    """

    mode = "assistant_session"

    def __init__(self, root: Path, model: str, base_url: str, context_sha256: str) -> None:
        super().__init__(root, model, base_url)
        self.context_sha256 = context_sha256

    def _index(self) -> dict[str, Any]:
        index_path = self.root / PATCH_INDEX_PATH
        if not index_path.is_file():
            raise MiniMaxError(f"缺少补丁索引 {PATCH_INDEX_PATH}")
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        entries = payload.get("patches")
        if not isinstance(entries, list):
            raise MiniMaxError(f"{PATCH_INDEX_PATH} 格式不正确")
        return payload

    def select_patch(self) -> dict[str, Any]:
        payload = self._index()
        for entry in payload["patches"]:
            if entry.get("context_sha256") == self.context_sha256:
                return entry
        known = ", ".join(str(item.get("context_sha256", ""))[:16] for item in payload["patches"])
        raise MiniMaxError(
            "当前上下文没有对应的 MiniMax 助手补丁（上下文已变化）。"
            f"已知上下文摘要: {known}；请设置 MINIMAX_API_KEY 用官方 API 重新生成，"
            "或提交该上下文对应的补丁并登记到 patches/index.json。"
        )

    def chat(self, messages: list[dict[str, str]], purpose: str) -> ChatResult:
        started = time.monotonic()
        entry = self.select_patch()
        patch_path = self.root / "patches" / str(entry["file"])
        if not patch_path.is_file():
            raise MiniMaxError(f"补丁文件不存在: {patch_path}")
        raw = patch_path.read_bytes()
        text = raw.decode("utf-8")
        if "src/refund.py" not in text:
            raise MiniMaxError(f"补丁 {patch_path.name} 未修改 src/refund.py")
        latency_ms = int((time.monotonic() - started) * 1000)
        log_path = self._write_log(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "mode": self.mode,
                "purpose": purpose,
                "model": self.model,
                "base_url": self.base_url,
                "session": entry.get("session"),
                "context_sha256": self.context_sha256,
                "patch_file": str(entry["file"]),
                "patch_sha256": hashlib.sha256(raw).hexdigest(),
                "spec_version": entry.get("spec_version"),
                "messages": messages,
                "response_text": text,
                "latency_ms": latency_ms,
            }
        )
        return ChatResult(text, self.mode, self.model, self.base_url, log_path, latency_ms)


class MiniMaxClient(_BaseClient):
    """真实 MiniMax chat/completions 调用。"""

    mode = "real"

    def __init__(self, root: Path, api_key: str, model: str, base_url: str) -> None:
        super().__init__(root, model, base_url)
        self.api_key = api_key

    def chat(self, messages: list[dict[str, str]], purpose: str) -> ChatResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "max_tokens": 4096,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=120) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise MiniMaxError(f"MiniMax chat/completions HTTP {error.code}: {detail[:800]}") from error
        except URLError as error:
            raise MiniMaxError(f"MiniMax unreachable: {error.reason}") from error
        latency_ms = int((time.monotonic() - started) * 1000)
        base_resp = raw.get("base_resp") if isinstance(raw, dict) else None
        if isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0):
            raise MiniMaxError(f"MiniMax 返回错误: {base_resp}")
        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise MiniMaxError(f"无法解析 MiniMax 响应: {raw}") from error
        log_path = self._write_log(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "mode": self.mode,
                "purpose": purpose,
                "model": self.model,
                "base_url": self.base_url,
                "messages": messages,
                "response_text": text,
                "raw_response": raw,
                "latency_ms": latency_ms,
            }
        )
        return ChatResult(text, self.mode, self.model, self.base_url, log_path, latency_ms)


def create_client(root: Path, buggy_source: str, context_sha256: str = "") -> _BaseClient:
    """选择 MiniMax 接入方式：官方 API > 编码助手会话 > 确定性 Mock。"""
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    model = os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
    base_url = os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL)
    if api_key:
        return MiniMaxClient(root, api_key, model, base_url)
    if (root / PATCH_INDEX_PATH).is_file() and context_sha256:
        return AssistantSessionClient(root, model, ASSISTANT_SESSION_BASE_URL, context_sha256)
    return MockClient(root, model, base_url, buggy_source)


def extract_unified_diff(text: str) -> str:
    """从模型输出中提取 unified diff（优先 ```diff 代码块）。"""
    fenced = re.findall(r"```(?:diff|patch)?\s*\n(.*?)```", text, re.DOTALL)
    candidates = fenced + [text]
    allowed_prefixes = (" ", "+", "-", "@", "\\", "diff ", "index ", "new file", "deleted file", "--- ", "+++ ")
    for candidate in candidates:
        lines = candidate.splitlines()
        start = None
        for index, line in enumerate(lines):
            if line.startswith("--- ") or line.startswith("diff --git"):
                start = index
                break
        if start is None:
            continue
        collected: list[str] = []
        for line in lines[start:]:
            if collected and line and not line.startswith(allowed_prefixes):
                break
            collected.append(line)
        diff = "\n".join(collected).rstrip() + "\n"
        if "@@" in diff and ("--- " in diff and "+++ " in diff):
            return diff
    raise MiniMaxError("模型输出中没有可用的 unified diff")
