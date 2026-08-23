## auto_push.py

#### 介绍

该模块负责插件中的自动化推送任务，但不直接依赖任何 AstrBot API。它只负责获取数据、维护状态、加工纯文本消息，并把待发送消息交给 `main.py` 注入的发送函数处理。

包含：

- 定时推送 Codeforces 近期比赛信息
- 定时轮询已绑定用户的最新提交记录
- 检测新的 Accepted 提交并向对应群聊播报
- 维护 `last_ac_fingerprint`，避免重复播报历史提交

模块被拆分出来后，`main.py` 负责插件主干装配、命令入口、生命周期转发，以及真正的消息发送。

#### 模块实例化

在 `main.py` 中实例化为 `self.automation_push_handler`，初始化时注入业务模块与消息发送回调：

```python
self.automation_push_handler = AutomationPushHandler(
    user_status_handler=self.user_status_handler,
    contest_info_handler=self.contest_info_handler,
    luogu_client=self.luogu_client,
    user_db_handler=self.user_db_handler,
    loop_time=self.loop_time,
    enable_getter=lambda: self.enable,
    message_sender=self._send_automation_message,
    contest_message_sender=self._send_contest_automation_message,
    contest_number=self.contest_number,
    contest_push_time=self.contest_push_time,
    contest_push_sessions=self.contest_push_sessions,
)
```

#### 生命周期接口

**启动自动化任务**

```python
async def start(self) -> None
    """启动比赛推送与提交轮询任务"""
```

**停止自动化任务**

```python
async def stop(self) -> None
    """取消后台任务，并等待任务退出"""
```

#### 比赛推送逻辑

- `contest_push_time` 为空时，不启动比赛定时推送
- `contest_push_time` 必须为 `HH:MM` 格式
- 到达指定时间后，调用 `ContestInfoRequest()` 获取比赛信息
- 通过 `build_contest_message()` 生成文本兜底消息
- 遍历 `contest_push_sessions`，优先将 `(session_id, result, fallback_message)` 交给 `contest_message_sender`
- `contest_message_sender` 由 `main.py` 注入，负责调用 AstrBot `html_render()` 渲染比赛图片；渲染失败时回退到 `message_sender`

#### 提交播报逻辑

- 每隔 `loop_time` 秒执行一轮查询
- 只读取开启播报的绑定记录
- 同一个 `cf_handle` 在多个群绑定时只请求一次 Codeforces API
- 最新提交不是 `OK` 时，只在首次轮询时写入 `baseline:<submission_id>` 作为基线
- 最新提交是 `OK` 且指纹变化时，生成纯文本播报消息并交给 `message_sender`
- 播报消息交给 `main.py` 后，再写回 `last_ac_fingerprint`
- 每次 Codeforces API 请求后等待 2.5 秒，避免触发请求频率限制
