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
- 设计文档：`docs/PRD-v2.md`（产品规格）、`docs/架构-v1.html` / `.drawio`（架构图）、
  `docs/记忆-同行调研.html`（记忆机制调研：同行怎么做的 + 本项目的画像/馆藏设计）、
  `docs/采集-技术选型对比.md`（推送输入侧：L0–L3 降级链 / 源配置 / 两级 cron）、
  `docs/采集-历史排查-opencode.md`（旧新闻守护进程考古：无源清单、空转 33 万次、已停止）、
  `docs/设计-消息推送.md`（消息推送的完整设计：架构 / 任务协议 / 消息协议 / 工作台 / 失败模式）、
  `hermes/skills/selfsec-news/SKILL.md`（Hermes 执行 skill：五个源 + 消息 CRUD/合并 API）、
  `docs/会话记录/`（重要设计对话的原文导出存档）

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
python migrate_v3.py                           # 一次性迁移：v2 → v3（画像分节 + 馆藏索引卡 + 迭代锁）
python eval_memory.py                          # 记忆评测：离线回放（不调模型）+ 命中率/分块占比/staleness
python -m app.ingest.runner --source qbitai --out ../.hermes/qbitai.json
                                               # 采集 runner（确定性，不调模型；Hermes skill 的 stage A）
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
聊天窗口 → POST /api/chat  → System Prompt (长且稳定)  4.1 画像（分 5 节）   对话 messages
定时触发   意图路由 + 编排       Memory Block（五 Block）4.2 馆藏（索引卡）    事件 events
Hermes     生成 + 迭代时钟        当前 User Message     4.3 迭代三时钟        plans / 画像 / 索引卡
                                4.4 初始化问卷                            → 一句话回应 + 卡片
