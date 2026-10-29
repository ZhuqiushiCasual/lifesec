---
name: selfsec-news
description: 执行 selfsec 工作台下发的新闻采集任务：按 L0–L3 降级链确定性抓取五个 AI/金融源，生成总结/详情/影响后回调 selfsec 写入消息。适用于收到 selfsec.ingest.task webhook，或 cron 轮询 GET /api/ingest/tasks/next 拿到任务的场景。
---

# selfsec-news

selfsec 是前台（用户看消息）和控制面（源配置、任务、执行记录）；**Hermes 是执行面**。
本 skill 只做两件事：**把任务跑完**、**把结果写回 selfsec**。

```
selfsec 工作台 / 每日调度
        │  queued 任务（push webhook 或 pull tasks/next）
        ▼
Hermes ── stage A：确定性 runner（不调模型）──→ 中间 JSON
        └─ stage B：LLM 生成 summary/detail/impact/topics/importance
                       │
                       ▼
              POST /api/ingest/messages  →  selfsec 前台出现洞察卡
              POST /api/ingest/tasks/{id}/finish
```

> **两条硬规则**
> 1. 抓取必须走确定性脚本，不要在 agent 里即兴搜索网页。源、选择器、降级顺序都在
>    `backend/app/services/ingest/sources.py` 与 `crawler.py` 里，可复现、可离线测试。
> 2. 摘要/详情/影响只能基于 runner 给出的正文，**不许补写正文里没有的事实**。

---

## 0. 环境

| 变量 | 说明 |
|---|---|
| `SELFSEC_API_BASE` | selfsec 地址，如 `http://127.0.0.1:8000`（不要带结尾 `/`） |
| `SELFSEC_API_TOKEN` | 对应 selfsec 的 `API_TOKEN`；selfsec 未配置时可为空 |
| `SELFSEC_BACKEND_DIR` | selfsec 仓库的 `backend/` 绝对路径（stage A 需要） |
| `DATABASE_URL` | runner 读源配置用；与 selfsec 相同（SQLite / MySQL 都可） |

依赖（一次性）：

```bash
cd "$SELFSEC_BACKEND_DIR"
pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt
```

所有请求带：

```http
X-API-Token: <SELFSEC_API_TOKEN>
Content-Type: application/json
```

鉴权失败返回 `401 {"detail": "..."}`；不要重试到死，把错误写进任务收尾即可。

---

## 1. 接任务

### 1.1 push（推荐）

selfsec 向 Hermes webhook 发送：

```json
{
  "event": "selfsec.ingest.task",
  "task_id": "tsk_xxx",
  "task": {"id": "tsk_xxx", "status": "dispatched", "source_keys": [], "...": "..."},
  "api_base": "http://127.0.0.1:8000",
  "hint": "调用 /api/ingest/tasks/{task_id}/claim 领取，再按 skill 的流程执行"
}
```

请求头：

```http
X-Webhook-Timestamp: 1793000000
X-Webhook-Signature-V2: <hex(HMAC-SHA256(secret, "<timestamp>.<raw body>"))>
```

Hermes 侧应校验签名与时间戳（±5 分钟），然后 `claim`。

### 1.2 pull（穿 NAT 兜底）

Hermes cron 每 10–15 分钟跑一次：

```bash
curl -sS -H "X-API-Token: $SELFSEC_API_TOKEN" \
  "$SELFSEC_API_BASE/api/ingest/tasks/next?worker=hermes"
```

没有任务时返回 `{"task": null, "sources": [], "api_base": "..."}`，**安静退出，不要告警**。

### 1.3 claim

拿到 `task_id` 后先领取（幂等，重复 claim 同一个任务返回同样内容）：

```bash
curl -sS -X POST -H "X-API-Token: $SELFSEC_API_TOKEN" \
  "$SELFSEC_API_BASE/api/ingest/tasks/$TASK_ID/claim?worker=hermes"
```

返回：

```json
{
  "task": {"id": "...", "status": "running", "source_keys": ["qbitai"], "...": "..."},
  "sources": [{"key": "qbitai", "name": "量子位", "feed_url": "...", "config": {...}}],
  "api_base": "http://127.0.0.1:8000",
  "message_api": "/api/ingest/messages"
}
```

