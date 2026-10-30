"""分词与打分的行为测试（对应 docs/DESIGN.md 任务 2、任务 7）。"""

import pytest

from rca import textutil


def test_tokens_use_bigrams_but_never_single_chars():
    token_set = textutil.tokens("检索")
    assert token_set == {"检索"}
    assert "检" not in token_set and "索" not in token_set


def test_tokens_keep_english_words_and_numbers():
    token_set = textutil.tokens("VARCHAR(64) 与 pylibseekdb")
    assert {"varchar", "64", "pylibseekdb"} <= token_set


def test_stop_chars_are_removed_but_topic_chars_kept():
    sequence = textutil.cjk_sequence("数据的检索")
    assert sequence == "数据检索"
    assert "的" not in sequence


def test_coverage_ratio():
    query = {"数据", "检索"}
    assert textutil.coverage(query, "数据的检索") == 1.0
    assert textutil.coverage(query, "完全无关的内容") == 0.0
    assert textutil.coverage(set(), "任意文本") == 0.0


def test_score_matches_design_formula():
    # coverage = 2/4，repeated = 1（aa 出现两次）=> 0.5 + 0.15 * 1/4
    assert textutil.score({"aa", "bb", "cc", "dd"}, "aa aa bb") == pytest.approx(0.5375)


def test_score_separates_relevant_from_irrelevant_text():
    query = textutil.tokens("降低嵌入式数据库文档检索延迟")
    relevant = "嵌入式数据库的文档检索延迟主要来自文本传输与重排，降低单次检索的延迟需要控制块长度。"
    irrelevant = "今天天气很好，我们去公园散步，顺便买了一些水果。"

    assert textutil.score(query, relevant) >= 0.30
    assert textutil.score(query, irrelevant) < 0.10


def test_keywords_are_bounded_and_space_separated():
    text = "数据" * 200 + " embedded database retrieval latency " * 20

    keywords = textutil.keywords_of(text)

    parts = keywords.split(" ")
    assert 0 < len(parts) <= 40
    assert all(part for part in parts)
    assert keywords == keywords.strip()


def test_first_sentence_skips_headings_tables_short_lines_and_fragments():
    text = (
        "# 标题行不能当结论\n\n"
        "| 表格 | 行 |\n\n"
        "短句。\n\n"
        "，从句子中间开始的片段应当被跳过。\n\n"
        "这是第一条完整可读的证据句子，长度超过十二个字符。"
    )

    assert textutil.first_sentence(text) == "这是第一条完整可读的证据句子，长度超过十二个字符。"


def test_first_sentence_takes_first_complete_sentence():
    text = "这是第一句完整的话，长度足够十二个字。这是第二句完整的话。"

    assert textutil.first_sentence(text) == "这是第一句完整的话，长度足够十二个字。"


def test_first_sentence_truncates_without_terminator():
    text = "这是一段没有任何句末标点的文字" * 20

    assert textutil.first_sentence(text, limit=40) == text[:40] + "…"


def test_first_sentence_strips_list_markers():
    assert (
        textutil.first_sentence("- 慢档：查跨文档聚合与去重，目标 60ms，只在最终报告阶段执行。")
        == "慢档：查跨文档聚合与去重，目标 60ms，只在最终报告阶段执行。"
    )
    assert textutil.first_sentence("* 列表项同样去掉星号前缀，再取第一句。") == "列表项同样去掉星号前缀，再取第一句。"
    assert textutil.first_sentence("+ 加号列表也需处理，不能带前缀进入结论。") == "加号列表也需处理，不能带前缀进入结论。"


def test_first_sentence_never_returns_empty():
    assert textutil.first_sentence("") == "（无可用摘录）"
    assert textutil.first_sentence("", title="块标题") == "块标题"
    assert textutil.first_sentence("# 只有标题\n\n短。", title="文档标题") == "文档标题"