```

- **`services/agent.py` 是编排核心**：
  `意图路由 → 组装 Context（五个 Block）→ 生成回应 + 归档决定 → 落窗口 → 合并/新建事件 → 落待办 → 落回应 → 迭代时钟`
- **回应、抽取、标签、合并判定必须来自同一轮生成**（`services/ai/reply.py`）——它们本来就是同一个理解的不同侧面，
  拆开会让模型重复理解同一句话，还会出现"回应说合并了、归档却新建了一条"。
  `route()` 只做本地能确定的事（判断是否在表达情绪）。
  **记忆侧的迭代（档摘要 / 画像）不在对话路径里**，由 `services/memory/lifecycle.py` 的三个时钟驱动
- **事件合并**（`services/records.py`）：今天已有的事件作为候选进 Context，模型返回 `merge_event_id`；
  命中就**整体替换**那条事件（`content` / `entities` / `tags` 都给合并后的完整版本，`last_at` 往后推、
  `merged_count += 1`），否则新建。**id 必须在候选集合里**，否则按新建处理——
  多一条冗余事件，好过让幻觉改写历史
- **标签**：`events.tags` 由模型每次生成（自由命名）。prompt 里给的只是命名风格参考、不是可选清单；
  刻意**不做标签字典表**，避免"固定枚举 + 挑选"那套。
  **软归一**（三件一起上，都不需要硬编码枚举）：① 每轮把「已有标签清单」注入 prompt，要求优先复用已有写法；
  ② `tag_aliases(alias → canonical)` 记别名，检索时按 canonical 聚合、**不合并事件本身**；
  ③ `POST /api/memory/tags/merge` 或 `eval_memory.py --merge-tags` 让模型定期给归并建议
- **记忆层 = 画像 + 馆藏**（`services/memory/`）——画像回答"你是谁"，馆藏回答"你做过什么"。
  与 ChatGPT / Claude / Hermes / Gemini 的逐项对照见 `docs/记忆-同行调研.html`
  - `profile.py` 4.1 **画像**——**分 5 节**：identity / style / avoid / current / insight。
    各节**半衰期不同**（身份以年计、正在做的事以周计），所以分开存、只重算变了的那节；
    硬上限 `PORTRAIT_CHAR_LIMIT`（1500 字符），超了按节截断；每节带 **provenance**（来源事件 id + 更新时间）；
    变更摘要 + 版本历史（`profile_versions`）落库
  - `library.py` 4.2 **馆藏**——三层：**索引卡**（`tag_index`，常驻目录）/ **分档**（命中后展开的摘要 + 最近原文）/
    **原文**（`events`，真相源）。索引卡是**派生产物**，随时可从 events 重建（`rebuild_index`）。
    命中规则全在本地：字面命中标签名或别名 → 会话热集 → 兜底取最近几档
  - `lifecycle.py` 4.3 **迭代三时钟**——每 10 轮档迭代 / 每 20 轮画像迭代 / 00:00 每日兜底。
    幂等由 `job_runs(job, period_key)` 唯一键保证（三个时钟会打架，没锁就是同一次迭代算两遍）
  - `onboarding.py` 4.4 **初始化**——10 题问卷 + 可审阅预览（每题都直接产出一句画像；
    预览不调模型，所以免费、即时、可重复）
  - `stats.py` 事实与统计——纯 SQL 聚合/对比，**不过 LLM**，提供"比较档"回应的原料
  - `insights.py` 洞察记忆——外部驱动，读 `events(source=hermes)`
  - `session.py` 会话短期——`as_history` 给多轮上下文；`user_turns` 提供 Block C（近 40 轮用户提问、
    只取我说的 + 时间锚 + 主题）
  - `context.py` ③ Context 组装——**五个 Block，顺序就是缓存策略**：稳定的在前、每轮都变的命中档放最末
- **消息推送**（`services/ingest/`）：工作台/每日调度建 `ingest_task` → push webhook 或 Hermes pull
  → `runner` 确定性抓取（L0 RSS/官方 API → L1 HTTP → L2/L3 浏览器）→ Hermes 用 LLM 生成
  summary/detail/impact → `POST /api/ingest/messages` 写回 → 前台洞察卡。源配置在 `sources.py`，
  站点适配在 `crawler.py`/`fetch.py`，任务状态机在 `tasks.py`，HMAC 下发在 `dispatch.py`
- **约会探店**（`services/date_visits.py`）：聊天里「已经发生的吃饭 / 会面」和「计划去吃」的判定
  仍在同一轮生成里完成（`date_visit.is_visit`）；命中菜单里的店就落一条 `date_visits`，
  同时关联 `date_menu.id` 和当天的 `event`。店名对不上菜单时 `restaurant_id` 为空、保留店名快照。
  同人 + 同店 + 同日期只保留一条，后续补充更新它。前台怎么呈现待定，先用
  `GET /api/date/admin/visits` 核对
- **内置调度**（`services/scheduler.py`）：一个 asyncio 循环，早晚各一次问候 + 00:00 每日兜底
  （兜底走 `lifecycle.daily`：距上次迭代 > `PORTRAIT_HOURS` 且确有新增才补跑，不是无条件重写）
  + 每日采集（默认 07:10，`INGEST_HOUR` / `INGEST_MINUTE`）。
  采集任务的幂等锁是 `job_runs(job=ingest_daily, period_key=day:YYYY-MM-DD)`——
  进程重启、多实例都只建一个任务。刻意不引 APScheduler
- **前端零依赖零构建**：`static/app.js` 渲染"我说的 + 它说的"合一的消息流，卡片是唯一的结构化输出形式
  （卡片上带 AI 生成的标签 chips；并入已有事件时卡片会标出"第 N 次补充"）。
  **洞察卡**额外分三段：总结（卡面 3 行） / 详情（弹层，`openInsight`） / 原文链接（卡面与弹层各一个入口）

## API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/chat` | **唯一入口**。意图路由 + 抽取 + 标签 + 回应（含归档决定），返回 `{reply, card, message_id, event_id, merged, date_visit_id, restaurant_id}` |
| GET | `/api/messages?limit=` | 窗口流（单表 `messages`：`role=me` 我说的 + `role=secretary` 它说的） |
| GET | `/api/messages?filter=record` | 回溯里的「事件」线：合并后的事件，带 `tags` / `merged_count` / `occurred_on` |
| GET | `/api/messages?filter=insight` | 回溯里的「洞察」线（`messages.kind=insight`） |
| POST | `/api/insights` | **Hermes 单条回调**（旧入口，仍兼容）。落 `events(source=hermes)` + 洞察消息，按 `source_url` 幂等 |
| GET | `/api/ingest/tasks/next` | **Hermes pull 入口**：原子领取最早一个 queued 任务；没有则 `{"task": null}` |
| POST | `/api/ingest/tasks/{id}/claim` | push 模式下领指定任务（幂等；被抢/已结束 409） |
| GET | `/api/ingest/tasks/{id}` | 任务 + 各源运行记录 |
| POST | `/api/ingest/tasks/{id}/runs` | 上报单源执行结果（层级 / 条数 / 错误 / 耗时） |
| POST | `/api/ingest/tasks/{id}/finish` | 任务收尾（succeeded / partial / failed） |
| GET | `/api/ingest/sources` | 源配置（可 `enabled_only=true`） |
| POST | `/api/ingest/messages` | **Hermes 批量写回**：新增/更新，按 canonical URL 幂等，保留已读状态 |
| GET/PATCH/DELETE | `/api/ingest/messages/{event_id}` | 单条查询 / 修改 / 删除（只动 Hermes 来源） |
| POST | `/api/ingest/messages/merge` | 合并重复消息（任一 id 不存在则整次 404） |
| — | `/api/workbench/*` | 工作台：概览 / 源增删改启停 / 任务下发重试取消 / 消息管理；需 `X-Workbench-Password` |
| GET | `/workbench` | 采集工作台页面（静态 `static/workbench.html`） |
| GET | `/api/plans` | 待办列表（默认只返回 open） |
| PATCH | `/api/plans/{id}` | 勾选待办（`{"status": "open\|done"}`） |
| GET | `/api/memory` | 画像：分节正文 + 每节 provenance + 变更摘要 |
| POST | `/api/memory/refresh` | 手动强制重算画像（force，不推 nudge） |
| GET | `/api/memory/library` | 馆藏：索引卡（标签→条数→最近→档首摘要）+ 画像版本历史 |
| POST | `/api/memory/tags/merge` | 标签归并（软归一 ②③ 层：写别名表，不合并事件） |
| GET | `/api/onboarding/questions` | 初始化 10 题 |
| POST | `/api/onboarding/preview` | 可审阅预览：答案 → 五节草稿（不调模型） |
| POST | `/api/onboarding/apply` | 确认落盘：问卷事件（`source=questionnaire`）+ 第一版画像 |
| GET | `/api/date/menu` | **约会挑餐厅**的前台菜单（**不需要 token**）：`ORDER BY sort, id`，隐藏项不返回 |
| POST | `/api/date/choose` | 她挑完发的那句话：落一条 `messages(role=me)`，不调模型（**不需要 token**） |
| — | `/api/date/admin/*`、`/api/date/items`、`/api/date/reorder` | 菜单增删改 + 上下移排序，需请求头 `X-Date-Password`（`DATE_ADMIN_PASSWORD`） |
| GET | `/api/date/admin/visits` | 探店记录查询（可按 `restaurant_id` 过滤），需 `X-Date-Password` |
| GET | `/date` | 约会挑餐厅页面（给另一半看的短链接，静态 `static/date.html`） |
| GET | `/health` | 健康检查（无鉴权） |
| GET | `/` | 前端静态页 |

