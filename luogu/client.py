"""使用洛谷官网当前 JSON 接口查询公开用户资料和比赛。"""

import asyncio
import json
import re
import time
from typing import Any
from urllib.parse import unquote

import requests

from .models import (
    LuoguContestProfile,
    LuoguContestResult,
    LuoguSubmission,
    LuoguSubmissionResult,
    LuoguUserProfile,
    LuoguUserResult,
)


class LuoguClient:
    BASE_URL = "https://www.luogu.com.cn"
    REQUEST_TIMEOUT = 12
    MAX_CONTEST_PAGES = 3
    USER_AGENT = "AstrBot-XCPC-Luogu/0.1"

    STATUS_NAMES = {
        0: "等待评测", 1: "正在评测", 2: "编译中", 3: "运行中",
        4: "编译错误", 5: "未知错误", 6: "系统错误", 7: "内存超限",
        8: "时间超限", 9: "输出超限", 10: "运行错误", 11: "答案错误",
        12: "Accepted", 13: "部分正确", 14: "文件错误", 15: "作弊",
    }
    LANGUAGE_NAMES = {
        0: "C++98", 1: "C++11", 2: "Pascal", 3: "Java 8", 4: "Python 2",
        5: "Python 3", 7: "C", 8: "C++14", 9: "C++17", 14: "Go",
        27: "C++20", 28: "C++20 (O2)", 34: "C++23",
    }
    DIFFICULTY_NAMES = {
        0: "暂无评定",
        1: "入门",
        2: "普及-",
        3: "普及/提高-",
        4: "普及+/提高",
        5: "提高+/省选-",
        6: "省选/NOI-",
        7: "NOI/NOI+/CTSC",
    }

    def __init__(self, cookie: str = "") -> None:
        self.cookie = str(cookie or "").strip()

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
    def _decode_record_response(response: requests.Response) -> dict:
        """兼容 lentille JSON 与普通页面中的 _feInjection 数据。"""
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            payload = response.json()
        else:
            match = re.search(
                r'window\._feInjection\s*=\s*JSON\.parse\(decodeURIComponent\("([^"]+)"\)\)',
                response.text,
            )
            if match is None:
                raise ValueError("响应中没有找到提交记录数据")
            payload = json.loads(unquote(match.group(1)))
        if not isinstance(payload, dict):
            raise ValueError("洛谷返回了不支持的提交记录格式")
        return payload

    def _request_submissions(self, uid: int, count: int) -> LuoguSubmissionResult:
        if not self.cookie:
            return LuoguSubmissionResult(
                False,
                "查询洛谷提交记录需要登录态，请管理员先在插件配置的 luogu_setting.cookie 中填写洛谷 Cookie",
            )
        uid = int(uid)
        count = max(1, min(int(count), 10))
        try:
            headers = self._headers(lentille=True)
            headers["Cookie"] = self.cookie
            response = requests.get(
                f"{self.BASE_URL}/record/list",
                params={"user": uid, "page": 1},
                headers=headers,
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = self._decode_record_response(response)
            # 洛谷目前并存两种 lentille 响应结构：
            # 旧版 currentTemplate/currentData 与新版 instance/template/data。
            data = payload.get("currentData")
            if not isinstance(data, dict):
                data = payload.get("data")
            records = data.get("records") if isinstance(data, dict) else None
            items = records.get("result") if isinstance(records, dict) else None
            is_login_page = (
                payload.get("currentTemplate") in {"AuthLogin", "Login"}
                or payload.get("instance") == "auth"
                or payload.get("template") == "login"
            )
            if is_login_page:
                raise ValueError("登录态无效或已过期，请管理员更新洛谷 Cookie")
            if not isinstance(items, list):
                raise ValueError("洛谷响应缺少 records.result")

            submissions = []
            for item in items[:count]:
                if not isinstance(item, dict):
                    continue
                problem = item.get("problem") if isinstance(item.get("problem"), dict) else {}
                user = item.get("user") if isinstance(item.get("user"), dict) else {}
                record_id = self._optional_int(item.get("id"))
                submit_time = self._optional_int(item.get("submitTime"))
                status = self._optional_int(item.get("status"))
                pid = problem.get("pid")
                title = problem.get("title")
                if None in (record_id, submit_time, status) or not isinstance(pid, str):
                    continue
                submissions.append(LuoguSubmission(
                    id=record_id,
                    uid=uid,
                    username=user.get("name") if isinstance(user.get("name"), str) else str(uid),
                    problem_id=pid,
                    problem_title=title if isinstance(title, str) else pid,
                    difficulty=self._optional_int(problem.get("difficulty")),
                    submit_time=submit_time,
                    status=status,
                    score=self._optional_int(item.get("score")),
                    language=item.get("language") if isinstance(item.get("language"), (int, str)) else None,
                    time_ms=self._optional_int(item.get("time")),
                    memory_kb=self._optional_int(item.get("memory")),
                ))
            if not submissions:
                return LuoguSubmissionResult(True, f"洛谷 UID {uid} 暂无提交记录", [])
            result = LuoguSubmissionResult(True, "", submissions)
            result.message = self.format_submissions(result)
            return result
        except requests.exceptions.Timeout:
            return LuoguSubmissionResult(False, "洛谷没有在 12 秒内返回提交记录，请求超时")
        except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as exc:
            return LuoguSubmissionResult(False, f"请求洛谷提交记录失败：{exc}")

    async def submission_info(self, uid: int, count: int = 5) -> LuoguSubmissionResult:
        return await asyncio.to_thread(self._request_submissions, uid, count)

    def format_submissions(self, result: LuoguSubmissionResult) -> str:
        if not result.ok or not result.submissions:
            return result.message
        lines = [f"{result.submissions[0].username}（UID {result.submissions[0].uid}）最近提交："]
        for index, submission in enumerate(result.submissions, 1):
            status = self.STATUS_NAMES.get(submission.status, f"状态 #{submission.status}")
            language = self.LANGUAGE_NAMES.get(submission.language, f"语言 #{submission.language}")
            difficulty = self.DIFFICULTY_NAMES.get(submission.difficulty, "未知")
            score = "未知" if submission.score is None else str(submission.score)
            resource = []
            if submission.time_ms is not None:
                resource.append(f"{submission.time_ms} ms")
            if submission.memory_kb is not None:
                resource.append(f"{submission.memory_kb} KB")
            lines.extend([
                f"\n{index}. {submission.problem_id} {submission.problem_title}",
                f"结果：{status}｜{score} 分｜{language}",
                f"难度：{difficulty}",
                f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(submission.submit_time))}",
                f"资源：{' / '.join(resource) if resource else '未知'}",
                f"记录：https://www.luogu.com.cn/record/{submission.id}",
            ])
        return "\n".join(lines)

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
