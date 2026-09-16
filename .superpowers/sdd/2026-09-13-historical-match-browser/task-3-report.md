# Task 3 实施报告：前端 API 客户端与数据格式化

## 交付内容

- 新增 `frontend/src/features/history/types.ts`：定义筛选参数、分页比赛、赔率市场和数据摘要的前端驼峰命名类型。
- 新增 `frontend/src/features/history/api.ts`：实现 `fetchMatchPage(filters, signal)` 与 `fetchDataSummary(signal)`。
- 新增 `frontend/src/features/history/api.test.ts`：覆盖 URL 编码、空筛选、响应字段格式化、摘要格式化及非 2xx 错误。

## 实现说明

- 使用 `URLSearchParams` 按稳定顺序追加 `page`、`page_size` 及非空字符串筛选；球队名称保留原文，由后端负责匹配规范化。
- 所有请求选项只传入 `{ signal }`，支持页面通过 `AbortController`（中止控制器）取消过期请求。
- 响应的下划线字段在客户端边界转换为驼峰字段；时间戳保持 ISO 字符串，显示层再决定本地化格式。
- 非 2xx 响应统一抛出带 HTTP 状态码的 `DataRequestError`。
- 客户端不填充比赛、比分、赔率或摘要默认值，真实数据缺失仍由服务端响应中的 `null` 或空数组表达。

## TDD 记录

1. 先创建测试并运行：Vitest（测试运行器）因无法解析 `./api` 而失败，确认测试确实针对尚不存在的客户端。
2. 添加最小类型与客户端实现后，定向测试通过。
3. 自审时补充摘要成功格式化测试，再次运行定向测试并通过。

## 验证结果

- `node .../vitest.mjs run src/features/history/api.test.ts`：4 个测试通过。
- `node .../vitest.mjs run`：3 个测试文件、6 个测试通过。
- `node .../typescript/bin/tsc -b --pretty false`：通过。
- `node .../eslint/bin/eslint.js .`：通过，无错误输出。
- `git diff --check`：通过。

## 关注事项

- 当前客户端市场类型与 Task 2 的完整响应保持一致，包含来源、提供方、采集时间和可用时间字段；客户端不对这些字段填充默认值。
- `fetchMatchPage` 和 `fetchDataSummary` 要求调用方显式传入 `AbortSignal`，与页面取消过期请求的设计一致。

## 修复轮次：补齐赔率市场元数据（2026-09-13）

上游 Task 2 新增了 `source`、`provider`、`captured_at` 和 `available_at`。本轮先在已有比赛响应 fixture（固定测试数据）中加入这四个字段，并断言客户端输出 `source`、`provider`、`capturedAt` 和 `availableAt`；测试先因客户端丢失字段而失败，再补充响应类型、前端 `MatchMarket` 类型和格式化映射后通过。未添加任何缺失值默认值。

本轮验证：定向 API 测试 4 个通过；TypeScript 类型检查和 ESLint 通过。
