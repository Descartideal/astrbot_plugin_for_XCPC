"""AstrBot 插件入口，负责命令注册、参数校验和消息发送。"""
import asyncio
from pathlib import Path
import re
import sqlite3
import time

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.api.message_components import At, Plain, BaseMessageComponent
from astrbot.core.utils.astrbot_path import get_astrbot_data_path, get_astrbot_temp_path

from .user_handle.user_info import UserInfoHandler
from .user_handle.user_card import UserProfileCardRenderer
from .user_status.user_status import UserStatusHandler
from .contests.contest_info import ContestInfoHandler
from .contests.contest_card import ContestCardRenderer
from .storage.user_db import DataStorageHandler
from .automation import AutomationPushHandler
from .luogu import LuoguClient, LuoguContestCardRenderer, LuoguUserCardRenderer


PLUGIN_NAME = "astrbot_plugin_for_XCPC"
T2I_TEMP_FILE_PATTERN = "io_temp_img_*"
T2I_TEMP_FILE_TTL_SECONDS = 24 * 60 * 60
T2I_CLEANUP_INTERVAL_SECONDS = 60 * 60


@register(
    PLUGIN_NAME,
    "Bricks0411",
    "基于 Astrbot 框架的简单插件，为算法竞赛选手提供各种功能",
    "0.1.0",
)
class PluginForXCPC(Star):
    """XCPC 辅助插件主类，负责 AstrBot 生命周期和命令注册。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.loop_time = config["loop_time"]
        
        self.admin_id = config["admin_setting"]["Admin ID"]
        self.api_key = config["admin_setting"]["API key"]
        self.enable = config["admin_setting"]["enable"]

        self.contest_number = config["contest_setting"]["contest_number"]
        self.contest_push_time = config["contest_setting"]["contest_push_time"]
        self.contest_push_sessions = config["contest_setting"]["contest_push_sessions"]
        self._t2i_cleanup_task: asyncio.Task | None = None

        self.user_info_handler = UserInfoHandler()
        self.user_card_renderer = UserProfileCardRenderer()
        self.user_status_handler = UserStatusHandler()
        self.contest_info_handler = ContestInfoHandler()
        self.contest_card_renderer = ContestCardRenderer()
        self.luogu_client = LuoguClient()
        self.luogu_user_card_renderer = LuoguUserCardRenderer()
        self.luogu_contest_card_renderer = LuoguContestCardRenderer()
        self.user_db_handler = DataStorageHandler(db_path=self._build_user_db_path())
        self.automation_push_handler = AutomationPushHandler(
            user_status_handler=self.user_status_handler,
            contest_info_handler=self.contest_info_handler,
            user_db_handler=self.user_db_handler,
            loop_time=self.loop_time,
            enable_getter=lambda: self.enable,
            message_sender=self._send_automation_message,
            contest_message_sender=self._send_contest_automation_message,
            contest_number=self.contest_number,
            contest_push_time=self.contest_push_time,
            contest_push_sessions=self.contest_push_sessions,
        )

    def _build_user_db_path(self) -> Path:
        """构造插件专用 SQLite 数据库路径。"""
        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        return plugin_data_dir / "user_bindings.sqlite3"

    def _get_event_session_id(self, event: AstrMessageEvent) -> str:
        """从 AstrBot 事件中提取统一会话 ID。"""
        session_id = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not session_id:
            raise ValueError("无法获取当前会话 ID")
        return session_id

    @staticmethod
    def _is_rendered_image_file(file_path: str | Path) -> bool:
        """用文件头判断 html_render 返回值是否是真实图片文件。"""
        try:
            with Path(file_path).open("rb") as image_file:
                header = image_file.read(12)
        except OSError:
            return False

        return (
            header.startswith(b"\x89PNG\r\n\x1a\n")
            or header.startswith(b"\xff\xd8\xff")
            or header.startswith(b"GIF87a")
            or header.startswith(b"GIF89a")
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        )

    async def initialize(self):
        """启动后台任务。"""
        await self._cleanup_t2i_temp_files()
        self._t2i_cleanup_task = asyncio.create_task(self._t2i_cleanup_loop())
        await self.automation_push_handler.start()

    async def _t2i_cleanup_loop(self) -> None:
        """周期性清理 AstrBot 文转图临时文件。"""
        while True:
            try:
                await asyncio.sleep(T2I_CLEANUP_INTERVAL_SECONDS)
                await self._cleanup_t2i_temp_files()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"定时清理 t2i 临时文件失败: {e}")

    async def _cleanup_t2i_temp_files(self) -> None:
        """删除超过 TTL 的 t2i 临时图片。"""
        temp_dir = Path(get_astrbot_temp_path()).resolve()
        if not temp_dir.exists():
            return

        now = time.time()
        deleted_count = 0
        deleted_size = 0
        expired_before = now - T2I_TEMP_FILE_TTL_SECONDS

        for file_path in temp_dir.glob(T2I_TEMP_FILE_PATTERN):
            try:
                resolved_path = file_path.resolve()
                # 只删除 temp_dir 直属文件，避免通配符或符号链接误伤其它路径。
                if resolved_path.parent != temp_dir or not resolved_path.is_file():
                    continue

                stat = resolved_path.stat()
                if stat.st_mtime > expired_before:
                    continue

                deleted_size += stat.st_size
                resolved_path.unlink()
                deleted_count += 1
            except OSError as e:
                logger.warning(f"清理 t2i 临时文件失败: {file_path}, {e}")

        if deleted_count:
            logger.info(f"已清理 {deleted_count} 个 t2i 临时文件，释放 {deleted_size} 字节")

    async def _send_automation_message(self, session_id: str, message: str) -> None:
        """发送自动化模块生成的纯文本消息。"""
        logger.info("执行自动信息回调")
        await self.context.send_message(session_id, MessageChain().message(message))

    async def _render_contest_card_image(self, result) -> Path:
        """渲染比赛卡片，并校验 AstrBot 返回的是图片文件。"""
        template, data, options = self.contest_card_renderer.build(result)
        card_path = await self.html_render(template, data, return_url=False, options=options)
        if not self._is_rendered_image_file(card_path):
            raise ValueError(
                f"AstrBot HTML 渲染返回的文件不是图片: {card_path}，"
                "请检查 AstrBot 文转图服务状态"
            )
        return Path(card_path)

    async def _send_contest_automation_message(
        self,
        session_id: str,
        result,
        fallback_message: str,
    ) -> None:
        """比赛信息卡片发送逻辑"""
        try:
            card_path = await self._render_contest_card_image(result)
            await self.context.send_message(
                session_id,
                MessageChain().file_image(str(card_path)),
            )
        except Exception as e:
            logger.error(f"渲染比赛信息卡片失败，回退为文本推送: {e}")
            await self._send_automation_message(session_id, fallback_message)

    def GetArgs(self, messages: list[BaseMessageComponent]):
        """解析纯文本参数，并过滤 QQTools 注入的消息 ID 前缀。"""
        args = []
        for msg in messages:
            if isinstance(msg, At):
                continue
            if isinstance(msg, Plain):
                text = re.sub(
                    r"\[MSG_ID:[^\]]+\]\s*",
                    "",
                    msg.text,
                    flags=re.IGNORECASE,
                ).strip()
                if text:
                    args.extend(text.split())
        return args

    def GetCommandArgs(
        self,
        messages: list[BaseMessageComponent],
        command_names: set[str],
    ) -> list[str]:
        """兼容消息链保留或移除命令词的不同 AstrBot/适配器行为。"""
        args = self.GetArgs(messages)
        normalized_commands = {name.lstrip("/").casefold() for name in command_names}
        if args and args[0].lstrip("/").casefold() in normalized_commands:
            return args[1:]
        return args

    @staticmethod
    def _get_at_user_ids(messages: list[BaseMessageComponent]) -> list[str]:
        """获取消息中被 @ 的平台用户 ID，排除 @全体成员。"""
        user_ids = []
        for message in messages:
            if not isinstance(message, At):
                continue
            user_id = str(getattr(message, "qq", "") or "").strip()
            if user_id and user_id.casefold() != "all":
                user_ids.append(user_id)
        return user_ids

    async def _render_luogu_user_card(self, profile) -> Path:
        template, data, options = self.luogu_user_card_renderer.build(profile)
        card_path = await self.html_render(template, data, return_url=False, options=options)
        if not self._is_rendered_image_file(card_path):
            raise ValueError(f"AstrBot HTML 渲染返回的文件不是图片: {card_path}")
        return Path(card_path)

    async def _render_luogu_contest_card(self, result) -> Path:
        template, data, options = self.luogu_contest_card_renderer.build(result)
        card_path = await self.html_render(template, data, return_url=False, options=options)
        if not self._is_rendered_image_file(card_path):
            raise ValueError(f"AstrBot HTML 渲染返回的文件不是图片: {card_path}")
        return Path(card_path)
    
    @filter.command("cf", alias={"CF", "cF", "Cf"})
    async def GetCodeforcesUserInfo(self, event: AstrMessageEvent):
        """查询指定 Codeforces 用户信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /cf 指令")
            return

        messages = event.get_messages()
        args = self.GetCommandArgs(messages, {"cf", "CF", "cF", "Cf"})

        if len(args) != 1:
            logger.warning(f"参数数量不合法，期望 1，接收到 {len(args)}")
            yield event.plain_result("用法: /cf <Codeforces handle>")
            return

        user_handle = args[0]
        logger.info(f"从消息链中解析出 codeforces handle: {user_handle}")

        result = await self.user_info_handler.UserInfoRequest(user_handle)
        if not result.ok or result.profile is None:
            logger.warning(result.message)
            yield event.plain_result(result.message)
            return

        try:
            template, data, options = self.user_card_renderer.build(result.profile)
            card_path = await self.html_render(template, data, return_url=False, options=options)
            if not self._is_rendered_image_file(card_path):
                raise ValueError(
                    f"AstrBot HTML 渲染返回的文件不是图片: {card_path}，"
                    "请检查 AstrBot 文转图服务状态"
                )
            logger.info(f"已渲染 Codeforces 用户信息卡片: {card_path}")
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"渲染 Codeforces 用户信息卡片失败: {e}")
            yield event.plain_result(result.message)


    @filter.command("比赛", alias={"contest", "contests", "cf比赛"})
    async def GetCodeForcesContestInfo(self, event: AstrMessageEvent):
        """查询 Codeforces 比赛信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /比赛 指令")
            return
        
        logger.info(f"向 Codeforces.com 请求最近 {self.contest_number} 场的比赛数据")
        result = await self.contest_info_handler.ContestInfoRequest(self.contest_number)
        logger.info(result.message)

        message_chain = self.automation_push_handler.build_contest_message(result)

        if not result.ok or result.contests is None:
            yield event.plain_result(result.message)
            return

        try:
            card_path = await self._render_contest_card_image(result)
            logger.info(f"已渲染 Codeforces 比赛信息卡片: {card_path}")
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"渲染 Codeforces 比赛信息卡片失败: {e}")
            yield event.plain_result(message_chain)

    @filter.command("洛谷", alias={"luogu", "lg"})
    async def GetLuoguUserInfo(self, event: AstrMessageEvent):
        """查询洛谷用户公开资料并渲染卡片。"""
        if self.enable is False:
            return
        args = self.GetCommandArgs(event.get_messages(), {"洛谷", "luogu", "lg"})
        if len(args) != 1:
            yield event.plain_result("用法：/洛谷 <用户名或 UID>")
            return

        result = await self.luogu_client.user_info(args[0])
        if not result.ok or result.profile is None:
            yield event.plain_result(result.message)
            return
        try:
            card_path = await self._render_luogu_user_card(result.profile)
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"渲染洛谷用户信息卡片失败，回退为文本: {e}")
            yield event.plain_result(result.message)

    @filter.command("比赛洛谷", alias={"洛谷比赛", "luogu_contest"})
    async def GetLuoguContestInfo(self, event: AstrMessageEvent):
        """查询进行中及即将开始的洛谷比赛。"""
        if self.enable is False:
            return
        result = await self.luogu_client.contest_info(self.contest_number)
        fallback = self.luogu_client.format_contests(result)
        if not result.ok or not result.contests:
            yield event.plain_result(result.message)
            return
        try:
            card_path = await self._render_luogu_contest_card(result)
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"渲染洛谷比赛卡片失败，回退为文本: {e}")
            yield event.plain_result(fallback)

    async def _bind_luogu_account(
        self,
        *,
        target_user_id: str,
        group_id: str,
        uid_text: str,
    ) -> str:
        """校验洛谷 UID，并为指定平台成员建立会话内绑定。"""
        if not uid_text.isdigit() or int(uid_text) <= 0:
            return "洛谷 UID 必须是正整数"
        uid = int(uid_text)
        result = await self.luogu_client.user_info(str(uid))
        if not result.ok or result.profile is None:
            return f"绑定失败：{result.message}"

        existing = await self.user_db_handler.aget_group_luogu_binding_by_uid(group_id, uid)
        if existing is not None and existing.user_id != str(target_user_id):
            return "该洛谷 UID 已被本会话其他成员绑定"
        try:
            binding = await self.user_db_handler.abind_luogu_user(
                target_user_id,
                group_id,
                uid,
                result.profile.name,
            )
        except sqlite3.IntegrityError:
            return "该洛谷 UID 已被本会话其他成员绑定"
        return (
            f"洛谷绑定成功！平台用户: {binding.user_id}，"
            f"洛谷用户: {binding.luogu_name}（UID {binding.luogu_uid}）"
        )

    @filter.command("绑定洛谷")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def BindLuoguUser(self, event: AstrMessageEvent):
        """当前成员按洛谷数字 UID 绑定账号。"""
        if self.enable is False:
            return
        args = self.GetCommandArgs(event.get_messages(), {"绑定洛谷"})
        if len(args) != 1:
            yield event.plain_result("用法：/绑定洛谷 <洛谷 UID>")
            return
        message = await self._bind_luogu_account(
            target_user_id=str(event.get_sender_id()),
            group_id=self._get_event_session_id(event),
            uid_text=args[0],
        )
        yield event.plain_result(message)

    @filter.command("代绑洛谷", alias={"管理员绑定洛谷"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def AdminBindLuoguUser(self, event: AstrMessageEvent):
        """管理员通过 @成员 或平台用户 ID 代绑洛谷 UID。"""
        sender_id = str(event.get_sender_id())
        if sender_id not in {str(item) for item in self.admin_id}:
            yield event.plain_result("仅插件管理员可以使用 /代绑洛谷")
            return
        if self.enable is False:
            return

        messages = event.get_messages()
        args = self.GetCommandArgs(messages, {"代绑洛谷", "管理员绑定洛谷"})
        at_user_ids = self._get_at_user_ids(messages)
        if at_user_ids and len(args) == 1:
            target_user_id, uid_text = at_user_ids[0], args[0]
        elif not at_user_ids and len(args) == 2:
            target_user_id, uid_text = args[0], args[1]
        else:
            yield event.plain_result(
                "用法：/代绑洛谷 @成员 <洛谷 UID>\n"
                "或：/代绑洛谷 <平台用户 ID> <洛谷 UID>"
            )
            return

        message = await self._bind_luogu_account(
            target_user_id=target_user_id,
            group_id=self._get_event_session_id(event),
            uid_text=uid_text,
        )
        yield event.plain_result(message)

    @filter.command("查询绑定洛谷")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def CheckLuoguBinding(self, event: AstrMessageEvent):
        if self.enable is False:
            return
        binding = await self.user_db_handler.aget_luogu_binding(
            event.get_sender_id(),
            self._get_event_session_id(event),
        )
        if binding is None:
            yield event.plain_result("您还没有绑定洛谷账号")
            return
        yield event.plain_result(
            f"当前绑定：{binding.luogu_name}（洛谷 UID {binding.luogu_uid}）"
        )

    @filter.command("解绑洛谷")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def UnbindLuoguUser(self, event: AstrMessageEvent):
        if self.enable is False:
            return
        removed = await self.user_db_handler.aunbind_luogu_user(
            event.get_sender_id(),
            self._get_event_session_id(event),
        )
        yield event.plain_result("洛谷解绑成功" if removed else "没有洛谷绑定记录")


    @filter.command("绑定", alias={"绑定cf"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def BindUserCodeForcesSubmitInfo(self, event: AstrMessageEvent):
        """用户绑定 Codeforces 用户信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /绑定 指令")
            return

        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)
        messages = event.get_messages()
        args = self.GetCommandArgs(messages, {"绑定", "绑定cf"})
        
        if len(args) != 1:
            logger.warning(f"参数数量不合法，期望 1，接收到 {len(args)}")
            yield event.plain_result("用法：/绑定 <Codeforces handle>")
            return

        cf_handle = args[0]
        logger.info(f"用户 {user_id} 尝试在群聊 {group_id} 绑定 cf 用户 {cf_handle}")

        handle_result = await self.user_info_handler.UserInfoRequest(cf_handle)
        if handle_result.ok is False:
            logger.warning(f"请求出错！原因：{handle_result.message}")
            yield event.plain_result(f"请求出错！原因：{handle_result.message}")
            return
        
        existing = await self.user_db_handler.aget_group_binding_by_handle(group_id, cf_handle)
        if existing is not None and existing.user_id != str(user_id):
            logger.info(f"检测到 {existing.cf_handle} 已经被 {existing.user_id} 绑定")
            yield event.plain_result("该 Codeforces 用户已被本群其他用户绑定")
            return

        try:
            # 数据库唯一约束是最后一道防线，避免并发绑定同一 handle。
            await self.user_db_handler.abind_user(user_id, group_id, cf_handle, None)
        except sqlite3.IntegrityError:
            logger.info(f"检测到 {cf_handle} 已经被 {user_id} 绑定")
            yield event.plain_result("该 Codeforces 用户已被本群其他用户绑定")
            return

        logger.info(f"用户 {user_id} 绑定 cf handle {cf_handle} 成功！")
        yield event.plain_result(f"绑定成功！(user_id: {user_id}, cf_handle: {cf_handle})")

    
    @filter.command("解绑")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def UnBindUserCodeForcesSubmitInfo(self, event: AstrMessageEvent):
        """解绑逻辑"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /解绑 指令")
            return
        
        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)

        result = await self.user_db_handler.aunbind_user(user_id, group_id)
        if not result:
            yield event.plain_result("没有绑定记录")
            return

        logger.info(f"用户 {user_id} 解绑成功")
        yield event.plain_result(f"解绑成功！(user_id: {user_id})")


    @filter.command("查询绑定")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def CheckUserBindInformation(self, event: AstrMessageEvent):
        """查询绑定信息，仅支持查询发送者自身信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /查询绑定 指令")
            return
        
        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)
        
        result = await self.user_db_handler.aget_binding(user_id, group_id)

        if result is None:
            logger.info(f"用户 {user_id} 未在群 {group_id} 中绑定任何信息")
            yield event.plain_result(f"您还暂未绑定用户！(user_id: {user_id})")
            return
        
        logger.info(f"用户 {user_id} 在群 {group_id} 中绑定的 cf 用户为 {result.cf_handle}")
        yield event.plain_result(f"您当前绑定的用户为 {result.cf_handle} (user_id: {user_id})")

    
    @filter.command("显示记录")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def EnableUserBroadCast(self, event: AstrMessageEvent):
        """修改过题记录可见性为 true"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /显示记录 指令")
            return
        
        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)

        result = await self.user_db_handler.aset_broadcast_enabled(user_id, group_id, True)

        if result is None:
            logger.info(f"用户 {user_id} 不在群 {group_id} 的绑定记录中，无法开启过题记录播报")
            yield event.plain_result("您还暂未绑定用户，请先使用 /绑定 <Codeforces handle>")
            return
        
        logger.info(f"用户 {user_id} 在群 {group_id} 中开启过题记录播报成功")
        yield event.plain_result("已开启过题记录播报")

    
    @filter.command("隐藏记录")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def DisableUserBroadCast(self, event: AstrMessageEvent):
        """修改过题记录可见性为 False"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /隐藏记录 指令")
            return
        
        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)

        result = await self.user_db_handler.aset_broadcast_enabled(user_id, group_id, False)

        if result is None:
            logger.info(f"用户 {user_id} 不在群 {group_id} 的绑定记录中，无法关闭过题记录播报")
            yield event.plain_result("您还暂未绑定用户，请先使用 /绑定 <Codeforces handle>")
            return
        
        logger.info(f"用户 {user_id} 在群 {group_id} 中关闭过题记录播报成功")
        yield event.plain_result("已关闭过题记录播报")

    @filter.command("enable_cf")
    async def EnablePlugin(self, event: AstrMessageEvent):
        """启用插件功能，仅配置的管理员 ID 可调用"""
        user_id = event.get_sender_id()
        logger.info(f"用户 {user_id} 尝试启用插件总开关")
        if user_id not in self.admin_id:
            logger.warning(f"用户 {user_id} 无权执行该操作，退出")
            return
        if self.enable is True:
            yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已经开启！无需重复操作")
            logger.info("检测到重复操作")
            return
        self.enable = True
        yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已开启！bot 将重新开始响应指令")
        logger.info("插件总开关已经开启")

    @filter.command("disable_cf")
    async def DisablePlugin(self, event: AstrMessageEvent):
        """关闭插件功能，仅配置的管理员 ID 可调用"""
        user_id = event.get_sender_id()
        logger.info(f"用户 {user_id} 尝试关闭插件总开关")
        if user_id not in self.admin_id:
            logger.warning(f"用户 {user_id} 无权执行该操作，退出")
            return
        if self.enable is False:
            yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已经关闭！无需重复操作")
            logger.info("检测到重复操作")
            return
        self.enable = False
        yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已关闭！之后不会响应任何指令，直到开关被重新开启")
        logger.info("插件总开关已经关闭")

    async def terminate(self):
        """停止后台任务并关闭数据库连接。"""
        if self._t2i_cleanup_task:
            # 先停清理任务，再停自动推送和数据库连接，避免后台任务继续访问已关闭资源。
            self._t2i_cleanup_task.cancel()
            try:
                await self._t2i_cleanup_task
            except asyncio.CancelledError:
                pass
        await self.automation_push_handler.stop()
        await self.user_db_handler.aclose()
        

    @filter.command("测试指纹", alias={"fingerprint", "test_fingerprint"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def CheckCurrentUserSubmissionFingerprint(self, event: AstrMessageEvent):
        """测试命令：查询当前用户最新提交记录的指纹"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /测试指纹 指令")
            return
        
        user_id = event.get_sender_id()
        if user_id not in self.admin_id:
            logger.warning(f"用户 {user_id} 无权执行该操作，退出")
            return

        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)

        binding = await self.user_db_handler.aget_binding(user_id, group_id)
        if binding is None:
            logger.info(f"用户 {user_id} 未在群 {group_id} 中绑定任何信息，无法查询提交指纹")
            yield event.plain_result("您还暂未绑定用户，请先使用 /绑定 <Codeforces handle>")
            return

        result = await self.user_status_handler.UserStatusRequest(binding.cf_handle)
        if not result.ok:
            logger.warning(f"查询 {binding.cf_handle} 提交指纹失败: {result.message}")
            yield event.plain_result(f"查询提交指纹失败：{result.message}")
            return

        status = result.latest_status
        if status is None:
            logger.info(f"{binding.cf_handle} 暂无提交记录，无法生成提交指纹")
            yield event.plain_result(f"{binding.cf_handle} 暂无提交记录，无法生成提交指纹")
            return

        fingerprint = self.automation_push_handler._build_submission_fingerprint(status)
        logger.info(
            f"用户 {user_id} 在群 {group_id} 查询 {binding.cf_handle} 最新提交指纹: {fingerprint}"
        )

        problem = status.problem
        problem_id = (
            f"{problem.contestId}{problem.index}"
            if problem.contestId is not None
            else problem.index
        )
        verdict_text = status.verdict or "未知"

        yield event.plain_result(
            "\n".join(
                [
                    "当前用户最新提交指纹：",
                    f"Codeforces 用户: {binding.cf_handle}",
                    f"提交指纹: {fingerprint}",
                    f"已记录指纹: {binding.last_ac_fingerprint or '无'}",
                    f"提交 ID: {status.id}",
                    f"题目: {problem_id}. {problem.name}",
                    f"判题结果: {verdict_text}",
                ]
            )
        )
