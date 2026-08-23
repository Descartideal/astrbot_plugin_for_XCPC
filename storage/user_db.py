"""SQLite 用户绑定存储。"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Iterable

from .models import CodeforcesBinding, LuoguBinding

class DataStorageHandler:
    """基于 SQLite 实现的 cf 信息绑定模块"""
    def __init__(
        self,
        db_path: str | Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        """初始化数据库连接、表结构和内存缓存。"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = RLock()

        self._bindings: dict[tuple[str, str], CodeforcesBinding] = {}
        self._group_index: dict[str, set[tuple[str, str]]] = {}
        self._handle_index: dict[str, set[tuple[str, str]]] = {}

        self._conn = sqlite3.connect(
            self.db_path,
            timeout=busy_timeout_ms / 1000,
            isolation_level="IMMEDIATE",
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row

        self._configure_connection(busy_timeout_ms)
        self._init_schema()
        self.reload_cache()

    def _configure_connection(self, busy_timeout_ms: int) -> None:
        """连接参数配置：同步策略、日志策略、超时时长等"""
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            self._conn.execute("PRAGMA wal_autocheckpoint=1000")

    def _init_schema(self) -> None:
        """表创建逻辑"""
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cf_bindings (
                    user_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    cf_handle TEXT NOT NULL,
                    enable_broadcast INTEGER NOT NULL DEFAULT 1
                        CHECK (enable_broadcast IN (0, 1)),
                    last_ac_fingerprint TEXT DEFAULT NULL,
                    updated_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, group_id)
                );

                CREATE INDEX IF NOT EXISTS idx_bind_group
                ON cf_bindings(group_id);

                CREATE INDEX IF NOT EXISTS idx_bind_handle
                ON cf_bindings(cf_handle);

                CREATE UNIQUE INDEX IF NOT EXISTS uq_bind_group_handle
                ON cf_bindings(group_id, cf_handle COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS luogu_bindings (
                    user_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    luogu_uid INTEGER NOT NULL CHECK (luogu_uid > 0),
                    luogu_name TEXT NOT NULL,
                    enable_broadcast INTEGER NOT NULL DEFAULT 1
                        CHECK (enable_broadcast IN (0, 1)),
                    last_ac_fingerprint TEXT DEFAULT NULL,
                    updated_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, group_id)
                );

                CREATE INDEX IF NOT EXISTS idx_luogu_bind_group
                ON luogu_bindings(group_id);

                CREATE UNIQUE INDEX IF NOT EXISTS uq_luogu_bind_group_uid
                ON luogu_bindings(group_id, luogu_uid);
                """
            )
            # 从 v0.1/v0.2 原表原位升级，不重建、不清空任何绑定数据。
            luogu_columns = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(luogu_bindings)")
            }
            if "enable_broadcast" not in luogu_columns:
                self._conn.execute(
                    "ALTER TABLE luogu_bindings ADD COLUMN "
                    "enable_broadcast INTEGER NOT NULL DEFAULT 1"
                )
            if "last_ac_fingerprint" not in luogu_columns:
                self._conn.execute(
                    "ALTER TABLE luogu_bindings ADD COLUMN "
                    "last_ac_fingerprint TEXT DEFAULT NULL"
                )
            self._conn.commit()

    def _run_write(self, sql: str, params: Iterable[object] = ()) -> sqlite3.Cursor:
        """写操作逻辑：线程先获取锁，然后通过事务提交修改或回滚修改"""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(sql, tuple(params))
                return cursor

    @staticmethod
    def _normalize_id(value: str | int) -> str:
        """统一把 AstrBot/QQ ID 转成非空字符串。"""
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("user_id and session/group_id cannot be empty")
        return normalized

    @staticmethod
    def _normalize_handle(value: str) -> str:
        """统一清理 Codeforces handle，保留原大小写用于展示。"""
        handle = value.strip()
        if not handle:
            raise ValueError("cf_handle cannot be empty")
        return handle

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> CodeforcesBinding:
        """将返回行对象加工为规定的数据类"""
        return CodeforcesBinding(
            user_id=row["user_id"],
            group_id=row["group_id"],
            cf_handle=row["cf_handle"],
            enable_broadcast=bool(row["enable_broadcast"]),
            last_ac_fingerprint=row["last_ac_fingerprint"],
            updated_at=int(row["updated_at"]),
        )

    def _replace_cache(self, bindings: Iterable[CodeforcesBinding]) -> None:
        """内存更新逻辑"""
        self._bindings.clear()
        self._group_index.clear()
        self._handle_index.clear()
        for binding in bindings:
            self._cache_add(binding)

    def _cache_add(self, binding: CodeforcesBinding) -> None:
        """向内存索引添加单条记录，调用方需保证 key 不重复"""
        key = (binding.user_id, binding.group_id)
        self._bindings[key] = binding
        self._group_index.setdefault(binding.group_id, set()).add(key)
        self._handle_index.setdefault(binding.cf_handle.casefold(), set()).add(key)

    def _cache_put(self, binding: CodeforcesBinding) -> None:
        """向内存中添加 / 更新单条记录"""
        key = (binding.user_id, binding.group_id)
        old_binding = self._bindings.get(key)
        if old_binding is not None:
            self._cache_remove(old_binding.user_id, old_binding.group_id)
        
        self._cache_add(binding)

    def _cache_remove(self, user_id: str, group_id: str) -> CodeforcesBinding | None:
        """删除内存中指定的 key，并返回对应的 CodeforcesBinding 对象"""
        key = (user_id, group_id)
        binding = self._bindings.pop(key, None)
        if binding is None:
            return None

        group_keys = self._group_index.get(group_id)
        if group_keys is not None:
            group_keys.discard(key)
            if not group_keys:
                self._group_index.pop(group_id, None)

        handle_key = binding.cf_handle.casefold()
        handle_keys = self._handle_index.get(handle_key)
        if handle_keys is not None:
            handle_keys.discard(key)
            if not handle_keys:
                self._handle_index.pop(handle_key, None)

        return binding

    def reload_cache(self) -> None:
        """从数据库中加载所有数据至内存"""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT user_id, group_id, cf_handle, enable_broadcast,
                       last_ac_fingerprint, updated_at
                FROM cf_bindings
                """
            ).fetchall()
            self._replace_cache(self._row_to_binding(row) for row in rows)

    async def areload_cache(self) -> None:
        """线程方法：从数据库中加载所有数据至内存"""
        await asyncio.to_thread(self.reload_cache)

    def bind_user(
        self,
        user_id: str | int,
        group_id: str | int,
        cf_handle: str,
        enable_broadcast: bool | None = None,
    ) -> CodeforcesBinding:
        """线程方法：用户绑定逻辑"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        cf_handle = self._normalize_handle(cf_handle)
        updated_at = int(time.time())

        with self._lock:
            current = self._bindings.get((user_id, group_id))
            last_ac_fingerprint = (
                current.last_ac_fingerprint
                if current is not None and current.cf_handle.casefold() == cf_handle.casefold()
                else None
            )
            if enable_broadcast is None and current is not None:
                broadcast_enabled = current.enable_broadcast
            elif enable_broadcast is None:
                broadcast_enabled = True
            else:
                broadcast_enabled = bool(enable_broadcast)

            self._run_write(
                """
                INSERT INTO cf_bindings (
                    user_id, group_id, cf_handle, enable_broadcast,
                    last_ac_fingerprint, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    cf_handle = excluded.cf_handle,
                    enable_broadcast = excluded.enable_broadcast,
                    updated_at = excluded.updated_at,
                    last_ac_fingerprint = excluded.last_ac_fingerprint
                """,
                (
                    user_id,
                    group_id,
                    cf_handle,
                    int(broadcast_enabled),
                    last_ac_fingerprint,
                    updated_at,
                ),
            )
            binding = CodeforcesBinding(
                user_id=user_id,
                group_id=group_id,
                cf_handle=cf_handle,
                enable_broadcast=broadcast_enabled,
                last_ac_fingerprint=last_ac_fingerprint,
                updated_at=updated_at,
            )
            self._cache_put(binding)
            return binding

    async def abind_user(
        self,
        user_id: str | int,
        group_id: str | int,
        cf_handle: str,
        enable_broadcast: bool | None = None,
    ) -> CodeforcesBinding:
        """异步 IO：创建单独线程执行用户绑定操作，保证数据一致性"""
        return await asyncio.to_thread(
            self.bind_user,
            user_id,
            group_id,
            cf_handle,
            enable_broadcast,
        )

    def unbind_user(self, user_id: str | int, group_id: str | int) -> bool:
        """线程方法：解绑用户逻辑，并返回布尔值，表示是否删除成功"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)

        with self._lock:
            cursor = self._run_write(
                "DELETE FROM cf_bindings WHERE user_id = ? AND group_id = ?",
                (user_id, group_id),
            )
            removed = cursor.rowcount > 0
            if removed:
                self._cache_remove(user_id, group_id)
            return removed

    async def aunbind_user(self, user_id: str | int, group_id: str | int) -> bool:
        """异步 IO：创建单独线程执行用户解绑操作"""
        return await asyncio.to_thread(self.unbind_user, user_id, group_id)

    def get_binding(self, user_id: str | int, group_id: str | int) -> CodeforcesBinding | None:
        """线程方法：通过指定键值对查询内存数据"""
        key = (self._normalize_id(user_id), self._normalize_id(group_id))
        with self._lock:
            return self._bindings.get(key)

    async def aget_binding(
        self,
        user_id: str | int,
        group_id: str | int,
    ) -> CodeforcesBinding | None:
        """异步 IO：创建单独线程执行查询操作"""
        return await asyncio.to_thread(self.get_binding, user_id, group_id)

    def list_group_bindings(
        self,
        group_id: str | int,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """线程方法：通过 AstrBot 会话 ID 获取对应会话内所有的绑定信息"""
        group_id = self._normalize_id(group_id)
        with self._lock:
            keys = self._group_index.get(group_id, set()).copy()
            bindings = [self._bindings[key] for key in keys if key in self._bindings]

        if only_broadcast_enabled:
            bindings = [binding for binding in bindings if binding.enable_broadcast]
        return sorted(bindings, key=lambda binding: (binding.cf_handle.casefold(), binding.user_id))

    async def alist_group_bindings(
        self,
        group_id: str | int,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """异步 IO：创建单独线程获取群绑定信息列表"""
        return await asyncio.to_thread(
            self.list_group_bindings,
            group_id,
            only_broadcast_enabled,
        )

    def list_bindings(
        self,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """线程方法：获取所有绑定信息。"""
        with self._lock:
            bindings = list(self._bindings.values())

        if only_broadcast_enabled:
            bindings = [binding for binding in bindings if binding.enable_broadcast]
        return sorted(
            bindings,
            key=lambda binding: (
                binding.cf_handle.casefold(),
                binding.group_id,
                binding.user_id,
            ),
        )

    async def alist_bindings(
        self,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """异步 IO：获取所有绑定信息。"""
        return await asyncio.to_thread(
            self.list_bindings,
            only_broadcast_enabled,
        )

    def find_by_handle(self, cf_handle: str) -> list[CodeforcesBinding]:
        """线程方法：通过 handle 获取绑定信息列表"""
        handle_key = self._normalize_handle(cf_handle).casefold()
        with self._lock:
            keys = self._handle_index.get(handle_key, set()).copy()
            bindings = [self._bindings[key] for key in keys if key in self._bindings]
        return sorted(bindings, key=lambda binding: (binding.group_id, binding.user_id))

    async def afind_by_handle(self, cf_handle: str) -> list[CodeforcesBinding]:
        """异步 IO：创建单独线程获取用户绑定信息列表"""
        return await asyncio.to_thread(self.find_by_handle, cf_handle)

    def set_broadcast_enabled(
        self,
        user_id: str | int,
        group_id: str | int,
        enabled: bool,
    ) -> CodeforcesBinding | None:
        """线程方法：修改用户 enable 字段"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        updated_at = int(time.time())

        with self._lock:
            current = self._bindings.get((user_id, group_id))
            if current is None:
                return None
            
            cursor = self._run_write(
                """
                UPDATE cf_bindings
                SET enable_broadcast = ?, updated_at = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (int(enabled), updated_at, user_id, group_id),
            )
            if cursor.rowcount <= 0:
                self._cache_remove(user_id, group_id)
                return None

            binding = CodeforcesBinding(
                user_id=user_id,
                group_id=group_id,
                cf_handle=current.cf_handle,
                enable_broadcast=enabled,
                last_ac_fingerprint=current.last_ac_fingerprint,
                updated_at=updated_at,
            )
            self._cache_put(binding)
            return binding

    async def aset_broadcast_enabled(
        self,
        user_id: str | int,
        group_id: str | int,
        enabled: bool,
    ) -> CodeforcesBinding | None:
        """异步 IO：创建单独线程执行线程方法"""
        return await asyncio.to_thread(
            self.set_broadcast_enabled,
            user_id,
            group_id,
            enabled,
        )

    def update_last_ac_fingerprint(
        self,
        user_id: str | int,
        group_id: str | int,
        fingerprint: str | None,
    ) -> CodeforcesBinding | None:
        """线程方法：更新用户记录指纹"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        updated_at = int(time.time())

        with self._lock:
            current = self._bindings.get((user_id, group_id))
            if current is None:
                return None

            cursor = self._run_write(
                """
                UPDATE cf_bindings
                SET last_ac_fingerprint = ?, updated_at = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (fingerprint, updated_at, user_id, group_id),
            )
            if cursor.rowcount <= 0:
                self._cache_remove(user_id, group_id)
                return None

            binding = CodeforcesBinding(
                user_id=user_id,
                group_id=group_id,
                cf_handle=current.cf_handle,
                enable_broadcast=current.enable_broadcast,
                last_ac_fingerprint=fingerprint,
                updated_at=updated_at,
            )
            self._cache_put(binding)
            return binding

    async def aupdate_last_ac_fingerprint(
        self,
        user_id: str | int,
        group_id: str | int,
        fingerprint: str | None,
    ) -> CodeforcesBinding | None:
        """异步 IO：更新指定用户的记录指纹"""
        return await asyncio.to_thread(
            self.update_last_ac_fingerprint,
            user_id,
            group_id,
            fingerprint,
        )
    
    def get_group_binding_by_handle(self, group_id, cf_handle):
        """线程方法：查询 cf handle 是否被唯一绑定"""
        group_id = self._normalize_id(group_id)
        handle_key = self._normalize_handle(cf_handle).casefold()
        with self._lock:
            keys = self._handle_index.get(handle_key, set()).copy()
            for key in keys:
                binding = self._bindings.get(key)
                if binding is not None and binding.group_id == group_id:
                    return binding
        return None
    
    async def aget_group_binding_by_handle(
        self,
        group_id: str | int,
        cf_handle: str | int,
    ) -> CodeforcesBinding | None:
        """异步 IO：查询绑定唯一性"""
        return await asyncio.to_thread(
            self.get_group_binding_by_handle,
            group_id,
            cf_handle
        )

    @staticmethod
    def _row_to_luogu_binding(row: sqlite3.Row) -> LuoguBinding:
        return LuoguBinding(
            user_id=row["user_id"],
            group_id=row["group_id"],
            luogu_uid=int(row["luogu_uid"]),
            luogu_name=row["luogu_name"],
            enable_broadcast=bool(row["enable_broadcast"]),
            last_ac_fingerprint=row["last_ac_fingerprint"],
            updated_at=int(row["updated_at"]),
        )

    def bind_luogu_user(
        self,
        user_id: str | int,
        group_id: str | int,
        luogu_uid: int,
        luogu_name: str,
    ) -> LuoguBinding:
        """按数字 UID 绑定洛谷账号；同一会话内 UID 唯一。"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        if isinstance(luogu_uid, bool) or int(luogu_uid) <= 0:
            raise ValueError("luogu_uid must be a positive integer")
        luogu_uid = int(luogu_uid)
        luogu_name = str(luogu_name).strip()
        if not luogu_name:
            raise ValueError("luogu_name cannot be empty")
        updated_at = int(time.time())

        with self._lock:
            current_row = self._conn.execute(
                """
                SELECT luogu_uid, enable_broadcast, last_ac_fingerprint
                FROM luogu_bindings WHERE user_id = ? AND group_id = ?
                """,
                (user_id, group_id),
            ).fetchone()
            enable_broadcast = (
                bool(current_row["enable_broadcast"])
                if current_row is not None else True
            )
            last_ac_fingerprint = (
                current_row["last_ac_fingerprint"]
                if current_row is not None and int(current_row["luogu_uid"]) == luogu_uid
                else None
            )
            self._run_write(
                """
                INSERT INTO luogu_bindings (
                    user_id, group_id, luogu_uid, luogu_name, enable_broadcast,
                    last_ac_fingerprint, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    luogu_uid = excluded.luogu_uid,
                    luogu_name = excluded.luogu_name,
                    enable_broadcast = excluded.enable_broadcast,
                    last_ac_fingerprint = excluded.last_ac_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id, group_id, luogu_uid, luogu_name,
                    int(enable_broadcast), last_ac_fingerprint, updated_at,
                ),
            )
        return LuoguBinding(
            user_id, group_id, luogu_uid, luogu_name,
            enable_broadcast, last_ac_fingerprint, updated_at,
        )

    async def abind_luogu_user(self, *args) -> LuoguBinding:
        return await asyncio.to_thread(self.bind_luogu_user, *args)

    def get_luogu_binding(
        self,
        user_id: str | int,
        group_id: str | int,
    ) -> LuoguBinding | None:
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT user_id, group_id, luogu_uid, luogu_name,
                       enable_broadcast, last_ac_fingerprint, updated_at
                FROM luogu_bindings WHERE user_id = ? AND group_id = ?
                """,
                (user_id, group_id),
            ).fetchone()
        return self._row_to_luogu_binding(row) if row is not None else None

    async def aget_luogu_binding(self, *args) -> LuoguBinding | None:
        return await asyncio.to_thread(self.get_luogu_binding, *args)

    def get_group_luogu_binding_by_uid(
        self,
        group_id: str | int,
        luogu_uid: int,
    ) -> LuoguBinding | None:
        group_id = self._normalize_id(group_id)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT user_id, group_id, luogu_uid, luogu_name,
                       enable_broadcast, last_ac_fingerprint, updated_at
                FROM luogu_bindings WHERE group_id = ? AND luogu_uid = ?
                """,
                (group_id, int(luogu_uid)),
            ).fetchone()
        return self._row_to_luogu_binding(row) if row is not None else None

    async def aget_group_luogu_binding_by_uid(self, *args) -> LuoguBinding | None:
        return await asyncio.to_thread(self.get_group_luogu_binding_by_uid, *args)

    def list_luogu_bindings(
        self,
        only_broadcast_enabled: bool = False,
    ) -> list[LuoguBinding]:
        sql = (
            "SELECT user_id, group_id, luogu_uid, luogu_name, "
            "enable_broadcast, last_ac_fingerprint, updated_at "
            "FROM luogu_bindings"
        )
        if only_broadcast_enabled:
            sql += " WHERE enable_broadcast = 1"
        sql += " ORDER BY luogu_uid, group_id, user_id"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [self._row_to_luogu_binding(row) for row in rows]

    async def alist_luogu_bindings(self, *args) -> list[LuoguBinding]:
        return await asyncio.to_thread(self.list_luogu_bindings, *args)

    def set_luogu_broadcast_enabled(
        self,
        user_id: str | int,
        group_id: str | int,
        enabled: bool,
    ) -> LuoguBinding | None:
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        updated_at = int(time.time())
        with self._lock:
            cursor = self._run_write(
                """
                UPDATE luogu_bindings
                SET enable_broadcast = ?, updated_at = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (int(enabled), updated_at, user_id, group_id),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_luogu_binding(user_id, group_id)

    async def aset_luogu_broadcast_enabled(self, *args) -> LuoguBinding | None:
        return await asyncio.to_thread(self.set_luogu_broadcast_enabled, *args)

    def update_luogu_last_ac_fingerprint(
        self,
        user_id: str | int,
        group_id: str | int,
        fingerprint: str | None,
    ) -> LuoguBinding | None:
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        updated_at = int(time.time())
        with self._lock:
            cursor = self._run_write(
                """
                UPDATE luogu_bindings
                SET last_ac_fingerprint = ?, updated_at = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (fingerprint, updated_at, user_id, group_id),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_luogu_binding(user_id, group_id)

    async def aupdate_luogu_last_ac_fingerprint(self, *args) -> LuoguBinding | None:
        return await asyncio.to_thread(self.update_luogu_last_ac_fingerprint, *args)

    def unbind_luogu_user(self, user_id: str | int, group_id: str | int) -> bool:
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        with self._lock:
            cursor = self._run_write(
                "DELETE FROM luogu_bindings WHERE user_id = ? AND group_id = ?",
                (user_id, group_id),
            )
            return cursor.rowcount > 0

    async def aunbind_luogu_user(self, *args) -> bool:
        return await asyncio.to_thread(self.unbind_luogu_user, *args)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    async def aclose(self) -> None:
        """关闭数据库连接"""
        await asyncio.to_thread(self.close)
