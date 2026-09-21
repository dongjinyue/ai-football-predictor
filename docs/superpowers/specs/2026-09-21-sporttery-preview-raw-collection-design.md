# 中国竞彩赛事前瞻原始数据采集设计

## 1. 状态与范围

- 日期：2026-09-21
- 状态：对话设计已确认，等待书面规格审阅
- 数据源：中国体彩网公开的竞彩足球赛事前瞻接口
- 关联键：比赛列表与固定奖金接口中的 `matchId`，对应前瞻接口的 `sportteryMatchId`；积分榜接口虽然参数名为 `gmMatchId`，仍传入同一个中国竞彩比赛编号
- 本阶段目标：在现有比赛结果与固定奖金采集过程中，可选地同步保存七类赛事前瞻原始 JSON，并提供独立检查点、失败隔离和覆盖率审计

本阶段不解析训练特征、不训练模型、不在前端展示前瞻内容。原始响应缺少统一的历史发布时间，在证明其确实代表目标比赛的赛前状态前，不得直接进入训练集。

## 2. 成功标准

实现完成后，用户可以使用一条命令采集指定自然年内的比赛结果、固定奖金和赛事前瞻：

```powershell
python -m app.sporttery.cli collect --start 2015-01-01 --end 2015-12-31 --include-preview --delay-min 1 --delay-max 2 --resume
```

系统必须满足：

- 每发现一场有效比赛，先完成现有比赛与固定奖金流程，再依次处理七类前瞻接口；
- 前瞻接口彼此独立，单个接口无数据或业务失败不丢弃比赛、赔率和其他前瞻响应；
- 每次真实网络请求都服从现有统一限速，不因前瞻接口增加并发；
- 原始 JSON 按比赛、年份和数据集稳定落盘，并保存请求地址、采集时间、状态码和 SHA-256 校验值；
- `--resume` 复用有效原始响应，只补尚未完成或上次失败的接口；
- `emptyFlag=true` 或合法空值记录为 `empty`，属于已处理状态，不无限重试；
- HTTP 567 保存当前检查点并停止任务；
- 旧版检查点可以无损升级，已采集的比赛和赔率不需要重新下载；
- 覆盖率报告可以按年份统计每类前瞻的成功、空数据和失败数量。

## 3. 官方接口目录

所有请求使用现有基础地址：

```text
https://webapi.sporttery.cn/gateway/uniform/football
```

接口与参数如下：

| 数据集代码 | 接口 | 参数 | 用途 |
|---|---|---|---|
| `match_feature` | `getMatchFeatureV1.qry` | `termLimits=10`, `sportteryMatchId` | 双方近况汇总、主客场表现、场均进失球 |
| `result_history` | `getResultHistoryV1.qry` | `sportteryMatchId`, `termLimits=10`, `tournamentFlag=0`, `homeAwayFlag=0` | 历史交锋 |
| `match_tables` | `getMatchTablesV2.qry` | `gmMatchId` | 积分榜与主客场排名 |
| `match_result` | `getMatchResultV1.qry` | `sportteryMatchId`, `termLimits=10`, `tournamentFlag=0`, `homeAwayFlag=0` | 双方近期战绩 |
| `future_matches` | `getFutureMatchesV1.qry` | `sportteryMatchId`, `termLimits=4` | 后续赛程与赛程密度 |
| `match_player` | `getMatchPlayerV1.qry` | `sportteryMatchId`, `termLimits=3` | 球员与来源提供的阵容信息 |
| `injury_suspension` | `getInjurySuspensionV1.qry` | `sportteryMatchId` | 伤停与停赛名单 |

接口目录由代码中的不可变配置统一维护。`match_tables` 只改变参数名称，不转换编号。响应中的 `matchId`、`uniformMatchId`、球队 ID 等其他编号完整保留在原始 JSON 中，但不替代采集关联键。

## 4. 采集架构

### 4.1 流程

```text
日期窗口和比赛列表
  -> 保存并导入比赛结果
  -> 按 sporttery matchId 保存并导入固定奖金
  -> 启用 --include-preview 时遍历七类前瞻数据集
       -> 读取并校验本地缓存
       -> 缓存不存在时限速请求官方接口
       -> 校验通用响应信封
       -> 原子保存原始 JSON
       -> 写入请求审计记录
       -> 更新该数据集的独立检查点
  -> 继续下一场比赛
```

现有 `SportteryCollectionService` 继续负责流程编排。新增专门的前瞻目录配置和通用采集方法，避免在服务中复制七段近似逻辑。`SportteryClient` 为七个接口提供明确的公开方法，底层继续复用现有请求头、超时、有限重试和错误分类。

### 4.2 开关与兼容性

- 新增 `--include-preview`，默认关闭，避免改变现有命令的请求数量和运行时间；
- 带该参数运行现有已完成年份并使用 `--resume` 时，比赛列表和固定奖金从原始缓存重放，只请求缺少的前瞻数据；
- 不带该参数时，行为、报告和退出码保持现状；
- `--dry-run` 增加前瞻数据集数量说明，但仍不发送网络请求；
- 不恢复多进程写同一个 DuckDB 的方案，单年采集仍使用单线程网络请求。

## 5. 原始数据与审计

原始响应路径为：

```text
data/raw/sporttery/previews/{year}/{match_id}/match_feature.json
data/raw/sporttery/previews/{year}/{match_id}/result_history.json
data/raw/sporttery/previews/{year}/{match_id}/match_tables.json
data/raw/sporttery/previews/{year}/{match_id}/match_result.json
data/raw/sporttery/previews/{year}/{match_id}/future_matches.json
data/raw/sporttery/previews/{year}/{match_id}/match_player.json
data/raw/sporttery/previews/{year}/{match_id}/injury_suspension.json
```

