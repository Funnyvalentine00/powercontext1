"""中英混合文本的分词与匹配打分（不依赖第三方分词库）。

不做中文分词，改用「去停用字后的二元组 + 英文词」的集合匹配，要求见 docs/DESIGN.md 任务 2。
"""

from __future__ import annotations

import re
from collections import Counter

# DESIGN 9.1 指定；只去虚词字，保留「数」「据」「检」「索」「库」等主题实词。
STOP_CHARS = set("的了是在和与或对及把被从到有为以这那个之而其所以可在不没很更最再又还就能会要")

_ENGLISH_WORD = re.compile(r"[a-z0-9]+")
_CJK_START, _CJK_END = "\u4e00", "\u9fff"
# 以这些标点开头的行，说明内容从句子中间被截断（多是分块重叠造成的）。
_LEADING_PUNCT = set("，。；！？、：,.;!?")
_MIN_SENTENCE_LINE = 12
_LIST_MARKERS = ("- ", "* ", "+ ")


def cjk_sequence(text: str) -> str:
    """保留中文实词字、去掉虚词字与空白，用于构造二元组。"""
    return "".join(
        char for char in text if _CJK_START <= char <= _CJK_END and char not in STOP_CHARS
    )


def _token_list(text: str) -> list[str]:
    words = [word for word in _ENGLISH_WORD.findall(text.lower()) if len(word) >= 2]
    cjk = cjk_sequence(text)
    bigrams = [cjk[index : index + 2] for index in range(len(cjk) - 1)]
    return words + bigrams


def tokens(text: str) -> set[str]:
    """匹配用词集合 = 英文/数字词（长度 >= 2）+ 中文二元组。

    二元组会产生跨词噪声，但查询侧与文档侧同样处理，比例上仍能区分主题；
    不要退化成「只按单字匹配」，单字区分度太低。
    """
    return set(_token_list(text))


def coverage(query_tokens: set[str], text: str) -> float:
    """查询词被文本覆盖的比例，落在 [0, 1]。"""
    if not query_tokens:
        return 0.0
    return len(query_tokens & tokens(text)) / len(query_tokens)


def score(query_tokens: set[str], text: str) -> float:
    """覆盖度为主，重复出现给小权重加成，结果截断到 [0, 1]。"""
    if not query_tokens:
        return 0.0
    counts = Counter(_token_list(text))
    covered = len(query_tokens & counts.keys())
    repeated = sum(1 for token in query_tokens if counts[token] >= 2)
    return min(1.0, covered / len(query_tokens) + 0.15 * repeated / len(query_tokens))


def keywords_of(text: str, limit: int = 40) -> str:
    """抽取入库用的关键词列（空格分隔），供 SQL LIKE 检索使用。"""
    counts = Counter(_token_list(text))
    ranked = sorted(counts, key=lambda token: (-counts[token], -len(token), token))
    return " ".join(ranked[:limit])


def _complete_sentences(line: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for index, char in enumerate(line):
        if char in "。；！？":
            sentences.append(line[start : index + 1])
            start = index + 1
    return sentences


def first_sentence(text: str, limit: int = 160, title: str = "") -> str:
    """取首句作为证据摘要（只截取不改写），规则见 docs/DESIGN.md 9.14。

    依次跳过空行、`#` 标题行、`|` 表格行、少于 12 字的行、以标点开头的行，
    再取第一个长度不超过 limit 的完整句；找不到时截断加省略号，
    仍为空则用块标题兜底，绝不返回空串。
    """
    fallback_title = title.strip()
    usable: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 列表项去掉标记后继续参与取句，避免整行跳过丢掉块内唯一内容。
        for marker in _LIST_MARKERS:
            if line.startswith(marker):
                line = line[len(marker) :].strip()
                break
        if not line:
            continue
        if line.startswith("#"):
            if not fallback_title:
                fallback_title = line.lstrip("#").strip()
            continue
        if line.startswith("|"):
            continue
        if len(line) < _MIN_SENTENCE_LINE:
            continue
        if line[0] in _LEADING_PUNCT:
            continue
        usable.append(line)
        for sentence in _complete_sentences(line):
            candidate = sentence.strip()
            if candidate and len(candidate) <= limit:
                return candidate
    if usable:
        truncated = "".join(usable)[:limit].rstrip()
        if truncated:
            return f"{truncated}…"
    return fallback_title or "（无可用摘录）"
