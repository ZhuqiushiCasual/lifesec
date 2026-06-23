# Life Secretary 后端架构说明

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| Web 框架 | FastAPI (async) | `app/main.py` 注册路由, lifespan 自动建表 |
| ORM | SQLAlchemy 2.0 (async) | `app/database.py`, DeclarativeBase |
| 数据库 | MySQL | 驱动 `asyncmy`, 库名 `life_secretary` |
| AI | OpenAI SDK → DeepSeek | `api.deepseek.com`, model `deepseek-v4-pro`, Whisper-1 语音转写 |
| 认证 | 自研 HMAC-SHA256 Token | 非 JWT, 30 天过期; 密码 SHA-256+salt (`app/services/auth.py`) |
| 部署 | Docker + uvicorn | `startup.py` 含 DB 重试 + 建表 |

## 目录结构

```
backend/
├── app/
│   ├── main.py            # FastAPI app, 路由注册, lifespan 建表
│   ├── config.py          # 环境变量配置 (Settings)
│   ├── database.py        # async engine + session + Base
│   ├── api/               # 路由层 (8 个 router)
│   │   ├── auth.py        #   注册/登录
│   │   ├── voice.py       #   语音转写 + 意图识别 ★
│   │   ├── events.py      #   事件 CRUD (含 AI 抽取) ★
│   │   ├── finance.py     #   财务 CRUD + summary/assets ★
│   │   ├── insights.py    #   洞察只读查询
│   │   ├── digests.py     #   日报只读查询
│   │   ├── board.py       #   今日看板 (聚合)
│   │   └── memory.py      #   趋势/回顾
│   ├── models/            # ORM 模型 (5 表)
│   ├── schemas/           # Pydantic 校验/响应模型
│   └── services/
│       ├── auth.py        # 密码哈希 + Token 签发/校验
│       ├── deps.py        # get_current_user (当前硬编码默认用户)
│       └── ai/
│           ├── client.py          # AsyncOpenAI 单例 (lru_cache)
│           ├── event_parser.py    # 事件解析 + 财务意图检测 ★
│           └── finance_parser.py  # 财务解析 ★
├── mock_data.sql          # 种子数据 (3 用户 + 事件/财务/洞察/日报)
├── requirements.txt
├── Dockerfile
└── startup.py             # 启动: 检查 DB → 建表 → uvicorn
```

## 数据库表与关系

5 张表, 均以 `user_id` 外键关联 `users.id` (1:N), 子表之间无直接关联。

```
users (主表)
 ├── 1:N  events          事件记录 (语音/文字输入, AI 抽取)
 ├── 1:N  finance_txns    财务收支
 ├── 1:N  insights        信息洞察 (只读)
 └── 1:N  digests         日报总结 (只读)
```

| 表 | 关键字段 | 备注 |
|---|---|---|
| `users` | id(UUID PK), email(UNIQUE), hashed_password, preferences(JSON) | 注册写入 |
| `events` | user_id(FK), type, content(原文), entities(JSON), sentiment, sentiment_score, tags(JSON), voice_source | AI 抽取写入 |
| `finance_txns` | user_id(FK), type(income/expense), amount(Numeric), category, counterparty, account | AI 抽取写入 |
| `insights` | user_id(FK), title, summary, impact, category, importance(1~5), source_url | **无写入 API**, 仅 mock 种子 |
| `digests` | user_id(FK), date, score(0~100), highlights/problems/suggestions/trends(JSON) | **无写入 API**, 仅 mock 种子 |

## 数据分类 (4 类)

1. **生活事件 (events)** — type: health / dietary / work / social / mood / sport / invest / event
2. **财务记录 (finance_txns)** — type: income / expense / asset / liability; category: food / transport / salary / rent / shopping / medical / invest_* / real_estate / cash / other
3. **信息洞察 (insights)** — category: tech / finance / health / career (外部知识/文章摘要)
4. **日报总结 (digests)** — 每日生活评分 + 亮点/问题/建议/趋势

## 数据生成方式