**鉴权分三套，互不替代**（不要为了省事把其中一个复用到另一个）：

| 范围 | 凭证 | 说明 |
|---|---|---|
| `/api/*`（除工作台、约会；Hermes / 脚本） | `X-API-Token`（`API_TOKEN`） | 为空时不校验，仅限本地开发 |
| `/api/workbench/*`、`/workbench` | `X-Workbench-Password`（`WORKBENCH_PASSWORD`） | **不要求 `X-API-Token`**；密码为空 = 工作台整体禁用（503），且**不复用 `DATE_ADMIN_PASSWORD`** |
| `/api/date/menu`、`/api/date/choose` | 公开 | 给另一半看的页面，不能要求 token |
| `/api/date/admin/*`、`/api/date/items`、`/api/date/reorder` | `X-Date-Password`（`DATE_ADMIN_PASSWORD`） | 只保护增删改排序与探店查询 |

## 数据模型（13 张表 + 用户锚点）

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
memory_profile  画像，单用户单行：sections(JSON 分 5 节) + sources(JSON 每节 provenance)
                + summary(最近变更摘要) + version / event_count(依据事件数) / msg_count(依据轮数)
                content 是分节渲染后的全文（给人看 / 兜底）
profile_versions 画像版本历史——防漂移的最后一环：每次迭代留一份，可回溯可回滚
tag_index       馆藏索引卡，一行一个标签：tag / count / last_at / digest(档首摘要) / digest_count
                **派生产物**，可从 events 重建，丢了不心疼
