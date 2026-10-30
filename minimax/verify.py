"""6 项验收自动检查：退出码 0 表示无 FAIL（SKIP 可接受）。"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import hashlib
import os

from sddsync import cli
from sddsync.context import load_task
from sddsync.ingest import load_ingest_manifest
from sddsync.minimax_client import DEFAULT_MODEL, extract_unified_diff
from sddsync.state import load_contract, load_state

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
RESULTS: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str) -> None:
    RESULTS.append((name, status, detail))


def check_runnable() -> None:
    required = [
        cli.ROOT / "bootstrap.sh",
        cli.ROOT / "run.sh",
        cli.ROOT / "verify.py",
        cli.ROOT / "README.md",
        cli.ROOT / "TECHNICAL-NOTE.md",
        cli.ROOT / "docs" / "minimax-development-log.md",
        cli.ROOT / "docs" / "verification-sample.md",
        cli.ROOT / "docs" / "code-diff.md",
        cli.ROOT / "patches" / "index.json",
        cli.ROOT / "tasks" / "task-001.yaml",
        cli.SAMPLE_APP / "spec" / "refund.md",
        cli.SAMPLE_APP / "src" / "refund.py",
        cli.SAMPLE_APP / "tests" / "test_refund.py",
        cli.WORK_DIR / "context.md",
        cli.WORK_DIR / "patch.diff",
        cli.WORK_DIR / "test-report.json",
        cli.APP_DIR / "src" / "refund.py",
        cli.LOGS_DIR / "minimax" / "calls.jsonl",
        cli.LOGS_DIR / "db" / "inspect.json",
    ]
    missing = [str(path.relative_to(cli.ROOT)) for path in required if not path.exists()]
    if missing:
        record("1. 可运行", FAIL, "缺少产物: " + ", ".join(missing))
        return
    pc = cli.client()
    if not (pc.health_live() and pc.health_ready()):
        record("1. 可运行", FAIL, "PowerContext Server 未就绪")
        return
    record("1. 可运行", PASS, f"Server ready；{len(required)} 个产物齐全；scope={cli.scope_id(pc)}")


def _read_last_minimax_record() -> dict | None:
    path = cli.LOGS_DIR / "minimax" / "calls.jsonl"
    if not path.is_file():
        return None
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def check_minimax() -> None:
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    meta_path = cli.WORK_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    mode = meta.get("minimax_mode", "mock")
    task = load_task(cli.ROOT)

    if mode == "mock":
        record(
            "2. MiniMax 真实参与",
            SKIP,
            f"补丁来自确定性 MockClient（mode=mock），不计为真实参与；配置 MINIMAX_API_KEY 可切到官方 API",
        )
        return
    if mode not in ("real", "assistant_session"):
        record("2. MiniMax 真实参与", FAIL, f"未知的 MiniMax 接入模式: {mode}")
        return
    if api_key and mode != "real":
        record("2. MiniMax 真实参与", FAIL, f"配置了 API Key 但补丁来自 mode={mode}")
        return
    log = _read_last_minimax_record()
    if not log or log.get("mode") != mode or log.get("purpose") != "propose_patch":
        record("2. MiniMax 真实参与", FAIL, f"logs/minimax 中没有 mode={mode} 的 propose_patch 调用记录")
        return
    if not log.get("base_url") or "mock" in log.get("base_url", "").lower():
        record("2. MiniMax 真实参与", FAIL, f"base_url 不可信: {log.get('base_url')}")
        return
    model = str(log.get("model", ""))
    if not model.startswith("MiniMax"):
        record("2. MiniMax 真实参与", FAIL, f"模型不是 MiniMax 系列: {model}")
        return
    if mode == "real" and model != DEFAULT_MODEL:
        record("2. MiniMax 真实参与", FAIL, f"模型不符: {model} != {DEFAULT_MODEL}")
        return
    messages = json.dumps(log.get("messages", []), ensure_ascii=False)
    missing_tokens = [token for token in task.get("required_context_tokens", []) if token not in messages]
    if missing_tokens:
        record("2. MiniMax 真实参与", FAIL, "MiniMax 请求消息缺少任务上下文: " + ", ".join(missing_tokens))
        return
    try:
        logged_diff = extract_unified_diff(log.get("response_text", ""))
    except Exception as error:  # noqa: BLE001
        record("2. MiniMax 真实参与", FAIL, f"响应无法提取补丁: {error}")
        return
    local_diff = (cli.WORK_DIR / "patch.diff").read_text(encoding="utf-8")
    if logged_diff.strip() != local_diff.strip():
        record("2. MiniMax 真实参与", FAIL, "补丁与 MiniMax 响应不一致")
        return

    if mode == "assistant_session":
        patch_file = str(log.get("patch_file", ""))
        committed = cli.ROOT / "patches" / patch_file
        if not committed.is_file():
            record("2. MiniMax 真实参与", FAIL, f"会话补丁文件不存在: patches/{patch_file}")
            return
        digest = hashlib.sha256(committed.read_bytes()).hexdigest()
        if digest != log.get("patch_sha256"):
            record("2. MiniMax 真实参与", FAIL, "仓库中的会话补丁与调用记录 sha256 不一致")
            return
        index_path = cli.ROOT / "patches" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {"patches": []}
        entry = next(
            (item for item in index.get("patches", []) if item.get("file") == patch_file),
            None,
        )
        if entry is None:
            record("2. MiniMax 真实参与", FAIL, f"补丁索引中没有登记 patches/{patch_file}")
            return
        if entry.get("patch_sha256") != digest or entry.get("context_sha256") != log.get("context_sha256"):
            record("2. MiniMax 真实参与", FAIL, "补丁索引登记的指纹与实际补丁不一致")
            return
        dev_log = cli.ROOT / "docs" / "minimax-development-log.md"
        if not dev_log.is_file():
            record("2. MiniMax 真实参与", FAIL, "缺少 docs/minimax-development-log.md 开发记录")
            return
        dev_text = dev_log.read_text(encoding="utf-8")
        for token in (digest, model, task["id"]):
            if token not in dev_text:
                record("2. MiniMax 真实参与", FAIL, f"开发记录缺少 {token}")
                return
        record(
            "2. MiniMax 真实参与",
            PASS,
            f"mode={mode} model={model} session={log.get('session')} "
            f"patch=patches/{patch_file} sha256={digest[:16]}；开发记录 docs/minimax-development-log.md 已核对",
        )
        return

    record(
        "2. MiniMax 真实参与",
        PASS,
        f"mode={mode} model={model} base_url={log.get('base_url')} latency={log.get('latency_ms')}ms",
    )


def check_context() -> None:
    task = load_task(cli.ROOT)
    context_path = cli.WORK_DIR / "context.md"
    if not context_path.is_file():
        record("3. 上下文正确", FAIL, "缺少 work/context.md")
        return
    text = context_path.read_text(encoding="utf-8")
    missing_tokens = [token for token in task.get("required_context_tokens", []) if token not in text]
    if missing_tokens:
        record("3. 上下文正确", FAIL, "上下文缺少: " + ", ".join(missing_tokens))
        return
    code_symbol = re.search(rf"{re.escape(task['code']['file'])}:L\d+-L\d+", text)
    test_symbol = re.search(
        rf"{re.escape(task['tests']['file'])}::{re.escape(task['target_test'])} \(L\d+-L\d+\)", text
    )
    if not code_symbol or not test_symbol:
        record("3. 上下文正确", FAIL, "代码符号/测试用例缺少行号引用")
        return
    if "[source: minimax:" not in text:
        record("3. 上下文正确", FAIL, "条款/代码/测试缺少 PowerContext Source 引用")
        return
    log = _read_last_minimax_record()
    if not log or any(
        token not in json.dumps(log.get("messages", []), ensure_ascii=False)
        for token in task["required_context_tokens"]
    ):
        record("3. 上下文正确", FAIL, "MiniMax 请求消息未包含完整任务上下文")
        return
    try:
        manifest = load_ingest_manifest(cli.WORK_DIR)
        pc = cli.client()
        scope = cli.scope_id(pc)
        resolved = [path for path in manifest if pc.get_source(scope, manifest[path].source_id)]
    except Exception as error:  # noqa: BLE001
        record("3. 上下文正确", FAIL, f"Source 证据无法回查: {error}")
        return
    record(
        "3. 上下文正确",
        PASS,
        f"条款 {task['spec']['clauses']} + 代码行号 {code_symbol.group(0)} + 用例 {task['target_test']}；{len(resolved)} 个 Source 可回查",
    )


def _sqlite_stats() -> tuple[int, int, list[str]]:
    db = cli.PC_HOME / "powercontext.db"
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        rows = sum(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables)
    finally:
        connection.close()
    return db.stat().st_size, rows, tables


def check_database() -> None:
    pc = cli.client()
    scope = cli.scope_id(pc)
    try:
        sources = pc.list_sources(scope, limit=100).get("items", [])
        entries = pc.list_memory_entries(scope).get("entries", [])
    except Exception as error:  # noqa: BLE001
        record("4. 数据库真实参与", FAIL, f"无法通过 API 读取数据库内容: {error}")
        return
    kind = os.environ.get("POWERCONTEXT_SERVER_DATABASE_KIND", "sqlite")
    if kind.lower() == "sqlite":
        db = cli.PC_HOME / "powercontext.db"
        if not db.is_file():
            record("4. 数据库真实参与", FAIL, f"缺少 SQLite 数据库文件 {db}")
            return
        size, rows, tables = _sqlite_stats()
        if size <= 0 or rows <= 0:
            record("4. 数据库真实参与", FAIL, "数据库文件为空")
            return
        detail = (
            f"SQLite {db.name} {size} bytes，{len(tables)} 张表 {rows} 行；"
            f"API 读到 {len(sources)} 个 Source、{len(entries)} 条 Memory"
        )
    else:
        path = cli.PC_HOME / "seekdb"
        if not path.exists():
            record("4. 数据库真实参与", FAIL, f"缺少 seekdb 目录 {path}")
            return
        inspect_path = cli.LOGS_DIR / "db" / "inspect.json"
        if not inspect_path.is_file():
            record("4. 数据库真实参与", FAIL, "缺少 db-inspect 取证材料 logs/db/inspect.json")
            return
        payload = json.loads(inspect_path.read_text(encoding="utf-8"))
        evidence = payload.get("evidence", [])
        hits = [item for item in evidence if item.get("table")]
        if len(hits) < 4:
            record(
                "4. 数据库真实参与",
                FAIL,
                f"seekdb 中只命中 {len(hits)}/{len(evidence)} 条关键证据（规格/代码/测试/任务状态）",
            )
            return
        tables = payload.get("tables", [])
        total_rows = sum(int(table["rows"]) for table in tables)
        if total_rows <= 0:
            record("4. 数据库真实参与", FAIL, "seekdb 中没有任何数据行")
            return
        detail = (
            f"seekdb {path}：{len(tables)} 张表 {total_rows} 行；"
            f"命中 {len(hits)} 条关键证据（{', '.join(item['label'] for item in hits)}）；"
            f"API 读到 {len(sources)} 个 Source、{len(entries)} 条 Memory"
        )
    if len(sources) < 6 or not entries:
        record("4. 数据库真实参与", FAIL, "数据库中的 Source/Memory 数量不足")
        return
    context_text = (cli.WORK_DIR / "context.md").read_text(encoding="utf-8")
    readbacks = re.findall(r"\[readback: (minimax:[^\]\s]+) sha256=([0-9a-f]{64})\]", context_text)
    if len(readbacks) < 3:
        record("4. 数据库真实参与", FAIL, f"上下文生成时只回读了 {len(readbacks)} 个 Source")
        return
    for source_id, digest in readbacks:
        content = pc.get_source(scope, source_id).get("content")
        if hashlib.sha256(str(content).encode("utf-8")).hexdigest() != digest:
            record("4. 数据库真实参与", FAIL, f"上下文回读的 Source 内容不一致: {source_id}")
            return
    record(
        "4. 数据库真实参与",
        PASS,
        f"{detail}；生成上下文时回读并复核 {len(readbacks)} 个 Source，Memory 经 API 读取",
    )


def check_restart_reuse() -> None:
    task = load_task(cli.ROOT)
    old_pid = cli.server_pid()
    try:
        cli.restart_server()
    except Exception as error:  # noqa: BLE001
        record("5. 重启后状态复用", FAIL, f"重启失败: {error}")
        return
    new_pid = cli.server_pid()
    if old_pid is None or new_pid is None or old_pid == new_pid:
        record("5. 重启后状态复用", FAIL, f"PID 未变化 old={old_pid} new={new_pid}")
        return
    pc = cli.client()
    scope = cli.scope_id(pc)
    try:
        state = load_state(pc, scope, task["id"])
        contract = load_contract(pc, scope, state["contract_source_id"])
    except Exception as error:  # noqa: BLE001
        record("5. 重启后状态复用", FAIL, f"重启后无法从 PowerContext 恢复状态: {error}")
        return
    patch_sha = hashlib.sha256((cli.WORK_DIR / "patch.diff").read_bytes()).hexdigest()
    if state.get("patch_sha256") != patch_sha:
        record("5. 重启后状态复用", FAIL, "重启后 patch sha256 不一致")
        return
    if contract.get("objective") != str(task["objective"]).strip():
        record("5. 重启后状态复用", FAIL, "重启后 Work Contract 目标不一致")
        return
    record(
        "5. 重启后状态复用",
        PASS,
        f"PID {old_pid}->{new_pid}；从 Memory 恢复 state，从 Source 回读 Work Contract，patch sha256 一致",
    )


def check_modification() -> None:
    report_path = cli.WORK_DIR / "test-report.json"
    if not report_path.is_file():
        record("6. 修改前后测试对比", FAIL, "缺少 work/test-report.json")
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    task = load_task(cli.ROOT)
    before_code, before_out = cli.run_pytest(cli.SAMPLE_APP)
    after_code, after_out = cli.run_pytest(cli.APP_DIR)
    before_ok = before_code != 0 and task["target_test"] in before_out and "AssertionError" in before_out
    after_ok = after_code == 0
    files_differ = (cli.SAMPLE_APP / "src" / "refund.py").read_text(encoding="utf-8") != (
        cli.APP_DIR / "src" / "refund.py"
    ).read_text(encoding="utf-8")
    if not (report["before"]["target_failed_with_assertion"] and report["after"]["all_passed"]):
        record("6. 修改前后测试对比", FAIL, "报告未记录 改前失败/改后通过")
        return
    if not (before_ok and after_ok and files_differ):
        record(
            "6. 修改前后测试对比",
            FAIL,
            f"复跑不一致: before={before_code} after={after_code} files_differ={files_differ}",
        )
        return
    record(
        "6. 修改前后测试对比",
        PASS,
        f"基线 pytest exit={before_code}（{task['target_test']} AssertionError），修复后 exit={after_code}，源码确有差异",
    )


def main() -> int:
    cli.load_settings()
    cli.start_server()
    for check in (
        check_runnable,
        check_minimax,
        check_context,
        check_database,
        check_restart_reuse,
        check_modification,
    ):
        try:
            check()
        except Exception as error:  # noqa: BLE001
            record(check.__name__, FAIL, f"异常: {error}")
    print("MiniMax SDD 上下文管理 —— 6 项验收")
    failed = 0
    for name, status, detail in RESULTS:
        print(f"[{status}] {name}: {detail}")
        if status == FAIL:
            failed += 1
    print(
        f"结果: {sum(1 for _, s, _ in RESULTS if s == PASS)} PASS / "
        f"{sum(1 for _, s, _ in RESULTS if s == SKIP)} SKIP / {failed} FAIL"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
