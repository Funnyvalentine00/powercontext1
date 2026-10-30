"""报告渲染与解析的行为测试（对应 docs/DESIGN.md 任务 4、任务 7）。"""

from rca import evidence, report


def _meta() -> report.ReportMeta:
    return report.ReportMeta(
        task_id="research-001",
        question="研究问题",
        generated_at="2026-10-30T23:00:00+08:00",
        documents=6,
        chunks=12,
        corpus_dir="/tmp/corpus",
    )


def _candidate(chunk_id: str, doc_id: str, text: str, doc_title: str | None = None) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "doc_title": doc_title or doc_id,
        "seq": 2,
        "text": text,
        "sha256": "a" * 64,
    }


def test_render_keeps_fixed_sections_and_column_order():
    book = evidence.EvidenceBook()
    item = book.register(_candidate("x-c000", "x", "这是第一条完整的证据句子，长度足够十二个字。这是第二条。"), 0.6)
    results = [evidence.AspectResult(aspect="索引结构", status="supported", evidence=[item])]

    text = report.render_report(_meta(), results, [], book)

    positions = [
        text.index(section)
        for section in (
            report.SECTION_OVERVIEW,
            report.SECTION_GAPS,
            report.SECTION_EVIDENCE,
            report.SECTION_VERIFY,
        )
    ]
    assert positions == sorted(positions)
    assert "| 编号 | 文献 | 段落 | 块编号 | sha256 | 原文片段 |" in text
    assert "`" + "a" * 64 + "`" in text
    assert "- 这是第一条完整的证据句子，长度足够十二个字。 [E1]" in text
    assert "第 3 段" in text
    assert "| E1 | `x` | 3 |" in text
    assert "证据覆盖：100%" in text


def test_render_parse_roundtrip():
    book = evidence.EvidenceBook()
    item = book.register(_candidate("x-c000", "x", "第一句。第二句。"), 0.6)
    results = [evidence.AspectResult(aspect="索引结构", status="supported", evidence=[item])]

    text = report.render_report(_meta(), results, [], book)

    assert report.parse_evidence_rows(text) == [
        {"ref": "E1", "chunk_id": "x-c000", "sha256": "a" * 64}
    ]
    assert report.parse_refs(text) == ["E1"]


def test_shared_chunk_keeps_single_evidence_row():
    book = evidence.EvidenceBook()
    item = book.register(_candidate("x-c000", "x", "第一句。"), 0.6)
    results = [
        evidence.AspectResult(aspect="甲", status="supported", evidence=[item]),
        evidence.AspectResult(aspect="乙", status="supported", evidence=[item]),
    ]

    text = report.render_report(_meta(), results, [], book)

    assert report.parse_evidence_rows(text) == [
        {"ref": "E1", "chunk_id": "x-c000", "sha256": "a" * 64}
    ]
    assert report.parse_refs(text) == ["E1"]


def test_parse_gap_count():
    gaps = [
        evidence.Gap(aspect="分布式部署", kind="insufficient", detail="仅 1 条证据"),
        evidence.Gap(aspect="GPU 加速", kind="missing", detail="没有匹配证据"),
    ]
    text = report.render_report(_meta(), [], gaps, evidence.EvidenceBook())
    assert report.parse_gap_count(text) == 2

    empty = report.render_report(_meta(), [], [], evidence.EvidenceBook())
    assert report.parse_gap_count(empty) == 0


def test_missing_aspect_writes_no_conclusion():
    results = [evidence.AspectResult(aspect="GPU 加速", status="missing")]

    text = report.render_report(_meta(), results, [], evidence.EvidenceBook())

    assert "不给出结论" in text
    assert "证据 0 条" in text


def test_table_cells_escape_pipe_and_newline():
    book = evidence.EvidenceBook()
    book.register(
        _candidate("x-c000", "x", "这是一条含 | 竖线的证据句子，长度足够十二个字。", doc_title="标题\n第二行"),
        0.6,
    )
    results = [evidence.AspectResult(aspect="甲|乙", status="supported", evidence=book.items)]
    gaps = [evidence.Gap(aspect="丙", kind="missing", detail="第一行\n第二行")]

    text = report.render_report(_meta(), results, gaps, book)

    assert "这是一条含 \\| 竖线" in text
    assert "标题 第二行" in text
    assert "第一行 第二行" in text
    assert "标题\n第二行" not in text
    assert report.parse_evidence_rows(text) == [
        {"ref": "E1", "chunk_id": "x-c000", "sha256": "a" * 64}
    ]
