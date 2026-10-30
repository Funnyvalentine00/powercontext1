"""报告渲染与解析。

报告的结构是硬契约：`verify` 会解析「证据清单」表格回查证据块，
所以章节标题与表格列顺序不能随意改动。格式见 docs/DESIGN.md 任务 4。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import textutil
from .evidence import AspectResult, EvidenceBook, Gap, coverage_ratio

STATUS_LABEL = {
    "supported": "证据充分",
    "insufficient": "证据不足",
    "single_doc": "证据单一",
    "missing": "语料未覆盖",
}

# 结论区的状态标记：只有 missing 是彻底给不出结论。
STATUS_MARK = {
    "supported": "OK",
    "insufficient": "WARN",
    "single_doc": "WARN",
    "missing": "GAP",
}

# 报告必须包含这五个二级标题，顺序固定。
SECTION_OVERVIEW = "## 一、结论与证据"
SECTION_GAPS = "## 二、证据缺口"
SECTION_EVIDENCE = "## 三、证据清单"
SECTION_VERIFY = "## 四、可核验说明"

# 证据清单表的列顺序固定：编号 | 文献 | 段落 | 块编号 | sha256 | 原文片段
EVIDENCE_COLUMNS = ("编号", "文献", "段落", "块编号", "sha256", "原文片段")
SNIPPET_CHARS = 180


@dataclass
class ReportMeta:
    task_id: str
    question: str
    generated_at: str
    documents: int
    chunks: int
    corpus_dir: str


def _cell(value: object) -> str:
    """表格单元格：竖线转义、换行压成空格（DESIGN 9.6）。"""
    text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return text.replace("|", "\\|").strip()


def _code(value: object) -> str:
    return f"`{_cell(value)}`"


def render_report(
    meta: ReportMeta,
    results: list[AspectResult],
    gaps: list[Gap],
    book: EvidenceBook,
) -> str:
    """按 docs/DESIGN.md 任务 4 的格式渲染 Markdown 报告。"""
    lines: list[str] = [f"# 研究问题：{meta.question}", ""]
    lines.append(
        f"> 任务编号：{meta.task_id} ｜ 生成时间：{meta.generated_at} ｜ "
        f"语料规模：{meta.documents} 篇文献 / {meta.chunks} 个块 ｜ "
        f"证据覆盖：{coverage_ratio(results) * 100:.0f}% ｜ 证据总数：{len(book.items)}"
    )

    lines.extend(["", SECTION_OVERVIEW])
    for index, result in enumerate(results, start=1):
        lines.extend(["", f"### {index}. {result.aspect}", ""])
        lines.append(
            f"状态：`{STATUS_MARK[result.status]}`，证据 {len(result.evidence)} 条，"
            f"文献 {len(result.documents)} 篇"
        )
        if result.evidence:
            lines.append("")
            for item in result.evidence:
                lines.append(f"- {textutil.first_sentence(item.text, title=item.doc_title)} [{item.ref}]")
                lines.append(
                    f"  - 出处：{_code(item.doc_title)} 第 {item.seq + 1} 段，"
                    f"块编号 {_code(item.chunk_id)}，匹配度 {item.score:.2f}"
                )
        else:
            lines.extend(["", "不给出结论：语料未覆盖该子问题。"])

    lines.extend(["", SECTION_GAPS, ""])
    lines.append("| 子问题 | 缺口类型 | 说明 | 缺失关键词 |")
    lines.append("| --- | --- | --- | --- |")
    if gaps:
        for gap in gaps:
            terms = "、".join(gap.missing_terms) if gap.missing_terms else "-"
            lines.append(
                f"| {_cell(gap.aspect)} | {gap.kind}（{STATUS_LABEL[gap.kind]}） | "
                f"{_cell(gap.detail)} | {_cell(terms)} |"
            )
    else:
        lines.append("（无）")

    lines.extend(["", SECTION_EVIDENCE, ""])
    lines.append("| " + " | ".join(EVIDENCE_COLUMNS) + " |")
    lines.append("| " + " | ".join("---" for _ in EVIDENCE_COLUMNS) + " |")
    for item in book.items:
        snippet = textutil.first_sentence(item.text, limit=SNIPPET_CHARS, title=item.doc_title)
        lines.append(
            f"| {item.ref} | {_code(item.doc_id)} | {item.seq + 1} | {_code(item.chunk_id)} | "
            f"{_code(item.sha256)} | {_cell(snippet)} |"
        )

    lines.extend(
        [
            "",
            SECTION_VERIFY,
            "",
            "本报告不调用大模型生成结论：结论区的每条内容都是证据块原文的首句截取，未改写、未补充推测。",
            "证据清单给出完整 chunk_id 与完整 64 位 sha256；`bash run.sh verify` 会逐条回查 seekdb 的 "
            "`rca_chunks` 表并比对哈希。",
            "若某条证据的 sha256 与库中记录不一致，说明报告被改动或语料已更新，该条结论应视为失效。",
            "",
        ]
    )
    return "\n".join(lines)


def _section(report: str, heading: str) -> str:
    start = report.find(heading)
    if start < 0:
        return ""
    start += len(heading)
    match = re.search(r"^## ", report[start:], re.MULTILINE)
    end = start + match.start() if match else len(report)
    return report[start:end]


def parse_evidence_rows(report: str) -> list[dict[str, str]]:
    """从证据清单表解析出 [{ref, chunk_id, sha256}]，供 verify 使用。"""
    rows: list[dict[str, str]] = []
    for line in _section(report, SECTION_EVIDENCE).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < 5:
            continue
        ref = cells[0].strip("`").strip()
        if not re.fullmatch(r"E\d+", ref):
            continue
        rows.append(
            {
                "ref": ref,
                "chunk_id": cells[3].strip("`").strip(),
                "sha256": cells[4].strip("`").strip(),
            }
        )
    return rows


def parse_refs(report: str) -> list[str]:
    """按出现顺序返回报告里所有 [En] 编号（去重）。"""
    refs: list[str] = []
    for match in re.finditer(r"\[(E\d+)\]", report):
        if match.group(1) not in refs:
            refs.append(match.group(1))
    return refs


def parse_gap_count(report: str) -> int:
    """统计「证据缺口」表的数据行数（跳过表头与分隔行）。"""
    count = 0
    for line in _section(report, SECTION_GAPS).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if not cells:
            continue
        if cells[0].strip("`").strip() == "子问题":
            continue
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        count += 1
    return count
