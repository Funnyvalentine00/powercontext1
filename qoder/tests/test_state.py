"""研究状态存取的行为测试（对应 docs/DESIGN.md 任务 5）。"""

import hashlib
import json

import pytest

from rca import state
from rca.pc_client import PowerContextError


class FakeClient:
    def __init__(self) -> None:
        self.memories: list[dict] = []
        self.sources: dict[str, str] = {}

    def remember(self, scope_id, kind, text, reason=None):
        entry = {"kind": kind, "text": text, "version": len(self.memories) + 1}
        self.memories.append(entry)
        return {"memory": {}, "entry": entry}

    def list_memory_entries(self, scope_id):
        return {"entries": list(self.memories)}

    def capture_source(self, scope_id, source_id, content, metadata):
        if source_id in self.sources:
            raise PowerContextError("conflict", status=409)
        self.sources[source_id] = content
        return {"status": "accepted", "source": {"name": "content", "source_id": source_id}, "position": 1}

    def get_source(self, scope_id, source_id):
        if source_id not in self.sources:
            raise PowerContextError("not found", status=404)
        return {"content": self.sources[source_id], "source_id": source_id}


def _kwargs(**overrides):
    payload = {
        "task_id": "research-001",
        "question": "如何降低检索延迟",
        "aspects": ["索引结构"],
        "statuses": {"索引结构": "supported"},
        "evidence": [
            {
                "ref": "E1",
                "chunk_id": "x-c000",
                "doc_id": "x",
                "sha256": "a" * 64,
                "text": "完整原文不应进入状态",
                "score": 0.9,
            }
        ],
        "gaps": [{"aspect": "GPU 加速", "kind": "missing", "detail": "无", "missing_terms": ["gpu"]}],
        "documents": ["x"],
        "report_source_id": "rca:report:research-001:0000000000000000",
        "report_sha256": "b" * 64,
        "chunk_stats": {"chunks": 12, "documents": 6},
    }
    payload.update(overrides)
    return payload


def test_build_state_keeps_contract_fields_and_trims_evidence():
    built = state.build_state(**_kwargs())

    assert built["schema"] == "rca.task-state.v1"
    assert built["task_id"] == "research-001"
    assert set(built["evidence"][0]) == {"ref", "chunk_id", "doc_id", "sha256"}
    assert "updated_at" in built


def test_save_and_load_latest_state():
    client = FakeClient()
    older = state.build_state(**_kwargs(report_sha256="c" * 64))
    older["updated_at"] = "2026-01-01T00:00:00+08:00"
    newer = state.build_state(**_kwargs(report_sha256="d" * 64))
    newer["updated_at"] = "2026-02-01T00:00:00+08:00"

    state.save_state(client, "scope", older)
    state.save_state(client, "scope", newer)

    loaded = state.load_state(client, "scope", "research-001")
    assert loaded["report_sha256"] == "d" * 64
    assert [item["task_id"] for item in state.list_states(client, "scope")] == ["research-001"]


def test_load_state_unknown_task_raises():
    with pytest.raises(LookupError, match="research-999"):
        state.load_state(FakeClient(), "scope", "research-999")


def test_save_state_rejects_oversize():
    client = FakeClient()
    payload = state.build_state(**_kwargs(question="超" * 4000))

    with pytest.raises(ValueError, match="8192"):
        state.save_state(client, "scope", payload)


def test_save_and_load_report_roundtrip():
    client = FakeClient()
    text = "# 报告\n\n正文。\n"

    source_id, digest = state.save_report(client, "scope", "research-001", text)

    assert source_id == f"rca:report:research-001:{digest[:16]}"
    assert digest == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert state.load_report(client, "scope", source_id) == text

    again_id, again_digest = state.save_report(client, "scope", "research-001", text)
    assert (again_id, again_digest) == (source_id, digest)


def test_save_report_detects_conflicting_content():
    client = FakeClient()
    text = "# 报告\n\n正文。\n"
    source_id, _ = state.save_report(client, "scope", "research-001", text)
    client.sources[source_id] = "被篡改的内容"

    with pytest.raises(RuntimeError, match="内容不一致"):
        state.save_report(client, "scope", "research-001", text)
