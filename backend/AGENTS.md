# Life Secretary 后端架构说明

> 更新：2026-09-01。原 Expo/RN 前端已移除，后端同时托管 API 与静态前端页面。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| Web 框架 | FastAPI (async) | `app/main.py` 注册路由 + 挂载静态页， lifespan 自动建表 |
| ORM | SQLAlchemy 2.0 (async) | `app/database.py`, DeclarativeBase |
| 数据库 | MySQL | 驱动 `asyncmy`, 库名 `life_secretary` |
| AI | OpenAI SDK → DeepSeek | `api.deepseek.com`, model `deepseek-v4-pro` |
| 鉴权 | 固定 API Token | 环境变量 `API_TOKEN` 非空时，`/api/*` 需请求头 `X-API-Token`；为空则不校验 |
| 前端 | 原生 HTML+CSS+JS | `static/` 目录, 无构建; PWA(manifest + sw.js) |
| 部署 | Docker + uvicorn | `startup.py` 含 DB 重试 + 建表 |

## 目录结构

```
backend/
├── app/
│   ├── main.py            # FastAPI app, 路由统一挂 verify_token, 静态页挂载
│   ├── config.py          # 环境变量 + .env 加载 (零依赖实现)
│   ├── database.py        # async engine + session + Base
│   ├── api/               # 路由层 (6 个 router)
│   │   ├── events.py      #   事件 CRUD (含 AI 抽取) ★
│   │   ├── finance.py     #   财务 CRUD + summary ★
│   │   ├── insights.py    #   洞察只读查询
│   │   ├── digests.py     #   日报只读查询
│   │   ├── board.py       #   今日看板 (聚合)
│   │   └── memory.py      #   趋势/周报/回顾
│   ├── models/            # ORM 模型 (5 表)
│   ├── schemas/           # Pydantic 校验/响应模型
│   ├── services/
│   │   ├── deps.py        # verify_token (固定 token) + get_current_user (默认用户)
│   │   └── ai/
│   │       ├── client.py          # AsyncOpenAI 单例 (lru_cache)
│   │       ├── event_parser.py    # 事件解析 + 财务意图检测 ★
│   │       └── finance_parser.py  # 财务解析 ★
│   └── static/            # 前端单页 (index.html / styles.css / app.js / manifest / sw.js / icons)
├── mock_data.sql          # 种子数据 (3 用户 + 事件/财务/洞察/日报)
├── requirements.txt
├── Dockerfile
└── startup.py             # 启动: 检查 DB → 建表 → uvicorn
```

## 数据库表与关系

5 张表, 均以 `user_id` 外键关联 `users.id` (1:N), 子表之间无直接关联。

```
users (主表, 实际仅用固定一行 Alice)
 ├── 1:N  events          事件记录
 ├── 1:N  finance_txns    财务收支
 ├── 1:N  insights        信息洞察 (只读)
 └── 1:N  digests         日报总结 (只读)
```

| 表 | 关键字段 | 备注 |
|---|---|---|
| `users` | id(UUID PK), email(UNIQUE), hashed_password, preferences(JSON) | 仅种子/历史注册数据 |
| `events` | user_id(FK), type, content(原文), entities(JSON), sentiment, sentiment_score, tags(JSON), voice_source | AI 抽取写入 |
| `finance_txns` | user_id(FK), type(income/expense), amount(Numeric), currency, category, counterparty, account | AI 抽取写入 |
| `insights` | user_id(FK), title, summary, impact, category, importance(1~5), source_url | **无写入 API**, 仅 mock 种子 |
| `digests` | user_id(FK), date, score(0~100), highlights/problems/suggestions/trends(JSON) | **无写入 API**, 仅 mock 种子 |

## 事件 type 取值

health / dietary / work / social / mood / sport / invest / sleep / event

## AI 抽取流程

### 事件创建路径 (核心)
```
POST /api/events {content}
  → parse_event(content)  [LLM, temp=0.1, json_object]
      输出: type, entities{food/activity/duration/symptom/mood/amount/...},
            sentiment, sentiment_score(0~1), tags[]
  → 写入 events 表
  → detect_finance_intent(parsed, content)
  → 若命中 → parse_finance(content) [LLM 二次调用]
      输出: type, amount, currency, category, counterparty, account
  → 写入 finance_txns 表 (同一事务)
```

### 财务直接路径
```
POST /api/finance/txns {content} → parse_finance → 写入 finance_txns
```

> 语音路径已移除：浏览器麦克风需要 HTTPS，原 `/api/voice/transcribe` 有缺陷且无前端调用。将来启用前需先部署 HTTPS。

## API 端点一览

所有 `/api/*` 在 `API_TOKEN` 非空时需请求头 `X-API-Token`。

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/events` | 创建事件 (AI 抽取, 可联动财务) |
| GET | `/api/events` | 事件列表 (分页) |
| DELETE | `/api/events/{id}` | 删除事件 |
| POST | `/api/finance/txns` | 创建财务 (AI 抽取) |
| GET | `/api/finance/txns` | 财务列表 |
| DELETE | `/api/finance/txns/{id}` | 删除财务 |
| GET | `/api/finance/summary` | 本月流入/流出/净额 |
| GET | `/api/insights` | 洞察列表 (可按 category 筛选) |
| GET | `/api/insights/{id}` | 洞察详情 |
| GET | `/api/digests/latest` | 最新日报 |
| GET | `/api/digests?date=` | 按日期查日报 |
| GET | `/api/board/today` | 今日看板 (聚合 events+insights+digests) |
| GET | `/api/memory/trends?days=` | 趋势统计 (事件类型/情感) |
| GET | `/api/memory/weekly` | 本周图表 (运动/睡眠/热量/心情/事件) |
| GET | `/api/memory/review?date=` | 指定日期事件回顾 |
| GET | `/health` | 健康检查 (无鉴权) |
| GET | `/` | 前端静态页 (StaticFiles) |

## 已知限制

- **insights / digests 无写入入口**: 只能靠 `mock_data.sql` 灌入, AI 自动生成日报/洞察未实现
- **无迁移工具**: 表结构靠 `Base.metadata.create_all`, 无 Alembic
- **secrets 曾硬编码入库**: 旧版本 config.py 内置过 DB 密码/API key (git 历史可见), 现已移至 `.env`, 建议轮换

## 开发命令

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量 (config.py 会自动读取 backend/.env)
cp .env.example .env  # 填入 DATABASE_URL / OPENAI_API_KEY / API_TOKEN

# 灌入种子数据
mysql life_secretary < mock_data.sql

# 启动 (含 DB 检查 + 建表)
python startup.py

# 或 Docker
docker compose up --build   # 仓库根目录, 端口 8000
```
