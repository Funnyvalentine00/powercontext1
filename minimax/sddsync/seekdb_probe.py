"""直连 embedded seekdb：执行真实 SQL，取证「工程资料确实存放在 seekdb 中」。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

TEXTUAL_TYPES = ("char", "text", "json", "clob", "blob")
SAMPLE_LIMIT = 2
SAMPLE_WIDTH = 220
# 关键证据标记：必须能在 seekdb 的表里搜到，证明工程资料与任务状态真的入库了。
EVIDENCE_MARKERS = {
    "规格条款": "优惠不叠加",
    "代码符号": "def compute_refund",
    "测试用例": "def test_member_discount_not_stacked_with_threshold",
    "任务状态": "minimax.sddsync.state.v1",
    "Work Contract": "powercontext.work-contract.v1",
}


def _is_textual(column_type: str) -> bool:
    lowered = column_type.lower()
    return any(token in lowered for token in TEXTUAL_TYPES)


async def _run(cursor, statement: str, parameters: tuple | None = None) -> list[Any]:
    await cursor.execute(statement, parameters)
    return list(await cursor.fetchall())


async def _inspect(path: Path, database: str) -> dict[str, Any]:
    import aiomysql
    import pylibseekdb

    instance = await pylibseekdb.aopen(str(path))
    options = dict(instance.connection_options())
    connection = await aiomysql.connect(
        user=str(options.get("user", "root")),
        password=options.get("password"),
        unix_socket=options.get("unix_socket"),
        db=database,
        autocommit=True,
    )
    queries: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    try:
        cursor = await connection.cursor()
        table_rows = await _run(cursor, "SHOW TABLES")
        queries.append({"sql": "SHOW TABLES", "rows": len(table_rows)})
        for (table,) in table_rows:
            count_rows = await _run(cursor, f"SELECT COUNT(*) FROM `{table}`")
            count = int(count_rows[0][0])
            column_rows = await _run(cursor, f"SHOW COLUMNS FROM `{table}`")
            columns = [
                {"name": row[0], "type": row[1]} for row in column_rows
            ]
            text_column = next(
                (column["name"] for column in columns if _is_textual(str(column["type"]))),
                None,
            )
            sample: list[dict[str, Any]] = []
            if text_column and count:
                sample_rows = await _run(
                    cursor, f"SELECT `{text_column}` FROM `{table}` LIMIT {SAMPLE_LIMIT}"
                )
                for row in sample_rows:
                    value = row[0]
                    if isinstance(value, (bytes, bytearray)):
                        value = value.decode("utf-8", errors="replace")
                    text = str(value)
                    sample.append({"column": text_column, "value": text[:SAMPLE_WIDTH]})
            queries.append({"sql": f"SELECT COUNT(*) FROM `{table}`", "rows": count})
            tables.append(
                {"name": table, "rows": count, "columns": columns, "sample": sample}
            )
        evidence = await _collect_evidence(cursor, tables, queries)
        await cursor.close()
    finally:
        connection.close()
        instance.close()
    return {
        "backend": "embedded seekdb (pylibseekdb)",
        "path": str(path),
        "database": database,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "queries": queries,
        "tables": tables,
        "evidence": evidence,
    }


async def _collect_evidence(
    cursor, tables: list[dict[str, Any]], queries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """用 LIKE 检索确认关键工程资料与任务状态确实落在 seekdb 表里。"""
    evidence: list[dict[str, Any]] = []
    for label, marker in EVIDENCE_MARKERS.items():
        hit: dict[str, Any] | None = None
        for table in tables:
            for column in table["columns"]:
                if not _is_textual(str(column["type"])):
                    continue
                statement = (
                    f"SELECT `{column['name']}` FROM `{table['name']}` "
                    f"WHERE `{column['name']}` LIKE %s LIMIT 1"
                )
                rows = await _run(cursor, statement, (f"%{marker}%",))
                queries.append({"sql": statement.replace("%s", f"'%{marker}%'"), "rows": len(rows)})
                if rows:
                    value = rows[0][0]
                    if isinstance(value, (bytes, bytearray)):
                        value = value.decode("utf-8", errors="replace")
                    position = str(value).find(marker)
                    start = max(0, position - 80)
                    hit = {
                        "label": label,
                        "marker": marker,
                        "table": table["name"],
                        "column": column["name"],
                        "snippet": str(value)[start : start + SAMPLE_WIDTH],
                    }
                    break
            if hit:
                break
        evidence.append(hit or {"label": label, "marker": marker, "found": False})
    return evidence


def inspect_seekdb(path: Path, database: str = "test") -> dict[str, Any]:
    return asyncio.run(_inspect(path, database))


def render_markdown(payload: dict[str, Any]) -> str:
    tables = payload["tables"]
    populated = [table for table in tables if table["rows"] > 0]
    evidence = payload.get("evidence", [])

    lines = [
        "# seekdb 数据库查询记录",
        "",
        f"- 后端：{payload['backend']}",
        f"- 数据目录：`{payload['path']}`",
        f"- 数据库：`{payload['database']}`",
        f"- 采集时间：{payload['captured_at']}",
        f"- 表总数：{len(tables)}；有数据的表：{len(populated)}；总行数：{sum(t['rows'] for t in tables)}",
        "",
        "## 执行的 SQL",
        "",
        "```sql",
        "SHOW TABLES;",
    ]
    for table in populated:
        lines.append(f"SELECT COUNT(*) FROM `{table['name']}`;  -- rows={table['rows']}")
    for item in evidence:
        if not item.get("table"):
            continue
        lines.append(
            f"SELECT `{item['column']}` FROM `{item['table']}` "
            f"WHERE `{item['column']}` LIKE '%{item['marker']}%';  -- 命中 1 行"
        )
    lines.extend(
        [
            "```",
            "",
            "> 上表之外还对每张表的每个文本列执行过同样的 `LIKE` 探测；",
            f"> 完整语句清单（{len(payload['queries'])} 条）见 `queries.sql` 与 `inspect.json`。",
        ]
    )
    lines.extend(["", "## 表与行数", "", "| 表 | 行数 | 文本列 |", "| --- | --- | --- |"])
    for table in tables:
        text_column = next(
            (item["column"] for item in table["sample"] if item.get("column")),
            "-",
        )
        lines.append(f"| `{table['name']}` | {table['rows']} | `{text_column}` |")
    lines.extend(["", "## 工程资料样本（有数据的表）", ""])
    for table in populated:
        for sample in table["sample"]:
            lines.append(f"### `{table['name']}`.`{sample['column']}`")
            lines.append("")
            lines.append("```text")
            lines.append(sample["value"])
            lines.append("```")
            lines.append("")
    lines.extend(["## 关键证据检索（LIKE 命中）", "", "| 证据 | 标记 | 表.列 | 片段 |", "| --- | --- | --- | --- |"])
    for item in evidence:
        if item.get("table"):
            snippet = str(item.get("snippet", "")).replace("|", "\\|").replace("\n", " ")[:160]
            lines.append(
                f"| {item['label']} | `{item['marker']}` | `{item['table']}`.`{item['column']}` | {snippet} |"
            )
        else:
            lines.append(f"| {item['label']} | `{item['marker']}` | 未命中 | - |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
