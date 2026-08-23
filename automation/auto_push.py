"""自动推送调度：比赛定时推送和提交记录轮询。"""
import asyncio
import datetime
import re
import time
from collections.abc import Awaitable, Callable

from astrbot.api import logger

class AutomationPushHandler:
    """通过回调发送消息的自动化任务调度器。"""

    API_REQUEST_INTERVAL_SECONDS = 3
    CONTEST_RETRY_SECONDS = 60

    def __init__(
        self,
        *,
        user_status_handler,
        contest_info_handler,
        luogu_client,
        user_db_handler,
        loop_time: int,
        enable_getter: Callable[[], bool],
        message_sender: Callable[[str, str], Awaitable[None]],
        contest_message_sender: Callable[[str, object, str], Awaitable[None]] | None = None,
        contest_number: int,
        contest_push_time: str,
        contest_push_sessions: list[str],
    ) -> None:
        self.user_status_handler = user_status_handler
        self.contest_info_handler = contest_info_handler
        self.luogu_client = luogu_client
        self.user_db_handler = user_db_handler
        self.loop_time = loop_time
        self.enable_getter = enable_getter
        self.message_sender = message_sender
        self.contest_message_sender = contest_message_sender
        self.contest_number = contest_number
        self.contest_push_time = contest_push_time
        self.contest_push_sessions = contest_push_sessions

        self.hour_contest = 0
        self.minute_contest = 0
        self._contest_push_running = True
        self._submission_push_running = True
        self._contest_scheduler_task: asyncio.Task | None = None
        self._submission_scheduler_task: asyncio.Task | None = None
        self._api_request_lock = asyncio.Lock()
        self._last_api_request_time: float | None = None
        self._luogu_cookie_warning_logged = False

        self._configure_contest_push()

    async def start(self) -> None:
        """启动自动化推送任务"""
        if self._contest_push_running and self.contest_push_sessions:
            self._contest_scheduler_task = asyncio.create_task(
                self._auto_time_scheduler_contest()
            )
            self._log_next_contest_run()
            logger.info("比赛自动推送任务已启动")
        elif self._contest_push_running:
            logger.info("未配置比赛推送会话，跳过比赛自动推送任务")

        if self._submission_push_running:
            self._submission_scheduler_task = asyncio.create_task(
                self._auto_time_scheduler_submission()
            )
            self._log_next_submission_run(datetime.datetime.now())
            logger.info("提交记录自动轮询任务已启动")

    async def stop(self) -> None:
        """停止自动化推送任务"""
        self._contest_push_running = False
        self._submission_push_running = False
        logger.info("正在停止自动化推送任务")
        tasks = []
        if self._contest_scheduler_task:
            self._contest_scheduler_task.cancel()
            tasks.append(self._contest_scheduler_task)
        if self._submission_scheduler_task:
            self._submission_scheduler_task.cancel()
            tasks.append(self._submission_scheduler_task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _configure_contest_push(self) -> None:
        """校验并初始化比赛定时推送配置"""
        if not self.contest_push_time:
            logger.info("未设置比赛推送时间，跳过")
            self._contest_push_running = False
            return

        if not self._validate_time(self.contest_push_time):
            logger.warning("时间格式错误，跳过比赛推送配置")
            self._contest_push_running = False
            return

        self.hour_contest, self.minute_contest = map(
            int,
            self.contest_push_time.split(":"),
        )

    def _get_next_run_contest(self) -> datetime.datetime:
        """计算下次比赛的推送时间"""
        now = datetime.datetime.now()
        target = now.replace(
            hour=self.hour_contest,
            minute=self.minute_contest,
            second=0,
            microsecond=0,
        )

        if target <= now:
            target += datetime.timedelta(days=1)

        return target

    def _get_next_run_submission(self) -> datetime.datetime:
        """计算下次提交轮询时间"""
        loop_seconds = max(1, int(self.loop_time))
        return datetime.datetime.now() + datetime.timedelta(seconds=loop_seconds)

    @staticmethod
    def _format_run_time(run_time: datetime.datetime) -> str:
        return run_time.strftime("%Y-%m-%d %H:%M:%S")

    def _log_next_contest_run(self, run_time: datetime.datetime | None = None) -> None:
        run_time = run_time or self._get_next_run_contest()
        logger.info(f"下次比赛推送时间：{self._format_run_time(run_time)}")

    def _log_next_submission_run(self, run_time: datetime.datetime | None = None) -> None:
        run_time = run_time or self._get_next_run_submission()
        logger.info(f"下次提交查询时间：{self._format_run_time(run_time)}")

    async def _wait_for_api_request_slot(self) -> None:
        """统一限制自动任务的 Codeforces API 请求起点"""
        async with self._api_request_lock:
            now = time.monotonic()
            if self._last_api_request_time is not None:
                elapsed = now - self._last_api_request_time
                wait_seconds = self.API_REQUEST_INTERVAL_SECONDS - elapsed
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

            self._last_api_request_time = time.monotonic()

    async def _contest_push_to_sessions(self) -> None:
        """自动推送比赛信息到指定群聊"""
        await self._wait_for_api_request_slot()
        result = await self.contest_info_handler.ContestInfoRequest(self.contest_number)
        message = self.build_contest_message(result)

        for recv in self.contest_push_sessions:
            logger.info(f"准备向群聊 {recv} 推送比赛信息")
            if self.contest_message_sender is not None:
                await self.contest_message_sender(recv, result, message)
            else:
                await self.message_sender(recv, message)
            logger.info(f"已经向群聊 {recv} 发送最近 {self.contest_number} 条比赛信息")

    async def _auto_time_scheduler_contest(self) -> None:
        """自动化任务：按照规定时间向指定群聊推送比赛信息"""
        while self._contest_push_running:
            try:
                next_run = self._get_next_run_contest()
                wait_seconds = (next_run - datetime.datetime.now()).total_seconds()

                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                if self._contest_push_running:
                    logger.info("开始向指定群聊推送比赛任务")
                    await self._contest_push_to_sessions()
                    logger.info("比赛任务推送完成")
                    self._log_next_contest_run()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"比赛任务推送出错：{e}")
                self._log_next_contest_run()
                await asyncio.sleep(self.CONTEST_RETRY_SECONDS)

    async def _auto_time_scheduler_submission(self) -> None:
        """自动化任务：定时轮询用户提交记录"""
        while self._submission_push_running:
            try:
                if self._submission_push_running:
                    await self._poll_submission_once()

                next_run = self._get_next_run_submission()
                wait_seconds = (next_run - datetime.datetime.now()).total_seconds()
                if self._submission_push_running and wait_seconds > 0:
                    self._log_next_submission_run(next_run)
                    await asyncio.sleep(wait_seconds)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"提交查询出错: {e}")
                retry_seconds = max(1, int(self.loop_time))
                next_run = datetime.datetime.now() + datetime.timedelta(
                    seconds=retry_seconds
                )
                self._log_next_submission_run(next_run)
                await asyncio.sleep(retry_seconds)

    async def _poll_submission_once(self) -> None:
        """执行一次提交轮询"""
        if not self.enable_getter():
            logger.info("插件功能被阻止，跳过本轮提交信息查询")
            return

        logger.info("开始执行提交信息查询")
        bindings = await self.user_db_handler.alist_bindings(
            only_broadcast_enabled=True
        )

        handle_map = {}
        for binding in bindings:
            handle_map.setdefault(binding.cf_handle.casefold(), []).append(binding)

        for handle_bindings in handle_map.values():
            cf_handle = handle_bindings[0].cf_handle
            logger.info(f"查询 handle: {cf_handle}")
            await self._poll_handle_submissions(cf_handle, handle_bindings)

        await self._poll_luogu_submissions()

    async def _poll_luogu_submissions(self) -> None:
        """按 UID 去重轮询洛谷最新提交并播报新 AC。"""
        bindings = await self.user_db_handler.alist_luogu_bindings(
            only_broadcast_enabled=True
        )
        if not bindings:
            return
        if not self.luogu_client.cookie:
            if not self._luogu_cookie_warning_logged:
                logger.warning("未配置洛谷 Cookie，跳过洛谷 AC 自动播报")
                self._luogu_cookie_warning_logged = True
            return

        uid_map = {}
        for binding in bindings:
            uid_map.setdefault(binding.luogu_uid, []).append(binding)
        for uid, uid_bindings in uid_map.items():
            try:
                await self._wait_for_api_request_slot()
                result = await self.luogu_client.submission_info(uid, 1)
            except Exception as exc:
                logger.error(f"查询洛谷 UID {uid} 提交记录出错: {exc}")
                continue
            if not result.ok:
                logger.warning(f"查询洛谷 UID {uid} 提交记录失败: {result.message}")
                continue
            if not result.submissions:
                continue
            await self._process_luogu_submission(uid_bindings, result.submissions[0])

    async def _process_luogu_submission(self, bindings: list, submission) -> None:
        fingerprint = str(submission.id)
        is_ac = submission.status == 12
        for binding in bindings:
            if binding.last_ac_fingerprint == fingerprint:
                continue
            if binding.last_ac_fingerprint is None:
                await self.user_db_handler.aupdate_luogu_last_ac_fingerprint(
                    binding.user_id, binding.group_id,
                    fingerprint if is_ac else f"baseline:{fingerprint}",
                )
                logger.info(
                    f"为洛谷 UID {binding.luogu_uid} 在会话 {binding.group_id} 初始化提交指纹"
                )
                continue
            if not is_ac:
                continue
            try:
                await self.message_sender(
                    binding.group_id,
                    self._build_luogu_submission_message(binding, submission),
                )
            except Exception as exc:
                logger.error(
                    f"向会话 {binding.group_id} 播报洛谷 UID {binding.luogu_uid} 的新 AC 失败: {exc}"
                )
                continue
            await self.user_db_handler.aupdate_luogu_last_ac_fingerprint(
                binding.user_id, binding.group_id, fingerprint
            )
            logger.info(
                f"已经向会话 {binding.group_id} 播报洛谷 UID {binding.luogu_uid} 的新 AC"
            )

    async def _poll_handle_submissions(self, cf_handle: str, handle_bindings: list) -> None:
        """查询并处理单个 Codeforces handle 的最新提交"""
        try:
            await self._wait_for_api_request_slot()
            result = await self.user_status_handler.UserStatusRequest(cf_handle)
        except Exception as e:
            logger.error(f"查询 {cf_handle} 提交记录出错: {e}")
            return

        if not result.ok:
            logger.warning(f"查询 {cf_handle} 提交记录失败: {result.message}")
            return

        status = result.latest_status
        if status is None:
            logger.info(f"{cf_handle} 暂无提交记录")
            return

        fingerprint = self._build_submission_fingerprint(status)

        if status.verdict != "OK":
            await self._initialize_non_ac_baseline(handle_bindings, fingerprint)
            logger.info(f"{cf_handle} 最新提交不是 AC，跳过")
            return

        for binding in handle_bindings:
            if binding.last_ac_fingerprint == fingerprint:
                continue

            if binding.last_ac_fingerprint is None:
                await self.user_db_handler.aupdate_last_ac_fingerprint(
                    binding.user_id,
                    binding.group_id,
                    fingerprint,
                )
                logger.info(
                    f"为 {binding.cf_handle} 在群 {binding.group_id} 初始化 AC 指纹"
                )
                continue

            message = self._build_submission_message(binding, status)
            try:
                await self.message_sender(
                    binding.group_id,
                    message,
                )
            except Exception as e:
                logger.error(
                    f"向群聊 {binding.group_id} 播报 {binding.cf_handle} 的新 AC 失败: {e}"
                )
                continue
            await self.user_db_handler.aupdate_last_ac_fingerprint(
                binding.user_id,
                binding.group_id,
                fingerprint,
            )
            logger.info(
                f"已经向群聊 {binding.group_id} 播报 {binding.cf_handle} 的新 AC"
            )

    async def _initialize_non_ac_baseline(self, handle_bindings: list, fingerprint: str) -> None:
        """首次轮询到非 AC 提交时写入基线，避免之后第一条 AC 被误判为历史记录"""
        for binding in handle_bindings:
            if binding.last_ac_fingerprint is None:
                await self.user_db_handler.aupdate_last_ac_fingerprint(
                    binding.user_id,
                    binding.group_id,
                    f"baseline:{fingerprint}",
                )

    @staticmethod
    def _build_submission_fingerprint(status) -> str:
        """构造提交记录指纹，优先使用 Codeforces 全局唯一 submission id"""
        return str(status.id)

    @staticmethod
    def _build_submission_message(binding, status) -> str:
        """构造 AC 播报消息。"""
        problem = status.problem
        problem_id = (
            f"{problem.contestId}{problem.index}"
            if problem.contestId is not None
            else problem.index
        )

        if problem.contestId is not None:
            contest_id = str(problem.contestId)
            if len(contest_id) <= 5:
                problem_url = (
                    f"https://codeforces.com/problemset/problem/{contest_id}/{problem.index}"
                )
            else:
                problem_url = (
                    f"https://codeforces.com/gym/{contest_id}/problem/{problem.index}"
                )
        else:
            problem_url = "https://codeforces.com/problemset"
        submit_time = datetime.datetime.fromtimestamp(
            status.creationTimeSeconds
        ).strftime("%Y-%m-%d %H:%M:%S")
        rating_text = f"{problem.rating}" if problem.rating is not None else "未知"

        return "\n".join(
            [
                "检测到新的 AC 提交！",
                f"用户: {binding.cf_handle} (QQ: {binding.user_id})",
                f"题目: {problem_id}. {problem.name}",
                f"难度: {rating_text}",
                f"语言: {status.programmingLanguage}",
                f"提交时间: {submit_time}",
                f"题目链接: {problem_url}",
            ]
        )

    def _build_luogu_submission_message(self, binding, submission) -> str:
        language = self.luogu_client.LANGUAGE_NAMES.get(
            submission.language, f"语言 #{submission.language}"
        )
        submit_time = datetime.datetime.fromtimestamp(submission.submit_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return "\n".join([
            "检测到新的洛谷 AC 提交！",
            f"用户: {binding.luogu_name} (UID: {binding.luogu_uid}，平台用户: {binding.user_id})",
            f"题目: {submission.problem_id} {submission.problem_title}",
            f"得分: {submission.score if submission.score is not None else 100}",
            f"语言: {language}",
            f"提交时间: {submit_time}",
            f"题目链接: https://www.luogu.com.cn/problem/{submission.problem_id}",
            f"提交记录: https://www.luogu.com.cn/record/{submission.id}",
        ])

    @staticmethod
    def build_contest_message(result) -> str:
        """封装比赛消息格式化逻辑"""
        if not result.ok or result.contests is None:
            return result.message

        contest_messages = []

        for index, contest in enumerate(result.contests, start=1):
            if contest.start_time_seconds is None:
                start_time = "未知"
            else:
                start_time = datetime.datetime.fromtimestamp(
                    contest.start_time_seconds
                ).strftime("%Y-%m-%d %H:%M:%S")

            duration_hours = contest.duration_seconds // 3600
            duration_minutes = contest.duration_seconds % 3600 // 60
            duration = f"{duration_hours} 小时 {duration_minutes} 分钟"

            contest_messages.append(
                "\n".join(
                    [
                        f"{index}. {contest.name}",
                        f"比赛 ID: {contest.id}",
                        f"比赛类型: {contest.type}",
                        f"当前状态: {contest.phase}",
                        f"开始时间: {start_time}",
                        f"持续时间: {duration}",
                        f"比赛链接: https://codeforces.com/contest/{contest.id}",
                    ]
                )
            )

        return "\n\n".join(contest_messages)

    @staticmethod
    def _validate_time(time_str: str) -> bool:
        """验证 HH:MM 时间格式是否合法"""
        if not isinstance(time_str, str):
            return False

        if re.fullmatch(r"\d{2}:\d{2}", time_str) is None:
            return False

        hour, minute = map(int, time_str.split(":"))
        return 0 <= hour <= 23 and 0 <= minute <= 59
