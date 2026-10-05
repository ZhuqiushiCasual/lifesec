# CLAUDE.md

本文件为 AI 编码助手在本仓库工作提供指引。

## 项目概述

**selfsec** —— 单用户的个人秘书（个人项目，非产品）。

核心是**一个对话接口**：用户说的话被记住、并得到回应；外部的重要消息主动找上门。
它不是"记录工具"，而是"有回应的东西"——每次输入都必须换来一句话。

- 架构极简：FastAPI 同时提供 API 与前端静态页，无独立前端工程、无构建步骤
- 记忆的最小单位是**事件**而不是消息：同一天的重复 / 补充会被合并成一条事件，并贴上 AI 每次生成的标签
- `backend/app/`：FastAPI (async) + SQLAlchemy 2.0
  - 默认 **SQLite**（零配置开箱即跑）；生产用 MySQL（`asyncmy`）
- `backend/static/`：前端（原生 HTML + CSS + JS，**只有一个聊天窗口**，无框架无构建）
- 设计文档：`docs/PRD-v2.md`（产品规格）、`docs/架构-v1.html` / `.drawio`（架构图）

## 常用命令

```bash
cd backend

# 依赖（Windows 用 conda 环境 life-secretary，Python 3.11）
# 直连 pypi.org 在本机会被重置，装包一律带镜像源（和 Dockerfile 里是同一个源）
pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt

# 配置：复制 .env.example 为 .env
#   不设 DATABASE_URL 就走 SQLite（./selfsec.db），无需装数据库
#   生产：DATABASE_URL=mysql+asyncmy://user:pass@host:3306/selfsec?charset=utf8mb4

python startup.py                              # 启动（等 DB → 建表 → uvicorn）
python smoke_test.py                           # 端到端冒烟测试（用 SQLite，不碰生产库）
python migrate_v2.py                           # 一次性迁移：v1 结构 → v2（幂等，可重复跑）
python -m uvicorn app.main:app --port 8123     # 直接起服务

# 远程部署（api + mysql）：容器内构建默认走阿里云 pip 源
# （backend/Dockerfile 的 ARG PIP_INDEX_URL 可覆盖，compose 的 build.args 也走这里）
docker compose up -d --build
```

表结构与锚点用户由 `app/main.py` 的 lifespan 自动创建，**没有种子 SQL、没有迁移工具**。

## 架构要点

一条主线，五个概念：

```
① 输入    ② 对话接口            ③ Context 组装        ④ 记忆层            ⑤/⑥ 数据与输出
聊天窗口 → POST /api/chat  → System Prompt (长且稳定)  4.1 长期画像         对话 messages
定时触发   意图路由 + 编排       Memory Block (动态)    4.2 事实与统计       事件 events
Hermes     一次 LLM 调用         当前 User Message     4.3 洞察记忆         plans / memory_profile
                                4.4 会话短期                              → 一句话回应 + 卡片
```

- **`services/agent.py` 是编排核心**：
  `意图路由 → 组装 Context（含今天的事件候选）→ 生成回应 + 归档决定 → 落窗口 → 合并/新建事件 → 落待办 → 落回应`
- **全程只有一次 LLM 调用**（`services/ai/reply.py`），意图判定、字段抽取、**标签生成**、以及
  **「并入今天哪条事件」**都在这一次里完成——它们本来就是同一个理解的不同侧面。
  `route()` 只做本地能确定的事（判断是否在表达情绪），不做第二次调用
- **事件合并**（`services/records.py`）：今天已有的事件作为候选进 Context，模型返回 `merge_event_id`；
  命中就**整体替换**那条事件（`content` / `entities` / `tags` 都给合并后的完整版本，`last_at` 往后推、
  `merged_count += 1`），否则新建。**id 必须在候选集合里**，否则按新建处理——
  多一条冗余事件，好过让幻觉改写历史
- **标签**：`events.tags` 由模型每次生成（自由命名）。prompt 里给的只是命名风格参考、不是可选清单；
  刻意**不做标签字典表**，避免"固定枚举 + 挑选"那套
- **记忆层四层**（`services/memory/`），按"变化频率 / 成本"划分：
  - `profile.py` 4.1 长期画像——「总结意识」，定期/阈值/手动把全部事件压成一段话（对应 Hermes 的 user.md）
  - `stats.py` 4.2 事实与统计——纯 SQL 聚合/对比，**不过 LLM**，提供"比较档"回应的原料
  - `insights.py` 4.3 洞察记忆——外部驱动，读 `events(source=hermes)`
  - `session.py` 4.4 会话短期——最近 N 轮，用于指代消解
- **内置调度**（`services/scheduler.py`）：一个 asyncio 循环，早晚各一次问候 + 夜间重算画像。
  刻意不引 APScheduler
- **前端零依赖零构建**：`static/app.js` 渲染"我说的 + 它说的"合一的消息流，卡片是唯一的结构化输出形式
  （卡片上带 AI 生成的标签 chips；并入已有事件时卡片会标出"第 N 次补充"）

## API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/chat` | **唯一入口**。意图路由 + 抽取 + 标签 + 回应（含归档决定），返回 `{reply, card, message_id, event_id, merged}` |
| GET | `/api/messages?limit=` | 窗口流（单表 `messages`：`role=me` 我说的 + `role=secretary` 它说的） |
| GET | `/api/messages?filter=record` | 回溯里的「事件」线：合并后的事件，带 `tags` / `merged_count` / `occurred_on` |
| GET | `/api/messages?filter=insight` | 回溯里的「洞察」线（`messages.kind=insight`） |
| POST | `/api/insights` | **Hermes 回调入口**。落 `events(source=hermes)` + 生成洞察消息，按 `source_url` 幂等 |
| GET | `/api/plans` | 待办列表（默认只返回 open） |
| PATCH | `/api/plans/{id}` | 勾选待办（`{"status": "open\|done"}`） |
| GET | `/api/memory` | 查看长期画像 |
| POST | `/api/memory/refresh` | 手动强制重算画像 |
| GET | `/health` | 健康检查（无鉴权） |
| GET | `/` | 前端静态页 |

