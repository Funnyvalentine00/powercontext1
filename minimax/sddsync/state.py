"""Work Contract / Task Outcome / 任务状态，经 PowerContext 持久化与复用。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .pc_client import PowerContextClient, PowerContextError

STATE_SCHEMA = "minimax.sddsync.state.v1"
CONTRACT_SOURCE_PREFIX = "minimax:work-contract:"
OUTCOME_SOURCE_PREFIX = "minimax:task-outcome:"


def contract_source_id(task_id: str, revision: str = "v1") -> str:
    return f"{CONTRACT_SOURCE_PREFIX}{task_id}:{revision}"


def outcome_source_id(task_id: str) -> str:
    return f"{OUTCOME_SOURCE_PREFIX}{task_id}:{time.strftime('%Y%m%dT%H%M%S')}"


def build_contract(task: dict[str, Any], context_sha256: str, sources: list[dict[str, str]]) -> dict[str, Any]:
    fact_lines = [f"{item['path']} sha256={item['sha256']} source={item['source_id']}" for item in sources]
    return {
        "schema": "powercontext.work-contract.v1",
        "trust": "untrusted_input",
        "objective": str(task["objective"]).strip(),
        "facts": [
            {"text": f"原始证据已写入 PowerContext：{line}", "basis": "declared", "evidence": []}
            for line in fact_lines
        ],
        "in_scope": [
            f"修改 {task['code']['file']} 中的 {', '.join(task['code']['symbols'])}，使其满足规格条款 "
            + ", ".join(task["spec"]["clauses"])
        ],
        "exclusions": ["不修改 src/ 下的 PowerContext 实现", "不修改测试用例本身"],
        "completion_criteria": [
            f"上下文摘要 sha256={context_sha256}",
            f"目标测试 {task['target_test']} 在修改前失败、修改后通过",
            "其余既有测试不回归",
        ],
        "authorization_notes": ["仅允许修改样例工程工作副本 work/app"],
        "open_questions": [],
    }


def save_contract(
    client: PowerContextClient,
    scope_id: str,
    task: dict[str, Any],
    contract: dict[str, Any],
) -> str:
    source_id = contract_source_id(task["id"])
    try:
        client.create_contract(scope_id, source_id, contract)
    except PowerContextError as error:
        # 同一 source_id 的重复提交返回 409：读取既有证据确认其已持久化。
        if error.status != 409:
            raise
        client.get_source(scope_id, source_id)
    return source_id


def load_contract(client: PowerContextClient, scope_id: str, source_id: str) -> dict[str, Any]:
    record = client.get_source(scope_id, source_id)
    content = record.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return json.loads(content)
    raise ValueError(f"无法从 Source {source_id} 解析 Work Contract")


def save_state(
    client: PowerContextClient,
    scope_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    payload = {"schema": STATE_SCHEMA, **state}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(text.encode("utf-8")) > 8192:
        raise ValueError("任务状态超过 Memory entry 的 8192 字节上限")
    return client.remember(scope_id, "task-state", text, reason="minimax SDD 任务状态（可复用）")


def load_state(client: PowerContextClient, scope_id: str, task_id: str) -> dict[str, Any]:
    entries = client.list_memory_entries(scope_id).get("entries", [])
    matches: list[tuple[int, dict[str, Any]]] = []
    for entry in entries:
        if entry.get("kind") != "task-state":
            continue
        try:
            payload = json.loads(entry.get("text", ""))
        except (TypeError, ValueError):
            continue
        if payload.get("schema") != STATE_SCHEMA or payload.get("task_id") != task_id:
            continue
        matches.append((int(entry.get("version", 0)), payload))
    if not matches:
        raise LookupError(f"PowerContext Memory 中没有 task_id={task_id} 的任务状态")
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def record_outcome(
    client: PowerContextClient,
    scope_id: str,
    task: dict[str, Any],
    *,
    status: str,
    summary: str,
    before_status: str,
    after_status: str,
    patch_sha256: str,
) -> str:
    source_id = outcome_source_id(task["id"])
    outcome = {
        "schema": "powercontext.task-outcome.v1",
        "trust": "untrusted_observation",
        "objective": str(task["objective"]).strip(),
        "status": status,
        "summary": summary,
        "observations": [
            {
                "text": f"补丁 sha256={patch_sha256}；修改前测试={before_status}；修改后测试={after_status}",
                "basis": "declared",
                "evidence": [],
            }
        ],
        "checks": [
            {
                "name": "before-change tests must fail",
                "status": "failed" if before_status == "failed" else "passed",
                "details": f"baseline pytest exit={before_status}",
                "basis": "declared",
                "evidence": [],
            },
            {
                "name": "after-change tests must pass",
                "status": "passed" if after_status == "passed" else "failed",
                "details": f"patched pytest exit={after_status}",
                "basis": "declared",
                "evidence": [],
            },
        ],
        "produced_artifacts": [],
        "remaining_work": [] if status == "succeeded" else ["检查失败的测试并重新生成补丁"],
    }
    client.record_outcome(scope_id, source_id, outcome)
    return source_id