| 数据 | 生成方式 |
|---|---|
| users | 注册 API (`POST /api/auth/register`) |
| events | 用户文字/语音 → `POST /api/events` → AI `parse_event` 抽取结构化字段 |
| finance_txns | ① 直接 `POST /api/finance/txns` → AI `parse_finance`; ② 事件创建时若 `detect_finance_intent()=True` 自动二次调用 finance_parser 联动生成 |
| insights | **无写入 API**, 仅 `mock_data.sql` 种子数据 |
| digests | **无写入 API**, 仅 `mock_data.sql` 种子数据 (设计预期: AI 汇总当日事件自动生成, 尚未实现) |

## AI 抽取流程

### 语音路径
```
audio(base64) → /api/voice/transcribe
  → Whisper-1 转文字
  → LLM 意图分类: "life" | "finance"
  → 返回 text + intent (前端据此路由)
```

### 事件创建路径 (核心)
```
POST /api/events {content}
  → parse_event(content)  [LLM, temp=0.1, json_object]
      System Prompt 定义输出结构:
        type, entities{food/activity/symptom/mood/amount/currency/...},
        sentiment, sentiment_score(0~1), tags[]
  → 写入 events 表
  → detect_finance_intent(parsed):
      type=="invest" OR (entities.amount!=null AND entities.category!=null)
  → 若 True → parse_finance(content) [LLM 二次调用]
      输出: type, amount, currency, category, counterparty, account
  → 写入 finance_txns 表 (同一事务)
```

### 财务直接路径
```
POST /api/finance/txns {content}
  → parse_finance(content) → 写入 finance_txns
```

## API 端点一览

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/voice/transcribe` | 语音转写 + 意图识别 |
| POST | `/api/events` | 创建事件 (AI 抽取, 可联动财务) |
| GET | `/api/events` | 事件列表 (分页) |
| DELETE | `/api/events/{id}` | 删除事件 |
| POST | `/api/finance/txns` | 创建财务 (AI 抽取) |
| GET | `/api/finance/txns` | 财务列表 |
| DELETE | `/api/finance/txns/{id}` | 删除财务 |
| GET | `/api/finance/summary` | 月度收支汇总 |
| GET | `/api/finance/assets` | 资产分布 (返回空占位) |
| GET | `/api/insights` | 洞察列表 (可按 category 筛选) |
| GET | `/api/insights/{id}` | 洞察详情 |
| GET | `/api/digests/latest` | 最新日报 |
| GET | `/api/digests?date=` | 按日期查日报 |
| GET | `/api/board/today` | 今日看板 (聚合 events+insights+digests) |
| GET | `/api/memory/trends` | 趋势统计 (按天, 事件类型/情感) |
| GET | `/api/memory/review?date=` | 指定日期事件回顾 |
| GET | `/health` | 健康检查 |

## 已知问题与注意点

- **认证未生效**: `app/services/deps.py` 的 `get_current_user` 硬编码返回 `DEFAULT_USER_ID`, 不校验 Token。所有需登录的接口实际操作的是固定用户 Alice (`u001...001`)。
- **voice.py 缺少 import**: `transcribe_voice` 使用了 `settings` 但未导入 (`from app.config import settings`), 运行会报 NameError。
- **insights / digests 无写入入口**: 两张表只能通过 `mock_data.sql` 灌入, 缺少 AI 自动生成日报/洞察的逻辑。
- **assets 接口返回空**: `/api/finance/assets` 和 summary 的 `total_assets`/`net_assets` 均返回 0, 资产统计尚未实现。
- **无迁移工具**: 表结构靠 `Base.metadata.create_all` 自动创建, 无 Alembic 迁移。

## 开发命令

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env  # 填入 DATABASE_URL / OPENAI_API_KEY

# 灌入种子数据
mysql life_secretary < mock_data.sql

# 启动 (含 DB 检查 + 建表)
python startup.py

# 或 Docker
docker build -t life-secretary-backend .
docker run -p 8000:8000 life-secretary-backend
```
