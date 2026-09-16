# 历史比赛浏览验证报告

验证日期：2026-09-14
验证范围：历史比赛查询 API（接口）、React（前端界面）浏览页，以及本地 DuckDB（嵌入式数据库）演示库 `data/processed/historical_demo.duckdb`。

## 可重复启动方式

在仓库根目录准备 `.env`，或在启动后端的终端设置以下变量：

```text
DATABASE_PATH=data/processed/historical_demo.duckdb
API_HOST=127.0.0.1
API_PORT=8000
VITE_API_BASE_URL=http://127.0.0.1:8000
```

随后在两个终端分别执行：

```bash
cd backend
python -m app
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 4173
```

打开 `http://127.0.0.1:4173/#历史比赛`。浏览页不会触发导入；数据库为空时会显示“尚未导入历史比赛”，需先按 README 的导入说明写入真实数据。

## 自动验证

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端 pytest（Python 测试框架） | `python -m pytest -q --disable-warnings --basetemp .pytest-tmp-task5-final-recheck`（在 `backend/`） | 94 passed |
| 前端 Vitest（测试框架） | `npm test`（在 `frontend/`） | 5 个测试文件、20 passed |
| ESLint（代码规范检查） | `npm run lint`（在 `frontend/`） | 通过 |
| TypeScript（类型检查）和 Vite（生产构建） | `npm run build`（在 `frontend/`） | 通过 |
| Git 空白检查 | `git diff --check main...HEAD` | 通过 |

> 受限执行环境禁止访问系统临时目录，因此后端测试通过 `--basetemp` 将 pytest 临时文件保存在可写的 `backend/` 目录。该选项只改变临时文件位置，不改变测试选择、应用配置或断言结果。

## 真实数据库与 API 核验

启动后端时以 `DATABASE_PATH=data/processed/historical_demo.duckdb` 指向演示库，并请求：

```text
GET /api/data/summary
GET /api/data/matches?page=1&page_size=20
```

确认摘要和分页响应均来自演示 DuckDB，而非浏览器内置样例。第一页为真实 Football-Data 英超 `E0`、赛季 `2324` 比赛；响应使用服务端分页，`page=1`、`page_size=20`，并返回筛选项、总数和市场详情。数据规模、首场比赛及页面检查结果见本报告最终的“实测证据”节。

## 人工页面核验

在 `#历史比赛` 页面使用同一个演示数据库核验：

- 侧边栏可打开“历史比赛”，页面默认加载数据摘要和 20 场按开球时间倒序的真实比赛；
- 联赛 `E0`、赛季 `2324` 和球队关键词筛选会重置到第一页；清除筛选恢复全部数据；
- 上一页/下一页显示正确范围并在边界禁用；
- 展开一场比赛后可见胜平负、大小球、亚洲让球、来源、提供方、阶段、采集时间、可用时间和时间精度；
- `kickoff_bound` 明确显示“仅能确认开球时可用，不能用于开球前回测”；
- 窄屏下表格容器可横向滚动，未把赔率列压缩成虚构卡片；
- 浏览器控制台无错误。

## 11 条验收标准复核

| # | 标准 | 结论 |
|---:|---|---|
| 1 | 侧边栏可打开历史比赛 | 通过 |
| 2 | 只展示 DuckDB 真实比赛 | 通过 |
| 3 | 开球时间倒序、每页 20 场 | 通过 |
| 4 | 联赛、赛季、球队筛选及清除 | 通过 |
| 5 | 半场、全场、收盘 1/X/2 赔率 | 通过 |
| 6 | 展开大小球、亚洲让球和时间语义 | 通过 |
| 7 | `kickoff_bound` 禁止开球前回测提示 | 通过 |
| 8 | 服务端分页，不一次返回全部数据 | 通过 |
| 9 | 加载、空库、无结果、失败状态 | 通过 |
| 10 | 自动测试和静态检查 | 通过 |
| 11 | 未实现预测、回测或自动购票 | 通过 |

## 实测证据

### 演示库与 API

`GET /api/data/summary` 返回：

| 联赛 | 球队 | 比赛 | 市场快照 | 赔率结果 |
|---:|---:|---:|---:|---:|
| 1 | 20 | 380 | 1,140 | 2,660 |

`GET /api/data/matches?page=1&page_size=20` 返回 `total_items=380`、`total_pages=19` 和 20 条 `items`；筛选项为 `competitions=["E0"]`、`seasons=["2324"]`。第一页首项是 Football-Data 的 Burnley 1–2 Nott'm Forest（2024-05-19T16:00:00Z），包含胜平负、大小球与亚洲让球三个 `closing` 市场，均带 `kickoff_bound` 时间精度。

### 浏览器交互

本机 Edge（浏览器）以 `http://127.0.0.1:4173/#历史比赛` 打开真实服务后，读取到：

| 操作 | 可观察结果 |
|---|---|
| 初始加载 | 标题为“历史比赛”；摘要显示 380、1、20、1,140、2,660；表格为第 1–20 场，共 380 场，含 20 个数据行 |
| 展开市场 | 第一场展开 3 个市场，并显示“仅能确认开球时可用，不能用于开球前回测” |
| 下一页 | 显示第 21–40 场，共 380 场；页码为 2 / 19 |
| 球队筛选 | 输入 Arsenal 后 URL 为 `?team=Arsenal`，页码重置为第 1 页，共 38 场，表格包含 Arsenal |
| 窄屏表格 | 390px 视口中容器 `clientWidth=287`、`scrollWidth=940`、`overflow-x=auto`；设定横向滚动后 `scrollLeft=240` |
| 控制台与网络 | 最终加载和上述交互期间无 JavaScript 异常、console error（控制台错误）或 HTTP 4xx/5xx |

验证中发现本地 Vite（前端开发服务器）与 API 使用不同端口时缺少 CORS（跨域资源共享）响应头，浏览器会拦截虽为 200 的 API 响应；已添加仅允许 `http://127.0.0.1:4173` 的只读 GET CORS 配置，并以测试覆盖。另补充页面 favicon（浏览器图标）引用，消除缺失 `/favicon.ico` 导致的 404 控制台错误。
