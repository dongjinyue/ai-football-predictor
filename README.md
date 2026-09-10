# AI Football Predictor

竞彩足球概率分析与研究项目。目前只完成项目基础骨架，尚未实现数据采集和预测模型。

## 目录

- `frontend/`：Vite + React + TypeScript + Tailwind CSS 前端。
- `backend/`：FastAPI 后端和健康检查。
- `data/`：原始、过渡和处理后数据的本地目录；实际数据默认不提交。
- `models/`：本地模型产物目录；模型文件默认不提交。
- `tests/`：未来跨模块和端到端测试的根目录。
- `docs/`：设计说明和实施计划。

## 启动后端

```bash
cd backend
python -m venv .venv
```

- `cd backend`：进入后端目录。
- `python -m venv .venv`：让 Python 通过 `-m` 运行内置的 `venv`（虚拟环境）模块，并把隔离环境创建在 `.venv` 目录。

激活虚拟环境后安装依赖：

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

- `pip install`：安装依赖；`-r requirements.txt` 表示从依赖清单读取包名。
- `uvicorn app.main:app`：从 `app/main.py` 导入名为 `app` 的 FastAPI 应用。
- `--reload`：开发时检测代码变化并自动重启服务。

打开 `http://127.0.0.1:8000/api/health`，应看到：

```json
{"status":"ok","service":"ai-football-predictor-api"}
```

数据库会在后端启动时自动初始化。打开
`http://127.0.0.1:8000/api/database/status`，可以查看 DuckDB 是否就绪、
当前结构版本和数据表数量。

当前数据库包含：

- `competitions`：联赛和赛事；
- `teams`：标准球队；
- `team_aliases`：不同数据来源中的球队别名；
- `matches`：比赛、赛果和数据可用时间；
- `market_snapshots`：带采集时间和可用时间的 SP 或赔率快照；
- `schema_migrations`：数据库结构版本记录。

默认数据库文件位于 `data/processed/football_predictor.duckdb`。可以通过
`.env` 中的 `DATABASE_PATH` 修改位置。数据库文件属于本地数据，不会提交到 Git。

运行后端测试：

```bash
python -m pytest tests -v
```

- `pytest tests`：运行 `tests` 目录中的测试。
- `-v`：显示每个测试的详细名称和结果。

## 启动前端

```bash
cd frontend
npm install
npm run dev
```

- `npm install`：根据 `package.json` 和 `package-lock.json` 安装前端依赖。
- `npm run dev`：启动 Vite 本地开发服务器，终端会显示访问地址。

前端完整检查：

```bash
npm test
npm run lint
npm run build
```

- `npm test`：运行 Vitest 组件测试。
- `npm run lint`：运行 ESLint 代码规范检查。
- `npm run build`：先进行 TypeScript 类型检查，再生成生产构建。

## 环境变量

复制根目录 `.env.example` 为 `.env` 后填写本机配置。`.env` 已被 Git 忽略，不要把 API Key（接口密钥）或其他秘密提交到仓库。

## 当前边界

本系统仅供分析与研究，不承诺收益，不自动购票。后续模块必须显示数据更新时间、数据质量、模型置信度和风险提示。
