# astrbot_plugin_for_XCPC

  <p align="center">
    <img src="https://img.shields.io/badge/License-AGPL_3.0-blue.svg" alt="License: AGPL-3.0">
    <img src="https://img.shields.io/badge/Python-3.10+-yellow.svg" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/AstrBot-v4.22.0+-orange.svg" alt="AstrBot v4.22.0+">
    <img src="https://img.shields.io/badge/Codeforces-API-red.svg" alt="Codeforces API">
  </p>


  <p align="center">
    <img src="https://count.getloli.com/@Brick0411andhisXCPCplugin?name=Brick0411andhisXCPCplugin&theme=green&padding=10&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">
  </p>

  面向 **XCPC 群聊场景** 的 AstrBot 插件，提供 Codeforces 与洛谷用户查询、群内账号绑定、近期比赛查询，以及 Codeforces 定时推送和群友 AC 播报。

  本分支基于 Bricks0411 原版修复了 QQTools `[MSG_ID:...]` 前缀导致的命令参数解析问题，并新增洛谷支持。

  整个项目大概十多个源码模块，其中有一半都是在 AI 的帮助下完成的，我说 **vibe coding** 是对的。

  ## 项目简介

  `astrbot_plugin_for_XCPC` 以 Codeforces API 为数据源，围绕算法竞赛群聊中的常见需求提供一组轻量化工具：

  - 查询 Codeforces 用户信息，并通过 AstrBot 文转图服务渲染为信息卡片
  - 查询近期 Codeforces 比赛，并生成中文比赛信息卡片
  - 将 QQ / 平台用户与 Codeforces handle 按 AstrBot 会话维度绑定
  - 周期性轮询已绑定用户的最新提交，发现新的 Accepted 后自动播报
  - 支持每日固定时间向指定会话推送近期比赛信息
  - 使用 SQLite 持久化绑定关系、播报开关与最近 AC 指纹

  插件主要面向 AstrBot 群聊环境开发，已将会话标识统一为 `event.unified_msg_origin`，可用于 AstrBot 的跨平台消息发送。

  ## 功能一览

  | 功能         | 指令 / 触发方式              | 说明                                                         |
  | :----------- | :--------------------------- | :----------------------------------------------------------- |
  | 用户信息查询 | `/cf <handle>`               | 查询 Codeforces 用户 rating、rank、贡献值、关注数、最近在线等信息，并渲染为卡片 |
  | 洛谷用户查询 | `/洛谷 <用户名或 UID>`       | 查询洛谷咕值、全站排名、社区贡献、关注和粉丝，并渲染为卡片 |
  | 比赛信息查询 | `/比赛`                      | 查询近期 Codeforces 比赛，展示名称、阶段、时间、时长与距离开赛时间 |
  | 洛谷比赛查询 | `/比赛洛谷`                  | 查询进行中及即将开始的洛谷比赛，并渲染为卡片             |
  | 洛谷提交查询 | `/提交洛谷 [UID] [数量]`     | 查询指定 UID 或当前绑定账号最近 1–10 条提交记录；需要配置洛谷 Cookie |
  | 账号绑定     | `/绑定 <handle>`             | 将当前平台用户与 Codeforces handle 绑定到当前 AstrBot 会话   |
  | 洛谷账号绑定 | `/绑定洛谷 <UID>`            | 按数字 UID 将当前平台用户与洛谷账号绑定到当前会话         |
  | 管理员代绑   | `/代绑洛谷 @成员 <UID>`      | 管理员替成员绑定洛谷 UID，也支持直接填写平台用户 ID       |
  | 解除绑定     | `/解绑`                      | 删除当前用户在当前会话下的绑定关系                           |
  | 查询绑定     | `/查询绑定`                  | 查看当前用户已绑定的 Codeforces handle                       |
  | 洛谷绑定管理 | `/查询绑定洛谷` / `/解绑洛谷` | 查看或删除当前会话内的洛谷 UID 绑定                        |
  | AC 播报开关  | `/显示记录` / `/隐藏记录`    | 控制当前用户是否参与自动 AC 播报                             |
  | 插件管理     | `/enable_cf` / `/disable_cf` | 管理员启用或停用插件功能                                     |
  | 指纹测试     | `/测试指纹`                  | 管理员查看自己的最新提交指纹，便于排查播报逻辑               |

  ## 项目结构

  ```text
  astrbot_plugin_for_XCPC/
  ├── automation/
  │   ├── __init__.py
  │   ├── auto_push.py
  │   └── README.md
  ├── contests/
  │   ├── contest_card.py
  │   ├── contest_info.py
  │   ├── models.py
  │   └── README.md
  ├── storage/
  │   ├── models.py
  │   ├── user_db.py
  │   └── README.md
  ├── user_handle/
  │   ├── models.py
  │   ├── user_card.py
  │   ├── user_info.py
  │   └── README.md
  ├── user_status/
  │   ├── models.py
  │   ├── user_status.py
  │   └── README.md
  ├── luogu/
  │   ├── client.py
  │   ├── cards.py
  │   └── models.py
  ├── _conf_schema.json
  ├── main.py
  ├── metadata.yaml
  └── README.md
  ```

  ## 项目架构

  ### 模块分工

  1. **入口层**
     - `main.py`：负责插件初始化、指令注册、消息处理、参数解析、权限校验与路由分发。
     - `metadata.yaml`：描述插件元数据。
     - `_conf_schema.json`：定义 AstrBot WebUI 配置项。

  2. **业务层**
     - `automation`：负责比赛定时推送、提交记录轮询、AC 播报与临时文件清理。
     - `contests`：负责比赛列表查询、比赛数据建模与比赛卡片渲染。
     - `user_handle`：负责 Codeforces 用户查询、用户信息建模与用户卡片渲染。
     - `user_status`：负责提交记录查询、Accepted 检测与提交指纹生成。
     - `storage`：负责 SQLite 持久化、绑定关系管理、播报开关与内存索引维护。

  3. **外部能力**
     - Codeforces API：提供用户、比赛与提交数据。
     - AstrBot `html_render()`：将 HTML / Jinja2 模板渲染为图片。
     - SQLite：保存绑定关系、播报开关与最近 AC 指纹。

  ### 运行逻辑

  群聊指令由 AstrBot 分发至插件入口，`main.py` 根据指令类型调用对应业务模块。业务模块请求 Codeforces API 或本地 SQLite 后，将结果组装为文本或 HTML 渲染数据。用户信息卡片与比赛信息卡片通过 AstrBot 文转图服务生成图片；如果渲染服务异常，则自动回退为纯文本输出。

  后台自动化任务独立运行，定时完成近期比赛推送、提交记录轮询、AC 指纹去重与临时文件清理。

  ### 架构图

  ```mermaid
  graph TD
      subgraph 上层框架 [AstrBot 宿主框架]
          A1[事件分发器]
          A2[插件管理器]
          A3[配置中心 WebUI]
          A4[文转图服务 html_render]
      end
  
      subgraph 插件入口 [astrbot_plugin_for_XCPC 主入口]
          B1[main.py 主逻辑]
          B2[metadata.yaml 插件元数据]
          B3[_conf_schema.json 配置定义]
      end
  
      subgraph 功能模块 [核心业务模块]
          C1[automation 自动化任务<br/>auto_push.py 定时推送/轮询/文件清理]
          C2[contests 比赛模块<br/>比赛查询、卡片渲染、数据模型]
          C3[user_handle 用户绑定模块<br/>CF账号查询、信息卡片、校验]
          C4[user_status 状态监控模块<br/>AC提交检测、指纹去重、播报]
          C5[storage 数据存储模块<br/>SQLite数据库、数据模型]
      end
  
      subgraph 外部依赖 [外部数据源 & 第三方能力]
          D1[Codeforces API<br/>用户/比赛/提交数据]
          D2[SQLite 本地数据库<br/>user_bindings.sqlite3]
          D3[本地临时文件<br/>图片缓存 data/temp]
      end
  
      %% 层级连线
      A1 --> B1
      A2 --> B2
      A3 --> B3
      B1 --> C1
      B1 --> C2
      B1 --> C3
      B1 --> C4
      B1 --> C5
      C1 --> D1
      C2 --> D1
      C3 --> D1
      C4 --> D1
      C5 --> D2
      C1 --> D3
      C2 --> A4
      C3 --> A4
  
      %% 样式美化
      classDef frame fill:#e1f5fe,stroke:#0288d1
      classDef entry fill:#f3e5f5,stroke:#8e24aa
      classDef module fill:#e8f5e9,stroke:#2e7d32
      classDef external fill:#fff8e1,stroke:#f57f17
  
      class A1,A2,A3,A4 frame
      class B1,B2,B3 entry
      class C1,C2,C3,C4,C5 module
      class D1,D2,D3 external
  ```

  ## 功能说明

  ### 1. 用户信息查询

  ```text
  /cf <Codeforces handle>
  ```

  别名：

  ```text
  /CF
  /cF
  /Cf
  ```

  返回内容包括：

  - Codeforces handle
  - 当前 rating / rank
  - 历史最高 rating
  - 贡献值
  - 关注数
  - 最近在线时间
  - 用户头像

  查询结果会通过 AstrBot 官方 `html_render()` 接口渲染为图片卡片。卡片主色调会根据用户 rank 自动变化，并带有 GitHub 标识水印。

  ### 2. 比赛信息查询

  ```text
  /比赛
  ```

  别名：

  ```text
  /contest
  /contests
  /cf比赛
  ```

  返回内容包括：

  - 比赛名称
  - 比赛 ID
  - 比赛类型
  - 当前阶段
  - 开始日期与时间
  - 比赛时长
  - 距离开赛时间

  比赛信息会渲染为中文图片卡片。若 AstrBot 文转图服务异常，插件会自动回退为纯文本结果。

  ### 3. 用户绑定

  ```text
  /绑定 <Codeforces handle>
  ```

  别名：

  ```text
  /绑定cf <Codeforces handle>
  ```

  绑定规则：

  - 绑定前会请求 Codeforces API 校验 handle 是否有效。
  - 同一 AstrBot 会话内，不允许多个用户绑定同一个 Codeforces handle。
  - 同一平台用户可以在不同 AstrBot 会话绑定不同 Codeforces handle。
  - 绑定关系以 `event.unified_msg_origin` 作为会话 ID 存储。

  ### 4. 解绑与查询绑定

  解绑当前用户：

  ```text
  /解绑
  ```

  查询当前用户绑定：

  ```text
  /查询绑定
  ```

  ### 5. 过题记录播报开关

  开启当前用户的 AC 播报：

  ```text
  /显示记录
  ```

  关闭当前用户的 AC 播报：

  ```text
  /隐藏记录
  ```

  开启后，自动化任务会周期性查询该用户的最新提交。如果检测到新的 Accepted 提交，会向绑定所在会话发送播报，并记录本次提交指纹，避免重复推送。

  ### 6. 管理员指令

  开启插件：

  ```text
  /enable_cf
  ```

  关闭插件：

  ```text
  /disable_cf
  ```

  查询当前管理员自己的最新提交指纹：

  ```text
  /测试指纹
  ```

  别名：

  ```text
  /fingerprint
  /test_fingerprint
  ```

  管理员指令仅允许配置项 `Admin ID` 中的用户调用。

  ## 自动化任务

  ### 比赛定时推送

  配置 `contest_push_time` 与 `contest_push_sessions` 后，插件会在每日指定时间向目标 AstrBot 会话推送近期比赛信息。

  运行规则：

  - 插件加载时记录下一次比赛推送时间。
  - 每次推送完成后更新下一次比赛推送时间。
  - 未配置推送时间或目标会话时，自动跳过比赛推送。
  - 图片渲染失败时，自动回退为纯文本比赛信息。

  ### 提交记录轮询

  插件会按照 `loop_time` 周期轮询所有已绑定且开启播报的用户。

  运行规则：

  - 插件加载时记录下一次提交查询时间。
  - 每轮查询完成后更新下一次提交查询时间。
  - 同一个 Codeforces handle 被多个会话绑定时，API 只请求一次，再分发到各会话绑定。
  - 使用提交指纹避免重复播报。
  - 新绑定用户如果最新提交不是 AC，会写入基线指纹，避免历史提交被误报。

  ### t2i 临时文件清理

  AstrBot 文转图服务下载到本地的图片会保存在 `data/temp` 中。插件会定期清理过期图片：

  - 插件启动时先清理一次。
  - 之后每 1 小时清理一次。
  - 只处理 `data/temp/io_temp_img_*`。
  - 只删除超过 24 小时的文件。
  - 不会清理刚生成、可能仍在发送流程中的图片。

  ## 配置说明

  配置文件由 AstrBot WebUI 与 `_conf_schema.json` 管理。

  ### 管理员设置

  | 配置项     | 类型           | 默认值 | 说明                                           |
  | :--------- | :------------- | :----- | :--------------------------------------------- |
  | `enable`   | `bool`         | `true` | 插件总开关，关闭后不响应功能指令               |
  | `API key`  | `list[string]` | `[]`   | 预留的 Codeforces API key 列表，留空表示不配置 |
  | `Admin ID` | `list[string]` | `[]`   | 管理员 ID 列表，仅列表内用户可调用管理员指令   |

  ### 比赛推送设置

  | 配置项                  | 类型           | 默认值 | 说明                                             |
  | :---------------------- | :------------- | :----- | :----------------------------------------------- |
  | `contest_number`        | `int`          | `5`    | 单次查询或推送展示的比赛数量                     |
  | `contest_push_time`     | `string`       | `""`   | 每日比赛推送时间，格式为 `HH:MM`，留空表示不启用 |
  | `contest_push_sessions` | `list[string]` | `[]`   | 接收比赛自动推送的 AstrBot 会话 ID 列表          |

  ### 轮询设置

  | 配置项      | 类型  | 默认值 | 说明                             |
  | :---------- | :---- | :----- | :------------------------------- |
  | `loop_time` | `int` | `600`  | 自动查询提交记录的间隔，单位为秒 |
  | `luogu_setting.cookie` | `string` | 空 | 洛谷登录 Cookie，仅用于提交记录查询，不要提交到 GitHub |
  | `luogu_setting.submission_number` | `int` | `5` | `/提交洛谷` 默认返回数量 |

  ## 图片渲染

  用户信息卡片和比赛信息卡片均通过 AstrBot 官方 `html_render()` 接口以及 AstrBot 文转图服务渲染。插件只维护：

  - HTML / Jinja2 模板
  - 渲染数据
  - 截图参数

  插件本身不直接启动浏览器进程，也不使用 PIL 绘制卡片。部署到 Linux 服务器时，插件侧无需额外管理 Playwright 浏览器运行时；只需确保 AstrBot 实例可以访问可用的文转图服务。

  如果 AstrBot 文转图服务返回 502 / 5xx 等异常响应，插件会记录错误并回退为文本信息发送。

  ## 数据存储

  绑定数据存储在 AstrBot 插件数据目录：

  ```text
  AstrBot/data/plugin_data/astrbot_plugin_for_XCPC/user_bindings.sqlite3
  ```

  数据表：

  ```sql
  CREATE TABLE IF NOT EXISTS cf_bindings (
      user_id TEXT NOT NULL,
      group_id TEXT NOT NULL,
      cf_handle TEXT NOT NULL,
      enable_broadcast INTEGER NOT NULL DEFAULT 1 CHECK (enable_broadcast IN (0, 1)),
      last_ac_fingerprint TEXT,
      updated_at INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (user_id, group_id)
  );
  ```

  索引：

  ```sql
  CREATE INDEX IF NOT EXISTS idx_bind_group
  ON cf_bindings(group_id);
  
  CREATE INDEX IF NOT EXISTS idx_bind_handle
  ON cf_bindings(cf_handle);
  
  CREATE UNIQUE INDEX IF NOT EXISTS uq_bind_group_handle
  ON cf_bindings(group_id, cf_handle COLLATE NOCASE);
  ```

  字段说明：

  - `user_id`：平台用户 ID。
  - `group_id`：AstrBot 会话 ID，实际来源为 `event.unified_msg_origin`。
  - `enable_broadcast`：控制该用户是否参与 AC 播报。
  - `last_ac_fingerprint`：记录最近一次已播报提交，避免重复推送。
  - `updated_at`：绑定信息更新时间。

  SQLite 启用 WAL 模式，运行时维护内存索引以提升查询效率。

  ## 安装方式

  将插件目录放入：

  ```text
  AstrBot/data/plugins/
  ```

  目录名建议保持为：

  ```text
  astrbot_plugin_for_XCPC
  ```

  然后在 AstrBot 中加载或重载插件。

  本插件主要依赖 AstrBot 运行环境以及 Python 标准库，Codeforces API 请求由项目内模块完成。图片渲染依赖 AstrBot 的文转图服务。

  ## 技术实现

  - AstrBot 插件 API
  - Codeforces API
  - SQLite 持久化存储
  - WAL 模式与内存索引
  - `asyncio` 后台任务
  - AstrBot `html_render()` 文转图
  - Jinja2 HTML 模板
  - 提交指纹去重

  ## 注意事项

  - Codeforces API 存在访问频率限制，提交轮询中会对 handle 查询做节流处理。
  - `contest_push_sessions` 必须填写 AstrBot 完整会话 ID，而不是纯数字群号。
  - 用户切换绑定的 Codeforces handle 后，最近 AC 指纹会重置。
  - t2i 图片清理只处理 `io_temp_img_*`，不会清理其它 AstrBot 临时文件。

  ## 版本迭代历史

  ### v0.1.0（Descartideal fork）

  - 修复 QQTools 注入 `[MSG_ID:...]` 时 `/cf`、`/绑定` 等命令参数解析失败的问题。
  - 新增 `/洛谷 <用户名或 UID>` 用户资料图片卡片。
  - 新增 `/比赛洛谷` 近期比赛图片卡片与文本降级。
  - 新增按数字 UID 的 `/绑定洛谷`、`/查询绑定洛谷` 和 `/解绑洛谷`。
  - 新增管理员 `/代绑洛谷 @成员 <UID>` 与平台用户 ID 代绑方式。
  - 洛谷公开资料不提供最近在线时间，卡片会明确显示“官网未公开”。

  ### v0.0.2

  - 修复 AC 播报中 Gym 题目链接错误的问题，支持根据 `contestId` 位数生成 `/problemset/problem/` 或 `/gym/` 链接。
  - 修复 `contestId` 为整数时直接调用 `len()` 导致自动播报异常的问题。
  - 保持比赛查询与比赛定时推送逻辑不变，继续只展示 Codeforces API 返回的普通 contest 数据。

  ### v0.0.1

  - 初始版本，支持 Codeforces 用户信息查询、比赛查询、账号绑定、AC 播报、比赛定时推送与图片卡片渲染。

  ## License

  本项目基于 GNU Affero General Public License v3.0 发布。

  你可以在遵守 AGPL-3.0 协议的前提下使用、修改和分发本项目。

  ## 贡献

  欢迎通过以下方式参与改进：

  - 提交 Issue 报告问题
  - 提交 Pull Request 改进功能
  - 提出更适合 XCPC / Codeforces 群聊场景的建议
