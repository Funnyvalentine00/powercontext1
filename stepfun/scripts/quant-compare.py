#!/usr/bin/env python3
"""量化前后对比：模型体积、推理耗时、检索质量（top-5 重合率）。

依赖：onnxruntime、tokenizers、numpy（见 README「可选：量化对比」一节）。
用法：python3 scripts/quant-compare.py
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "Xenova" / "all-MiniLM-L6-v2"
ONNX_DIR = MODEL_DIR / "onnx"
DOCS_DIR = ROOT / "data" / "sample-docs"

QUERIES = [
    "如何降低检索延迟",
    "分块策略应该怎么选",
    "内存受限时优先用哪种索引",
    "混合检索怎么融合两路结果",
    "怎样让结论回到原文",
]

MAX_LEN = 256


def load_tokenizer() -> Tokenizer:
    tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_LEN)
    tokenizer.enable_padding(length=MAX_LEN)
    return tokenizer


def split_chunks(text: str, target: int = 400) -> list[str]:
    paragraphs = [block.strip() for block in text.split("\n\n") if block.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(buffer) + len(paragraph) + 2 > target and buffer:
            chunks.append(buffer.strip())
            buffer = ""
        buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer.strip():
        chunks.append(buffer.strip())
    return [chunk for chunk in chunks if len(chunk) >= 40]


def load_corpus() -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        for index, chunk in enumerate(split_chunks(path.read_text(encoding="utf-8"))):
            documents.append({"id": f"{path.stem}-c{index:03d}", "text": chunk})
    return documents


def encode(session: ort.InferenceSession, tokenizer: Tokenizer, texts: list[str]) -> np.ndarray:
    encodings = tokenizer.encode_batch(texts)
    ids = np.array([item.ids for item in encodings], dtype=np.int64)
    mask = np.array([item.attention_mask for item in encodings], dtype=np.int64)
    types = np.zeros_like(ids)

    feeds = {}
    for value in session.get_inputs():
        if value.name == "input_ids":
            feeds[value.name] = ids
        elif value.name == "attention_mask":
            feeds[value.name] = mask
        elif value.name == "token_type_ids":
            feeds[value.name] = types
        else:
            feeds[value.name] = ids

    hidden = session.run(None, feeds)[0]
    weights = mask[..., None].astype(np.float32)
    pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
    norm = np.linalg.norm(pooled, axis=1, keepdims=True)
    return pooled / np.maximum(norm, 1e-9)


def top_k(similarities: np.ndarray, k: int = 5) -> list[int]:
    return list(np.argsort(-similarities)[:k])


def evaluate(model_path: Path, tokenizer: Tokenizer, corpus: list[dict[str, str]]) -> dict:
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    texts = [item["text"] for item in corpus]

    started = time.perf_counter()
    doc_vectors = encode(session, tokenizer, texts)
    doc_seconds = time.perf_counter() - started

    query_started = time.perf_counter()
    query_vectors = encode(session, tokenizer, QUERIES)
    query_seconds = time.perf_counter() - query_started

    similarities = query_vectors @ doc_vectors.T
    rankings = [top_k(row) for row in similarities]

    return {
        "file": model_path.name,
        "bytes": model_path.stat().st_size,
        "doc_seconds": doc_seconds,
        "query_seconds": query_seconds,
        "doc_count": len(texts),
        "rankings": rankings,
        "similarities": similarities,
    }


def main() -> int:
    if not (ONNX_DIR / "model.onnx").exists() or not (ONNX_DIR / "model_quantized.onnx").exists():
        print("缺少模型文件：需要 onnx/model.onnx 与 onnx/model_quantized.onnx")
        return 1

    tokenizer = load_tokenizer()
    corpus = load_corpus()
    if not corpus:
        print("示例语料为空")
        return 1

    fp32 = evaluate(ONNX_DIR / "model.onnx", tokenizer, corpus)
    int8 = evaluate(ONNX_DIR / "model_quantized.onnx", tokenizer, corpus)

    overlaps = []
    for fp32_rank, int8_rank in zip(fp32["rankings"], int8["rankings"]):
        overlaps.append(len(set(fp32_rank) & set(int8_rank)) / len(fp32_rank))

    ratio = fp32["bytes"] / int8["bytes"]
    result = {
        "corpus_chunks": len(corpus),
        "queries": len(QUERIES),
        "fp32_bytes": fp32["bytes"],
        "int8_bytes": int8["bytes"],
        "compression_ratio": round(ratio, 3),
        "fp32_doc_seconds": round(fp32["doc_seconds"], 3),
        "int8_doc_seconds": round(int8["doc_seconds"], 3),
        "fp32_query_seconds": round(fp32["query_seconds"], 3),
        "int8_query_seconds": round(int8["query_seconds"], 3),
        "top5_overlap_mean": round(statistics.mean(overlaps), 4),
        "top5_overlap_per_query": [round(value, 4) for value in overlaps],
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 打印每个查询的 top-3 便于人工核对
    for index, query in enumerate(QUERIES):
        fp32_top = [corpus[i]["id"] for i in fp32["rankings"][index][:3]]
        int8_top = [corpus[i]["id"] for i in int8["rankings"][index][:3]]
        print(f"\n[{query}]")
        print(f"  FP32: {fp32_top}")
        print(f"  INT8: {int8_top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
