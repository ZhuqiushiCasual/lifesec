# Hermes 接入说明

selfsec 负责**控制面**（源配置、任务、执行记录、消息展示），Hermes 负责**执行面**（抓取 + 生成）。
本目录放 Hermes 侧要用的 skill 与配置。

```
selfsec 工作台 ──queued task──▶ Hermes webhook ──▶ skill: selfsec-news
       ▲                                              │
       │                                              ├─ stage A：python -m app.ingest.runner
       └────── POST /api/ingest/messages ◀────────────┤
       └────── POST /api/ingest/tasks/{id}/finish ◀───┘
```

## 1. 安装 skill

把 `skills/selfsec-news/` 整个目录放到 Hermes 的 skills 目录（具体路径见 Hermes 文档），
确保 `SKILL.md` 的 frontmatter（`name` / `description`）能被加载。

skill 内已经写清：

- L0–L3 降级链与五个源；
- stage A runner 命令；
- stage B 摘要/详情/影响生成规范；
- **消息新增 / 修改 / 删除 / 合并 API**；
- 失败处理与任务收尾。

## 2. selfsec 侧配置

`backend/.env`：

```dotenv
# 任务下发（push）。不配也能用 pull。
HERMES_WEBHOOK_URL=http://<hermes-host>:<port>/webhook
HERMES_WEBHOOK_SECRET=<与 Hermes 侧一致>

# Hermes 回调 selfsec 的地址（返回到 claim 响应里）
SELFSEC_PUBLIC_URL=http://<selfsec-host>:8000

# 每日任务（服务器本地时间）
INGEST_ENABLED=1
INGEST_HOUR=7
INGEST_MINUTE=10
INGEST_LOOKBACK_HOURS=36

# 工作台密码（与 API_TOKEN 分开）
WORKBENCH_PASSWORD=<只给你自己看的密码>
```

## 3. Hermes 侧环境

```dotenv
SELFSEC_API_BASE=http://<selfsec-host>:8000
SELFSEC_API_TOKEN=<selfsec 的 API_TOKEN>
SELFSEC_BACKEND_DIR=/path/to/selfsec/backend
DATABASE_URL=<与 selfsec 相同的数据库连接串>
# 可选：GitHub Search API 限额
GITHUB_TOKEN=<token>
```

Hermes 机器需要能：

1. 访问 selfsec API（`SELFSEC_API_BASE`）；
2. 访问五个源站点；
3. 读取 selfsec 的数据库（runner 从 `ingest_sources` 读源配置）。
   如果 Hermes 不能读库，就让它跑在 selfsec 同机，或给 runner 一个只读库账号。

## 4. webhook 接收与验签

selfsec 发出的请求：

```http
POST <HERMES_WEBHOOK_URL>
Content-Type: application/json
X-Webhook-Timestamp: 1793000000
X-Webhook-Signature-V2: <hex>

{"event":"selfsec.ingest.task","task_id":"tsk_xxx","task":{...},"api_base":"...","hint":"..."}
```

验签（Python）：

```python
import hmac, hashlib, time

def verify(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    message = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**注意**：签名算的是 **原始 body 字节**，不要先 `json.loads` 再 `json.dumps`——键顺序/空格会变。

收到 `event == "selfsec.ingest.task"` 后：

1. 立即返回 `200`（不要同步跑采集，任务可能几分钟）；
2. 后台调用 skill，把 `task_id` 传进去；
3. skill 自己 `claim` → runner → 写回 → `finish`。

## 5. pull 兜底（推荐同时开）

Hermes cron（每 10–15 分钟）：

```cron
*/10 * * * * cd /path/to/hermes && /path/to/hermes run selfsec-news --task-source pull >> /var/log/hermes-selfsec.log 2>&1
```

或让 skill 自己执行：

```bash
curl -sS -H "X-API-Token: $SELFSEC_API_TOKEN" \
  "$SELFSEC_API_BASE/api/ingest/tasks/next?worker=hermes"
```

- 返回 `{"task": null}` → 退出码 0，不告警。
- selfsec 的 push 失败会把任务留在 `queued`，下一次 pull 自动捡走——**整条链路不需要人工重试**。

## 6. 验收清单

- [ ] 工作台 `/workbench` 能看到五个源，且 `enabled=true`
- [ ] 工作台「立即下发」后，任务状态从 `queued → dispatched → running → succeeded`
- [ ] `GET /api/ingest/tasks/{id}` 的 `runs` 每个源都有 `fetch_level` 与条数
- [ ] 前台窗口出现洞察卡：**总结**在卡片上、**详情**在弹层里、**原文链接**可点
- [ ] 同一天重跑同一任务，`created` 为 0（幂等），用户已读状态不被重置
- [ ] 故意关掉一个源（`enabled=false`）重跑，任务 `partial` 而不是整体失败

## 7. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 任务一直 `queued` | 没配 webhook，且 Hermes 的 pull 没在跑；检查 cron 与 `API_TOKEN` |
| `claim` 返回 `409` | 任务已被领走 / 已结束；不要抢，领下一个 |
| 任务停在 `running` | skill 没有调 `finish`；补一次 finish，或工作台取消后重试 |
| 某个源一直失败 | 先在工作台看 `last_error`；站点改版就改 `config` 选择器，或暂时 `enabled=false` |
| 消息重复 | 检查 `source_url` 是否被加了追踪参数；canonical URL 会去掉 `utm_*` / `spm` 等 |
| 前台看不到详情 | 检查写回时是否传了 `detail`；卡片只放 summary，详情在弹层 |
