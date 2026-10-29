# 采集层历史排查：opencode 新闻守护进程（2026-06 → 2026-10）

> 排查时间 2026-10-25 ｜ 目标机 `8.136.46.200`（阿里云 ECS）｜ **全程只读**，唯一写操作是经用户批准 `kill` 掉空转进程
> 起因：想找"之前在线上服务器用 Hermes/Agent 爬取过的微信公众号信息"

---

## 0. 结论

1. **这台服务器上从来没有装过 Hermes**。跑过的是 **opencode**（`/root/.config/opencode`、`/root/.local/share/opencode`）。记忆里的"Hermes 定时任务"实际是 `import_news.py --daemon` + `opencode run`。
2. **没有任何微信公众号数据**。全盘文本搜 `mp.weixin.qq.com` / `公众号` → 0 命中；`life_secretary.insights` 27 行里微信链接 0 条；prompt 与代码里零提及。
3. 真正存在的是 **2026-06-23/24 那批英文外媒新闻**（27 条）。
4. 那条"定时任务"**从 2026-06-26 起一次都没成功过**：336,491 次调用 opencode，0 次成功，日志 102 MB —— 已停止（见 §6）。

---

## 1. 链路是什么

```
nohup python3 import_news.py --daemon &     # .bash_history:734，2026-06-26 10:54 起
        │
        ├─ 每 30 秒一轮（本意每天 07:00）
        ├─ subprocess: opencode run "<RESEARCH_PROMPT>"     # 600s 超时
        ├─ opencode 用 anysearch 搜索 → 写 ai_news_{date}.json / finance_news_{date}.json 到当前目录
        ├─ 扫当前目录/上级目录的 *_news_{today}.json
        └─ asyncmy INSERT ... ON DUPLICATE KEY UPDATE → life_secretary.insights
```

文件：`/workspace/lifesec/backend/import_news.py`（247 行）
日志：`/workspace/lifesec/backend/nohup.out`（102,293,804 字节）
进程：`PID 131489`，存活 121 天 12 小时（已于 2026-10-25 23:26 停止）

---

## 2. Prompt 原文（这是整条链路的全部"抓取规则"）

```python
RESEARCH_PROMPT = """使用anysearch研究今天的金融新闻和AI新闻，总结输出为json格式。

要求:
1. 搜索今天({today})发布的金融(finance)和AI(tech)领域重要新闻
2. 每个类别各找最重要的 5-8 条
3. 每条新闻包含: title、summary、impact(对用户的影响分析)、category(finance或tech)、topics(标签数组)、importance(1-5)、source_url、source_name、published_at
example:每条新闻的 published_at 格式为: %Y-%m-%d %H:%M:%S
        [
          {{
            "title": "OpenAI 发布 GPT-5.5-Cyber：AI 漏洞发现速度超越人类",
            "summary": "OpenAI ...",
            "impact": "...",
            "category": "tech",
            "topics": ["AI安全"],
            "importance": 5,
            "source_url": "https://...",
            "source_name": "Times Now",
            "published_at": "2026-06-23 08:49:00"
          }}
        ]
4. 分别输出为 ai_news_{today}.json 和 finance_news_{today}.json，保存到当前目录"""
```

这份 prompt 后来被抽成了 `docs/hermes-新闻任务.md` 第 2 节，两处基本一字不差。

---

## 3. 相关网站：**一个都没指定**

prompt 里只有"使用 anysearch 研究今天的金融新闻和AI新闻"，**没有源清单、没有站点白名单、没有 RSS、没有 `site:` 限定**。来源完全由搜索引擎自由发挥。实际落库的来源分布：

| 域名 | 条数 |
|---|---|
| `timesnownews.com` | 4 |
| `example.com`（**测试假数据**） | 3 |
| `byteiota.com` / `scienmag.com` / `thehindu.com` / `cnbc.com` / `en.sedaily.com` / `searchenginejournal.com` | 各 2 |
| `foreignpolicy.com` / `cryptobriefing.com` / `coinmarketcap.com` / `straitstimes.com` / `chosun.com` / `thestar.com.my` / `financial-news.co.uk` / `budgetmodel.wharton.upenn.edu` | 各 1 |

**没有一条中文源。** 这是"不可复现"的根源：同一份 prompt 换一天跑，来源会整体换一批，无法解释"为什么今天推了这条、昨天没有"。

---

## 4. 三个问题

### ① 触发条件被注释掉 → 每 30 秒一轮，不是每天 07:00