所有 `/api/*` 在 `API_TOKEN` 非空时需请求头 `X-API-Token`；为空则不校验（本地开发）。

## 数据模型（4 张表 + 用户锚点）

```
users           单用户，仅作外键锚点，启动时自动创建
messages        窗口里的全部消息  ← role=me(我说的原话，永不改写) / secretary(它说的)
                kind: user | reply | greeting | insight | nudge
                card(JSON) 直接存卡片；ref_event_id 指向这条消息归入/所回应的事件
                **窗口渲染只读这张表**，时间点就是 created_at
events          合并后的事件  ← source=user(同一天合并的结果) / hermes(洞察，不合并)
                type: record | plan | finance | insight | feeling
                content 是"事件当前的完整表述"（合并时整体替换）；entities(JSON) 结构化字段
                tags(JSON) AI 每次生成的标签；occurred_on 归属日期（同一天才合并）
                recorded_at 第一次记到它 / last_at 最近一次补充 / merged_count 合并了几条消息
                dedup_key 供 Hermes 幂等
plans           待办 / 目标，从对话里长出来，可勾选
memory_profile  长期画像，单用户单行，version 递增
```

一次 `/api/chat` 的落库顺序：`messages(role=me, 原话)` → `events(合并或新建)` → 可选 `plans` → `messages(role=secretary, 回应)`。

**时间戳统一用 `app/database.py` 的 `DateTimeMicro`（`DateTime` + MySQL 侧的 `DATETIME(6)`），
默认值用 Python 侧 `default=now_local`，不是 `func.now()`。**
MySQL 的 `DATETIME` 默认精度只到「秒」，同一秒内落库的多条记录时间戳完全相同，`ORDER BY` 定不出先后
（表现为「它的回应显示在我发送的消息上面」）；`DateTimeMicro` 让 MySQL 侧建出 `DATETIME(6)`，
其它方言保持普通 `DateTime`（SQLite 本来就存到微秒）。**老库要手动跑 `docs/alter-datetime6.sql`**，
`create_all` 只建缺失的表、不会 ALTER 已有表。

## 与 Hermes 的边界

- 抓取 / 筛选 / 去重由 **Hermes** 负责（定时任务 + anysearch）
- selfsec **不自建抓取管线**，只接收一个标准回调 `POST /api/insights`
- Hermes 侧的 prompt 与接口约定见 `docs/hermes-新闻任务.md`

## 约定

- 注释与文档以中文为主，标识符用英文
- 分层：`api/`（路由）→ `services/`（业务）→ `models/` + `schemas/`
- **AI 调用只放在 `services/ai/`**（`client.py` 统一出口，失败抛 `AIUnavailable`，调用方必须降级）
- 任何 LLM 失败都不能让用户看到报错——回应生成有本地兜底（"记下了。"）
- 前端保持零依赖零构建：不引入框架/打包器；卡片样式统一在 `styles.css`
- 窗口流（`api/messages.py`）现在是**单表**查询 `messages`（以前是 events + messages 跨表归并）。
  排序键 `(created_at, 轮次, id)`：**同一时刻「我说的」必须排在「它说的」之前**——
  不能只按时间排，库的时间精度不保证（见下面时间戳那段）
- **合并判定必须复用唯一那次 LLM 调用**，不要为它加第二次调用；
  也**必须校验**模型返回的 `merge_event_id`（要在候选集合里），校验不过就按新建处理
- 标签永远由模型重新生成，不在代码里维护标签枚举 / 标签字典表
- 前端 `api()` 里 401 的处理必须**并发安全**：`loadAll` 一次发两个请求，两个都可能拿到 401，
  只允许弹一次 Token 输入框（并发请求共用一个输入过程 + 用当前 token 静默重试）
- 响应错误保持 `{"detail": "..."}` 风格

## 已知限制 / 注意点

1. **改表结构需重建库**：无 Alembic，`create_all` 只建缺失的表、不会 ALTER 已有表。
   从旧版升级（旧库有 `finance_txns` / `insights` / `digests`）**必须换新库**；
   - v1 → v2（`messages.role` + 事件的 `tags` / `occurred_on` / `last_at` / `merged_count`）：
     跑 `python migrate_v2.py`（幂等，SQLite / MySQL 都能跑；**在容器里跑**见 `docs/部署.md` 第十二节）
   - 时间戳精度升级（`DATETIME` → `DATETIME(6)`）要跑 `docs/alter-datetime6.sql`
2. **`backend/.env` 里现在指向的是旧的远程库**，且是旧表结构 —— 用之前先确认/更换 `DATABASE_URL`
3. **无测试框架**，只有 `smoke_test.py`（48 项断言，端到端，离线可跑）；
   迁移脚本的用例在仓库外的 scratch 里（未入库）
4. **secrets 曾入库**：旧版 `config.py` 硬编码过 DB 密码与 DeepSeek key（仍在 git 历史），建议轮换
5. **抚慰（P2）尚未实现**：`route()` 已识别情绪词并给模型提示，但没有独立的抚慰议程
6. **PWA 已移除**：`sw.js` / `manifest` / icons 已删，浏览器麦克风仍需 HTTPS
7. **合并的判定质量取决于模型**：同一天、同一件事才合并，模型偶尔会漏合并（多出一条事件）或
   合并过度。代码侧只能保证"候选内的 id 才生效 + 整体替换"，语义判断本身不设兜底
