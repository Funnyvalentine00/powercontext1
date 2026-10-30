"""rca 命令行入口：定义命令与参数，业务实现分布在 store / parser / evidence / report / state。

本文件中的环境准备（配置、PowerContext Server 启停）已可直接使用；
标了 TODO 的命令由 Qoder 按 docs/DESIGN.md 的任务清单实现。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import state as task_state
from . import textutil
from .evidence import (
    AspectResult,
    EvidenceBook,
    Gap,
    coverage_ratio,
    detect_gaps,
    select_for_aspect,
    split_aspects,
)
from .parser import build_chunks, load_documents
from .pc_client import PowerContextClient
from .report import (
    SECTION_OVERVIEW,
    STATUS_LABEL,
    ReportMeta,
    parse_evidence_rows,
    parse_gap_count,
    render_report,
)
from .store import SeekdbStore

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CORPUS_DIR = DATA_DIR / "corpus"
# 数据目录可在 .env 里用 RCA_SEEKDB_PATH / RCA_PC_HOME 覆盖：
# WSL 的 /mnt/d 是 drvfs，不支持 fallocate，seekdb 必须落在原生 ext4 上。
SEEKDB_PATH = DATA_DIR / "seekdb"
PC_HOME = DATA_DIR / "pc"
WORK_DIR = ROOT / "work"
REPORTS_DIR = WORK_DIR / "reports"
LOGS_DIR = ROOT / "logs"
PID_FILE = DATA_DIR / "server.pid"
SERVER_LOG = LOGS_DIR / "server.log"
QUERY_LOG = LOGS_DIR / "db-queries.jsonl"
SCOPE_KEY = "rca-research"
SCOPE_TITLE = "科研上下文助手"


# ---------------------------------------------------------------- 环境（可直接使用）


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
    """读取 .env 与默认配置；seekdb 不可用时回退 sqlite（仅用于非 Linux 环境调试）。"""
    global SEEKDB_PATH, PC_HOME
    load_env_file(ROOT / ".env")
    # 允许把数据目录挪到 WSL 原生 ext4（见 DESIGN 9.12）；不改就仍用 data/ 下默认路径。
    override_seekdb = os.environ.get("RCA_SEEKDB_PATH", "").strip()
    if override_seekdb:
        SEEKDB_PATH = Path(override_seekdb)
    override_pc = os.environ.get("RCA_PC_HOME", "").strip()
    if override_pc:
        PC_HOME = Path(override_pc)
    os.environ.setdefault("POWERCONTEXT_PORT", "8312")
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
        os.environ.setdefault("POWERCONTEXT_SERVER_DATABASE_ECHO", "true")


def _pythonpath() -> str:
    entries = [str(ROOT / "src"), os.environ["POWERCONTEXT_SRC"]]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    return ":".join(entries)


def client() -> PowerContextClient:
    return PowerContextClient(os.environ["POWERCONTEXT_URL"])


def scope_id(pc: PowerContextClient) -> str:
    return pc.ensure_scope(SCOPE_KEY, SCOPE_TITLE, "文献分块入库、任务状态与研究报告的上下文服务")


def server_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def start_server(wait_seconds: float = 90.0) -> bool:
    if client().health_live():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath()
    log_handle = SERVER_LOG.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "rca.cli", "serve"],
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
        if client().health_live():
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


def restart_server() -> tuple[int | None, int | None]:
    old_pid = server_pid()
    stop_server()
    start_server()
    new_pid = server_pid()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (LOGS_DIR / "restart.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "old_pid": old_pid, "new_pid": new_pid}
            )
            + "\n"
        )
    return old_pid, new_pid


# ---------------------------------------------------------------- 命令


def cmd_serve(_arguments: argparse.Namespace | None = None) -> int:
    from powercontext.server.factory import create_server_app
    from powercontext.server.settings import ServerSettings
    import uvicorn

    settings = ServerSettings()
    application = create_server_app(settings=settings)
    uvicorn.run(application, host=settings.http.host, port=settings.http.port, access_log=False)
    return 0


def cmd_start(_arguments: argparse.Namespace | None = None) -> int:
    created = start_server()
    print(f"[start] PowerContext Server {'已启动' if created else '已在运行'} -> {os.environ['POWERCONTEXT_URL']}")
    print(f"[start] scope_id={scope_id(client())}")
    return 0


def cmd_stop(_arguments: argparse.Namespace | None = None) -> int:
    print(f"[stop] {'已停止' if stop_server() else '没有运行中的 Server'}")
    return 0


def cmd_restart(_arguments: argparse.Namespace | None = None) -> int:
    old_pid, new_pid = restart_server()
    print(f"[restart] PID {old_pid} -> {new_pid}；之后的 resume/verify 只依赖 PowerContext 中的状态")
    return 0


def cmd_reset(_arguments: argparse.Namespace | None = None) -> int:
    stop_server()
    # 只清运行态；data/corpus 是作品输入语料，绝不能随 data/ 一起删掉（DESIGN 9.11）。
    for path in (SEEKDB_PATH, PC_HOME, WORK_DIR, LOGS_DIR):
        shutil.rmtree(path, ignore_errors=True)
    PID_FILE.unlink(missing_ok=True)
    print(f"[reset] 已清理 {SEEKDB_PATH}、{PC_HOME}、{PID_FILE}、work/、logs/（data/corpus 保留）")
    return 0


def cmd_ingest(arguments: argparse.Namespace) -> int:
    """扫描语料 -> 解析分块 -> 写入 seekdb，打印每篇文献的块数。"""
    corpus_dir = Path(arguments.path).resolve() if arguments.path else CORPUS_DIR
    documents = load_documents(corpus_dir)
    chunks = build_chunks(documents)

    async def run() -> tuple[dict[str, int], dict[str, int]]:
        async with SeekdbStore(SEEKDB_PATH, QUERY_LOG) as store:
            counts = await store.replace_documents(chunks)
            return counts, await store.stats()

    counts, totals = asyncio.run(run())
    for document in documents:
        print(f"[ingest] {document.doc_id}: {counts[document.doc_id]} 块（{document.title}）")
    print(
        f"[ingest] 共 {len(documents)} 篇文献、{totals['chunks']} 个块 -> {SEEKDB_PATH}"
        f"（SQL 记录：{QUERY_LOG}）"
    )
    return 0


def ensure_server() -> None:
    """需要 PowerContext 的命令先确保 Server 可用（已运行时不重复启动）。"""
    if start_server():
        print(f"[pc] PowerContext Server 已启动 -> {os.environ['POWERCONTEXT_URL']}")


def _progress_section(previous: dict) -> str:
    statuses = previous.get("statuses") or {}
    aspects = previous.get("aspects") or []
    gaps = previous.get("gaps") or []
    aspect_text = "、".join(f"{aspect}（{statuses.get(aspect, '未知')}）" for aspect in aspects) or "无"
    gap_text = "、".join(f"{gap.get('aspect')}（{gap.get('kind')}）" for gap in gaps) or "无"
    return "\n".join(
        [
            "## 零、上次任务进展（从 PowerContext 复用）",
            "",
            f"- 上次任务：{previous.get('task_id')}（更新于 {previous.get('updated_at') or '未知'}）",
            f"- 上次子问题：{aspect_text}",
            f"- 上次证据：{len(previous.get('evidence') or [])} 条",
            f"- 遗留缺口：{gap_text}",
        ]
    )


def _evidence_rows(results: list[AspectResult]) -> list[dict[str, object]]:
    """按子问题顺序摊平证据并按 chunk 去重，只保留状态契约里的四个字段。"""
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for result in results:
        for item in result.evidence:
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            rows.append(
                {
                    "ref": item.ref,
                    "chunk_id": item.chunk_id,
                    "doc_id": item.doc_id,
                    "sha256": item.sha256,
                }
            )
    return rows


def _state_payload(
    meta: ReportMeta,
    results: list[AspectResult],
    gaps: list[Gap],
    documents: list[str],
    source_id: str,
    digest: str,
    totals: dict[str, int],
) -> dict:
    return task_state.build_state(
        task_id=meta.task_id,
        question=meta.question,
        aspects=[result.aspect for result in results],
        statuses={result.aspect: result.status for result in results},
        evidence=_evidence_rows(results),
        gaps=[gap.as_mapping() for gap in gaps],
        documents=documents,
        report_source_id=source_id,
        report_sha256=digest,
        chunk_stats=totals,
    )


def _fit_state(
    meta: ReportMeta,
    results: list[AspectResult],
    gaps: list[Gap],
    documents: list[str],
    source_id: str,
    digest: str,
    totals: dict[str, int],
) -> dict:
    """超过 8192 字节时按 DESIGN 9.4 裁剪证据：先丢 missing，再按 score 升序丢且每子问题留 1 条。"""
    payload = _state_payload(meta, results, gaps, documents, source_id, digest, totals)
    while task_state.state_size(payload) > task_state.MAX_STATE_BYTES:
        candidates = sorted(
            ((result, item) for result in results for item in result.evidence),
            key=lambda pair: pair[1].score,
        )
        removed = False
        for result, item in candidates:
            if len(result.evidence) <= 1:
                continue
            sharing = [
                other
                for other in results
                if other is not result and any(entry.chunk_id == item.chunk_id for entry in other.evidence)
            ]
            if any(len(other.evidence) <= 1 for other in sharing):
                continue
            for owner in [result, *sharing]:
                owner.evidence = [entry for entry in owner.evidence if entry.chunk_id != item.chunk_id]
            removed = True
            break
        if not removed:
            raise ValueError(
                f"任务状态超过 Memory 上限 {task_state.MAX_STATE_BYTES} 字节且无法继续裁剪；请减少子问题数量"
            )
        payload = _state_payload(meta, results, gaps, documents, source_id, digest, totals)
    return payload


def cmd_ask(arguments: argparse.Namespace) -> int:
    """检索 -> 选证据 -> 判缺口 -> 渲染报告 -> 写 PowerContext Source 与 Memory 状态。"""
    explicit = None
    if arguments.aspects:
        explicit = [part.strip() for part in arguments.aspects.split(",") if part.strip()]

    ensure_server()
    pc = client()
    scope = scope_id(pc)
    previous = None
    if arguments.task:
        try:
            previous = task_state.load_state(pc, scope, arguments.task)
        except LookupError:
            previous = None

    async def run() -> tuple[list[AspectResult], list[Gap], EvidenceBook, dict[str, int], list[str]]:
        async with SeekdbStore(SEEKDB_PATH, QUERY_LOG) as store:
            book = EvidenceBook()
            results = []
            for aspect in split_aspects(arguments.question, explicit):
                candidates = await store.search(textutil.tokens(aspect))
                results.append(select_for_aspect(aspect, candidates, book))
            documents = [str(document["doc_id"]) for document in await store.list_documents()]
            return results, detect_gaps(results), book, await store.stats(), documents

    results, gaps, book, totals, documents = asyncio.run(run())
    meta = ReportMeta(
        task_id=arguments.task or "research-001",
        question=arguments.question,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        documents=totals["documents"],
        chunks=totals["chunks"],
        corpus_dir=str(CORPUS_DIR),
    )
    report_text = render_report(meta, results, gaps, book)
    if previous is not None:
        report_text = report_text.replace(
            SECTION_OVERVIEW, f"{_progress_section(previous)}\n\n{SECTION_OVERVIEW}", 1
        )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{meta.task_id}.md"
    report_path.write_text(report_text, encoding="utf-8")

    source_id, digest = task_state.save_report(pc, scope, meta.task_id, report_text)
    payload = _fit_state(meta, results, gaps, documents, source_id, digest, totals)
    saved = task_state.save_state(pc, scope, payload)
    # 仅供人看的快照；恢复与校验一律以 PowerContext 中的状态为准。
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = WORK_DIR / f"{meta.task_id}.state.json"
    with snapshot_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"[ask] 问题：{arguments.question}")
    for index, result in enumerate(results, start=1):
        print(
            f"[ask] {index}. {result.aspect} -> {result.status}"
            f"（{STATUS_LABEL[result.status]}；证据 {len(result.evidence)} 条，文献 {len(result.documents)} 篇）"
        )
    print(f"[ask] 证据覆盖：{coverage_ratio(results):.4f}")
    print(f"[ask] 证据缺口（{len(gaps)} 个）：")
    print("| 子问题 | 缺口类型 | 说明 | 缺失关键词 |")
    print("| --- | --- | --- | --- |")
    for gap in gaps:
        terms = "、".join(gap.missing_terms) if gap.missing_terms else "-"
        print(f"| {gap.aspect} | {gap.kind}（{STATUS_LABEL[gap.kind]}） | {gap.detail} | {terms} |")
    if arguments.task:
        if previous is not None:
            print(f"[ask] 已复用任务 {arguments.task} 的上次状态（更新于 {previous.get('updated_at')}）")
        else:
            print(f"[ask] 任务 {arguments.task} 没有历史状态，按新任务生成")
    print(f"[ask] 报告已写入 {report_path}（证据 {len(book.items)} 条）")
    print(f"[ask] 报告 Source：{source_id}")
    print(f"[ask] 状态已写入 Memory：{saved['bytes']} 字节（上限 {task_state.MAX_STATE_BYTES}）")
    print(f"[ask] 状态快照：{snapshot_path}（仅供查看，恢复只走 PowerContext）")
    return 0


def cmd_status(arguments: argparse.Namespace) -> int:
    """列出 PowerContext Memory 中的所有研究任务。"""
    ensure_server()
    pc = client()
    scope = scope_id(pc)
    states = task_state.list_states(pc, scope)
    if arguments.task:
        states = [item for item in states if item.get("task_id") == arguments.task]
    if not states:
        print("[status] PowerContext 中没有 research-state 记录；先执行 bash run.sh ask ...")
        return 0

    print(f"[status] 共 {len(states)} 个研究任务")
    for item in states:
        statuses = item.get("statuses") or {}
        aspects = item.get("aspects") or []
        aspect_text = "、".join(f"{aspect}（{statuses.get(aspect, '未知')}）" for aspect in aspects) or "无"
        print(f"- {item.get('task_id')} ｜ 更新于 {item.get('updated_at', '未知')}")
        print(f"  问题：{item.get('question', '')}")
        print(f"  子问题 {len(aspects)} 个：{aspect_text}")
        print(f"  证据 {len(item.get('evidence') or [])} 条；缺口 {len(item.get('gaps') or [])} 个")
        print(f"  报告 Source：{item.get('report_source_id', '')}")
    return 0


def cmd_resume(arguments: argparse.Namespace) -> int:
    """从 PowerContext 读回任务状态与报告，校验 sha256 后展示并提示续研。"""
    ensure_server()
    pc = client()
    scope = scope_id(pc)
    try:
        saved = task_state.load_state(pc, scope, arguments.task)
        report_text = task_state.load_report(pc, scope, str(saved.get("report_source_id", "")))
    except (LookupError, RuntimeError) as error:
        print(f"[resume] {error}")
        return 1

    digest = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
    expected = str(saved.get("report_sha256", ""))
    checksum_ok = digest == expected
    statuses = saved.get("statuses") or {}
    aspects = saved.get("aspects") or []
    gaps = saved.get("gaps") or []
    aspect_text = "、".join(f"{aspect}（{statuses.get(aspect, '未知')}）" for aspect in aspects) or "无"
    gap_text = "、".join(f"{gap.get('aspect')}（{gap.get('kind')}）" for gap in gaps) or "无"

    print(f"[resume] 任务：{saved.get('task_id')}")
    print(f"[resume] 问题：{saved.get('question', '')}")
    print(f"[resume] 更新时间：{saved.get('updated_at', '未知')}")
    print(f"[resume] 子问题：{aspect_text}")
    print(f"[resume] 证据：{len(saved.get('evidence') or [])} 条；遗留缺口：{gap_text}")
    print(f"[resume] 报告 Source：{saved.get('report_source_id', '')}")
    print(f"[resume] sha256 校验：{'通过' if checksum_ok else '不一致'}（{digest[:16]}…）")
    if not checksum_ok:
        print(f"[resume] 期望 sha256：{expected[:16]}…；报告可能在 PowerContext 之外被改动")
        return 1

    print("[resume] ----- 报告正文（从 PowerContext Source 读回）-----")
    print(report_text)
    print("[resume] ----- 续研提示 -----")
    print(
        f"[resume] 基于上次任务继续：bash run.sh ask \"{saved.get('question', '')}\" "
        f"--aspects \"{','.join(aspects)}\" --task {saved.get('task_id')}"
    )
    return 0


def cmd_verify(arguments: argparse.Namespace) -> int:
    """对 work/reports/ 下每份报告做证据回查、缺口核对与 PowerContext 报告哈希校验。"""
    if not SEEKDB_PATH.is_dir() or not any(SEEKDB_PATH.iterdir()):
        print(f"[verify] FAIL：seekdb 数据目录 {SEEKDB_PATH} 不存在或为空；请先执行 bash run.sh ingest")
        return 1
    report_paths = sorted(REPORTS_DIR.glob("*.md")) if REPORTS_DIR.is_dir() else []
    if not report_paths:
        print(f"[verify] FAIL：{REPORTS_DIR} 下没有报告；请先执行 bash run.sh ask ...")
        return 1

    ensure_server()
    pc = client()
    scope = scope_id(pc)

    reports: list[dict] = []
    for path in report_paths:
        text = path.read_text(encoding="utf-8")
        reports.append(
            {
                "path": path,
                "task_id": path.stem,
                "rows": parse_evidence_rows(text),
                "gap_count": parse_gap_count(text),
                "state": None,
                "pc_text": None,
                "errors": [],
            }
        )

    for item in reports:
        try:
            item["state"] = task_state.load_state(pc, scope, item["task_id"])
            item["pc_text"] = task_state.load_report(
                pc, scope, str(item["state"].get("report_source_id", ""))
            )
        except (LookupError, RuntimeError) as error:
            item["errors"].append(str(error))

    async def check_evidence() -> None:
        async with SeekdbStore(SEEKDB_PATH, QUERY_LOG) as store:
            for item in reports:
                for row in item["rows"]:
                    chunk = await store.get_chunk(row["chunk_id"])
                    if chunk is None:
                        item["errors"].append(f"证据 {row['ref']} 的块 {row['chunk_id']} 不在 seekdb 中")
                    elif str(chunk["sha256"]) != row["sha256"]:
                        item["errors"].append(
                            f"证据 {row['ref']}（{row['chunk_id']}）sha256 不一致："
                            f"报告 {row['sha256'][:16]}…，库中 {str(chunk['sha256'])[:16]}…"
                        )

    asyncio.run(check_evidence())

    for item in reports:
        if item["state"] is None:
            continue
        expected_gaps = len(item["state"].get("gaps") or [])
        if item["gap_count"] != expected_gaps:
            item["errors"].append(f"缺口行数不一致：报告 {item['gap_count']} 行，状态 {expected_gaps} 个")
        if item["pc_text"] is not None:
            digest = hashlib.sha256(item["pc_text"].encode("utf-8")).hexdigest()
            expected = str(item["state"].get("report_sha256", ""))
            if digest != expected:
                item["errors"].append(
                    f"PowerContext 报告 sha256 不一致：回读 {digest[:16]}…，状态 {expected[:16]}…"
                )

    failed = 0
    for item in reports:
        print(
            f"[verify] {item['path'].name}（任务 {item['task_id']}）："
            f"证据 {len(item['rows'])} 条、缺口 {item['gap_count']} 行"
        )
        if item["errors"]:
            failed += 1
            for message in item["errors"]:
                print(f"[verify]   FAIL：{message}")
        else:
            print("[verify]   证据 sha256 全部一致；缺口数量与状态一致；PowerContext 报告 sha256 一致")

    if failed:
        print(f"[verify] FAIL：{failed}/{len(reports)} 份报告未通过")
        return 1
    print(f"[verify] PASS：{len(reports)} 份报告全部通过（证据回查 + 缺口数量 + PowerContext 报告哈希）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rca", description="可核验的科研上下文助手")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="前台启动 PowerContext Server").set_defaults(function=cmd_serve)
    subparsers.add_parser("start", help="后台启动 PowerContext Server").set_defaults(function=cmd_start)
    subparsers.add_parser("stop", help="停止 PowerContext Server").set_defaults(function=cmd_stop)
    subparsers.add_parser("restart", help="重启 PowerContext Server").set_defaults(function=cmd_restart)
    subparsers.add_parser("reset", help="清空 data/ work/ logs/").set_defaults(function=cmd_reset)
    subparsers.add_parser("verify", help="可核验自检").set_defaults(function=cmd_verify)

    ingest = subparsers.add_parser("ingest", help="把语料导入 seekdb")
    ingest.add_argument("path", nargs="?", help="语料目录，默认 data/corpus")
    ingest.set_defaults(function=cmd_ingest)

    ask = subparsers.add_parser("ask", help="针对研究问题生成带证据与缺口的报告")
    ask.add_argument("question")
    ask.add_argument("--task", help="复用已有任务编号，报告里会带上上次进展")
    ask.add_argument("--aspects", help="逗号分隔的子问题，不填则按标点自动拆分")
    ask.set_defaults(function=cmd_ask)

    status = subparsers.add_parser("status", help="查看 PowerContext 中的任务状态")
    status.add_argument("--task")
    status.set_defaults(function=cmd_status)

    resume = subparsers.add_parser("resume", help="从 PowerContext 读回任务状态与报告")
    resume.add_argument("task")
    resume.set_defaults(function=cmd_resume)

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command != "serve":
        load_settings()
    return arguments.function(arguments)


if __name__ == "__main__":
    sys.exit(main())
