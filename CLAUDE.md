# CLAUDE.md

本文件为 AI 编码助手在本仓库工作提供指引。

## 项目概述

**selfsec** —— 单用户的个人秘书（个人项目，非产品）。

核心是**一个对话接口**：用户说的话被记住、并得到回应；外部的重要消息主动找上门。
它不是"记录工具"，而是"有回应的东西"——每次输入都必须换来一句话。

- 架构极简：FastAPI 同时提供 API 与前端静态页，无独立前端工程、无构建步骤
- `backend/app/`：FastAPI (async) + SQLAlchemy 2.0
  - 默认 **SQLite**（零配置开箱即跑）；生产用 MySQL（`asyncmy`）
- `backend/static/`：前端（原生 HTML + CSS + JS，**只有一个聊天窗口**，无框架无构建）
- 设计文档：`docs/PRD-v2.md`（产品规格）、`docs/架构-v1.html` / `.drawio`（架构图）

## 常用命令

```bash
cd backend

# 依赖（Windows 用 conda 环境 life-secretary，Python 3.11）
pip install -r requirements.txt

# 配置：复制 .env.example 为 .env
#   不设 DATABASE_URL 就走 SQLite（./selfsec.db），无需装数据库
#   生产：DATABASE_URL=mysql+asyncmy://user:pass@host:3306/selfsec?charset=utf8mb4

python startup.py                              # 启动（等 DB → 建表 → uvicorn）
python smoke_test.py                           # 端到端冒烟测试（用 SQLite，不碰生产库）
python -m uvicorn app.main:app --port 8123     # 直接起服务

docker compose up -d --build                   # 远程部署（api + mysql）
```

表结构与锚点用户由 `app/main.py` 的 lifespan 自动创建，**没有种子 SQL、没有迁移工具**。

## 架构要点

一条主线，五个概念：

```
① 输入    ② 对话接口            ③ Context 组装        ④ 记忆层            ⑤/⑥ 数据与输出
聊天窗口 → POST /api/chat  → System Prompt (长且稳定)  4.1 长期画像         events / messages
定时触发   意图路由 + 编排       Memory Block (动态)    4.2 事实与统计       plans / memory_profile
Hermes     一次 LLM 调用         当前 User Message     4.3 洞察记忆         → 一句话回应 + 卡片
                                4.4 会话短期
```

- **`services/agent.py` 是编排核心**：`意图路由 → 组装 Context → 生成回应 → 落事件 → 落消息`
- **全程只有一次 LLM 调用**（`services/ai/reply.py`），意图判定与字段抽取都在这一次里完成。
  `route()` 只做本地能确定的事（判断是否在表达情绪），不做第二次调用
- **记忆层四层**（`services/memory/`），按"变化频率 / 成本"划分：
  - `profile.py` 4.1 长期画像——「总结意识」，定期/阈值/手动把全部事件压成一段话（对应 Hermes 的 user.md）
  - `stats.py` 4.2 事实与统计——纯 SQL 聚合/对比，**不过 LLM**，提供"比较档"回应的原料
  - `insights.py` 4.3 洞察记忆——外部驱动，读 `events(source=hermes)`
  - `session.py` 4.4 会话短期——最近 N 轮，用于指代消解
- **内置调度**（`services/scheduler.py`）：一个 asyncio 循环，早晚各一次问候 + 夜间重算画像。
  刻意不引 APScheduler
- **前端零依赖零构建**：`static/app.js` 渲染"用户轮 + 秘书轮"合一的消息流，卡片是唯一的结构化输出形式

## API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/chat` | **唯一入口**。意图路由 + 抽取 + 回应，返回 `{reply, card, message_id}` |
| GET | `/api/messages?limit=` | 窗口流（`role=me` 用户轮 + `role=secretary` 秘书轮，按时间合并） |
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
events          进来的东西  ← source=user(用户输入) / hermes(洞察推送)
                type: record | plan | finance | insight | feeling
                entities(JSON) 存结构化字段；dedup_key 供 Hermes 幂等
messages        它说的话    ← kind: reply | greeting | insight | nudge
                card(JSON) 直接存卡片，前端不用 join
plans           待办 / 目标，从对话里长出来，可勾选
memory_profile  长期画像，单用户单行，version 递增
```

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
- 窗口流（`api/messages.py`）把 events 与 messages 归并成一条时间线，排序键是 `(created_at, 轮次, id)`：
  **同一时刻下用户轮必须排在秘书轮前面**。不能"降序排 → 截断 → 整体 reverse"，那会把并列项翻过来
- 前端 `api()` 里 401 的处理必须**并发安全**：`loadAll` 一次发两个请求，两个都可能拿到 401，
  只允许弹一次 Token 输入框（并发请求共用一个输入过程 + 用当前 token 静默重试）
- 响应错误保持 `{"detail": "..."}` 风格

## 已知限制 / 注意点

1. **改表结构需重建库**：无 Alembic，`create_all` 只建缺失的表、不会 ALTER 已有表。
   从旧版升级（旧库有 `finance_txns` / `insights` / `digests`）**必须换新库**；
   时间戳精度升级（`DATETIME` → `DATETIME(6)`）要手动跑 `docs/alter-datetime6.sql`
2. **`backend/.env` 里现在指向的是旧的远程库**，且是旧表结构 —— 用之前先确认/更换 `DATABASE_URL`
3. **无测试框架**，只有 `smoke_test.py`（29 项断言，端到端，离线可跑；含同秒并列的次序回归）
4. **secrets 曾入库**：旧版 `config.py` 硬编码过 DB 密码与 DeepSeek key（仍在 git 历史），建议轮换
5. **抚慰（P2）尚未实现**：`route()` 已识别情绪词并给模型提示，但没有独立的抚慰议程
6. **PWA 已移除**：`sw.js` / `manifest` / icons 已删，浏览器麦克风仍需 HTTPS
