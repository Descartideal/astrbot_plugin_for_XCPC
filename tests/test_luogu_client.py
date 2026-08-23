import time
import unittest

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


if __name__ == "__main__":
    unittest.main()
