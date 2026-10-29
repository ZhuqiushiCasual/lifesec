# Hermes · 新闻任务（selfsec 洞察线的生产者）

> **2026-10-27 更新**：采集链路已落地为「selfsec 控制面 + Hermes 执行面」。
> 现行接入方式以 **`hermes/skills/selfsec-news/SKILL.md`** 与 **`hermes/README.md`** 为准：
> 工作台/调度创建任务 → Hermes claim → `python -m app.ingest.runner` 确定性抓取 →
> LLM 生成总结/详情/影响 → `POST /api/ingest/messages` 写回。
> 本文保留为**历史背景**（旧版「agent 自己搜索 + 总结」与单条 `/api/insights` 回调），
> `/api/insights` 仍兼容，但新链路不再使用它。

> **职责边界**：抓取 / 筛选 / 去重由 Hermes 负责；selfsec 只接收结果、落库、生成洞察卡。
> 本文件是从已删除的 `backend/import_news.py` 中抽出的 prompt 与接口约定，供配置 Hermes 定时任务时使用。
>
> **已被取代的部分（2026-10-25 追记）**：本文的"agent 自己搜索 + 总结"链路，工程问题见
> `docs/采集-历史排查-opencode.md` —— prompt 没有源清单（来源随机、不可复现），且服务器上的
> `import_news.py --daemon` 在无 TTY 环境里 33 万次调用 opencode 全部失败（EBADF）、空转 121 天。
> 采集层的替代设计见 `docs/采集-技术选型对比.md`。**回调接口 `POST /api/insights` 本身仍然有效**，
> 需要改的只是上游怎么产出数据。

---

## 1. 定时任务（Hermes cron）

建议频率：每天 07:00 一次。

## 2. 研究 prompt（交给 Hermes）

```
使用 anysearch 研究今天的金融新闻和 AI 新闻，总结输出为 json 格式。

要求:
1. 搜索今天({today})发布的金融(finance)和 AI(tech) 领域重要新闻
2. 每个类别各找最重要的 5-8 条
3. 每条新闻包含: title、summary、impact(对用户的影响分析)、category(finance 或 tech)、
   topics(标签数组)、importance(1-5)、source_url、source_name、published_at
   published_at 格式: %Y-%m-%d %H:%M:%S

   示例:
   [
     {
       "title": "OpenAI 发布 GPT-5.5-Cyber：AI 漏洞发现速度超越人类",
       "summary": "OpenAI ...",
       "impact": "...",
       "category": "tech",
       "topics": ["AI安全"],
       "importance": 5,
       "source_url": "https://...",
       "source_name": "Times Now",
       "published_at": "2026-06-23 08:49:00"
     }
   ]
```

> 用户的关注点是 **AI / Agent 行业动向**（跳槽方向），金融类重要性低于技术类，
> 股票行情线已决定后续抛弃——筛选时应向 AI/Agent 倾斜。

## 3. 回调 selfsec

对每条新闻调用一次（或批量，见接口定义）：

```
POST http://<selfsec-host>:8000/api/insights
X-API-Token: <API_TOKEN>

{
  "title": "...",
  "summary": "...",
  "impact": "...",
  "category": "tech",
  "topics": ["AI安全"],
  "importance": 5,
  "source_url": "https://...",
  "source_name": "Times Now",
  "published_at": "2026-06-23 08:49:00"
}
```

selfsec 侧行为：
1. 写入 `events`（`source=hermes`, `type=insight`）
2. 生成一条 `messages`（`kind=insight`）→ 出现在聊天窗口的洞察卡
3. 同一条 `source_url` 重复推送时按幂等处理（不重复生成卡片）

## 4. 参考：旧实现

旧实现是 `backend/import_news.py`（opencode + anysearch 研究 → 写 JSON → 直连 MySQL 写 `insights` 表），
已删除。区别在于：**旧实现直连数据库，新实现只走 HTTP 接口**——
selfsec 不关心数据怎么来的，只接受一个标准回调。
