"""研究任务状态：经 PowerContext 持久化，重启后读回并继续使用。

状态字段是契约，报告、自检与续研都依赖它，见 docs/DESIGN.md 任务 5。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .pc_client import PowerContextClient, PowerContextError

STATE_SCHEMA = "rca.task-state.v1"
REPORT_PREFIX = "rca:report:"
# PowerContext Memory entry 的文本上限。
MAX_STATE_BYTES = 8192
STATE_KIND = "research-state"


def report_source_id(task_id: str, digest: str) -> str:
    """报告在 PowerContext 中的 Source 编号：含内容摘要，内容变化即编号变化。"""
    return f"{REPORT_PREFIX}{task_id}:{digest[:16]}"


def build_state(
    *,
    task_id: str,
    question: str,
    aspects: list[str],
    statuses: dict[str, str],
    evidence: list[dict[str, object]],
    gaps: list[dict[str, object]],
    documents: list[str],
    report_source_id: str,
    report_sha256: str,
    chunk_stats: dict[str, int],
) -> dict[str, Any]:
    """状态字段契约（字段名不要改）：

    schema / task_id / question / aspects / statuses / evidence / gaps /
    documents / report_source_id / report_sha256 / chunk_stats / updated_at

    其中 evidence 每项只保留 ref / chunk_id / doc_id / sha256，
    完整原文留在 seekdb，避免超过 Memory 的 8192 字节上限。
    """
    return {
        "schema": STATE_SCHEMA,
        "task_id": task_id,
        "question": question,
        "aspects": list(aspects),
        "statuses": dict(statuses),
        "evidence": [
            {
                "ref": str(item["ref"]),
                "chunk_id": str(item["chunk_id"]),
                "doc_id": str(item["doc_id"]),
                "sha256": str(item["sha256"]),
            }
            for item in evidence
        ],
        "gaps": [dict(gap) for gap in gaps],
        "documents": list(documents),
        "report_source_id": report_source_id,
        "report_sha256": report_sha256,
        "chunk_stats": dict(chunk_stats),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def serialize_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def state_size(state: dict[str, Any]) -> int:
    return len(serialize_state(state).encode("utf-8"))


def save_state(client: PowerContextClient, scope_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """序列化后用 /v1/memory/remember 写入，kind 固定为 research-state。"""
    text = serialize_state(state)
    size = len(text.encode("utf-8"))
    if size > MAX_STATE_BYTES:
        raise ValueError(
            f"任务状态序列化后 {size} 字节，超过 Memory 上限 {MAX_STATE_BYTES} 字节；请减少子问题数量"
        )
    response = client.remember(scope_id, STATE_KIND, text, reason=f"任务 {state.get('task_id')} 研究状态")
    return {"bytes": size, "entry": response.get("entry")}


def _states_from_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for entry in page.get("entries", []) or []:
        if entry.get("kind") != STATE_KIND:
            continue
        try:
            state = json.loads(entry.get("text") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
            continue
        states.append(state)
    states.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return states


def list_states(client: PowerContextClient, scope_id: str) -> list[dict[str, Any]]:
    """列出 scope 下全部研究状态；同一任务只取最新一条，整体按 updated_at 倒序。"""
    latest: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for item in _states_from_page(client.list_memory_entries(scope_id)):
        task_id = str(item.get("task_id", ""))
        if task_id in latest:
            continue
        latest[task_id] = item
        ordered.append(item)
    return ordered


def load_state(client: PowerContextClient, scope_id: str, task_id: str) -> dict[str, Any]:
    """取同 schema、同 task_id 的最新一条；找不到时抛出 LookupError。"""
    for state in list_states(client, scope_id):
        if state.get("task_id") == task_id:
            return state
    raise LookupError(f"PowerContext 中没有任务 {task_id} 的研究状态；请先执行 bash run.sh ask ... --task {task_id}")


def save_report(client: PowerContextClient, scope_id: str, task_id: str, text: str) -> tuple[str, str]:
    """把报告写入 /v1/sources/content，返回 (source_id, sha256)。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source_id = report_source_id(task_id, digest)
    metadata = {"task_id": task_id, "sha256": digest, "kind": "research-report"}
    try:
        client.capture_source(scope_id, source_id, text, metadata)
    except PowerContextError as error:
        if error.status != 409:
            raise
        # Source 编号含内容摘要：同编号必然同内容，读回确认后即可视为已入库。
        if load_report(client, scope_id, source_id) != text:
            raise RuntimeError(f"报告 Source {source_id} 已存在但内容不一致，拒绝覆盖") from error
    return source_id, digest


def load_report(client: PowerContextClient, scope_id: str, source_id: str) -> str:
    """从 /v1/scopes/{scope}/sources/content/{id} 读回报告正文。"""
    response = client.get_source(scope_id, source_id)
    content = response.get("content") if isinstance(response, dict) else None
    if not isinstance(content, str) or not content:
        raise LookupError(f"PowerContext 中没有报告 Source {source_id}")
    return content
