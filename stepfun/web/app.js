/**
 * 浏览器端：本地加载 embedding 模型、切块、向量化，再把向量与原文写入 seekdb。
 * 推理设备优先 WebGPU，不可用时自动降级 WASM，并在界面提示当前后端。
 */
import { pipeline, env } from './vendor/transformers.js';

// 模型从本地托管目录读取，不依赖浏览器访问外网（避免跨域与网络策略干扰）。
env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = '/models/';
env.useBrowserCache = true;
// onnxruntime-web 的 wasm 由本地 server 托管，避免依赖 CDN。
env.backends.onnx.wasm.wasmPaths = '/vendor/ort/';

const MODEL_ID = 'Xenova/all-MiniLM-L6-v2';
const DTYPE = 'q8'; // INT8
const BATCH_SIZE = 8;
const TARGET_CHUNK = 400;

const state = {
  extractor: null,
  device: null,
  ready: false,
};

const $ = (id) => document.getElementById(id);
const backendBadge = $('backend-badge');
const dbBadge = $('db-badge');
const ingestProgress = $('ingest-progress');
const docList = $('doc-list');
const timing = $('timing');
const results = $('results');

const timings = {
  modelLoad: null,
  ingestEmbed: null,
  ingestWrite: null,
  queryEmbed: null,
  querySearch: null,
};

function setBadge(element, text, kind) {
  element.textContent = text;
  element.className = `badge ${kind || ''}`.trim();
}

function formatMs(value) {
  return value == null ? '—' : `${Math.round(value)} ms`;
}

function updateTiming() {
  timing.textContent = [
    `模型加载：${formatMs(timings.modelLoad)}`,
    `文档向量化：${formatMs(timings.ingestEmbed)}`,
    `写入 seekdb：${formatMs(timings.ingestWrite)}`,
    `查询向量化：${formatMs(timings.queryEmbed)}`,
    `seekdb 检索：${formatMs(timings.querySearch)}`,
  ].join('\n');
}

async function initModel() {
  const started = performance.now();
  setBadge(backendBadge, '后端：加载模型…', 'pending');

  const attempts = [
    { device: 'webgpu', label: 'WebGPU' },
    { device: 'wasm', label: 'WASM' },
  ];

  for (const attempt of attempts) {
    try {
      state.extractor = await pipeline('feature-extraction', MODEL_ID, {
        device: attempt.device,
        dtype: DTYPE,
        progress_callback: (event) => {
          if (event && event.status === 'progress' && event.file) {
            setBadge(backendBadge, `后端：加载模型 ${Math.round(event.progress || 0)}%`, 'pending');
          }
        },
      });
      state.device = attempt.device;
      state.ready = true;
      timings.modelLoad = performance.now() - started;
      const label = attempt.device === 'webgpu' ? 'WebGPU（INT8）' : 'WASM（INT8，已从 WebGPU 降级）';
      setBadge(backendBadge, `后端：${label}`, attempt.device === 'webgpu' ? 'ok' : 'pending');
      updateTiming();
      return;
    } catch (error) {
      console.warn(`[model] ${attempt.device} 初始化失败：`, error && error.message ? error.message : error);
      state.extractor = null;
    }
  }

  setBadge(backendBadge, '后端：模型加载失败', 'pending');
  ingestProgress.textContent = '模型加载失败，请检查网络或模型镜像地址。';
}

async function embed(texts) {
  if (!state.ready) throw new Error('模型尚未就绪');
  const single = typeof texts === 'string';
  const input = single ? [texts] : texts;
  const output = await state.extractor(input, { pooling: 'mean', normalize: true });
  const vectors = output.tolist();
  return single ? vectors[0] : vectors;
}

function splitText(text, target = TARGET_CHUNK) {
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((item) => item.trim())
    .filter(Boolean);

  const chunks = [];
  let buffer = '';
  for (const paragraph of paragraphs) {
    if (buffer.length + paragraph.length + 2 > target && buffer) {
      chunks.push(buffer.trim());
      buffer = '';
    }
    buffer = buffer ? `${buffer}\n\n${paragraph}` : paragraph;
  }
  if (buffer.trim()) chunks.push(buffer.trim());

  return chunks.filter((chunk) => chunk.length >= 40);
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || '请求失败');
  return data;
}

