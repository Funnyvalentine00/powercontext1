"""seekdb 存储层：文献分块入库与检索。

表结构已经定好（见 DDL），实现方式见 docs/DESIGN.md 任务 1、任务 2。
连接方式：pylibseekdb 启动嵌入式实例 -> 从 connection_options() 取 unix_socket
-> aiomysql 连接（与 PowerContext 自身的 seekdb 后端一致）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .parser import Chunk
from .textutil import keywords_of

TABLE = "rca_chunks"
DATABASE = "test"
CANDIDATE_LIMIT = 300

# 数据模型契约：字段名与类型不要改动，报告与自检都按这些字段回查。
DDL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE}` (
  `chunk_id` VARCHAR(80) NOT NULL,
  `doc_id` VARCHAR(80) NOT NULL,
  `doc_title` VARCHAR(255) NOT NULL,
  `seq` INT NOT NULL,
  `text` TEXT NOT NULL,
  `keywords` VARCHAR(512),
  `sha256` VARCHAR(64) NOT NULL,
  PRIMARY KEY (`chunk_id`)
)
"""

INSERT_SQL = (
    f"INSERT INTO `{TABLE}` (`chunk_id`, `doc_id`, `doc_title`, `seq`, `text`, `keywords`, `sha256`) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
)


class SeekdbStore:
    """嵌入式 seekdb 的连接门面（异步）。"""

    def __init__(self, path: Path, query_log: Path | None = None) -> None:
        self.path = path
        self.query_log = query_log
        self.statements: list[str] = []
        self._instance = None
        self._connection = None
        self._cursor = None

    async def __aenter__(self) -> "SeekdbStore":
        await self.open()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def open(self) -> None:
        """启动 embedded seekdb、建立 aiomysql 连接、执行 DDL。"""
        # 嵌入式 seekdb 只跑在 Linux：Windows 路径说明命令没在 WSL 里执行。
        if not str(self.path).startswith("/"):
            raise RuntimeError(f"seekdb 数据目录必须是 WSL 绝对路径，当前为 {self.path}；请在 WSL 中执行本项目命令")
        import aiomysql
        import pylibseekdb

        self.path.mkdir(parents=True, exist_ok=True)
        # instance 必须挂在 self 上：一旦被回收，后续 SQL 会失去底层引擎。
        try:
            self._instance = await pylibseekdb.aopen(str(self.path))
        except Exception as error:
            raise RuntimeError(
                f"seekdb 启动失败（数据目录 {self.path}）：{error}；"
                "若在 WSL 的 /mnt/d 下运行，请先执行 bash scripts/dev-setup-wsl.sh"
            ) from error
        options = self._instance.connection_options()
        self._connection = await aiomysql.connect(
            user=options["user"],
            unix_socket=options["unix_socket"],
            db=DATABASE,
            charset="utf8mb4",
            autocommit=False,
        )
        self._cursor = await self._connection.cursor()
        await self._execute(DDL)
        await self._connection.commit()

    async def close(self) -> None:
        """按 cursor -> connection -> instance 顺序关闭；清理阶段的异常不向上抛。"""
        if self._cursor is not None:
            try:
                await self._cursor.close()
            except Exception:
                pass
            self._cursor = None
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
        if self._instance is not None:
            try:
                self._instance.close()
            except Exception:
                pass
            self._instance = None

    def _log(self, sql: str, params: object = None) -> None:
        """每条 SQL 都落一份 JSONL 取证记录，logs/db-queries.jsonl 是评审材料。"""
        self.statements.append(sql)
        if self.query_log is None:
            return
        self.query_log.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sql": sql,
            "params": params,
        }
        with self.query_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def _execute(self, sql: str, params: object = None) -> None:
        self._log(sql, params)
        await self._cursor.execute(sql, params)

    async def _fetchone(self, sql: str, params: object = None):
        await self._execute(sql, params)
        return await self._cursor.fetchone()

    async def _fetchall(self, sql: str, params: object = None) -> list[tuple]:
        await self._execute(sql, params)
        return list(await self._cursor.fetchall())

    async def replace_documents(self, chunks: list[Chunk]) -> dict[str, int]:
        """按 doc_id 覆盖写入（先 DELETE 再 INSERT），返回 {doc_id: 块数}。"""
        grouped: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.doc_id, []).append(chunk)

        counts: dict[str, int] = {}
        for doc_id, doc_chunks in grouped.items():
            await self._execute(f"DELETE FROM `{TABLE}` WHERE `doc_id` = %s", (doc_id,))
            records = [
                (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.doc_title,
                    chunk.seq,
                    chunk.text,
                    keywords_of(chunk.text),
                    chunk.sha256,
                )
                for chunk in doc_chunks
            ]
            self._log(INSERT_SQL, records)
            await self._cursor.executemany(INSERT_SQL, records)
            counts[doc_id] = len(doc_chunks)
        await self._connection.commit()
        return counts

    async def search(self, query_tokens: set[str]) -> list[dict[str, object]]:
        """按查询词构造 LIKE 条件下推到 seekdb，取回候选块（上限 CANDIDATE_LIMIT）。

        返回字段：chunk_id / doc_id / doc_title / seq / text / sha256。
        """
        # 大集合下 LIKE 的条件数要可控；长词比短词更有区分度，优先保留。
        selected = sorted((token for token in query_tokens if token), key=lambda token: (-len(token), token))[:16]
        if not selected:
            return []
        where = " OR ".join(["`text` LIKE %s"] * len(selected))
        rows = await self._fetchall(
            f"SELECT `chunk_id`, `doc_id`, `doc_title`, `seq`, `text`, `sha256` "
            f"FROM `{TABLE}` WHERE {where} LIMIT {CANDIDATE_LIMIT}",
            [f"%{token}%" for token in selected],
        )
        return [
            {
                "chunk_id": row[0],
                "doc_id": row[1],
                "doc_title": row[2],
                "seq": int(row[3]),
                "text": row[4],
                "sha256": row[5],
            }
            for row in rows
        ]

    async def get_chunk(self, chunk_id: str) -> dict[str, object] | None:
        """按主键读取单个证据块，供自检回查使用。"""
        row = await self._fetchone(
            f"SELECT `chunk_id`, `doc_id`, `doc_title`, `seq`, `text`, `sha256` "
            f"FROM `{TABLE}` WHERE `chunk_id` = %s",
            (chunk_id,),
        )
        if row is None:
            return None
        return {
            "chunk_id": row[0],
            "doc_id": row[1],
            "doc_title": row[2],
            "seq": int(row[3]),
            "text": row[4],
            "sha256": row[5],
        }

    async def stats(self) -> dict[str, int]:
        """返回 {"chunks": 总块数, "documents": 文献数}。"""
        row = await self._fetchone(
            f"SELECT COUNT(*), COUNT(DISTINCT `doc_id`) FROM `{TABLE}`"
        )
        return {"chunks": int(row[0]), "documents": int(row[1])}

    async def list_documents(self) -> list[dict[str, object]]:
        """返回 [{doc_id, doc_title, chunks}]，用于 status 展示。"""
        rows = await self._fetchall(
            f"SELECT `doc_id`, `doc_title`, COUNT(*) FROM `{TABLE}` "
            "GROUP BY `doc_id`, `doc_title` ORDER BY `doc_id`"
        )
        return [{"doc_id": row[0], "doc_title": row[1], "chunks": int(row[2])} for row in rows]
