import time
import unittest
from unittest.mock import patch

from luogu.client import LuoguClient


class FakeLuoguClient(LuoguClient):
    def _get_json(self, path, *, params=None, lentille=False):
        if path == "/api/user/search":
            return {"users": [{"uid": 8457, "name": "chen_zhe"}]}
        if path == "/user/8457":
            return {
                "data": {
                    "user": {
                        "uid": 8457,
                        "name": "chen_zhe",
                        "ranking": 307,
                        "followingCount": 286,
                        "followerCount": 40553,
                    },
                    "gu": {"rating": 334, "time": 1700000000, "scores": {"social": 100}},
                }
            }
        if path == "/contest/list":
            now = int(time.time())
            return {
                "data": {
                    "contests": {
                        "result": [
                            {"id": 2, "name": "later", "startTime": now + 7200, "endTime": now + 10800},
                            {"id": 1, "name": "near", "startTime": now + 3600, "endTime": now + 5400},
                            {"id": 0, "name": "finished", "startTime": now - 7200, "endTime": now - 3600},
                        ]
                    }
                }
            }
        raise AssertionError(path)


class LuoguClientTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeLuoguClient()

    def test_profile_maps_gu_ranking_and_social_contribution(self):
        result = self.client._request_user("8457")

        self.assertTrue(result.ok)
        self.assertEqual(result.profile.uid, 8457)
        self.assertEqual(result.profile.gu_value, 334)
        self.assertEqual(result.profile.ranking, 307)
        self.assertEqual(result.profile.contribution, 100)

    def test_contests_are_filtered_and_sorted_nearest_first(self):
        result = self.client._request_contests(5)

        self.assertTrue(result.ok)
        self.assertEqual([contest.id for contest in result.contests], [1, 2])

    def test_submissions_require_cookie(self):
        result = LuoguClient()._request_submissions(1080507, 5)
        self.assertFalse(result.ok)
        self.assertIn("Cookie", result.message)

    @patch("luogu.client.requests.get")
    def test_submission_page_maps_record_fields(self, get):
        payload = {
            "currentTemplate": "RecordList",
            "currentData": {"records": {"result": [{
                "id": 294911668,
                "submitTime": 1787507283,
                "status": 12,
                "score": 100,
                "language": 34,
                "time": 1164,
                "memory": 28964,
                "problem": {"pid": "U694435", "title": "D. Prefix Teleporter Sum", "difficulty": 5},
                "user": {"uid": 1080507, "name": "Descartideal"},
            }]}}
        }
        response = get.return_value
        response.headers = {"content-type": "application/json"}
        response.json.return_value = payload
        response.raise_for_status.return_value = None

        result = LuoguClient(cookie="sid=test")._request_submissions(1080507, 5)

        self.assertTrue(result.ok)
        self.assertEqual(result.submissions[0].problem_id, "U694435")
        self.assertEqual(result.submissions[0].status, 12)
        self.assertEqual(result.submissions[0].difficulty, 5)
        self.assertIn("难度：省选/NOI-", result.message)
        self.assertIn("Accepted", result.message)

    @patch("luogu.client.requests.get")
    def test_modern_lentille_submission_shape_is_supported(self, get):
        response = get.return_value
        response.headers = {"content-type": "application/json"}
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "instance": "record",
            "template": "list",
            "status": 200,
            "data": {"records": {"result": [{
                "id": 294911668,
                "submitTime": 1787507283,
                "status": 12,
                "score": 100,
                "language": 34,
                "time": 1164,
                "memory": 28964,
                "problem": {"pid": "U694435", "title": "D. Prefix Teleporter Sum", "difficulty": 2},
                "user": {"uid": 1080507, "name": "Descartideal"},
            }]}}
        }

        result = LuoguClient(cookie="__client_id=test")._request_submissions(1080507, 1)

        self.assertTrue(result.ok)
        self.assertEqual(result.submissions[0].id, 294911668)

    @patch("luogu.client.requests.get")
    def test_modern_login_response_reports_expired_cookie(self, get):
        response = get.return_value
        response.headers = {"content-type": "application/json"}
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "instance": "auth",
            "template": "login",
            "status": 200,
            "data": {"webauthn": {}},
            "user": None,
        }

        result = LuoguClient(cookie="__client_id=expired")._request_submissions(1080507, 1)

        self.assertFalse(result.ok)
        self.assertIn("登录态无效或已过期", result.message)


if __name__ == "__main__":
    unittest.main()
