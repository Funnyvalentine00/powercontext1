"""证据选择与缺口判定的行为测试（对应 docs/DESIGN.md 任务 3、任务 7）。"""

from rca import evidence


def _candidate(chunk_id: str, doc_id: str, text: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "doc_title": doc_id,
        "seq": 0,
        "text": text,
        "sha256": "0" * 64,
    }


def test_split_aspects_prefers_explicit_list():
    assert evidence.split_aspects("整句", [" 甲 ", "", "乙"]) == ["甲", "乙"]


def test_split_aspects_uses_chinese_punctuation():
    assert evidence.split_aspects("甲，乙；丙。丁？戊！") == ["甲", "乙", "丙", "丁", "戊"]


def test_split_aspects_falls_back_to_whole_question():
    assert evidence.split_aspects("没有标点的问题") == ["没有标点的问题"]


def test_select_for_aspect_missing():
    result = evidence.select_for_aspect(
        "alpha beta", [_candidate("x-c000", "x", "gamma delta")], evidence.EvidenceBook()
    )
    assert result.status == "missing"
    assert result.evidence == []


def test_select_for_aspect_insufficient():
    result = evidence.select_for_aspect(
        "alpha beta", [_candidate("x-c000", "x", "alpha beta 内容")], evidence.EvidenceBook()
    )
    assert result.status == "insufficient"
    assert len(result.evidence) == 1


def test_select_for_aspect_single_doc():
    candidates = [
        _candidate("x-c000", "x", "alpha beta"),
        _candidate("x-c001", "x", "alpha beta 再述"),
    ]

    result = evidence.select_for_aspect("alpha beta", candidates, evidence.EvidenceBook())

    assert result.status == "single_doc"
    assert result.documents == ["x"]


def test_select_for_aspect_supported():
    candidates = [
        _candidate("x-c000", "x", "alpha beta"),
        _candidate("y-c000", "y", "alpha beta"),
    ]

    result = evidence.select_for_aspect("alpha beta", candidates, evidence.EvidenceBook())

    assert result.status == "supported"
    assert len(result.documents) == 2


def test_evidence_book_reuses_ref_and_keeps_best_score():
    book = evidence.EvidenceBook()
    first = book.register(_candidate("x-c000", "x", "alpha beta"), 0.4)
    again = book.register(_candidate("x-c000", "x", "alpha beta"), 0.9)
    second = book.register(_candidate("y-c000", "y", "alpha beta"), 0.5)

    assert first is again
    assert first.ref == "E1"
    assert first.score == 0.9
    assert second.ref == "E2"
    assert [item.ref for item in book.items] == ["E1", "E2"]


def test_select_for_aspect_reuses_book_across_aspects():
    candidates = [
        _candidate("x-c000", "x", "alpha beta"),
        _candidate("y-c000", "y", "alpha beta"),
    ]
    book = evidence.EvidenceBook()

    first = evidence.select_for_aspect("alpha beta", candidates, book)
    second = evidence.select_for_aspect("alpha", candidates, book)

    assert [item.ref for item in first.evidence] == ["E1", "E2"]
    assert all(item.ref in {"E1", "E2"} for item in second.evidence)


def test_detect_gaps_maps_non_supported_results():
    results = [
        evidence.AspectResult(aspect="ok", status="supported"),
        evidence.AspectResult(aspect="none", status="missing", missing_terms=["gpu"]),
        evidence.AspectResult(aspect="few", status="insufficient"),
        evidence.AspectResult(aspect="one", status="single_doc"),
    ]

    gaps = evidence.detect_gaps(results)

    assert [gap.kind for gap in gaps] == ["missing", "insufficient", "single_doc"]
    assert gaps[0].missing_terms == ["gpu"]
    assert "0.30" in gaps[0].detail


def test_coverage_ratio():
    results = [
        evidence.AspectResult(aspect="a", status="supported"),
        evidence.AspectResult(aspect="b", status="missing"),
        evidence.AspectResult(aspect="c", status="missing"),
        evidence.AspectResult(aspect="d", status="missing"),
    ]

    assert evidence.coverage_ratio(results) == 0.25
    assert evidence.coverage_ratio([]) == 0.0
