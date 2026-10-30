"""sddsync 命令行：ingest / status / prepare / apply / test，以及 Server 与 reset 辅助命令。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PC_HOME = DATA_DIR / "pc"
WORK_DIR = ROOT / "work"
APP_DIR = WORK_DIR / "app"
SAMPLE_APP = ROOT / "sample-app"
LOGS_DIR = ROOT / "logs"
PID_FILE = DATA_DIR / "server.pid"
SERVER_LOG = LOGS_DIR / "server.log"
SCOPE_KEY = "minimax-sdd-task-001"
SCOPE_TITLE = "MiniMax SDD 上下文管理"


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _pylibseekdb_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pylibseekdb") is not None


def load_settings() -> None:
    load_env_file(ROOT / ".env")
    os.environ.setdefault("POWERCONTEXT_PORT", "8311")
    os.environ.setdefault("POWERCONTEXT_URL", f"http://127.0.0.1:{os.environ['POWERCONTEXT_PORT']}")
    os.environ.setdefault("DATABASE_KIND", "seekdb")
    os.environ.setdefault("POWERCONTEXT_HOME", str(PC_HOME))
    os.environ.setdefault("POWERCONTEXT_SERVER_DATABASE_KIND", os.environ["DATABASE_KIND"])
    os.environ.setdefault("POWERCONTEXT_SERVER_HTTP_HOST", "127.0.0.1")
    os.environ.setdefault("POWERCONTEXT_SERVER_HTTP_PORT", os.environ["POWERCONTEXT_PORT"])
    os.environ.setdefault("POWERCONTEXT_SERVER_MCP_ENABLED", "false")
    os.environ.setdefault("POWERCONTEXT_SERVER_METRICS_ENABLED", "false")
    os.environ.setdefault("POWERCONTEXT_SERVER_ACCESS_MODE", "disabled")
    os.environ.setdefault("POWERCONTEXT_SRC", str(ROOT.parent / "src"))
    if (
        os.environ["POWERCONTEXT_SERVER_DATABASE_KIND"].lower() == "seekdb"
        and not _pylibseekdb_available()
    ):
        print("[settings] 当前环境没有 pylibseekdb，回退到 SQLite 后端（评测环境为 Linux + seekdb）")
        os.environ["POWERCONTEXT_SERVER_DATABASE_KIND"] = "sqlite"
        os.environ["DATABASE_KIND"] = "sqlite"
    if os.environ["POWERCONTEXT_SERVER_DATABASE_KIND"].lower() == "sqlite":
        os.environ.setdefault(
            "POWERCONTEXT_SERVER_DATABASE_URL",
            f"sqlite+aiosqlite:///{PC_HOME / 'powercontext.db'}",
        )
    else:
        os.environ.setdefault("POWERCONTEXT_SERVER_DATABASE_PATH", str(PC_HOME / "seekdb"))
        os.environ.pop("POWERCONTEXT_SERVER_DATABASE_URL", None)
        # 记录真实执行的 SQL，供「数据库查询记录」取证。
        os.environ.setdefault("POWERCONTEXT_SERVER_DATABASE_ECHO", "true")


def _pythonpath() -> str:
    entries = [str(ROOT), os.environ["POWERCONTEXT_SRC"]]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    return ":".join(entries)


def client():  # 延迟导入，避免 serve 进程加载无关模块。
    from .pc_client import PowerContextClient

    return PowerContextClient(os.environ["POWERCONTEXT_URL"])


def scope_id(pc) -> str:
    return pc.ensure_scope(SCOPE_KEY, SCOPE_TITLE, "规格/代码/测试/Work Contract 的上下文管理样例")


def server_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def server_alive() -> bool:
    return client().health_live()


def start_server(wait_seconds: float = 90.0) -> bool:
    if server_alive():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath()
    log_handle = SERVER_LOG.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "sddsync.cli", "serve"],
        cwd=str(ROOT),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = SERVER_LOG.read_text(encoding="utf-8", errors="replace")[-4000:] if SERVER_LOG.exists() else ""
            raise RuntimeError(f"PowerContext Server 启动失败（exit={process.returncode}）：\n{tail}")
        if server_alive():
            return True
        time.sleep(0.5)
    raise RuntimeError(f"PowerContext Server 在 {wait_seconds:.0f}s 内未就绪，日志: {SERVER_LOG}")


def stop_server(wait_seconds: float = 20.0) -> bool:
    pid = server_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return False
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            PID_FILE.unlink(missing_ok=True)
            return True
        time.sleep(0.3)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return True


def restart_server() -> None:
    old_pid = server_pid()
    stop_server()
    start_server()
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "old_pid": old_pid, "new_pid": server_pid()}
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (LOGS_DIR / "restart.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def reset() -> None:
    stop_server()
    for path in (DATA_DIR, WORK_DIR, LOGS_DIR):
        shutil.rmtree(path, ignore_errors=True)
    for cache in SAMPLE_APP.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    for cache in SAMPLE_APP.rglob(".pytest_cache"):
        shutil.rmtree(cache, ignore_errors=True)
    (LOGS_DIR / "minimax").mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print("[reset] 已清理 data/ work/ logs/，样例工程恢复为未修复基线")


def cmd_serve() -> int:
    from powercontext.server.factory import create_server_app
    from powercontext.server.settings import ServerSettings
    import uvicorn

    settings = ServerSettings()
    application = create_server_app(settings=settings)
    uvicorn.run(
        application,
        host=settings.http.host,
        port=settings.http.port,
        access_log=False,
    )
    return 0


def cmd_start() -> int:
    created = start_server()
    print(f"[start] Server {'已启动' if created else '已在运行'} -> {os.environ['POWERCONTEXT_URL']}")
    print(f"[start] scope_id={scope_id(client())}")
    return 0


def cmd_stop() -> int:
    stopped = stop_server()
    print(f"[stop] {'已停止' if stopped else '没有运行中的 Server'}")
    return 0


def cmd_restart() -> int:
    restart_server()
    print(f"[restart] 新进程 PID={server_pid()}")
    return 0


def cmd_ingest() -> int:
    from .ingest import ingest, save_ingest_manifest

    start_server()
    pc = client()
    scope = scope_id(pc)
    entries = ingest(ROOT, pc, scope)
    save_ingest_manifest(WORK_DIR, entries)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (LOGS_DIR / "ingest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "scope_id": scope,
                 "sources": {key: entry.as_dict() for key, entry in entries.items()}},
                ensure_ascii=False,
            )
            + "\n"
        )
    print(f"[ingest] {len(entries)} 个 Source 已写入 PowerContext scope={scope}")
    for key, entry in entries.items():
        print(f"[ingest]   {key} -> {entry.source_id}")
    return 0


def cmd_prepare() -> int:
    from .context import load_task
    from .ingest import load_ingest_manifest
    from .minimax_client import create_client, extract_unified_diff
    from .state import build_contract, save_contract, save_state

    start_server()
    pc = client()
    scope = scope_id(pc)
    task = load_task(ROOT)

    manifest = load_ingest_manifest(WORK_DIR)
    from .context import build_context, context_digest

    context_text = build_context(ROOT, task, manifest, pc, scope)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "context.md").write_text(context_text, encoding="utf-8")
    ctx_sha = context_digest(context_text)

    contract = build_contract(task, ctx_sha, [entry.as_dict() for entry in manifest.values()])
    contract_id = save_contract(pc, scope, task, contract)

    buggy_source = (SAMPLE_APP / "src" / "refund.py").read_text(encoding="utf-8")
    mm = create_client(ROOT, buggy_source, ctx_sha)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 SDD 编码代理。输入是 PowerContext 提供的规格条款、代码符号与测试用例。"
                "只输出 unified diff，路径使用 a/src/refund.py 与 b/src/refund.py，不要解释。"
            ),
        },
        {"role": "user", "content": context_text + "\n请依据规格 R2 修复 src/refund.py，并保持 R1 上限。\n"},
    ]
    result = mm.chat(messages, "propose_patch")
    patch_text = extract_unified_diff(result.text)
    if "src/refund.py" not in patch_text:
        raise RuntimeError("模型返回的补丁未修改 src/refund.py")
    patch_path = WORK_DIR / "patch.diff"
    patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
    # 补丁指纹一律按文件原始字节计算，保证 Windows / Linux 两侧一致。
    patch_sha = hashlib.sha256(patch_path.read_bytes()).hexdigest()

    state = {
        "task_id": task["id"],
        "scope_id": scope,
        "context_sha256": ctx_sha,
        "contract_source_id": contract_id,
        "patch_sha256": patch_sha,
        "minimax_mode": result.mode,
        "model": result.model,
        "base_url": result.base_url,
        "minimax_log": str(Path(result.log_path).relative_to(ROOT)).replace("\\", "/"),
        "outcome_source_id": None,
    }
    save_state(pc, scope, state)
    meta = {
        **state,
        # 路径写相对 minimax/ 根目录的，便于随仓库一起提交与查阅。
        "minimax_log": str(Path(result.log_path).relative_to(ROOT)).replace("\\", "/"),
        "context_path": str((WORK_DIR / "context.md").relative_to(ROOT)).replace("\\", "/"),
        "patch_path": str(patch_path.relative_to(ROOT)).replace("\\", "/"),
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (WORK_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[prepare] 上下文 {len(context_text)} 字符 sha256={ctx_sha[:16]}")
    print(f"[prepare] Work Contract -> {contract_id}")
    print(f"[prepare] MiniMax mode={result.mode} model={result.model} patch sha256={patch_sha[:16]}")
    return 0


def cmd_apply() -> int:
    from .context import load_task
    from .state import load_contract, load_state

    start_server()
    pc = client()
    scope = scope_id(pc)
    task = load_task(ROOT)

    # 关键：重启后只从 PowerContext Memory 恢复状态，不依赖本地 state 文件。
    state = load_state(pc, scope, task["id"])
    contract = load_contract(pc, scope, state["contract_source_id"])
    if contract.get("objective") != str(task["objective"]).strip():
        raise RuntimeError("从 PowerContext 复用的 Work Contract 与任务目标不一致")

    patch_path = WORK_DIR / "patch.diff"
    patch_bytes = patch_path.read_bytes()
    if hashlib.sha256(patch_bytes).hexdigest() != state["patch_sha256"]:
        raise RuntimeError("补丁 sha256 与 PowerContext 状态不一致")

    shutil.rmtree(APP_DIR, ignore_errors=True)
    shutil.copytree(SAMPLE_APP, APP_DIR)
    for command in (["patch", "-p1", "-N", "--dry-run", "-d", str(APP_DIR)], ["patch", "-p1", "-N", "-d", str(APP_DIR)]):
        completed = subprocess.run(command, input=patch_bytes, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(
                "补丁应用失败: "
                + (completed.stdout + completed.stderr).decode("utf-8", errors="replace")[-2000:]
            )
    baseline = (SAMPLE_APP / "src" / "refund.py").read_text(encoding="utf-8")
    patched = (APP_DIR / "src" / "refund.py").read_text(encoding="utf-8")
    if baseline == patched:
        raise RuntimeError("应用补丁后工作副本没有变化")

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "state_loaded_from": "powercontext-memory",
        "contract_source_id": state["contract_source_id"],
        "server_pid": server_pid(),
        "patch_sha256": state["patch_sha256"],
    }
    with (LOGS_DIR / "apply.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[apply] 已从 PowerContext 恢复状态（contract={state['contract_source_id']}）")
    print(f"[apply] 补丁已应用到 {APP_DIR}")
    return 0


def run_pytest(app_dir: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(app_dir / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=str(app_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout + completed.stderr


def cmd_test() -> int:
    from .context import load_task
    from .state import load_state, record_outcome, save_state

    start_server()
    pc = client()
    scope = scope_id(pc)
    task = load_task(ROOT)
    state = load_state(pc, scope, task["id"])

    before_code, before_out = run_pytest(SAMPLE_APP)
    after_code, after_out = run_pytest(APP_DIR)
    (LOGS_DIR / "tests-before.txt").write_text(before_out, encoding="utf-8")
    (LOGS_DIR / "tests-after.txt").write_text(after_out, encoding="utf-8")

    target = task["target_test"]
    before_failed = before_code != 0 and target in before_out and "AssertionError" in before_out
    after_passed = after_code == 0 and "failed" not in after_out.lower()
    if before_code == 0:
        raise RuntimeError("修改前测试竟然通过，样例基线不成立")
    if not before_failed:
        raise RuntimeError(f"修改前目标测试未以 AssertionError 失败，输出:\n{before_out}")

    report = {
        "before": {"exit_code": before_code, "target_failed_with_assertion": before_failed},
        "after": {"exit_code": after_code, "all_passed": after_passed},
        "target_test": target,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (WORK_DIR / "test-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    succeeded = before_failed and after_passed
    outcome_id = record_outcome(
        pc,
        scope,
        task,
        status="succeeded" if succeeded else "failed",
        summary=f"修改前后对照：before={'failed' if before_failed else 'unexpected'}，after={'passed' if after_passed else 'failed'}",
        before_status="failed" if before_failed else "unexpected",
        after_status="passed" if after_passed else "failed",
        patch_sha256=state["patch_sha256"],
    )
    save_state(pc, scope, {**state, "outcome_source_id": outcome_id})

    print(f"[test] 修改前 exit={before_code}（目标用例以 AssertionError 失败={before_failed}）")
    print(f"[test] 修改后 exit={after_code}（全部通过={after_passed}）")
    print(f"[test] Task Outcome -> {outcome_id}")
    if not succeeded:
        print("[test] 修改前后对比未达标")
        return 1
    return 0


def extract_server_sql(limit: int = 400) -> list[str]:
    """从 Server 日志中抽取真实执行过的 SQL（seekdb 后端开启 echo 后可见）。"""
    if not SERVER_LOG.is_file():
        return []
    import re

    pattern = re.compile(
        r"INFO\s+sqlalchemy\.engine\.Engine\s+(SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE|ALTER TABLE)\b"
    )
    statements: list[str] = []
    for line in SERVER_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        matched = pattern.search(line)
        if not matched:
            continue
        sql = line[matched.start() :].strip()
        statements.append(sql[:800])
        if len(statements) >= limit:
            break
    return statements


def cmd_db_inspect() -> int:
    """直连 embedded seekdb，执行真实 SQL 并导出取证材料。"""
    from .seekdb_probe import inspect_seekdb, render_markdown

    kind = os.environ.get("POWERCONTEXT_SERVER_DATABASE_KIND", "sqlite").lower()
    if kind != "seekdb":
        print(f"[db-inspect] 当前后端为 {kind}，跳过 seekdb 直连取证")
        return 0
    path = PC_HOME / "seekdb"
    if not path.exists():
        print(f"[db-inspect] 缺少 seekdb 数据目录 {path}")
        return 1
    stop_server()
    try:
        payload = inspect_seekdb(path)
    finally:
        start_server()
    db_logs = LOGS_DIR / "db"
    db_logs.mkdir(parents=True, exist_ok=True)
    (db_logs / "inspect.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = render_markdown(payload)
    server_sql = extract_server_sql()
    if server_sql:
        (db_logs / "queries.sql").write_text(
            "-- 由 Server 日志抽取的真实 SQL（PowerContext -> embedded seekdb）\n"
            + "\n".join(f"{statement};" for statement in server_sql)
            + "\n",
            encoding="utf-8",
        )
        markdown += (
            f"\n## Server 实际执行的 SQL（节选 {min(60, len(server_sql))}/{len(server_sql)} 条）\n\n"
            "```sql\n" + "\n".join(server_sql[:60]) + "\n```\n"
            "\n> 完整清单见同目录 `queries.sql`。\n"
        )
    (db_logs / "inspect.md").write_text(markdown, encoding="utf-8")
    total_rows = sum(int(table["rows"]) for table in payload["tables"])
    print(f"[db-inspect] seekdb {len(payload['tables'])} 张表，共 {total_rows} 行 -> {db_logs / 'inspect.md'}")
    return 0


def cmd_status() -> int:
    from .state import load_state

    start_server()
    pc = client()
    scope = scope_id(pc)
    sources = pc.list_sources(scope, limit=100).get("items", [])
    entries = pc.list_memory_entries(scope).get("entries", [])
    print(f"[status] url={os.environ['POWERCONTEXT_URL']} scope={scope}")
    print(f"[status] sources={len(sources)} memory_entries={len(entries)}")
    try:
        state = load_state(pc, scope, "task-001")
        print(f"[status] state={json.dumps(state, ensure_ascii=False)}")
    except LookupError:
        print("[status] 尚无任务状态")
    return 0


def cmd_all() -> int:
    reset()
    start_server()
    cmd_ingest()
    cmd_prepare()
    restart_server()
    print("[all] Server 已重启；apply/test 将只依赖 PowerContext 中的状态")
    cmd_apply()
    if cmd_test() != 0:
        return 1
    cmd_db_inspect()
    verify = subprocess.run([sys.executable, str(ROOT / "verify.py")], cwd=str(ROOT), env=os.environ.copy())
    return verify.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddsync")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, function in (
        ("serve", cmd_serve),
        ("start", cmd_start),
        ("stop", cmd_stop),
        ("restart", cmd_restart),
        ("reset", reset),
        ("ingest", cmd_ingest),
        ("status", cmd_status),
        ("prepare", cmd_prepare),
        ("apply", cmd_apply),
        ("test", cmd_test),
        ("db-inspect", cmd_db_inspect),
        ("all", cmd_all),
    ):
        subparsers.add_parser(name).set_defaults(function=function)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_settings()
    arguments = build_parser().parse_args(argv)
    return arguments.function()


if __name__ == "__main__":
    sys.exit(main())
