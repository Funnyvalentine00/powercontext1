/**
 * HTTP 服务：静态页面 + 知识库 API。
 * 推理全部发生在浏览器；服务端只做 seekdb 读写与检索。
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const store = require('./seekdb');

const PORT = Number(process.env.APP_PORT || 8090);
const ROOT = path.join(__dirname, '..');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
  '.onnx': 'application/octet-stream',
  '.bin': 'application/octet-stream',
  '.txt': 'text/plain; charset=utf-8',
};

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  response.end(body);
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let raw = '';
    request.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 32 * 1024 * 1024) {
        reject(new Error('请求体过大'));
        request.destroy();
      }
    });
    request.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(new Error('请求体不是合法 JSON'));
      }
    });
    request.on('error', reject);
  });
}

function sendFile(response, target) {
  fs.readFile(target, (error, data) => {
    if (error) {
      response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      response.end('not found');
      return;
    }
    response.writeHead(200, { 'Content-Type': MIME[path.extname(target)] || 'application/octet-stream' });
    response.end(data);
  });
}

/**
 * 前端依赖不复制进仓库，直接从 node_modules 托管：
 * - /vendor/transformers.js -> @huggingface/transformers 的浏览器构建
 * - /vendor/ort/*           -> onnxruntime-web 的 wasm 与 mjs
 */
function serveVendor(response, urlPath) {
  const tfDist = path.join(ROOT, 'node_modules', '@huggingface', 'transformers', 'dist');
  const ortDist = path.join(ROOT, 'node_modules', 'onnxruntime-web', 'dist');

  if (urlPath === '/vendor/transformers.js') {
    // 用 transformers.min.js：它内置了 onnxruntime-web，
    // 而 transformers.web.min.js 会留下裸模块引用 `onnxruntime-web/webgpu`，浏览器无法解析。
    sendFile(response, path.join(tfDist, 'transformers.min.js'));
    return;
  }
  const ortName = urlPath.replace('/vendor/ort/', '');
  if (ortName.includes('..') || ortName.includes('/')) {
    response.writeHead(403);
    response.end('forbidden');
    return;
  }
  sendFile(response, path.join(ortDist, ortName));
}

function serveStatic(request, response, urlPath) {
  if (urlPath.startsWith('/vendor/')) {
    serveVendor(response, urlPath);
    return;
  }
  // 本地模型目录：浏览器只从这里读模型，不依赖外网
  if (urlPath.startsWith('/models/')) {
    const relative = urlPath.replace('/models/', '');
    if (relative.includes('..')) {
      response.writeHead(403);
      response.end('forbidden');
      return;
    }
    sendFile(response, path.join(ROOT, 'models', relative));
    return;
  }
  const relative = urlPath === '/' ? '/index.html' : urlPath;
  const target = path.join(ROOT, 'web', relative);
  if (!target.startsWith(path.join(ROOT, 'web'))) {
    response.writeHead(403);
    response.end('forbidden');
    return;
  }
  sendFile(response, target);
}

async function handleApi(request, response, route) {
  if (route === '/api/health' && request.method === 'GET') {
    const info = await store.stats();
    sendJson(response, 200, { ok: true, ...info });
    return;
  }

  if (route === '/api/documents' && request.method === 'POST') {
    const body = await readBody(request);
    const result = await store.addChunks(body.chunks);
    const info = await store.stats();
    sendJson(response, 200, { ok: true, ...result, total: info.count });
    return;
  }

  if (route === '/api/search' && request.method === 'POST') {
    const body = await readBody(request);
    if (!body.embedding) {
      sendJson(response, 400, { ok: false, error: '缺少 embedding' });
      return;
    }
    if (!body.text) {
      sendJson(response, 400, { ok: false, error: '缺少 text' });
      return;
    }
    const started = process.hrtime.bigint();
    const hits = await store.hybridSearch(body);
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
    sendJson(response, 200, { ok: true, hits, elapsedMs: Math.round(elapsedMs * 100) / 100 });
    return;
  }

  if (route === '/api/reset' && request.method === 'POST') {
    const result = await store.reset();
    sendJson(response, 200, { ok: true, ...result });
    return;
  }

  sendJson(response, 404, { ok: false, error: 'unknown route' });
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host || 'localhost'}`);
  try {
    if (url.pathname.startsWith('/api/')) {
      await handleApi(request, response, url.pathname);
      return;
    }
    serveStatic(request, response, url.pathname);
  } catch (error) {
    sendJson(response, 500, { ok: false, error: error.message });
  }
});

server.listen(PORT, () => {
  const config = store.config();
  console.log(`[app] http://127.0.0.1:${PORT}`);
  console.log(`[app] seekdb ${config.host}:${config.port}/${config.database} collection=${config.collection} dim=${config.dimension}`);
});

function shutdown() {
  server.close(() => {
    store.close().finally(() => process.exit(0));
  });
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
