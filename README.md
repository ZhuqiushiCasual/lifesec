# selfsec

一个只有聊天窗口的个人秘书。

你说的话会被记住，并且得到回应；外部的重要消息会主动找上门。

## 它解决什么

大部分记录类工具的死因不是"输入麻烦"，而是**记完没有任何东西回来**。
selfsec 的设计约束只有一条：**每次输入都必须换来一句话**——这句话里要有记忆
（"这周第三次，比上周多"），而不是一张趋势图。

- **记录 + 规划**：说一句就记下；提到待办就生成可勾选的事项
  同一天的重复 / 补充会**合并成一条**事件（不重复堆记录），并自动贴上标签（运动 / 心事 / 加班…）
- **问候**：早晚各一次，固定议程三问，不是自由聊天
- **洞察**：Hermes 抓来的行业动态，以卡片形式出现在同一个窗口里

## 快速开始

```bash
cd backend
pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt   # 直连 pypi.org 在国内很慢
cp .env.example .env        # 填 OPENAI_API_KEY；不填 DATABASE_URL 就走本地 SQLite
python startup.py           # http://localhost:8000
```

零配置起步：默认 SQLite，表结构和用户自动创建。
生产用 MySQL 时把 `DATABASE_URL` 换成 `mysql+asyncmy://...`。

端到端冒烟测试（用独立 SQLite，不碰你的库）：

```bash
cd backend && python smoke_test.py
```

## 架构

```
聊天窗口 ─┐
定时触发 ─┼→ POST /api/chat → Context 组装 → LLM → 一句话回应 + 卡片
Hermes  ─┘                     ↑
                          记忆层（四层）
                       4.1 长期画像  慢变，走 LLM，定期/阈值触发
                       4.2 事实统计  实时，纯 SQL，提供"比较"
                       4.3 洞察记忆  外部驱动
                       4.4 会话短期  最近 N 轮，指代消解
```

- **唯一入口**：`POST /api/chat`。记录、规划、问候走的都是同一条管道
- **唯一输出形式**：一句话 + 卡片。卡片出现在窗口内，不另开页面
- **一次 LLM 调用**：意图判定、字段抽取、生成回应在同一次调用里完成

详细设计见 `docs/PRD-v2.md`，架构图见 `docs/架构-v1.html`。

## 技术栈

| 层 | 技术 |
|---|---|
| Web | FastAPI (async) + Uvicorn |
| ORM / DB | SQLAlchemy 2.0 · SQLite（默认）/ MySQL |
| 模型 | DeepSeek（OpenAI 兼容 SDK） |
| 前端 | 原生 HTML + CSS + JS，零依赖零构建 |
| 调度 | 内置 asyncio 循环，无第三方调度库 |

## 边界（明确不做）

自由多轮陪聊 · 自建抓取管线 · 趋势图表 / 日报评分 · 多用户 / 登录 · 语音输入