async function refreshHealth() {
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    if (data.ok) {
      setBadge(dbBadge, `数据库：seekdb · ${data.collection} · ${data.count} 块`, 'ok');
    } else {
      setBadge(dbBadge, `数据库：${data.error || '不可用'}`, 'pending');
    }
  } catch (error) {
    setBadge(dbBadge, '数据库：连接失败', 'pending');
  }
}

async function ingest() {
  if (!state.ready) {
    ingestProgress.textContent = '模型还没加载完，请稍等。';
    return;
  }

  const files = Array.from($('file-input').files || []);
  const pasted = $('text-input').value.trim();
  if (files.length === 0 && !pasted) {
    ingestProgress.textContent = '请选择文件或粘贴文本。';
    return;
  }

  const documents = [];
  for (const file of files) {
    documents.push({ name: file.name, text: await file.text() });
  }
  if (pasted) {
    documents.push({ name: `粘贴文本-${new Date().toISOString().slice(11, 19)}`, text: pasted });
  }

  const button = $('ingest-btn');
  button.disabled = true;

  try {
    let totalChunks = 0;
    const embedStarted = performance.now();

    for (const document of documents) {
      const chunks = splitText(document.text);
      if (chunks.length === 0) continue;

      ingestProgress.textContent = `正在处理 ${document.name}（${chunks.length} 块）…`;

      const items = [];
      for (let offset = 0; offset < chunks.length; offset += BATCH_SIZE) {
        const batch = chunks.slice(offset, offset + BATCH_SIZE);
        const vectors = await embed(batch);
        batch.forEach((text, index) => {
          items.push({
            id: `${document.name}-c${String(offset + index).padStart(3, '0')}`,
            docId: document.name,
            title: document.name,
            seq: offset + index,
            text,
            embedding: vectors[index],
          });
        });
        ingestProgress.textContent =
          `正在处理 ${document.name}：${Math.min(offset + BATCH_SIZE, chunks.length)}/${chunks.length} 块`;
      }

      const writeStarted = performance.now();
      const response = await api('/api/documents', { chunks: items });
      timings.ingestWrite = (timings.ingestWrite || 0) + (performance.now() - writeStarted);
      totalChunks += response.added;
      docList.textContent = `最近写入 ${response.added} 块 · 库内共 ${response.total} 块`;
    }

    timings.ingestEmbed = performance.now() - embedStarted;
    updateTiming();
    ingestProgress.textContent = `完成：写入 ${totalChunks} 块`;
    await refreshHealth();
  } catch (error) {
    ingestProgress.textContent = `写入失败：${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function search() {
  if (!state.ready) {
    results.textContent = '模型还没加载完，请稍等。';
    return;
  }
  const query = $('query-input').value.trim();
  if (!query) {
    results.textContent = '请输入查询内容。';
    return;
  }

  const button = $('search-btn');
  button.disabled = true;
  results.innerHTML = '';

  try {
    const embedStarted = performance.now();
    const embedding = await embed(query);
    timings.queryEmbed = performance.now() - embedStarted;

    const data = await api('/api/search', { embedding, text: query, limit: 5 });
    timings.querySearch = data.elapsedMs;
    updateTiming();

    if (data.hits.length === 0) {
      results.textContent = '没有命中任何结果，试试换个说法或先导入语料。';
      return;
    }

    for (const hit of data.hits) {
      const card = document.createElement('div');
      card.className = 'hit';
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = `${hit.metadata.title || hit.metadata.docId || ''} · 第 ${(hit.metadata.seq || 0) + 1} 段 · 距离 ${Number(hit.distance).toFixed(4)}`;
      const text = document.createElement('div');
      text.className = 'text';
      text.textContent = hit.text;
      card.append(meta, text);
      results.appendChild(card);
    }
  } catch (error) {
    results.textContent = `检索失败：${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function reset() {
  if (!window.confirm('确定清空知识库？')) return;
  try {
    await api('/api/reset', {});
    docList.textContent = '已清空';
    results.innerHTML = '';
    await refreshHealth();
  } catch (error) {
    docList.textContent = `清空失败：${error.message}`;
  }
}

$('ingest-btn').addEventListener('click', ingest);
$('search-btn').addEventListener('click', search);
$('reset-btn').addEventListener('click', reset);
$('query-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') search();
});

updateTiming();
refreshHealth();
initModel();
