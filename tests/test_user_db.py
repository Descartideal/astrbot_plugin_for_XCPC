import tempfile
import unittest
import sqlite3
from pathlib import Path

from storage.user_db import DataStorageHandler


class DataStorageHandlerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "user_bindings.sqlite3"
        self.storage = DataStorageHandler(self.db_path)

    def tearDown(self):
        self.storage.close()
        self.temp_dir.cleanup()

    def test_bind_user_creates_binding_and_normalizes_values(self):
        binding = self.storage.bind_user(" 1001 ", " 2002 ", " tourist ")

        self.assertEqual(binding.user_id, "1001")
        self.assertEqual(binding.group_id, "2002")
        self.assertEqual(binding.cf_handle, "tourist")
        self.assertTrue(binding.enable_broadcast)
        self.assertIsNone(binding.last_ac_fingerprint)
        self.assertGreater(binding.updated_at, 0)
        self.assertEqual(self.storage.get_binding("1001", "2002"), binding)

    def test_bind_user_updates_handle_and_resets_submission_baseline(self):
        self.storage.bind_user("1001", "2002", "old_handle", enable_broadcast=False)
        self.storage.update_last_ac_fingerprint("1001", "2002", "1234-A")

        binding = self.storage.bind_user("1001", "2002", "new_handle")

        self.assertEqual(binding.cf_handle, "new_handle")
        self.assertFalse(binding.enable_broadcast)
        self.assertIsNone(binding.last_ac_fingerprint)
        self.assertEqual(self.storage.find_by_handle("old_handle"), [])
        self.assertEqual(self.storage.find_by_handle("NEW_HANDLE"), [binding])

    def test_bind_user_can_override_broadcast_enabled(self):
        self.storage.bind_user("1001", "2002", "tourist", enable_broadcast=False)

        binding = self.storage.bind_user("1001", "2002", "tourist", enable_broadcast=True)

        self.assertTrue(binding.enable_broadcast)

    def test_unbind_user_removes_database_row_and_cache_indexes(self):
        binding = self.storage.bind_user("1001", "2002", "tourist")

        self.assertTrue(self.storage.unbind_user("1001", "2002"))
        self.assertFalse(self.storage.unbind_user("1001", "2002"))
        self.assertIsNone(self.storage.get_binding("1001", "2002"))
        self.assertNotIn(binding, self.storage.list_group_bindings("2002"))
        self.assertEqual(self.storage.find_by_handle("tourist"), [])

    def test_list_group_bindings_sorts_and_filters_broadcast_enabled(self):
        disabled = self.storage.bind_user("u2", "g1", "beta", enable_broadcast=False)
        enabled_a = self.storage.bind_user("u1", "g1", "Alpha")
        enabled_b = self.storage.bind_user("u3", "g1", "charlie")
        self.storage.bind_user("u4", "g2", "delta")

        self.assertEqual(
            self.storage.list_group_bindings("g1"),
            [enabled_a, disabled, enabled_b],
        )
        self.assertEqual(
            self.storage.list_group_bindings("g1", only_broadcast_enabled=True),
            [enabled_a, enabled_b],
        )

    def test_set_broadcast_enabled_updates_existing_binding_only(self):
        self.storage.bind_user("1001", "2002", "tourist")
        self.storage.update_last_ac_fingerprint("1001", "2002", "1234-A")

        binding = self.storage.set_broadcast_enabled("1001", "2002", False)

        self.assertIsNotNone(binding)
        self.assertFalse(binding.enable_broadcast)
        self.assertEqual(binding.last_ac_fingerprint, "1234-A")
        self.assertIsNone(self.storage.set_broadcast_enabled("missing", "2002", True))

    def test_update_last_ac_fingerprint_updates_existing_binding_only(self):
        self.storage.bind_user("1001", "2002", "tourist", enable_broadcast=False)

        binding = self.storage.update_last_ac_fingerprint("1001", "2002", "1234-A")

        self.assertIsNotNone(binding)
        self.assertEqual(binding.last_ac_fingerprint, "1234-A")
        self.assertFalse(binding.enable_broadcast)
        self.assertIsNone(
            self.storage.update_last_ac_fingerprint("missing", "2002", "1234-A")
        )

    def test_reload_cache_reads_existing_database_rows(self):
        original = self.storage.bind_user("1001", "2002", "tourist")
        self.storage.close()

        self.storage = DataStorageHandler(self.db_path)

        self.assertEqual(self.storage.get_binding("1001", "2002"), original)
        self.assertEqual(self.storage.list_group_bindings("2002"), [original])
        self.assertEqual(self.storage.find_by_handle("Tourist"), [original])

    def test_empty_ids_and_handles_are_rejected(self):
        with self.assertRaises(ValueError):
            self.storage.bind_user("", "2002", "tourist")
        with self.assertRaises(ValueError):
            self.storage.bind_user("1001", " ", "tourist")
        with self.assertRaises(ValueError):
            self.storage.bind_user("1001", "2002", " ")

    def test_luogu_binding_uses_uid_and_is_unique_per_group(self):
        binding = self.storage.bind_luogu_user("1001", "group-1", 8457, "chen_zhe")

        self.assertEqual(binding.luogu_uid, 8457)
        self.assertEqual(
            self.storage.get_luogu_binding("1001", "group-1"),
            binding,
        )
        self.assertEqual(
            self.storage.get_group_luogu_binding_by_uid("group-1", 8457),
            binding,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.bind_luogu_user("1002", "group-1", 8457, "chen_zhe")

    def test_luogu_binding_can_be_replaced_and_unbound(self):
        self.storage.bind_luogu_user("1001", "group-1", 1, "kkksc03")
        replaced = self.storage.bind_luogu_user("1001", "group-1", 8457, "chen_zhe")

        self.assertEqual(replaced.luogu_uid, 8457)
        self.assertTrue(self.storage.unbind_luogu_user("1001", "group-1"))
        self.assertIsNone(self.storage.get_luogu_binding("1001", "group-1"))


class AsyncDataStorageHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "user_bindings.sqlite3"
        self.storage = DataStorageHandler(self.db_path)

    async def asyncTearDown(self):
        await self.storage.aclose()
        self.temp_dir.cleanup()

    async def test_async_wrappers_delegate_to_sync_operations(self):
        binding = await self.storage.abind_user("1001", "2002", "tourist")

        self.assertEqual(await self.storage.aget_binding("1001", "2002"), binding)
        self.assertEqual(await self.storage.afind_by_handle("tourist"), [binding])
        self.assertEqual(await self.storage.alist_group_bindings("2002"), [binding])

        updated = await self.storage.aset_broadcast_enabled("1001", "2002", False)
        self.assertIsNotNone(updated)
        self.assertFalse(updated.enable_broadcast)

        updated = await self.storage.aupdate_last_ac_fingerprint(
            "1001",
            "2002",
            "1234-A",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.last_ac_fingerprint, "1234-A")

        self.assertTrue(await self.storage.aunbind_user("1001", "2002"))
        self.assertIsNone(await self.storage.aget_binding("1001", "2002"))


if __name__ == "__main__":
    unittest.main()
