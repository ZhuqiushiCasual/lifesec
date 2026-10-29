# PRD v2 · 个人秘书（selfsec）

版本：v2.1 ｜ 更新：2026-10-27 ｜ 状态：主体已实施；消息推送链路已落地
取代：`docs/APP PRD.md`（v1.1，保留为历史）

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v2.0 | 2026-10-04 | 架构定稿 |
| v2.1 | 2026-10-27 | 细化消息推送：采集源、任务下发、Hermes skill、消息 CRUD/合并 API、工作台、前台洞察卡 |

---

## 0. 一句话

**一个只有聊天窗口的个人秘书：你说的话被记住，并且得到回应；重要的外部消息主动来找你。**

---

## 1. 产品原则

冲突时按序号让路。

1. **一个窗口。** 所有**用户侧**操作都发生在聊天窗口里，不新增需要用户填表的页面。
   运维侧的源配置 / 任务下发放在独立后台（`/workbench`），不计入用户界面。
2. **永远回应。** 系统对每一次输入都返回一句话。只有落库、没有回应 = 不成立。
3. **记得住。** 回应必须能引用历史（"这周第三次"）。引用不了历史的回应等于通用聊天，不做。
4. **可验证。** 每条主线必须有可观测指标（见 §5）。没有指标的模块不进主线。

---

## 2. 主线与优先级

| 优先级 | 主线 | 解决的问题 | 触发者 |
|---|---|---|---|
| P0 | 记录 + 规划 | 记不住、没规划 | 用户 |
| P1 | 问候 | 不被看见 | 定时 |
| P1 | 洞察（消息推送） | 错过重要消息 | Hermes |
| P1 | 采集运维（后台） | 不知道定时任务跑没跑、哪条源坏了 | 每日调度 / 人工 |
| P2 | 抚慰 | 情绪需要被接住 | 议程 + 记忆命中 |

> **依赖提示**：问候与洞察共用同一条回话总线，**问候应先于洞察**——它是总线的自测，且不依赖外部系统。

---

## 3. 交互模型（核心）

**唯一输入面 = 聊天窗口。**

```
用户输入（无分类、无表单）
   ↓ 意图识别：记录 / 规划 / 回应问候 / 情绪 / 闲聊
   ↓ 处理（记忆检索 + LLM）
   ↓
一句话回应  +  可选卡片
```

卡片是唯一的结构化输出形式，出现在窗口内，**不另开页面**：

| 卡片 | 何时出现 | 内容 |
|---|---|---|
| 记录卡 | 解析出结构化事件时 | 类型 / 关键实体 / 时间 |
| 计划卡 | 识别出待办或目标时 | 事项 / 状态 / 可勾选 |
| 问候卡 | 定时问候时 | 今日小结 / 问话 |
| 洞察卡 | Hermes 推送到达时 | 来源徽标 / 发布时间 / 标题 / **总结** / 影响 / 标签；操作：**详情**、**原文链接** |

> 设计意图：**洞察不是另一个页面，而是窗口里的一张卡。** 记录结果、问候、洞察共用同一个容器，因而共用同一套渲染与存储。
>
> 洞察卡的**总结**直接显示在卡片上（最多 3 行）；**详情**点开弹层查看；**原文链接**始终可点，
> 卡片和弹层各有一个入口。三段信息的分工是「一眼知道发生了什么 → 想看时看全 → 不信时回原文」。

---

## 4. 数据模型

主表 + 待办 + 采集三表。**对话与记忆分开**：窗口渲染只读 `messages`，记忆只读 `events`；
采集层只描述「怎么抓、抓过没」，与记忆层解耦。

```
messages        窗口里的全部消息 ← 我说的每一句（role=me，原样保留、永不改写）+ 它说的每一句
events          合并后的事件     ← 同一天重复/补充被合并成一条；Hermes 推来的洞察也在这里（不合并）
plans           待办 / 目标      ← 从对话里长出来，可勾选
ingest_sources  采集源配置       ← 站点、类型、降级层级、选择器、启停、最近一次状态
ingest_tasks    一次下发任务     ← queued/dispatched/running/succeeded/partial/failed/cancelled
ingest_runs     任务内单源执行   ← 每个源的条数、层级、耗时、错误
```