```python
    while True:
        now = datetime.now()
        # 每天 07:00 ~ 07:01 之间触发，且当天未执行过
       # if now.hour == 7 and now.minute == 0 and today_done != now.date():
        today_done = now.date()
        await daily_job()          # ← 无条件执行
        await asyncio.sleep(30)    # ← 每 30 秒一轮
```

### ② 336,491 次调用，0 次成功

```
「开始执行 opencode」  336,491
「✅ 每日任务完成」          0
「opencode 执行失败」  336,490
```

失败原因每次都相同 —— opencode 在 nohup 的无 TTY 环境下起不来：

```
opencode 返回非零: 1
stderr: Error: Unexpected error
EBADF: bad file descriptor, read
```

### ③ 日志 102 MB / 336 万行

`nohup.out` 从 2026-06-21 22:53 一直写到 2026-10-25 23:11，混杂了旧栈 uvicorn 的启动日志和 33 万轮报错。

---

## 5. 数据现状（排查期间的盘点）

| 位置 | 内容 |
|---|---|
| `life_secretary.insights` | **27 行**，`published_at` 2026-06-16 ~ 06-24，`created_at` 06-23 16:17 ~ 06-24 09:51 |
| `/workspace/lifesec/backend/ai_news_2026-06-24.json` | 8 条 |
| `/workspace/lifesec/backend/finance_news_2026-06-24.json` | 8 条 |
| `life_secretary.digests` | 2 行（内容为空/未取到） |
| `selfsec.events` | 37 行，**`source` 全部为 `user`** → 新栈从未收到过 `source=hermes` 的洞察 |
| `selfsec.messages` | 102 行（API `filter=insight` 返回空） |

**说明**：新栈的回写入口 `POST /api/insights` 上线至今**没有被真实调用过一次**。上一版"新闻 → 平台"的闭环只存在于旧栈 `life_secretary`。

### 排查过的位置（全部为空）

```
/root/.hermes、hermes 可执行文件、npm 全局        → 不存在（服务器上没装过 Hermes）
docker ps -a                                      → 只有 homebalance / selfsec-api / mysql
crontab -l、/etc/cron.d、systemd timers           → 无新闻相关任务
全盘文件名 *wechat* *gzh* *weixin* *wx_*          → 0
全盘文本 mp.weixin.qq.com / 公众号                → 0（仅命中依赖包）
/root/.local/share/opencode（会话库）              → 搜「微信/公众号」→ 0
本机 Hermes state.db（17 会话 3813 消息）          → 搜 mp.weixin/公众号 → 0
本机 opencode.db                                  → 仅命中无关页面正文
```

**判定：微信公众号数据不在这台服务器，也不在本机。** 最可能是当时在交互式会话里试过、没有落盘；或记混了机器。

---

## 6. 已执行的清理

```bash
kill 131489            # 2026-10-25 23:26
```

验证：

```
进程已退出
40 秒日志增量：0 字节（此前每 30 秒写一轮）
残留 opencode / import_news 进程：无
load average：0.13 / 0.33 / 0.26
```

不会自动重启：没有对应 cron、没有 systemd 单元，当初是手工 `nohup ... &` 起的。

---

## 7. 遗留

- `nohup.out`（102 MB）仍在磁盘上，未归档（内容全是同一条 EBADF 报错）。
- `life_secretary` 库（含 27 条 insights）仍在，属于待弃用的旧栈；如需保留历史，应导出为 JSON 存进仓库 `docs/archive/`。
- `/workspace/lifesec` 整栈已停，数据卷未动，可回滚。

---

## 8. 对新采集设计的启示

1. **没有源清单的采集 = 不可复现**。老 prompt 只给领域不给源，结果就是"今天 Times Now、明天 Scienmag"，无法做变更检测、无法解释推送、无法回归测试。新设计必须走 `sources.yaml`（`docs/采集-技术选型对比.md` §6.2）。
2. **无 TTY 环境里跑交互式 Agent 是死路**。`opencode run` 在 nohup 下 EBADF 挂了 33 万次；同理，Hermes cron 里也不该让 LLM 承担抓取执行体 —— 抓取必须是确定性脚本（§5.5）。
3. **"守护进程里写死时间判断"是脆弱的定时器**。一次注释、一次改时区就变成 30 秒空转 121 天。定时交给 cron / systemd timer（Hermes 侧用 `cronjob`），业务脚本只做单次执行，并保证**幂等 + 失败告警**（0 次成功却持续 4 个月无人发现，就是没有告警）。