tag_aliases     标签别名 → 规范名（软归一）。只做映射，**不合并事件本身**
job_runs        迭代幂等锁：(job, period_key) 唯一键，跑过就跳过
date_menu       约会挑餐厅的菜单项：内容 + 口味三轴(清/辣/油) + sort/hidden
                **与记忆层无关**，只服务 /date 那一个页面；后台可增删改排序
date_visits     约会探店记录：一次已经发生的吃饭 / 会面
                restaurant_id → date_menu.id（可空）+ 店名/分店/菜系快照
                event_id → 当天的合并事件；visited_on 就餐日期
                rating(1–5, 可为 4.5) / dishes(JSON) / companion / occasion / review
                同人 + 同店 + 同日期只保留一条，后续补充更新它
ingest_sources  采集源配置：key / name / feed_url / kind(rss|json_api|html|github)
                / level / category / enabled / priority / max_items / config(JSON)
                加源 = 加一行配置，不在代码里写站点逻辑；种子只补缺失 key
ingest_tasks    一次下发任务：trigger(manual|schedule) / status
                queued → dispatched → running → succeeded | partial | failed
                source_keys(JSON) / worker / dispatched_at / started_at / finished_at / stats
ingest_runs     任务内单源执行记录：source_key / status / fetch_level
                items_found/new/updated/failed / error / detail(JSON) / 起止时间
                **单源失败不影响其他源**；finish 时按 runs 再校正一次任务状态