| 表 | 关键字段 |
|---|---|
| `messages` | id, **role(me/secretary)**, kind(user/reply/greeting/insight/nudge), content, card(JSON), ref_event_id, created_at, read_at |
| `events` | id, source(user/hermes), type(record/plan/finance/insight/feeling), content, entities(JSON), **tags(JSON)**, **occurred_on**, recorded_at, **last_at**, **merged_count**, dedup_key |
| `plans` | id, title, status(open/done), due_date, ref_event_id |
| `ingest_sources` | id, **key**, name, home_url, feed_url, **kind(rss/json_api/html/github)**, level, category, enabled, priority, max_items, config(JSON), last_run_at, last_status, last_error |
| `ingest_tasks` | id, trigger(manual/schedule), **status**, source_keys(JSON), worker, dispatched_at, started_at, finished_at, error, stats(JSON) |
| `ingest_runs` | id, task_id, source_key, status, fetch_level, items_found/new/updated/failed, error, detail(JSON), started_at, finished_at |

**洞察消息的存储复用现有两张表**：`events(source=hermes, type=insight)` 存事实，`messages(kind=insight, card=JSON)` 存窗口里那张卡。
不新增第二套消息表——前台渲染、回溯、已读状态都沿用原有机制。
`source_url` 规范化后作为 `dedup_key`，保证同一个链接重跑不会多出一张卡。

**同一天合并**：一条输入进来，先看当天已有的事件（作为候选进 Context），
如果它是其中某一条的重复 / 更正 / 补充（同一天、同一件事），就**整体替换**那条事件
（content / entities / tags 都给合并后的完整版本，last_at 往后推，merged_count +1）；
否则新建一条事件。判定复用唯一那次对话 LLM 调用，命中判定后仍要校验 id 在候选里。

**标签**：`events.tags` 由模型**每次重新生成**（自由命名，名词短语 2-6 字），
不维护标签字典表、不从固定枚举里挑——参考清单只出现在 prompt 里，且明确允许造新词。

**旧模型处置**：`finance_txns` → 降为 `events.type=finance`；`insights` → 并入 `events(source=hermes)` + `messages`；`digests` 表 → 删除，并入 `messages`。

---

## 5. 模块规格

### 5.1 记录 + 规划（P0）
- **输入**：一句话，不选类型。
- **输出**：一句话回应 + 记录卡（卡片上带 AI 生成的标签；并入已有事件时标出"第 N 次补充"）；
  含待办时附计划卡。
- **合并**：同一天同一件事的重复 / 补充合并成**一条**事件，不重复堆记录。
- **回应的三档**：确认（"记下了"）→ 比较（"这周第三次"）→ 追问（"上次你说要跑，跑了吗"）。M2 只做前两档。
- **指标**：连续记录天数。

### 5.2 问候（P1）
- **触发**：每日定时 2 次（早 8:00 / 晚 21:00）。
- **内容**：固定议程三问（睡好没 / 今天最重要的一件事 / 昨天有什么没放下）。**是议程，不是自由聊天。**
- **输出**：问候卡 + 一条 message。
- **指标**：问候的次日回应率。

### 5.3 洞察 · 消息推送（P1）

#### 5.3.1 目标与边界

用户打开聊天窗口，就能看到今天值得知道的 AI / 金融消息：**一眼有总结，想看有详情，不信能回原文**。

| 角色 | 负责 | 不负责 |
|---|---|---|
| **selfsec（前台 + 控制面）** | 源配置、任务排队、执行记录、消息落库与展示、人工增删改合并 | 不常驻抓取、不跑浏览器集群 |
| **Hermes（执行面）** | 领取任务、运行确定性 runner、LLM 生成总结/详情/影响、回调写回 | 不维护源清单的业务配置、不直接改库 |
| **工作台（后台页面）** | 看任务执行情况、源健康度、手工触发/重试、消息管理 | 不面向普通用户 |

> 与 v2.0 的措辞差异：仍然**不自建常驻抓取服务**，但采集逻辑以**确定性 runner**的形式放在仓库里
> （`backend/app/services/ingest/`），由 Hermes 执行。这样源配置、解析器、降级链可版本化、可离线测试，
> 同时 selfsec 进程本身不背抓取负载。

#### 5.3.2 信息源

首期覆盖 AI / Agent 行业，金融作为同一条采集链的 `category`，只收与科技公司、融资、IPO 强相关的条目。

