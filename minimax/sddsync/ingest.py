"""把规格、代码与测试作为 Source 证据写入 PowerContext。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .pc_client import PowerContextClient, PowerContextError

# 这些路径相对 minimax/ 根目录。
INGEST_PATHS = (
    "sample-app/spec/refund.md",
    "sample-app/src/refund.py",
    "sample-app/tests/test_refund.py",
    "fixtures/spec-v1.md",
    "fixtures/spec-v2.md",
    "fixtures/spec-v3.md",
    "tasks/task-001.yaml",
)


@dataclass(frozen=True)
class SourceEntry:
    path: str
    sha256: str
    source_id: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "source_id": self.source_id}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_id_for(relpath: str, digest: str) -> str:
    # Source ID 不能含空格/斜杠（GET 路由按路径段匹配），用可读的扁平化形式。
    flat = relpath.replace("/", "__")
    return f"minimax:{flat}:{digest[:16]}"


def ingest(root: Path, client: PowerContextClient, scope_id: str) -> dict[str, SourceEntry]:
    entries: dict[str, SourceEntry] = {}
    for relpath in INGEST_PATHS:
        path = root / relpath
        if not path.is_file():
            raise FileNotFoundError(f"缺少待采集文件: {relpath}")
        text = path.read_text(encoding="utf-8")
        digest = sha256_text(text)
        source_id = source_id_for(relpath, digest)
        metadata = {"path": relpath, "sha256": digest, "kind": "sdd", "producer": "minimax-sddsync"}
        try:
            client.capture_source(scope_id, source_id, text, metadata)
        except PowerContextError as error:
            if error.status != 409:
                raise
            # 同一 path+sha256 已采集：把 409 视为幂等重试，再读一次确认证据存在。
            client.get_source(scope_id, source_id)
        # 同时写入 Memory，让数据库侧的检索（全文索引）能命中工程资料。
        client.remember(
            scope_id,
            "sdd-source",
            text,
            reason=f"SDD 工程资料 {relpath}（sha256={digest}）",
        )
        entries[relpath] = SourceEntry(path=relpath, sha256=digest, source_id=source_id)
    return entries


def save_ingest_manifest(work_dir: Path, entries: dict[str, SourceEntry]) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = work_dir / "sources.json"
    manifest_path.write_text(
        json.dumps({key: value.as_dict() for key, value in entries.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def load_ingest_manifest(work_dir: Path) -> dict[str, SourceEntry]:
    manifest_path = work_dir / "sources.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("缺少 work/sources.json，请先执行 ingest")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        key: SourceEntry(path=value["path"], sha256=value["sha256"], source_id=value["source_id"])
        for key, value in payload.items()
    }
