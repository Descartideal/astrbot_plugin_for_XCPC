"""使用洛谷官网当前 JSON 接口查询公开用户资料和比赛。"""

import asyncio
import time
from typing import Any

import requests

from .models import (
    LuoguContestProfile,
    LuoguContestResult,
    LuoguUserProfile,
    LuoguUserResult,
)


class LuoguClient:
    BASE_URL = "https://www.luogu.com.cn"
    REQUEST_TIMEOUT = 12
    MAX_CONTEST_PAGES = 3
    USER_AGENT = "AstrBot-XCPC-Luogu/0.1"

    def _headers(self, *, lentille: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Referer": f"{self.BASE_URL}/",
            # 洛谷会拒绝 python-requests 默认 UA 和以 Mozilla/ 开头的 UA。
            "User-Agent": self.USER_AGENT,
        }
        if lentille:
            headers["x-lentille-request"] = "content-only"
        return headers

    def _get_json(self, path: str, *, params=None, lentille: bool = False) -> dict:
        response = requests.get(
            f"{self.BASE_URL}{path}",
            params=params,
            headers=self._headers(lentille=lentille),
            timeout=self.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("洛谷返回了不支持的响应格式")
        return payload

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _resolve_user(self, handle: str) -> dict | None:
        payload = self._get_json("/api/user/search", params={"keyword": handle})
        users = payload.get("users")
        if not isinstance(users, list):
            raise ValueError("洛谷用户搜索响应缺少 users 列表")

        normalized = handle.casefold()
        for user in users:
            if not isinstance(user, dict):
                continue
            name = user.get("name")
            uid = user.get("uid")
            if isinstance(name, str) and name.casefold() == normalized:
                return user
            if handle.isdigit() and str(uid) == handle:
                return user
        return None

    def _request_user(self, handle: str) -> LuoguUserResult:
        handle = str(handle).strip()
        if not handle:
            return LuoguUserResult(False, "洛谷用户名不能为空")

        try:
            resolved = self._resolve_user(handle)
            if resolved is None:
                return LuoguUserResult(False, f"未找到洛谷用户：{handle}")
            uid = self._optional_int(resolved.get("uid"))
            if uid is None:
                raise ValueError("洛谷用户搜索结果缺少有效 UID")

            payload = self._get_json(f"/user/{uid}", lentille=True)
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ValueError("洛谷用户详情响应缺少 data")
            user = data.get("user")
            if not isinstance(user, dict):
                raise ValueError("洛谷用户详情响应缺少 user")
            gu = data.get("gu") if isinstance(data.get("gu"), dict) else {}
            scores = gu.get("scores") if isinstance(gu.get("scores"), dict) else {}

            name = user.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("洛谷用户详情缺少用户名")
            profile = LuoguUserProfile(
                uid=uid,
                name=name,
                avatar=user.get("avatar") if isinstance(user.get("avatar"), str) else None,
                color=user.get("color") if isinstance(user.get("color"), str) else None,
                badge=user.get("badge") if isinstance(user.get("badge"), str) else None,
                slogan=user.get("slogan") if isinstance(user.get("slogan"), str) else None,
                gu_value=self._optional_int(gu.get("rating")),
                ranking=self._optional_int(user.get("ranking")),
                contribution=self._optional_int(scores.get("social")),
                following_count=self._optional_int(user.get("followingCount")),
                follower_count=self._optional_int(user.get("followerCount")),
                passed_problem_count=self._optional_int(user.get("passedProblemCount")),
                submitted_problem_count=self._optional_int(user.get("submittedProblemCount")),
                register_time=self._optional_int(user.get("registerTime")),
                gu_updated_at=self._optional_int(gu.get("time")),
            )
            return LuoguUserResult(True, self._format_user_text(profile), profile)
        except requests.exceptions.Timeout:
            return LuoguUserResult(False, "洛谷没有在 12 秒内返回数据，请求超时")
        except (requests.exceptions.RequestException, ValueError) as exc:
            return LuoguUserResult(False, f"请求洛谷用户信息失败：{exc}")

    @staticmethod
    def _format_user_text(profile: LuoguUserProfile) -> str:
        return "\n".join(
            [
                f"洛谷用户：{profile.name}（UID {profile.uid}）",
                f"咕值：{profile.gu_value if profile.gu_value is not None else '未知'}",
                f"排名：{profile.ranking if profile.ranking is not None else '未知'}",
                f"社区贡献：{profile.contribution if profile.contribution is not None else '未知'}",
                f"关注 / 粉丝：{profile.following_count or 0} / {profile.follower_count or 0}",
                "最近在线：洛谷官网未公开",
                f"主页：https://www.luogu.com.cn/user/{profile.uid}",
            ]
        )

    async def user_info(self, handle: str) -> LuoguUserResult:
        return await asyncio.to_thread(self._request_user, handle)

    def _contest_from_dict(self, item: dict) -> LuoguContestProfile | None:
        contest_id = self._optional_int(item.get("id"))
        start_time = self._optional_int(item.get("startTime"))
        end_time = self._optional_int(item.get("endTime"))
        name = item.get("name")
        if contest_id is None or start_time is None or end_time is None or not isinstance(name, str):
            return None
        host = item.get("host") if isinstance(item.get("host"), dict) else {}
        return LuoguContestProfile(
            id=contest_id,
            name=name,
            start_time=start_time,
            end_time=end_time,
            method=self._optional_int(item.get("method")),
            rated=self._optional_int(item.get("rated")),
            host_name=host.get("name") if isinstance(host.get("name"), str) else None,
            problem_count=self._optional_int(item.get("problemCount")),
        )

    def _request_contests(self, count: int) -> LuoguContestResult:
        count = max(1, min(int(count), 10))
        now = int(time.time())
        contests: dict[int, LuoguContestProfile] = {}
        try:
            for page in range(1, self.MAX_CONTEST_PAGES + 1):
                payload = self._get_json("/contest/list", params={"page": page}, lentille=True)
                data = payload.get("data")
                listing = data.get("contests") if isinstance(data, dict) else None
                items = listing.get("result") if isinstance(listing, dict) else None
                if not isinstance(items, list):
                    raise ValueError("洛谷比赛列表响应缺少 contests.result")

                saw_finished = False
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    contest = self._contest_from_dict(item)
                    if contest is None:
                        continue
                    if contest.end_time < now:
                        saw_finished = True
                        continue
                    contests[contest.id] = contest
                # 列表按开始时间倒序；遇到已结束比赛后无需继续翻页。
                if saw_finished or not items:
                    break

            selected = sorted(contests.values(), key=lambda contest: contest.start_time)[:count]
            if not selected:
                return LuoguContestResult(False, "暂未查询到进行中或即将开始的洛谷比赛")
            return LuoguContestResult(
                True,
                f"查询到 {len(selected)} 场进行中或即将开始的洛谷比赛",
                selected,
            )
        except requests.exceptions.Timeout:
            return LuoguContestResult(False, "洛谷没有在 12 秒内返回比赛数据，请求超时")
        except (requests.exceptions.RequestException, ValueError) as exc:
            return LuoguContestResult(False, f"请求洛谷比赛信息失败：{exc}")

    async def contest_info(self, count: int) -> LuoguContestResult:
        return await asyncio.to_thread(self._request_contests, count)

    @staticmethod
    def format_contests(result: LuoguContestResult) -> str:
        if not result.ok or not result.contests:
            return result.message
        now = int(time.time())
        messages = []
        for index, contest in enumerate(result.contests, 1):
            phase = "进行中" if contest.start_time <= now <= contest.end_time else "未开始"
            duration = max(0, contest.end_time - contest.start_time)
            messages.append(
                "\n".join(
                    [
                        f"{index}. {contest.name}",
                        f"状态：{phase}",
                        f"开始时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(contest.start_time))}",
                        f"时长：{duration // 3600} 小时 {(duration % 3600) // 60} 分钟",
                        f"链接：https://www.luogu.com.cn/contest/{contest.id}",
                    ]
                )
            )
        return "\n\n".join(messages)