```

一次 `/api/chat` 的落库顺序：`messages(role=me, 原话)` → `events(合并或新建)`
→ 可选 `date_visits(探店)` → 可选 `plans` → `messages(role=secretary, 回应)`。

**时间戳统一用 `app/database.py` 的 `DateTimeMicro`（`DateTime` + MySQL 侧的 `DATETIME(6)`），
默认值用 Python 侧 `default=now_local`，不是 `func.now()`。**
MySQL 的 `DATETIME` 默认精度只到「秒」，同一秒内落库的多条记录时间戳完全相同，`ORDER BY` 定不出先后
（表现为「它的回应显示在我发送的消息上面」）；`DateTimeMicro` 让 MySQL 侧建出 `DATETIME(6)`，
其它方言保持普通 `DateTime`（SQLite 本来就存到微秒）。**老库要手动跑 `docs/alter-datetime6.sql`**，
`create_all` 只建缺失的表、不会 ALTER 已有表。

## 与 Hermes 的边界

- 抓取 / 生成 / 过滤由 **Hermes** 执行；selfsec 负责**源配置、任务排队、执行记录、消息落库与展示**
- **不自建常驻抓取服务、不在 API 进程里跑浏览器**；采集逻辑是确定性 runner
  （`backend/app/services/ingest/`，入口 `python -m app.ingest.runner`），由 Hermes 调用
- 任务下发双通道：push（HMAC V2 webhook）+ pull（`GET /api/ingest/tasks/next`）。
  push 失败任务留在 `queued`，pull 会捡走——**最终一定执行**
- 消息写回复用 `events(source=hermes)` + `messages(kind=insight)`，不新增第二套消息表；
  canonical URL 作为幂等键
- Hermes 侧的 skill / prompt / 消息 CRUD 文档：`hermes/skills/selfsec-news/SKILL.md`、
  `hermes/README.md`；旧版说明见 `docs/hermes-新闻任务.md`

## 约定

- 注释与文档以中文为主，标识符用英文
- 分层：`api/`（路由）→ `services/`（业务）→ `models/` + `schemas/`
- **AI 调用只放在 `services/ai/`**（`client.py` 统一出口，失败抛 `AIUnavailable`，调用方必须降级）
- 任何 LLM 失败都不能让用户看到报错——回应生成有本地兜底（"记下了。"）
- 前端保持零依赖零构建：不引入框架/打包器；卡片样式统一在 `styles.css`
- 窗口流（`api/messages.py`）现在是**单表**查询 `messages`（以前是 events + messages 跨表归并）。
  排序键 `(created_at, 轮次, id)`：**同一时刻「我说的」必须排在「它说的」之前**——
  不能只按时间排，库的时间精度不保证（见下面时间戳那段）
- **窗口流的 `limit` 取的是「最近 N 条」，不是「最早的 N 条」**：SQL 侧一律倒序 `LIMIT`，
  需要正序时把结果整体翻转（倒序是含 `id` 的严格全序，翻转不会打乱并列项的先后）。
  反过来按正序 `LIMIT`，攒够 N 条之后新记的东西就再也进不了窗口——
  表现是「我说了、它没回应」，而库里每条都在（2026-10-15 就是这么挂的）
- **合并判定与标签生成必须来自同一轮生成**（它们本来就是同一个理解的不同侧面），不要为它单独再加一次调用；
  也**必须校验**模型返回的 `merge_event_id`（要在候选集合里），校验不过就按新建处理
- 标签永远由模型重新生成，不在代码里维护标签枚举 / 标签字典表
- **探店记录的语义判定也只来自模型**：`date_visit.is_visit` 决定「这是不是一次已经发生的吃饭 / 会面」；
  代码只校验 `restaurant_id` 必须命中 `date_menu`（不命中就按店名 / 正文本地匹配），
  并把未来日期当作计划、不落记录。菜单里没有的店保留店名快照，不自动加进 `/date` 菜单
- 前端 `api()` 里 401 的处理必须**并发安全**：`loadAll` 一次发两个请求，两个都可能拿到 401，
  只允许弹一次 Token 输入框（并发请求共用一个输入过程 + 用当前 token 静默重试）
- 响应错误保持 `{"detail": "..."}` 风格
- **采集源只走配置**：加源 = `ingest_sources` 加一行（`sources.py` 只提供种子，且只在启动时补缺失 key、
  不覆盖工作台改过的配置）。站点差异写进 `config`（`content_selectors` / `detail_api` / `queries` /
  `allow_render` …），**不在 skill 里、也不在 API 进程里写站点专用抓取代码**
- **抓取必须走确定性 runner**（`python -m app.ingest.runner`），不要在 agent 里即兴搜索/抓网页；
  源、选择器、降级顺序可复现、可离线测试
- **消息写回幂等**：`source_url` 先规范化（去 `utm_*` / `spm` / `from` / `source` / `ref` / `share_*` /
  `scene` / 排序参数 / 锚点）再当 `dedup_key`；同 key + `raw_hash` 不变 → `skipped`，内容变化 → `updated`，
  **且保留 `status`**（重跑不能把用户已读/隐藏打回 `new`）
- **合并是破坏性操作**：只动 `events(source=hermes)`；`primary_id` 或任一 `duplicate_ids` 不存在就整次 404，
  不允许"合了一半"；重复项的 tags/topics/detail 并入主条，id 记进 `merged_from`
- **任务无论成败都必须 `finish`**：否则永远停在 `running`，工作台看得见但再也不会被领取；
  部分源失败必须报 `partial`，不要谎报成功

## 已知限制 / 注意点

1. **改表结构需重建库**：无 Alembic，`create_all` 只建缺失的表、不会 ALTER 已有表。
   从旧版升级（旧库有 `finance_txns` / `insights` / `digests`）**必须换新库**；
   - v1 → v2（`messages.role` + 事件的 `tags` / `occurred_on` / `last_at` / `merged_count`）：
     跑 `python migrate_v2.py`（幂等，SQLite / MySQL 都能跑；**在容器里跑**见 `docs/部署.md` 第十二节）
   - v2 → v3（画像分节 + `tag_index` / `tag_aliases` / `job_runs` / `profile_versions`）：
     跑 `python migrate_v3.py`（幂等；新表走 `create_all`，老库的一整段画像会搬进 `sections.insight` 不丢）
   - 时间戳精度升级（`DATETIME` → `DATETIME(6)`）要跑 `docs/alter-datetime6.sql`
2. **`backend/.env` 里现在指向的是旧的远程库**，且是旧表结构 —— 用之前先确认/更换 `DATABASE_URL`
3. **无测试框架**，只有 `smoke_test.py`（161 项断言，端到端，离线可跑；含采集链路 [18]–[22] 与探店 [23]）
   + `eval_memory.py`（记忆评测：离线回放不调模型，另有 `--rebuild-index` / `--merge-tags`）；
   迁移脚本的用例在仓库外的 scratch 里（未入库）
4. **secrets 曾入库**：旧版 `config.py` 硬编码过 DB 密码与 DeepSeek key（仍在 git 历史），建议轮换
5. **抚慰（P2）尚未实现**：`route()` 已识别情绪词并给模型提示，但没有独立的抚慰议程
6. **PWA 已移除**：`sw.js` / `manifest` / icons 已删，浏览器麦克风仍需 HTTPS
7. **画像会漂移，靠四件事压住**（没有它们，每天 00:00 无条件重写会让画像缓慢变味）：
   ① 没有新增就不重算 ② 把上一版画像作为输入、要求"没有新依据不要改写" ③ 变更摘要 + 版本历史
   ④ 变更摘要作为 `kind=nudge` 推给用户——"它对我的理解变了"要看得见
8. **合并的判定质量取决于模型**：同一天、同一件事才合并，模型偶尔会漏合并（多出一条事件）或
   合并过度。代码侧只能保证"候选内的 id 才生效 + 整体替换"，语义判断本身不设兜底
9. **采集 runner 需要读 selfsec 的库**（源配置在 `ingest_sources`）：Hermes 与 selfsec 同机最省事，
   否则要给 runner 一个能读该库的 `DATABASE_URL`。消息写回始终走 HTTP，不直连写库
10. **webhook 签名算的是原始 body 字节**：Hermes 侧验签前不要 `json.loads` 再 `dumps`，
    键顺序/空格变化会导致签名对不上；时间戳窗口 ±5 分钟
11. **L2 / L3 是按需依赖**：`requirements.txt` 只装 `httpx` / `feedparser` / `beautifulsoup4` / `curl_cffi`；
    Playwright（L2）与 Camoufox（L3）**默认不装**，没装时降级链止步于 L1.5，且必须优雅失败
    （`fetch.py` 里全部是函数内可选导入，不要在模块顶层 import）。能用 L0 解决就不要上浏览器
12. **采集 runner 自带 bootstrap**：`python -m app.ingest.runner` 首次运行会 `create_all` 建缺失的表、
    补缺失的源种子，所以全新 SQLite 也能直接跑；生产仍以 selfsec 启动时建表为准。
    runner 需要读 `ingest_sources`（见第 9 条），消息写回始终走 HTTP
13. **每日采集的触发窗口**：调度循环按分钟轮询，只在 `INGEST_HOUR:INGEST_MINUTE` 之后的**同一小时内**
    补触发；如果那个小时服务整体没起来，当天不会补建任务（需要手动在工作台「立即下发」）
14. **探店记录的识别质量取决于模型**：`is_visit` 由模型判定；模型不可用时不建探店记录（事件照记）。
    菜单里没有的店只保留店名快照，不会自动加进 `/date` 菜单