- `source_keys` 为空 = 跑全部启用源。
- `409` 表示任务已被别人领走 / 已结束：**换个任务或直接退出**，不要抢。

---

## 2. stage A：确定性抓取

```bash
cd "$SELFSEC_BACKEND_DIR"
TASK_ID="tsk_xxx"
OUT="../.hermes/ingest-$TASK_ID.json"

python -m app.ingest.runner \
  --task-id "$TASK_ID" \
  --out "$OUT"
```

runner 的行为：

- 读取任务与源配置（`ingest_sources`），把任务置为 `running`；
- 按源的 `kind` 抓取：`rss` / `json_api` / `html` / `github`；
- 每个源结束就 `POST /api/ingest/tasks/{id}/runs` 上报（成功/失败、fetch_level、条数、耗时、错误）；
- 输出统一中间格式；**不调模型、不写消息**；
- 退出码：至少一个源成功 → `0`，全部失败 → `1`。

只跑单源调试：

```bash
python -m app.ingest.runner --source qbitai --out ../.hermes/qbitai.json
```

### 2.1 中间格式

```json
{
  "task_id": "tsk_xxx",
  "generated_at": "2026-10-27 08:10:00",
  "lookback_hours": 36,
  "sources": [
    {"source_key": "qbitai", "source_name": "量子位", "status": "succeeded",
     "fetch_level": "L1", "items": 10, "error": null, "elapsed_ms": 4210}
  ],
  "items": [
    {
      "source_key": "qbitai",
      "source_name": "量子位",
      "title": "刚刚，Anthropic 公开 335 页招股书",
      "url": "https://www.qbitai.com/2026/10/505551.html",
      "summary": "RSS 摘要或正文开头（未经模型加工）",
      "content": "正文纯文本，最多 12000 字",
      "published_at": "2026-10-27 00:06:31",
      "topics": ["Anthropic", "IPO"],
      "category": "tech",
      "importance": 4,
      "fetch_level": "L1",
      "raw_hash": "sha256:..."
    }
  ]
}
```

---

## 3. stage B：生成总结 / 详情 / 影响

对 `items` 逐条处理（可批量放在同一轮提示里，但每条独立判断）。

### 3.1 产出字段

| 字段 | 要求 |
|---|---|
| `summary` | 1–2 句中文，≤ 120 字；说清「发生了什么」，不写评价 |
| `detail` | 2–5 段中文，≤ 1200 字；补充关键数字、人物、时间线、技术细节 |
| `impact` | 1 句中文，≤ 60 字；对读者（关注 AI/Agent 行业方向的人）意味着什么 |
| `topics` | 2–4 个中文名词短语，优先复用已有标签写法 |
| `importance` | 1–5；5 = 行业级大事，4 = 重要产品/模型/融资，3 = 常规，2 = 边缘，1 = 几乎不相关 |
| `category` | `tech` / `finance`；AI 为主，金融只收与科技公司/融资/IPO 强相关的 |

### 3.2 质量约束

- **不编造**：数字、引语、公司名必须能在 `content` 里找到。
- 正文不足以支撑 `detail` 时（少于 200 字），`detail` 可为空，宁可短。
- 与 AI / Agent / 开发者工具 / 科技公司资本事件无关的条目直接丢弃（不写回）。
- 同一事件被多个源报道时，**先各自写回，再用 merge 合并**（见 §5.4），不要在 stage B 里自己吞掉。
- `source_url` 原样保留 runner 的 `url`；不要加追踪参数。

### 3.3 建议提示词（可调整）

```text
你是科技新闻编辑，读者关注 AI / Agent 行业动向与科技公司资本事件。
下面是同一批抓取结果（JSON）。请逐条输出：

1. summary：1–2 句中文，≤120 字，只陈述事实；
2. detail：2–5 段中文，≤1200 字，补充正文里的关键数字、人物、时间线、技术细节；
3. impact：1 句中文，≤60 字，说明对读者的影响；
4. topics：2–4 个中文名词短语；
5. importance：1–5；
6. category：tech 或 finance。

硬性要求：
- 只能使用 content 中出现的信息，禁止补写、推测、编造。
- content 少于 200 字时 detail 可以留空。
- 与 AI / Agent / 开发者工具 / 科技公司资本事件无关的条目返回 {"skip": true}。
- 输出 JSON 数组，每项包含 title、url、summary、detail、impact、topics、importance、category。
```

