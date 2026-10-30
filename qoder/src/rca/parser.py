"""文档解析与分块：段落边界优先、长度兜底。

接口已定好，算法细节由 Qoder 实现，要求见 docs/DESIGN.md 任务 1。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

TARGET_CHARS = 480
OVERLAP_RATIO = 0.12
MIN_CHUNK_CHARS = 80
SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt")
# 说明性文件不入库，否则会污染证据判定。
EXCLUDED_NAMES = {"README.md", "index.md"}

_TITLE_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
# 超长段落先按句末标点拆开，避免在句子中间硬切。
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    path: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    seq: int
    text: str
    sha256: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "seq": self.seq,
            "text": self.text,
            "sha256": self.sha256,
        }


def load_documents(root: Path) -> list[Document]:
    """扫描语料目录，返回按路径排序的文档列表。

    doc_id 取文件名主干，title 优先取第一个 Markdown 标题，否则用文件名。
    """
    if not root.is_dir():
        raise FileNotFoundError(f"语料目录不存在：{root}；请放入 .md / .txt 文献后重试")
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES and path.name not in EXCLUDED_NAMES
    )
    if not paths:
        raise FileNotFoundError(
            f"语料目录为空：{root}；请放入 .md / .txt 文献（README.md、index.md 会被跳过）"
        )

    documents: list[Document] = []
    seen: dict[str, Path] = {}
    for path in paths:
        doc_id = path.stem
        if doc_id in seen:
            raise ValueError(f"doc_id 冲突：{seen[doc_id]} 与 {path} 的主文件名都是 {doc_id}")
        seen[doc_id] = path
        text = path.read_text(encoding="utf-8-sig")
        match = _TITLE_PATTERN.search(text)
        title = match.group(1).strip() if match else doc_id
        documents.append(Document(doc_id=doc_id, title=title, path=str(path), text=text))
    return documents


def _split_paragraph(paragraph: str, target: int) -> list[str]:
    """把单个超长段落按句子拆成不超过 target 的单元；单句仍超长才硬切。"""
    if len(paragraph) <= target:
        return [paragraph]
    units: list[str] = []
    current = ""
    for sentence in (part for part in _SENTENCE_SPLIT.split(paragraph) if part):
        if len(sentence) > target:
            if current:
                units.append(current)
                current = ""
            units.extend(sentence[offset : offset + target] for offset in range(0, len(sentence), target))
            continue
        if current and len(current) + len(sentence) > target:
            units.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        units.append(current)
    return units


def split_text(text: str, target: int = TARGET_CHARS, overlap_ratio: float = OVERLAP_RATIO) -> list[str]:
    """按空行切段落，聚合到 target 长度，相邻块保留 overlap_ratio 的重叠。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT.split(normalized) if part.strip()]

    units: list[str] = []
    for paragraph in paragraphs:
        units.extend(_split_paragraph(paragraph, target))

    bodies: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        extra = len(unit) + (2 if current else 0)
        if current and current_len + extra > target:
            bodies.append("\n\n".join(current))
            current, current_len = [], 0
            extra = len(unit)
        current.append(unit)
        current_len += extra
    if current:
        tail = "\n\n".join(current)
        # 末尾不足 MIN_CHUNK_CHARS 的碎片并回上一块，避免产出几乎不可检索的块。
        if bodies and len(tail) < MIN_CHUNK_CHARS:
            bodies[-1] = f"{bodies[-1]}\n\n{tail}"
        else:
            bodies.append(tail)

    overlap_chars = int(target * overlap_ratio)
    chunks: list[str] = []
    for index, body in enumerate(bodies):
        if index == 0 or overlap_chars <= 0:
            chunks.append(body)
        else:
            chunks.append(f"{bodies[index - 1][-overlap_chars:]}\n\n{body}")
    return chunks


def build_chunks(documents: list[Document], target: int = TARGET_CHARS) -> list[Chunk]:
    """把文档切成 Chunk，chunk_id 形如 `{doc_id}-c003`，sha256 为块文本的 sha256。"""
    chunks: list[Chunk] = []
    for document in documents:
        for seq, text in enumerate(split_text(document.text, target)):
            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id}-c{seq:03d}",
                    doc_id=document.doc_id,
                    doc_title=document.title,
                    seq=seq,
                    text=text,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return chunks
