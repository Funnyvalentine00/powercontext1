"""按任务拼装上下文：规格条款 + 代码符号/行号 + 测试用例 id。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import yaml

from .ingest import SourceEntry, sha256_text
from .pc_client import PowerContextClient

# 动态部分起点：其后的回读/检索片段不参与上下文摘要。
DYNAMIC_MARKER = "## PowerContext 证据回读"


def load_task(root: Path) -> dict[str, Any]:
    task_path = root / "tasks" / "task-001.yaml"
    return yaml.safe_load(task_path.read_text(encoding="utf-8"))


def extract_clause(spec_text: str, clause_id: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(clause_id)}\b.*?(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(spec_text)
    if not match:
        raise ValueError(f"规格中找不到条款 {clause_id}")
    lines = match.group(0).strip().splitlines()
    # 去掉 markdown 标题行，避免与上下文里的 "### R1" 重复。
    return "\n".join(lines[1:]).strip() if lines else ""


def extract_symbols(source_text: str, symbol_names: list[str]) -> dict[str, tuple[int, int, str]]:
    tree = ast.parse(source_text)
    found: dict[str, tuple[int, int, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in symbol_names:
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            segment = ast.get_source_segment(source_text, node) or ""
            found[node.name] = (start, end, segment)
    missing = [name for name in symbol_names if name not in found]
    if missing:
        raise ValueError(f"代码中找不到符号: {', '.join(missing)}")
    return found


def extract_tests(source_text: str) -> dict[str, tuple[int, int]]:
    tree = ast.parse(source_text)
    found: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            found[node.name] = (node.lineno, getattr(node, "end_lineno", node.lineno))
    return found


def _source_line(entry: SourceEntry) -> str:
    return f"[source: {entry.source_id} | path: {entry.path} | sha256: {entry.sha256}]"


def build_context(
    root: Path,
    task: dict[str, Any],
    sources: dict[str, SourceEntry],
    client: PowerContextClient | None = None,
    scope_id: str | None = None,
) -> str:
    spec_path = task["spec"]["file"]
    code_path = task["code"]["file"]
    test_path = task["tests"]["file"]
    spec_text = (root / spec_path).read_text(encoding="utf-8")
    code_text = (root / code_path).read_text(encoding="utf-8")
    test_text = (root / test_path).read_text(encoding="utf-8")

    parts: list[str] = [
        f"# SDD 任务上下文 — {task['id']}",
        "",
        "## 任务目标",
        "",
        str(task["objective"]).strip(),
        "",
    ]

    parts.extend(["", "## 规格条款", ""])
    for clause_id in task["spec"]["clauses"]:
        clause = extract_clause(spec_text, clause_id)
        parts.extend([f"### {clause_id}", _source_line(sources[spec_path]), "", clause, ""])

    symbols = extract_symbols(code_text, list(task["code"]["symbols"]))
    parts.extend(["", "## 代码符号", ""])
    for name in task["code"]["symbols"]:
        start, end, segment = symbols[name]
        parts.extend(
            [
                f"### {name} ({code_path}:L{start}-L{end})",
                _source_line(sources[code_path]),
                "",
                "```python",
                segment,
                "```",
                "",
            ]
        )

    tests = extract_tests(test_text)
    parts.extend(["", "## 测试用例", ""])
    for test_id in task["tests"]["ids"]:
        if test_id not in tests:
            raise ValueError(f"测试文件中找不到用例 {test_id}")
        start, end = tests[test_id]
        parts.extend([f"### {test_path}::{test_id} (L{start}-L{end})", _source_line(sources[test_path]), ""])

    parts.extend(
        [
            "",
            "## 代码全文（供生成补丁）",
            "",
            f"[source: {sources[code_path].source_id} | path: {code_path}]",
            "```python",
            code_text.rstrip(),
            "```",
            "",
        ]
    )

    if client is not None and scope_id:
        readbacks: list[str] = []
        for relpath in (spec_path, code_path, test_path):
            entry = sources[relpath]
            record = client.get_source(scope_id, entry.source_id)
            content = record.get("content")
            if not isinstance(content, str):
                raise ValueError(f"Source {entry.source_id} 的内容不是文本")
            digest = sha256_text(content)
            if digest != entry.sha256:
                raise ValueError(f"Source {entry.source_id} 回读内容与采集时 sha256 不一致")
            readbacks.append(f"[readback: {entry.source_id} sha256={digest}]")
        parts.extend(
            [
                "",
                "## PowerContext 证据回读",
                "",
                "以下证据在生成上下文时从 PowerContext Source API 读取并复核 sha256：",
                "",
            ]
            + readbacks
        )

    if client is not None and scope_id:
        query = " ".join(
            [str(task["title"]), *task["spec"]["clauses"], *task["code"]["symbols"]]
        )
        recalled = client.prepare_context(scope_id, query=query, max_bytes=4000)
        content = recalled.get("content") or ""
        parts.extend(
            [
                "",
                "## 数据库检索结果（seekdb 全文索引）",
                "",
                f"- 检索式：`{query}`",
                f"- 命中字节：{recalled.get('content_bytes', 0)}",
                "- 来源：PowerContext prepare_context（底层在 embedded seekdb 上执行检索）",
                "",
            ]
        )
        if content.strip():
            parts.extend([content.strip(), ""])
        else:
            parts.extend(["（全文索引未命中，规格与代码以上面的 Source 回读内容为准）", ""])

    context_text = "\n".join(parts).rstrip() + "\n"
    missing = [
        token for token in task.get("required_context_tokens", []) if token not in context_text
    ]
    if missing:
        raise ValueError(f"上下文缺少任务要求的内容: {', '.join(missing)}")
    return context_text


def context_digest(context_text: str) -> str:
    """上下文摘要：只覆盖确定性部分（任务/规格/代码/测试）。

    回读与检索片段随数据库运行状态变化，不参与摘要，
    这样同一份输入工程始终得到同一个摘要，补丁可被精确复用。
    """
    head = context_text.split(DYNAMIC_MARKER, 1)[0]
    return sha256_text(head)
