# AI Football Predictor

竞彩足球概率分析与研究项目。当前已提供 Football-Data 和中国竞彩官方历史数据采集管道；模型训练仍在建设中，不承诺收益，也不自动购票。

## 目录

- `frontend/`：Vite + React + TypeScript + Tailwind CSS 前端。
- `backend/`：FastAPI 后端和健康检查。
- `data/`：原始、过渡和处理后数据的本地目录；实际数据默认不提交。
- `models/`：本地模型产物目录；模型文件默认不提交。
- `tests/`：未来跨模块和端到端测试的根目录。
- `docs/`：设计说明和实施计划。

Football-Data 原始 CSV（逗号分隔值）缓存位于 `data/raw/football_data/`，DuckDB（嵌入式数据库）默认位于 `data/processed/football_predictor.duckdb`。两者都是本地运行数据，不会提交到 Git；`backend/tests/fixtures/*.csv` 是提交到仓库的固定测试样例，不受原始缓存忽略规则影响。

中国竞彩原始 JSON（结构化文本）、SHA-256（安全散列校验值）和断点检查点位于 `data/raw/sporttery/`，同样只保存在本机，不提交到 GitHub。

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
python -m app
```

- `pip install`：安装依赖；`-r requirements.txt` 表示从依赖清单读取包名。
- `python -m app`：启动 FastAPI 应用，并从仓库根目录 `.env` 读取
  `API_HOST`、`API_PORT` 和 `DATABASE_PATH`；开发时会自动重载代码。

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
- `matches`：比赛、全场与半场赛果，以及数据可用时间；
- `market_snapshots`：带来源、赛前/收盘阶段、采集时间、可用时间和时间精度的 SP 或赔率快照；
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

## 浏览历史比赛

历史比赛页是只读的数据核验页面：它只显示已经写入 DuckDB（嵌入式数据库）的真实比赛和市场记录，**不会**在打开页面时导入数据、生成预测或创建示例比赛。请先启动后端，再启动前端：

```bash
cd backend
python -m app
```

- 这两条命令应在仓库根目录执行；`cd backend` 进入后端工作目录，随后 `python -m app` 启动 FastAPI（后端 API 框架）服务。
- 默认监听 `http://127.0.0.1:8000`；`API_HOST` 和 `API_PORT` 可在根目录 `.env` 中修改监听地址和端口。
- 后端按照根目录 `.env` 的 `DATABASE_PATH` 读取数据库。若要查看随工作区准备的演示数据，可设为 `data/processed/historical_demo.duckdb`；不设置时使用默认的 `data/processed/football_predictor.duckdb`。

另开一个终端，并在仓库根目录执行：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 4173
```

- `cd frontend` 进入前端工作目录；`npm run dev` 启动 Vite（前端开发服务器）。
- `--host 127.0.0.1` 只允许本机访问，`--port 4173` 固定前端端口，便于按下方地址复现验证。
- `VITE_API_BASE_URL` 是前端请求后端 API（接口）的基础地址，默认值为 `http://127.0.0.1:8000`；后端端口变更时必须同步修改该变量。