| 源 | 主链路 | 详情获取 |
|---|---|---|
| 机器之心 | L0 官方 JSON | `article_library/articles/{slug}.json` |
| 量子位 | L0 WordPress RSS | L1 文章页 `.content` |
| InfoQ | L0 RSS | L1 文章页；RSS 摘要常为「点击查看原文」，必须抓正文 |
| 新智元 | L0 WP RSS | L0 WP REST `wp-json/wp/v2/posts/{id}?_embed=1`（页面本身也是 JS 调它） |
| GitHub | L0 Search API | 每个 topic 单独查询后合并；可选 `GITHUB_TOKEN` |

**降级链**：L0 RSS/官方 API → L1 HTTP+解析 → L1.5 TLS 指纹伪装 → L2 Playwright → L3 Camoufox。
源配置里记录 `kind` 与选择器，能在 L0 解决就不上浏览器；站点改版先改配置，长期失效则 `enabled=false`。

#### 5.3.3 任务链路

```
每日调度（默认 07:10） / 工作台「立即下发」
        ↓  创建 ingest_task(status=queued)
push：HMAC 签名的 webhook  ──▶ Hermes（失败不报错，任务留在 queued）
pull：Hermes cron GET /api/ingest/tasks/next ──▶ 领取
        ↓  POST /tasks/{id}/claim
stage A：python -m app.ingest.runner --task-id <id>   （不调模型）
        ↓  每个源结束就 POST /tasks/{id}/runs
stage B：LLM 生成 summary / detail / impact / topics / importance
        ↓  POST /api/ingest/messages（批量、幂等）
        ↓  POST /api/ingest/tasks/{id}/finish
selfsec 前台出现洞察卡；工作台看到每个源的条数与错误
```

- **push 与 pull 共用同一个 queued 任务**：push 只是加速，pull 保证最终一定被执行。
- **任务状态机**：`queued → dispatched → running → succeeded / partial / failed`；可人工 `cancel`，失败可 `retry`（新建一条重试任务）。
- **单源失败不影响其他源**：`ingest_runs` 独立记录，任务最终自动落为 `partial`。

#### 5.3.4 消息 API（Hermes 回调）

