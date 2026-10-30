/**
 * seekdb 数据层：集合管理、文档写入、向量 + 全文混合检索。
 *
 * 检索一律通过 collection.hybridSearch 交给 seekdb 执行（DBMS_HYBRID_SEARCH + RRF），
 * 不在应用侧合并两路结果。
 */
const { SeekdbClient, Schema, VectorIndexConfig } = require('seekdb');

const HOST = process.env.SEEKB_HOST || '127.0.0.1';
const PORT = Number(process.env.SEEKB_PORT || 2881);
const USER = process.env.SEEKB_USER || 'root';
const PASSWORD = process.env.SEEKB_PASSWORD || '';
const DATABASE = process.env.SEEKB_DATABASE || 'stepfun_kb';
const COLLECTION = process.env.SEEKB_COLLECTION || 'kb';
const DIM = Number(process.env.EMBED_DIM || 384);

let client = null;
let collection = null;
let databaseReady = false;

/**
 * seekdb 默认只有 test 库，这里用 mysql2 先建好本次使用的库。
 */
async function ensureDatabase() {
  if (databaseReady) return;
  const mysql = require('mysql2/promise');
  const connection = await mysql.createConnection({
    host: HOST,
    port: PORT,
    user: USER,
    password: PASSWORD,
  });
  try {
    await connection.query(`CREATE DATABASE IF NOT EXISTS \`${DATABASE}\``);
  } finally {
    await connection.end();
  }
  databaseReady = true;
}

function config() {
  return {
    backend: 'seekdb-server',
    host: HOST,
    port: PORT,
    database: DATABASE,
    collection: COLLECTION,
    dimension: DIM,
  };
}

async function getClient() {
  if (client) return client;
  await ensureDatabase();
  client = new SeekdbClient({
    host: HOST,
    port: PORT,
    user: USER,
    password: PASSWORD,
    database: DATABASE,
  });
  return client;
}

async function ensureCollection() {
  if (collection) return collection;
  const active = await getClient();

  try {
    collection = await active.getCollection({ name: COLLECTION, embeddingFunction: null });
    return collection;
  } catch (error) {
    // 集合不存在：按显式 schema 创建（向量维度必须与浏览器模型一致）
    const schema = new Schema({
      vectorIndex: new VectorIndexConfig({
        hnsw: { dimension: DIM },
        embeddingFunction: null,
      }),
    });
    try {
      collection = await active.createCollection({ name: COLLECTION, schema });
      return collection;
    } catch (createError) {
      // 创建时撞到已存在的元数据：说明集合其实在，重新读取即可
      collection = await active.getCollection({ name: COLLECTION, embeddingFunction: null });
      return collection;
    }
  }
}

/**
 * 写入文档块。每个块自带向量（由浏览器端模型生成），服务端只负责落库。
 */
async function addChunks(items) {
  const target = await ensureCollection();
  if (!items || items.length === 0) return { added: 0 };

  const ids = [];
  const documents = [];
  const embeddings = [];
  const metadatas = [];

  for (const item of items) {
    if (!Array.isArray(item.embedding) || item.embedding.length !== DIM) {
      throw new Error(`向量维度不正确：期望 ${DIM}，实际 ${item.embedding ? item.embedding.length : 0}`);
    }
    ids.push(String(item.id));
    documents.push(String(item.text));
    embeddings.push(item.embedding);
    metadatas.push({
      docId: String(item.docId || item.id),
      title: String(item.title || ''),
      seq: Number(item.seq || 0),
      sha256: String(item.sha256 || ''),
    });
  }

  await target.add({ ids, documents, embeddings, metadatas });
  return { added: ids.length };
}

/**
 * 混合检索：向量 + 全文由 seekdb 内部融合（RRF），一次调用返回排序结果。
 */
async function hybridSearch({ embedding, text, limit }) {
  const target = await ensureCollection();
  if (!Array.isArray(embedding) || embedding.length !== DIM) {
    throw new Error(`查询向量维度不正确：期望 ${DIM}`);
  }
  const n = Math.max(1, Math.min(Number(limit) || 5, 20));

  const result = await target.hybridSearch({
    query: { whereDocument: { $contains: text }, nResults: n },
    knn: { queryEmbeddings: [embedding], queryTexts: [text] },
    rank: { rrf: {} },
    nResults: n,
    include: ['documents', 'metadatas', 'distances'],
  });

  const ids = (result.ids && result.ids[0]) || [];
  const documents = (result.documents && result.documents[0]) || [];
  const metadatas = (result.metadatas && result.metadatas[0]) || [];
  const distances = (result.distances && result.distances[0]) || [];

  return ids.map((id, index) => ({
    id,
    text: documents[index] || '',
    distance: distances[index],
    metadata: metadatas[index] || {},
  }));
}

async function stats() {
  try {
    const target = await ensureCollection();
    const count = await target.count();
    return { count: Number(count) || 0, ...config() };
  } catch (error) {
    return { count: 0, error: error.message, ...config() };
  }
}

async function reset() {
  const active = await getClient();
  try {
    await active.deleteCollection(COLLECTION);
  } catch (error) {
    // 集合不存在时忽略
  }
  collection = null;
  return { reset: true, collection: COLLECTION };
}

async function close() {
  if (client) {
    await client.close();
    client = null;
    collection = null;
  }
}

module.exports = { addChunks, hybridSearch, stats, reset, close, config };