两个服务均就绪后，打开 [http://127.0.0.1:4173/#history](http://127.0.0.1:4173/#history)。页面默认按开球时间倒序显示 10 条比赛，可切换每页 20 或 50 条，也可直接跳转页码；同时支持按联赛、赛季和球队筛选，并展开查看收盘赔率的来源与时间语义。窄屏请在表格区域横向滚动。

若页面显示“尚未导入历史比赛”，表示当前 `DATABASE_PATH` 指向的数据库没有比赛数据；请先按下方“历史数据导入”说明完成导入，然后刷新页面。不要把空页面当作前端提供了演示数据。

## 环境变量

复制根目录 `.env.example` 为 `.env` 后填写本机配置。`.env` 已被 Git 忽略，不要把 API Key（接口密钥）或其他秘密提交到仓库。

- `DATABASE_PATH`：后端 DuckDB 数据库路径，相对路径以仓库根目录为基准；
- `FOOTBALL_DATA_RAW_PATH`：Football-Data 原始 CSV 缓存目录；建议保留默认的 `data/raw/football_data`；
- `API_HOST`：`python -m app` 监听的主机地址；
- `API_PORT`：`python -m app` 监听的端口；
- `VITE_API_BASE_URL`：前端访问后端 API（接口）的基础地址。Vite 已配置为读取根目录 `.env`。

历史赔率的下载时间不等于赔率可用时间。没有准确采集时间的收盘赔率会按
`captured_at = available_at = kickoff_at` 保存，并标记为 `closing` 和
`kickoff_bound`；开球前回测不得读取这类记录，以避免未来信息泄漏。

## 历史数据导入

首个数据源是 [Football-Data](https://football-data.co.uk/)。导入器只请求该站公开提供的 CSV 文件；使用前请自行阅读并遵守其网站的许可、归属和使用条款。

- 支持目录中配置的 38 个公开联赛；默认范围是每个联赛最近 5 个**已完成**赛季。22 个主联赛按赛季文件读取，16 个额外联赛使用 Football-Data 的 `new/{代码}.csv` 合并文件并按行内赛季筛选。
- 导入比赛日期与开赛时间、主客队、全场赛果、可用的半场赛果，以及来源实际提供的胜平负（1X2）、2.5 球大小球和亚洲让球赔率。
- 缺少赔率不会阻止有效赛果导入；未提供的玩法不会被推测、补造或伪装成竞彩足球 SP（赔率）。
- 同一源文件重复导入会产生独立审计记录，但不会重复写入比赛、市场快照或市场选项。

Football-Data 的历史收盘赔率通常没有来源采集时间。因此，下载时间仅记录文件获取行为，系统保守地将 `captured_at` 与 `available_at` 都设为 `kickoff_at`，并标记 `stage=closing`、`time_precision=kickoff_bound`。这表示赔率只能在开球时刻确认，开球前回测不得读取它们，避免未来信息泄漏。

### 导入 API（接口）

- `POST /api/data/import`：触发导入。空对象使用默认的 38 个联赛与最近 5 个已完成赛季，对应 126 个源文件请求（22 个联赛 × 5 个赛季 + 16 个合并文件）；显式年份范围支持 2000–2020，对应 456 个源文件请求（22 个联赛 × 20 个赛季 + 16 个合并文件）。
- `GET /api/data/imports/latest`：读取最近一次运行的安全摘要、请求范围和计数，不返回本机路径或异常堆栈。
- `GET /api/data/summary`：读取比赛、球队、市场快照和市场选项数量，以及最近开赛时间和最近成功导入时间。

例如，只导入英超 E0 的 2023/24 赛季：

```bash
curl -X POST http://127.0.0.1:8000/api/data/import -H "Content-Type: application/json" -d '{"competition_codes":["E0"],"seasons":["2324"]}'
```

- `curl`：发送 HTTP（超文本传输协议）请求的命令行工具。
- `-X POST`：指定创建导入运行所需的 `POST` 方法。
- `-H "Content-Type: application/json"`：声明请求正文是 JSON（结构化文本）。
- `-d ...`：传入精确范围；`E0` 是英超代码，`2324` 表示 2023/24 赛季。
- 预期结果：返回唯一 `run_id`、`status` 及文件、比赛、跳过行计数。

查询最近运行和当前数据摘要：

```bash
curl http://127.0.0.1:8000/api/data/imports/latest
curl http://127.0.0.1:8000/api/data/summary
```

- 第一条命令返回最近导入运行；第二条返回当前数据库汇总。
- 预期结果：两条命令均返回 JSON；未运行过导入时，`latest_run` 为 `null`，汇总计数为零。

合并文件中的每场比赛会根据来源的 `Season` 列写入实际数据库赛季；不在本次年份范围内的行会被过滤，不会把整份合并文件错误归到一个范围标签。早期 Football-Data 文件如果使用 `cp1252` 或 `Latin-1` 编码，系统会兼容读取；希腊等旧文件的 `HT/AT` 主客队表头也会映射为统一字段。

## 中国竞彩官方历史采集

采集器读取中国体彩网公开的比赛结果和固定奖金历史接口，保存胜平负、让球胜平负、总进球、比分和半全场五类来源数据。它使用单线程请求，每次真实网络请求默认间隔 3–5 秒；HTTP 567 被视为来源安全策略阻断，程序会保存检查点并停止，不会持续重试或绕过验证。

先执行不联网的全年演练：

```bash
cd backend
python -m app.sporttery.cli collect --start 2015-01-01 --end 2015-12-31 --dry-run
```

- `--start` / `--end`：采集日期范围，当前一次任务必须位于同一自然年。
- `--dry-run`：只显示会拆分出的 7 天窗口数量，不发送网络请求。
- 预期输出：2015 全年共 53 个窗口，`network_requests` 为 0。

正式采集 2015 全年：

```bash
cd backend
python -m app.sporttery.cli collect --start 2015-01-01 --end 2015-12-31 --delay-min 3 --delay-max 5 --resume
```

- `--delay-min 3` / `--delay-max 5`：两次网络请求之间随机等待 3–5 秒，降低对官方服务的压力。
- `--resume`：复用已校验的原始响应和检查点。首次运行也可带此参数；中断后必须带它继续，否则程序会提示 `existing_checkpoint_use_resume`，防止误开一个与旧进度冲突的任务。
- 全年包含数千场比赛和逐场奖金请求，通常需要数小时。终端每完成一个列表页或一场奖金会输出一行 JSON 进度；不能根据短时间无输出判断任务卡死。
- 原始响应、检查点、运行报告和 DuckDB 文件均受 `.gitignore` 保护，不会出现在 Git 提交列表中。

查看已经落库的 2015 覆盖率：

```bash
cd backend
python -m app.sporttery.cli report --year 2015
```

输出包括唯一比赛数、有奖金历史的比赛数、五类玩法快照数、奖金选项数和请求审计数。比赛列表只有比赛日期，没有可证明的精确开球时刻，因此当前先进入竞彩专用事实表；取得并验证详情接口的精确开球时间前，不生成 T-24h、T-12h、T-6h、T-1h 训练样本，避免时间泄漏。

## 当前边界

### 最近验证结果（2026-09-12）

已在临时缓存和临时 DuckDB 中完成一次受控 E0/2324 真实导入：下载的 CSV 为 172196 字节，SHA-256（安全散列校验值）为 `b2e057b0ed959f198b0f63d2391c01239f3608e6de5db68edab3f88e04d07ff3`。首次导入完成 380 场比赛、1140 个市场快照和 2660 个市场选项；所有市场均符合 `kickoff_bound` 时间规则。第二次导入复用缓存，业务表计数不增长，证明导入具备幂等性（重复执行得到相同业务数据）。后端 pytest（Python 测试框架）83 项、前端 Vitest（测试框架）2 项、ESLint（代码规范检查）和 Vite 生产构建均已通过。

完整验证证据见 [`docs/verification/2026-09-12-historical-data-import.md`](docs/verification/2026-09-12-historical-data-import.md)。

本系统仅供分析与研究，不承诺收益，不自动购票。后续模块必须显示数据更新时间、数据质量、模型置信度和风险提示。