全部挂在 `API_TOKEN` 下，文档同时内置于 `hermes/skills/selfsec-news/SKILL.md`。

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/ingest/messages` | 批量新增 / 更新（按 canonical URL 幂等） |
| GET | `/api/ingest/messages` | 列表（按源、是否含隐藏过滤） |
| GET | `/api/ingest/messages/{event_id}` | 单条 |
| PATCH | `/api/ingest/messages/{event_id}` | 修改标题/总结/详情/影响/分类/标签/重要性/状态 |
| DELETE | `/api/ingest/messages/{event_id}` | 删除（只删 Hermes 来源） |
| POST | `/api/ingest/messages/merge` | 合并重复：`primary_id` + `duplicate_ids` |

**写回字段**：

| 字段 | 必填 | 说明 |
|---|---|---|
| `source_url` | 是 | 原文链接；规范化后作为幂等键 |
| `title` | 是 | 原始标题 |
| `summary` | 是 | 1–2 句中文，≤120 字；卡片上显示 |
| `detail` | 否 | 2–5 段中文；弹层显示 |
| `impact` | 否 | 1 句，对读者的影响 |
| `topics` | 否 | 2–4 个标签 |
| `importance` | 否 | 1–5，默认 3 |
| `category` | 否 | `tech` / `finance` |
| `source_key` / `source_name` | 否 | 来源徽标 |
| `published_at` | 否 | 原文发布时间 |
| `content` | 否 | 正文纯文本（回溯用，入库截断） |

**幂等与更新**：同一 `source_url` + 内容哈希不变 → `skipped`；内容变化 → `updated`，且**保留用户已读/隐藏状态**；
新链接 → 新建事件 + 洞察消息。批量中单条失败不影响其他条目，错误随响应返回。

**合并**：同一事件的多源报道先各自写回，再由 skill 最后一步调用 merge。`primary_id` 保留，
重复项的标签/主题/详情并入主条后删除（重复项 id 记进 `merged_from`）；宁可不合并，也不合并不同事件。

#### 5.3.5 前台展示（用户侧）

洞察卡出现在聊天窗口的消息流里，与记录卡、问候卡共用同一套容器：

| 区域 | 内容 |
|---|---|
| 卡头 | 来源名徽标 · 发布时间 · 「重点」标记（importance ≥ 4） |
| 主标题 | 原文标题 |
| **总结** | 1–2 句，最多 3 行；超出省略 |
| 影响 | 「影响」前缀的一句话（可选） |
| 标签 | AI 生成的 topic chips |
| 操作 | **详情**（打开弹层） · **原文链接 ↗**（新窗口） |

详情弹层：完整元信息 → 标题 → **总结** → 标签 → **详情**（分段正文）→ 底部固定「原文链接 ↗」。
回溯抽屉里的洞察条目同样提供「详情」与「原文链接」，不要求用户回到消息流里找。

**状态**：`new / read / hidden`；打开详情不强制标记已读，隐藏只在工作台操作。卡片正文永不改写用户记录。

#### 5.3.6 指标与验收

| 指标 | 口径 | 目标 |
|---|---|---|
| 任务成功率 | `succeeded / 全部 finished 任务` | ≥ 95% |
| 源失败可见率 | 有 `last_error` 的源在工作台可见 | 100% |
| 卡片产出 | 每任务写入条数、去重后条数 | 可解释，不异常膨胀 |
| 重复率 | 同一天同一 `source_url` 重复卡片 | 0 |
| 详情打开率 | 点击「详情」的卡片 / 曝光卡片 | 观察项，不设硬指标 |

验收：工作台能看到任务从 `queued` 走到 `succeeded` 且每个源有 `fetch_level`；
前台卡片有总结、能打开详情、原文链接可点；同一任务重跑不产生重复卡片。

### 5.4 采集工作台（P1，后台）

独立页面 `/workbench`，给「我一个人」看的运维界面，**不进入用户侧导航**。

- **鉴权**：`X-Workbench-Password`（`WORKBENCH_PASSWORD`），与 `API_TOKEN`、约会密码分开；密码为空时整站拒绝。
- **概览**：任务状态计数、源健康度、消息总数/24h 新增/状态分布、最近任务与运行记录、当前调度与下发配置。
- **任务**：选源 →「立即下发」；任务列表显示状态、触发方式、各源条数；支持重试、取消、查看运行明细。
- **源**：增删改、启停、调整优先级/条数/JSON 配置、单源「立即跑」、补回内置源。
- **消息**：按源筛选、看隐藏项、批量勾选合并、编辑、隐藏/恢复、删除。
- **刷新**：30 秒自动刷新当前标签页；打开弹层时暂停，避免输入被覆盖。

工作台只做「看」和「手工纠正」，不做抓取；所有抓取仍然由 Hermes 执行。

### 5.5 抚慰（P2，优先级最低）
- **触发**：议程命中 + 记忆命中，或用户明确表达情绪。**不主动开启话题。**
- **硬约束**：单次不超过 N 轮，不鼓励沉浸——避免强化反刍。
- **依赖**：完整记忆层。**记忆层完成前不开工。**
- **指标**：暂缺（不可验证），标注为实验性。

---

## 6. 明确不做

| 不做 | 原因 |
|---|---|
| 自由多轮陪聊（无边界对话） | 产品退化为套壳 LLM，无护城河 |
| 常驻抓取服务 / 自己维护调度集群 | 执行交给 Hermes；selfsec 只做源配置、任务与执行记录 |
| 在 selfsec 进程里跑浏览器抓取 | 抓取由 Hermes 侧 runner 执行，避免拖垮 API 服务 |
| 趋势图表 / 日报评分 / 资产分布 | 是"审判"不是"反馈"，用户不会看 |
| 多用户 / 注册登录 | 单用户 |
| 语音输入 | 需 HTTPS，后置 |

---

## 7. 实施顺序

| 阶段 | 内容 | 完成标志 |
|---|---|---|
| **M0 架构** | 定 `messages` / `events` / `plans` 表，建消息总线 | 一页纸落成代码，UI 无变化 |
| **M1 瘦身** | 摘掉假数据页面、趋势图、评分卡 | 界面上不存在假数据 |
| **M2 记录有回应** | `POST /api/events` 返回一句话 + 记录卡 | 输入后收到回应，而不是 toast |
| **M3 问候** | 定时任务 + 问候卡 | 每天两次自动出现 |
| **M4 洞察** | 接 Hermes 回调 | 外部消息出现在同一窗口 |
| **M4.5 采集链路** | 采集三表 + 工作台 + runner + 五个源 + skill | 工作台可下发、可看执行；前台卡片有总结/详情/原文 |
| **M5 抚慰** | 记忆层完成后开工 | 实验性 |
| **M6 打磨** | 合并建议、源健康告警、卡片交互统计 | 长期运行不靠人工盯 |

**顺序原则**：架构 → 瘦身 → 加功能 → 丰满。**瘦身必须在架构之后**，否则新功能会缝回旧结构。
