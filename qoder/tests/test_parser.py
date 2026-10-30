"""分块与语料扫描的行为测试（对应 docs/DESIGN.md 任务 1、任务 7）。"""

import hashlib

import pytest

from rca import parser


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_load_documents_scans_and_skips_readme(tmp_path):
    _write(tmp_path / "README.md", "# 说明\n不应入库")
    _write(tmp_path / "index.md", "# 索引\n不应入库")
    _write(tmp_path / "alpha.md", "# 阿尔法标题\n\n正文 A")
    _write(tmp_path / "beta.txt", "纯文本正文 B")

    documents = parser.load_documents(tmp_path)

    assert [document.doc_id for document in documents] == ["alpha", "beta"]
    assert documents[0].title == "阿尔法标题"
    assert documents[1].title == "beta"


def test_load_documents_rejects_empty_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match="语料目录为空"):
        parser.load_documents(tmp_path)


def test_load_documents_rejects_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match="语料目录不存在"):
        parser.load_documents(tmp_path / "missing")


def test_split_text_keeps_every_paragraph():
    paragraphs = [f"第{index}段：" + ("数据库检索与分块策略。" * 20) for index in range(3)]
    text = "\n\n".join(paragraphs)

    chunks = parser.split_text(text)

    assert len(chunks) > 1
    for paragraph in paragraphs:
        assert any(paragraph in chunk for chunk in chunks), "分块不得丢段落"


def test_split_text_overlaps_neighbouring_chunks():
    paragraphs = [f"第{index}段：" + ("检索延迟与索引结构。" * 20) for index in range(3)]

    chunks = parser.split_text("\n\n".join(paragraphs))

    overlap_chars = int(parser.TARGET_CHARS * parser.OVERLAP_RATIO)
    assert chunks[1].startswith(chunks[0][-overlap_chars:])


def test_split_text_handles_blank_input():
    assert parser.split_text("   \n\n  ") == []


def test_build_chunks_ids_hashes_and_seq():
    document = parser.Document(
        doc_id="demo",
        title="示例",
        path="/tmp/demo.md",
        text="\n\n".join("第%d段：%s" % (index, "内容" * 100) for index in range(3)),
    )

    chunks = parser.build_chunks([document])

    assert [chunk.chunk_id for chunk in chunks] == [f"demo-c{seq:03d}" for seq in range(len(chunks))]
    assert [chunk.seq for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.doc_id == "demo"
        assert chunk.doc_title == "示例"
        assert chunk.sha256 == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert len(chunk.sha256) == 64