---

## 4. 写回 selfsec —— 消息新增 / 修改 / 删除 / 合并

### 4.1 批量新增 / 更新（幂等）

```http
POST /api/ingest/messages
X-API-Token: <token>

{
  "task_id": "tsk_xxx",
  "items": [
    {
      "source_key": "qbitai",
      "source_name": "量子位",
      "title": "刚刚，Anthropic 公开 335 页招股书",
      "summary": "Anthropic 递交招股书，披露 335 页财务与风险信息……",
      "detail": "第一段……\n\n第二段……",
      "impact": "AI 公司上市窗口打开，估值锚点将被重估。",
      "category": "tech",
      "topics": ["Anthropic", "IPO"],
      "importance": 5,
      "source_url": "https://www.qbitai.com/2026/10/505551.html",
      "published_at": "2026-10-27 00:06:31",
      "content": "正文纯文本（可选，用于回溯）",
      "fetch_level": "L1",
      "raw_hash": "sha256:...",
      "batch_id": "tsk_xxx"
    }
  ]
}
```

返回：

```json
{
  "accepted": 1, "created": 1, "updated": 0, "skipped": 0,
  "event_ids": ["evt_xxx"], "errors": []
}
```

幂等规则（**重跑任务不会产生重复卡片**）：

- 以 `source_url` 规范化后的 URL 作为 `dedup_key`；没有 URL 时用 `title`。
- 同一 key + `raw_hash` 相同 → `skipped +1`，不重写。
- 同一 key + 内容变化 → `updated +1`，覆盖标题/摘要/详情等字段，**保留 `status`**（用户已读/隐藏不会被重跑打回 `new`）。
- 新 key → 新建 `events(source=hermes)` + 一条 `messages(kind=insight)`。
- 批量里有坏条目不会中断整批，错误进 `errors`。

**只写 Hermes 自己的数据**：不会碰用户自己记的事件。

### 4.2 列表 / 单条

```http
GET /api/ingest/messages?limit=100&source_key=qbitai&include_hidden=false
GET /api/ingest/messages/{event_id}
```

返回 `MessageOut`：`event_id / message_id / title / summary / detail / source_url / source_name / source_key / category / topics / impact / importance / published_at / status / tags / created_at / updated_at`。

### 4.3 修改

```http
PATCH /api/ingest/messages/{event_id}
X-API-Token: <token>

{
  "title": "新标题",
  "summary": "新总结",
  "detail": "新详情",
  "impact": "新影响",
  "category": "finance",
  "topics": ["OpenAI", "融资"],
  "importance": 4,
  "status": "read",
  "source_url": "https://..."
}
```

- 只传要改的字段；`status` 可设 `new / read / hidden`。
- 改 `source_url` 会同步重算 `dedup_key`。
- `404` = 没有这条（或不是 Hermes 写的）。

### 4.4 合并重复

```http
POST /api/ingest/messages/merge
X-API-Token: <token>

{
  "primary_id": "evt_primary",
  "duplicate_ids": ["evt_dup1", "evt_dup2"],
  "title": "可选：合并后的标题"
}
```

行为：

- `primary_id` 保留并更新；重复项的标签/主题/详情并入主条，重复项 id 记进 `merged_from`；
- 重复项的 `events` 与消息被删除（它们是 Hermes 数据，不涉及用户记录）；
- 返回合并后的 `MessageOut`；
- `primary_id` 或任一 `duplicate_ids` 不存在 → `404`，整次操作不生效。

**什么时候合并**：同一事件、不同源的报道（例如机器之心 + 量子位都写同一场发布会）在各自写回之后，
由 skill 的最后一步按 `title` 相似度 + 正文实体判断，调用 merge。宁可不合并，也不要合并不同事件。

### 4.5 删除

```http
DELETE /api/ingest/messages/{event_id}
```