继续复用 `RawResponseStore` 的原子写入与 SHA-256 校验。每个文件保留：

- 完整但不含 Cookie、Token 等秘密信息的请求 URL；
- HTTP 状态码；
- UTC 采集时间；
- 原始官方 JSON；
- 原始数据校验值。

数据库新增前瞻来源审计表，一行表示一场比赛的一个数据集，至少保存：

- 中国竞彩比赛 ID；
- 数据集代码；
- `completed` 或 `empty` 状态；
- 原始文件相对路径与 SHA-256；
- 请求 URL、HTTP 状态码和采集时间；
- 是否存在可用的 `value`。

该表只提供来源追溯和覆盖率统计，不展开业务字段。数据库写入使用唯一键保证重复执行幂等。

## 6. 检查点与恢复

现有年度检查点新增 `preview_datasets`，按数据集分别保存：

```json
{
  "preview_datasets": {
    "match_feature": {
      "completed_ids": [2041615],
      "empty_ids": [],
      "failed_ids": []
    }
  }
}
```

规则如下：

- `completed`：通用响应信封合法，并且来源明确表示存在数据；
- `empty`：响应成功，但 `emptyFlag=true`、`value=null` 或该接口约定的合法空结构；
- `failed`：业务错误、无法解析的响应信封或有限重试后仍失败；
- HTTP 567：不记为普通失败，保存检查点并停止，以免持续触发来源风控；
- 原始文件已经存在且校验通过时，以文件为事实来源重新写入审计表并修复检查点，不发网络请求；
- 旧检查点没有 `preview_datasets` 时按空映射读取，不改变已有页面和赔率完成记录。

为了避免年度检查点不断重复写入巨大的嵌套对象，内存中使用集合维护 ID，落盘时排序并去重。检查点仍通过临时文件原子替换。

## 7. 错误隔离与任务状态

单个前瞻接口失败时输出一条结构化进度：

```json
{"event":"preview","dataset":"match_player","match_id":2041615,"status":"failed","code":"business_missing"}
```

随后继续该场其他数据集和后续比赛。年度报告新增：

- `completed_preview`：有数据的接口响应总数；
- `empty_preview`：合法空响应总数；
- `failed_preview`：失败接口总数；
- `preview_by_dataset`：七类数据分别统计。

只要比赛列表和采集流程没有发生阻断，存在普通前瞻失败时任务返回 `completed_with_errors`。HTTP 567、列表接口失败或原始文件校验失败仍按现有规则阻断并返回非零退出码。

## 8. 时间语义与训练隔离

下载时间只表示本系统何时取得响应，不证明数据何时由来源发布。七类原始数据默认标记为“历史可用时间未验证”，在完成以下检查前不得直接成为模型输入：

- `result_history` 和 `match_result` 中的比赛日期必须早于目标比赛；
- `future_matches` 中的比赛日期应晚于目标比赛，只允许提取赛程间隔，不允许使用未来赛果；
- `match_tables` 和 `match_feature` 必须验证是否对应目标比赛当时的赛前状态，而不是当前重新计算值；
- `match_player` 不得自动当作确认首发，除非字段含义和发布时间得到验证；
- `injury_suspension` 必须证明是目标比赛赛前名单，而不是赛后修订状态；
- 任何未通过时间证据检查的数据只能用于页面核验或研究，不进入正式回测。

后续特征工程必须从原始层派生有版本的数据集，并记录解析器版本、证据时间和拒绝原因，不能覆盖原始 JSON。

## 9. 测试与验收

自动测试使用固定 JSON 样例，不把中国体彩网在线接口作为日常测试依赖，覆盖：

- 七个客户端方法生成正确接口名和参数，尤其是 `gmMatchId` 的特殊命名；
- 通用成功、有数据、合法空数据、业务失败和未知响应结构；
- 一场比赛七类接口独立完成，单个失败不影响其他数据；
- HTTP 567 保存检查点并停止；
- 首次采集、缓存重放和 `--resume` 不重复网络请求；
- 旧检查点兼容读取，新检查点排序、去重和原子写入；
- 审计表重复导入不增加重复行；
- 不带 `--include-preview` 时现有测试行为不变；
- 年度报告与分数据集统计正确。

在线验收分两步：

1. 使用已知比赛 `2041615` 逐个请求七类接口，确认原始文件、参数、空值判断和审计记录；
2. 从 2015 年抽取少量比赛运行带前瞻的恢复测试，确认历史接口是否仍有数据以及内容的时间一致性。

小样本通过后才允许启动 2015 全年补采。若早期年份大量返回合法空数据，应如实记录覆盖率，不伪造、不从当前页面反推历史状态。

## 10. 文档与命令说明

README 增加：

- `--include-preview` 的作用、请求量增长和预计耗时；
- `--resume` 如何跳过已完成的比赛、赔率和前瞻数据；
- 原始目录和覆盖率报告含义；
- `completed`、`empty`、`failed` 与 HTTP 567 的区别；
- 前瞻原始数据在时间证据验证前不得用于训练的说明。

## 11. 非目标

本阶段不包含：

- 将七类 JSON 全部展开为训练特征表；
- 模型训练、预测 API 或回测页面；
- 天气、实时战术事件、射门、角球、控球率或第三方高级指标采集；
- 绕过验证码、登录、付费限制或来源安全策略；
- 提高并发以规避正常限速；
- 猜测缺失伤停、首发、排名或比赛统计。
