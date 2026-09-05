# CLAUDE.md

本文件为 Claude Code 在本仓库工作提供指引。

## 项目概述

**Life Secretary** —— 个人生活工作台（单用户）。通过聊天文本记录生活与财务，LLM（DeepSeek，OpenAI 兼容 SDK）自动解析为结构化事件与收支记录，并以看板、周趋势、日报形式呈现。

- **架构极简**：FastAPI 同时提供 API 和前端静态页，无独立前端工程、无构建步骤
- `backend/app/`：FastAPI (async) + SQLAlchemy 2.0 + MySQL（asyncmy）
- `backend/static/`：前端（原生 HTML + CSS + JS 单页，3 个视图：记录/秘书/洞察，PWA 可添加到主屏幕）
- 历史说明：原 Expo/React Native 前端已废弃删除（git 历史中可找回），如需恢复勿基于它继续开发

## 常用命令

```bash
# 后端（Windows 用 conda 环境 life-secretary，Python 3.11；仓库根 venv/ 已废弃为空壳）
#   python 路径：%USERPROFILE%\.conda\envs\life-secretary\python.exe
pip install -r backend/requirements.txt
# 配置在 backend/.env（参考 backend/.env.example）：
#   DATABASE_URL / OPENAI_API_KEY / OPENAI_MODEL / API_TOKEN
mysql life_secretary < backend/mock_data.sql   # 本地首次需灌种子数据（含固定用户 Alice）；docker 部署自动灌

cd backend && python startup.py                # 启动（DB 检查 + 自动建表 + uvicorn）
# 或 python -m uvicorn app.main:app

docker compose up -d --build                   # 远程部署：api + mysql 两容器，端口 8000，首次自动建表+灌种子
```

- 无测试、无 lint 配置、无 CI；改完直接启动验证
- 手机访问：浏览器打开 `http://<服务器IP>:8000`；HTTPS 环境下可安装为 PWA（manifest + sw.js 已就绪，HTTP 下 service worker 会被浏览器禁用，属正常降级）

## 架构要点

- `app/main.py`：lifespan 自动建表（无 Alembic，改模型需手动改表或重建库）；所有 API 路由挂 `verify_token` 依赖；`/` 挂载 StaticFiles(html=True) 托管前端
- **鉴权**：单固定 token——环境变量 `API_TOKEN` 非空时，所有 `/api/*` 请求必须带 `X-API-Token` 头，否则 401；为空则跳过（本地开发）。前端遇 401 弹窗索要并存 localStorage
- **单用户**：`services/deps.py` 硬编码 `DEFAULT_USER_ID`（Alice），`users` 表仅作外键锚点，无注册/登录
- 分层：`api/`（路由）→ `services/`（业务）→ `models/`（5 表）+ `schemas/`（Pydantic）
- AI 调用集中在 `services/ai/`：`client.py`（AsyncOpenAI 单例）、`event_parser.py`（temp=0.1，json_object）、`finance_parser.py`
- 核心数据流：`POST /api/events` → `parse_event` 抽取 → `detect_finance_intent` 命中则二次调用 `parse_finance` → 同事务写 `finance_txns`
- 前端无框架无构建：`static/index.html`（结构）+ `styles.css`（主题变量同原 RN 配色）+ `app.js`（hash 路由 + fetch，`X-API-Token` 统一注入）

## API 端点（全部需要 X-API-Token，若启用）

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/events` | 创建事件（AI 抽取，命中财务意图时联动生成流水） |
| GET | `/api/events?page=&page_size=` | 事件分页列表 |
| DELETE | `/api/events/{id}` | 删除事件 |
| POST | `/api/finance/txns` | 创建财务（AI 解析） |
| GET | `/api/finance/txns?page=` | 流水列表 |
| DELETE | `/api/finance/txns/{id}` | 删除流水 |
| GET | `/api/finance/summary` | 本月流入/流出/净额 |
| GET | `/api/insights?category=&page=` | 洞察列表（只读，种子数据） |
| GET | `/api/insights/{id}` | 洞察详情 |
| GET | `/api/digests/latest` | 最新日报（只读，种子数据） |
| GET | `/api/digests?date=` | 按日期查日报 |
| GET | `/api/board/today` | 今日看板聚合 |
| GET | `/api/memory/trends?days=` | 按类型/情感的趋势统计 |
| GET | `/api/memory/weekly` | 本周图表数据（运动/睡眠/热量/心情/事件） |
| GET | `/api/memory/review?date=` | 指定日期回顾 |
| GET | `/health` | 健康检查（无鉴权） |

## 已知限制 / 注意点

1. **insights / digests 无写入入口**：两表只靠 `mock_data.sql` 种子；日报/洞察 AI 自动生成未实现
2. **语音录入已移除**：原 voice 路由有 bug 且前端未使用，已删除；浏览器方案需 HTTPS 才能用麦克风，将来要做时需先上 HTTPS
3. **无迁移工具**：改 `models/` 字段需手动 ALTER 或删库重建；Docker 初始建表 SQL 由 `backend/gen_schema.py` 生成（`cd backend && python gen_schema.py` → `docker-init/01-schema.sql`），改模型后需重新生成
4. **secrets 曾入库**：旧 config.py 硬编码过 DB 密码与 DeepSeek key（仍在 git 历史），现值已移至 `backend/.env`（gitignored），建议轮换 key
5. `docker-compose.yml` 内 MySQL 密码为明文默认值（仅容器内网可用，3306 未对宿主机暴露），个人部署可接受；OPENAI_API_KEY / API_TOKEN 经 `env_file` 注入 `backend/.env`，不进镜像

## 约定

- 注释与文档以中文为主，标识符用英文
- 后端遵循 api → services → models/schemas 分层；AI prompt 与解析逻辑只放在 `services/ai/`
- 前端保持零依赖零构建：不引入框架/打包器；样式统一用 `styles.css` 的 CSS 变量，不要硬编码颜色
- 响应错误保持 `{"detail": "..."}` 风格