返回 `{"ok": true}`。只删 Hermes 来源的消息。

---

## 5. 收尾

```http
POST /api/ingest/tasks/{task_id}/finish
X-API-Token: <token>

{
  "status": "succeeded",
  "error": null,
  "stats": {"sources": 5, "found": 46, "written": 18, "merged": 2}
}
```

- `status`：`succeeded` / `partial` / `failed`。部分源失败必须报 `partial`，不要谎报成功。
- selfsec 会按运行的实际情况再校正一次：全部 run 失败 → `failed`，有失败 → `partial`。
- **无论成功失败都要 finish**；否则任务永远停在 `running`，工作台上看得到、但再也不会被领取。

## 6. 失败处理

| 情况 | 做法 |
|---|---|
| 某个源抓取失败 | runner 已自动上报该源的 `runs(status=failed)`；继续跑其他源；最终 `partial` |
| 全部源失败 | runner 退出码 1；仍要 `finish(status=failed, error=摘要)` |
| LLM 调用失败 | 用 runner 的原始 `summary` 写回（`detail` 留空），任务记 `partial`，**不要重试到超时** |
| 写回接口 5xx | 指数退避重试 2 次（1s / 3s）；仍失败则 `finish(partial)` 并把 `event_ids` 已写入的保留 |
| 任务被取消 / 409 | 立即停止，不写回 |
| 没有任务 | 正常空跑，退出码 0 |

**禁止**：在无 TTY 环境里调用交互式 agent / 等待人工输入（历史事故见
`docs/采集-历史排查-opencode.md`）；禁止无限重试；禁止跳过 `finish`。

---

## 7. 五个源与降级链

| key | 名称 | 当前主链路 | 说明 |
|---|---|---|---|
| `jiqizhixin` | 机器之心 | L0 官方 JSON（列表 + 详情） | `article_library/articles.json` |
| `qbitai` | 量子位 | L0 WordPress RSS + L1 文章页 | 正文选择器 `.content` |
| `infoq` | InfoQ | L0 RSS + L1 文章页 | RSS 摘要常是「点击查看原文」，需抓正文 |
| `aiera` | 新智元 | L0 WP RSS + WP REST 详情 | 页面是 JS 壳，正文取 `content.rendered` |
| `github` | GitHub | L0 Search API | 每个 topic 单独查后合并；可选 `GITHUB_TOKEN` |

降级顺序（站点改版时逐级下探，**能用 L0 就不要上浏览器**）：

```
L0   RSS / Atom / sitemap / 官方 JSON API
L1   httpx + BeautifulSoup
L1.5 curl_cffi（TLS 指纹伪装）
L2   Playwright（无头 Chromium）
L3   Camoufox（反检测浏览器，最后手段）
```

- 降级不是自动乱试：源配置里写清 `kind` 和选择器，`allow_render` 控制是否允许 L2。
- 新源接入 = 在工作台加一条配置；不要在 skill 里写站点专用代码。
- 某个源长期失效：工作台 `enabled=false`，主链路不受影响。

---

## 8. 常用命令速查

```bash
# 领任务（pull）
curl -sS -H "X-API-Token: $SELFSEC_API_TOKEN" \
  "$SELFSEC_API_BASE/api/ingest/tasks/next?worker=hermes"

# 跑抓取
cd "$SELFSEC_BACKEND_DIR"
python -m app.ingest.runner --task-id "$TASK_ID" --out "../.hermes/ingest-$TASK_ID.json"

# 单源调试
python -m app.ingest.runner --source qbitai --out ../.hermes/qbitai.json

# 查任务执行情况
curl -sS -H "X-API-Token: $SELFSEC_API_TOKEN" \
  "$SELFSEC_API_BASE/api/ingest/tasks/$TASK_ID"

# 收尾
curl -sS -X POST -H "X-API-Token: $SELFSEC_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"succeeded","stats":{}}' \
  "$SELFSEC_API_BASE/api/ingest/tasks/$TASK_ID/finish"
```

工作台：`$SELFSEC_API_BASE/workbench`（`X-Workbench-Password`，与 `API_TOKEN` 分开）。
