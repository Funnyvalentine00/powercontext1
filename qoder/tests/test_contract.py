"""契约测试：防止实现过程中改坏表结构、报告格式与判定阈值。

这些测试只校验「约定」，不校验算法，因此骨架阶段就能跑，
实现完成后继续保留，作为防回归的第一道闸。
业务行为的测试由 docs/DESIGN.md 任务 7 补充。
"""

from rca import cli, evidence, report, state, store

ALLOWED_STATUS = {"supported", "insufficient", "single_doc", "missing"}


def test_chunk_table_contract():
    assert store.TABLE == "rca_chunks"
    ddl = store.DDL
    for column in ("chunk_id", "doc_id", "doc_title", "seq", "text", "keywords", "sha256"):
        assert f"`{column}`" in ddl, f"表结构缺少字段 {column}"
    assert "PRIMARY KEY (`chunk_id`)" in ddl


def test_evidence_thresholds_contract():
    assert evidence.MIN_SCORE == 0.30
    assert evidence.MIN_EVIDENCE == 2
    assert evidence.MIN_DOCUMENTS == 2
    assert evidence.TOP_K_PER_ASPECT == 4


def test_report_sections_contract():
    assert report.SECTION_OVERVIEW == "## 一、结论与证据"
    assert report.SECTION_GAPS == "## 二、证据缺口"
    assert report.SECTION_EVIDENCE == "## 三、证据清单"
    assert report.SECTION_VERIFY == "## 四、可核验说明"
    assert report.EVIDENCE_COLUMNS == ("编号", "文献", "段落", "块编号", "sha256", "原文片段")


def test_status_labels_contract():
    assert set(report.STATUS_LABEL) == ALLOWED_STATUS


def test_state_contract():
    assert state.STATE_SCHEMA == "rca.task-state.v1"
    assert state.MAX_STATE_BYTES == 8192
    assert state.report_source_id("research-001", "a" * 64).startswith("rca:report:research-001:")


def test_dataclasses_are_constructible():
    item = evidence.EvidenceItem(
        ref="E1",
        chunk_id="demo-c001",
        doc_id="demo",
        doc_title="示例",
        seq=0,
        text="原文",
        sha256="0" * 64,
        score=0.5,
    )
    assert item.as_mapping()["ref"] == "E1"

    gap = evidence.Gap(aspect="子问题", kind="语料未覆盖", detail="说明")
    assert gap.as_mapping()["kind"] == "语料未覆盖"


def test_cli_parser_contract():
    parser = cli.build_parser()
    arguments = parser.parse_args(["ask", "研究问题", "--aspects", "分块策略,分布式部署"])
    assert arguments.command == "ask"
    assert arguments.question == "研究问题"
    assert arguments.aspects == "分块策略,分布式部署"
    assert arguments.task is None

    arguments = parser.parse_args(["resume", "research-001"])
    assert arguments.command == "resume"
    assert arguments.task == "research-001"

    for command in ("ingest", "status", "verify", "start", "stop", "restart", "reset"):
        assert parser.parse_args([command]).command == command


def test_paths_point_inside_project():
    root = cli.ROOT
    assert root.name == "qoder"
    assert (root / "src" / "rca").is_dir()
    assert cli.CORPUS_DIR == root / "data" / "corpus"
    assert cli.REPORTS_DIR == root / "work" / "reports"
