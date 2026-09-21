# 中国竞彩赛事前瞻原始数据采集实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有中国竞彩比赛与固定奖金采集命令中加入可选的七类赛事前瞻原始 JSON 采集，并提供独立断点、失败隔离、数据库审计和覆盖率报告。

**Architecture:** 使用一个不可变前瞻接口目录统一定义端点和参数，客户端继续复用现有 HTTP 校验、限速和错误分类。采集服务按比赛 ID 依次处理固定奖金与七类前瞻，原始文件是事实来源，年度检查点按数据集分别记录完成、空数据和失败 ID，DuckDB 只保存来源审计元数据，不在本阶段展开训练特征。

**Tech Stack:** Python 3.11、httpx（HTTP 客户端）、DuckDB（嵌入式数据库）、pytest（测试框架）、argparse（命令行参数解析）

**Spec:** `docs/superpowers/specs/2026-09-21-sporttery-preview-raw-collection-design.md`

## Global Constraints

- 七类接口统一使用比赛列表中的中国竞彩 `matchId`；仅 `match_tables` 将参数名写成 `gmMatchId`。
- 新功能必须由 `--include-preview` 显式开启；不带参数时保持现有行为、报告和退出码。
- 所有真实请求继续单线程执行并共用 `delay-min` / `delay-max` 限速。
- `emptyFlag=true` 或合法空值属于已处理的 `empty`，不能无限重试。
- HTTP 567 必须保存检查点并停止，不绕过来源风控。
- 原始 JSON、检查点和 DuckDB 仍位于被 `.gitignore` 忽略的本地数据目录。
- 前瞻数据在时间证据验证前不得进入模型训练，本计划不实现特征工程。
- 重要业务逻辑使用简洁中文注释，保持现有项目结构和编码风格。

## Review Focus

- 旧版 `2015.json` 检查点完全没有 `preview_datasets` 时应正常加载为空状态，并保留原比赛与赔率进度；Task 2 添加兼容测试。
- 来源返回 `success=true`、`emptyFlag=true`、`value=null` 时应保存原始响应并记为 `empty`，不能报 `invalid_value_shape`；Task 1 和 Task 4 添加测试。
- 七个接口中的一个发生普通业务错误时，其余接口和后续比赛仍应继续；Task 4 添加失败隔离测试。
- 已有原始文件但检查点写入前进程终止时，恢复应重放缓存、补写审计和检查点且不访问网络；Task 4 添加崩溃窗口测试。
- HTTP 567 出现在任意前瞻接口时，应保留此前完成的前瞻状态并立即返回 `blocked`；Task 4 添加阻断测试。

---

### Task 1: 前瞻接口目录、响应分类与客户端请求

**Files:**
- Create: `backend/app/sporttery/preview.py`
- Modify: `backend/app/sporttery/client.py`
- Modify: `backend/tests/test_sporttery_client.py`
- Create: `backend/tests/test_sporttery_preview.py`

**Interfaces:**
- Produces: `PREVIEW_DATASETS: tuple[PreviewDataset, ...]`
- Produces: `PreviewDataset(code: str, endpoint: str, parameters(match_id: int) -> dict[str, object])`
- Produces: `classify_preview_payload(data: dict[str, Any]) -> Literal["completed", "empty"]`
- Produces: `SportteryClient.fetch_preview(dataset: PreviewDataset, match_id: int) -> HttpPayload`
- Consumes: 现有 `SportteryClient._get()`、`HttpPayload` 和来源错误分类。

- [ ] **Step 1: 编写接口目录和响应分类的失败测试**

在 `backend/tests/test_sporttery_preview.py` 中覆盖完整目录和空响应：

```python
from app.sporttery.preview import PREVIEW_DATASETS, classify_preview_payload


def test_preview_catalog_contains_all_official_datasets() -> None:
    assert [item.code for item in PREVIEW_DATASETS] == [
        "match_feature", "result_history", "match_tables", "match_result",
        "future_matches", "match_player", "injury_suspension",
    ]
    tables = next(item for item in PREVIEW_DATASETS if item.code == "match_tables")
    assert tables.parameters(2041615) == {"gmMatchId": 2041615}


def test_preview_payload_classifies_source_empty_response() -> None:
    assert classify_preview_payload({
        "success": True, "errorCode": "0", "emptyFlag": True, "value": None,
    }) == "empty"
    assert classify_preview_payload({
        "success": True, "errorCode": "0", "emptyFlag": False, "value": {"home": {}},
    }) == "completed"
```

- [ ] **Step 2: 运行新测试并确认因模块不存在而失败**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_preview.py -v`

Expected: FAIL，提示 `ModuleNotFoundError: app.sporttery.preview`。

- [ ] **Step 3: 实现不可变接口目录和严格响应分类**

在 `preview.py` 中定义冻结数据类。每个参数生成器返回新字典；分类器只接受来源成功信封，`emptyFlag=true`、`value is None`、空字典或空列表判为 `empty`，其他字典判为 `completed`，未知结构抛出 `SourceBusinessError("invalid_preview_value_shape")`。接口目录精确使用规格中的七组参数。

```python
@dataclass(frozen=True)
class PreviewDataset:
    code: str
    endpoint: str
    parameters: Callable[[int], dict[str, object]]


def classify_preview_payload(data: dict[str, Any]) -> Literal["completed", "empty"]:
    value = data.get("value")
    if data.get("emptyFlag") is True or value is None or value == {} or value == []:
        return "empty"
    if not isinstance(value, dict):
        raise SourceBusinessError("invalid_preview_value_shape")
    return "completed"
```

- [ ] **Step 4: 编写七个客户端请求参数和合法空响应测试**

在 `test_sporttery_client.py` 中用 `httpx.MockTransport` 遍历目录，断言 URL 路径与查询参数；另加一个响应 `emptyFlag=true, value=null` 的测试，调用 `fetch_preview` 后应返回 `HttpPayload` 而不抛错。还要断言 `match_id <= 0` 抛出 `ValueError("invalid_match_id")`。

- [ ] **Step 5: 运行客户端测试并确认新方法不存在**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_client.py tests/test_sporttery_preview.py -v`

Expected: FAIL，提示 `SportteryClient` 没有 `fetch_preview`。

- [ ] **Step 6: 实现前瞻请求并保留现有严格校验**

为 `_get` 增加仅供前瞻使用的 `allow_empty_value: bool = False` 参数。比赛列表和固定奖金继续要求 `value` 为对象；`fetch_preview` 传 `allow_empty_value=True`，允许来源成功信封中的 `value` 为 `None`、字典或列表，具体业务分类交给 `classify_preview_payload`。

- [ ] **Step 7: 运行 Task 1 测试并提交**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_client.py tests/test_sporttery_preview.py -v`

Expected: PASS。

```powershell
git add backend/app/sporttery/preview.py backend/app/sporttery/client.py backend/tests/test_sporttery_client.py backend/tests/test_sporttery_preview.py
git commit -m "feat: add sporttery preview client catalog"
```

### Task 2: 向后兼容的逐数据集检查点

**Files:**
- Modify: `backend/app/sporttery/storage.py`
- Modify: `backend/tests/test_sporttery_storage.py`

**Interfaces:**
- Produces: `PreviewDatasetCheckpoint(dataset: str, completed_ids: tuple[int, ...], empty_ids: tuple[int, ...], failed_ids: tuple[int, ...])`
- Extends: `CollectionCheckpoint.preview_datasets: tuple[PreviewDatasetCheckpoint, ...]`
- Produces: `get_preview_checkpoint(checkpoint, dataset) -> PreviewDatasetCheckpoint`
- Produces: `replace_preview_checkpoint(checkpoint, state) -> CollectionCheckpoint`
- Consumes: Task 1 的合法数据集代码集合。

- [ ] **Step 1: 编写新检查点往返和旧文件兼容测试**

扩展 `test_sporttery_storage.py`：

```python
def test_preview_checkpoint_round_trip_sorts_ids_and_datasets(tmp_path) -> None:
    store = CheckpointStore(tmp_path)
    checkpoint = CollectionCheckpoint(
        year=2015,
        preview_datasets=(PreviewDatasetCheckpoint(
            dataset="match_feature",
            completed_ids=(2041615, 62373, 62373),
            empty_ids=(62374,),
            failed_ids=(62375,),
        ),),
    )
    store.save(checkpoint)
    loaded = store.load(2015)
    assert get_preview_checkpoint(loaded, "match_feature").completed_ids == (62373, 2041615)


def test_old_checkpoint_without_preview_data_loads_as_empty(tmp_path) -> None:
    path = tmp_path / "checkpoints" / "2015.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"year":2015,"completed_bonus_ids":[62373]}', encoding="utf-8")
    loaded = CheckpointStore(tmp_path).load(2015)
    assert loaded.completed_bonus_ids == (62373,)
    assert loaded.preview_datasets == ()
```

同时断言未知数据集、同一 ID 同时出现在完成和失败集合时抛出 `StorageError("invalid_preview_checkpoint")`。

- [ ] **Step 2: 运行检查点测试并确认类型尚不存在**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_storage.py -v`

Expected: FAIL，导入 `PreviewDatasetCheckpoint` 失败。

- [ ] **Step 3: 实现不可变状态、规范化和 JSON 映射**

内部使用按数据集排序的元组，磁盘格式按规格写为 `preview_datasets` 对象。加载时缺失该字段视为空；保存时排序、去重，并验证三个状态集合互斥、数据集代码受支持。`replace_preview_checkpoint` 只替换目标数据集，不改变比赛页、比赛 ID、赔率或停止原因。

- [ ] **Step 4: 运行存储测试与现有服务测试**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_storage.py tests/test_sporttery_service.py -v`

Expected: PASS，证明旧检查点与现有采集流程未回归。

- [ ] **Step 5: 提交检查点改动**

```powershell
git add backend/app/sporttery/storage.py backend/tests/test_sporttery_storage.py
git commit -m "feat: track sporttery preview checkpoints"
```

### Task 3: 前瞻来源审计表与覆盖率

**Files:**
- Create: `backend/app/migrations/009_sporttery_preview_sources.sql`
- Modify: `backend/app/storage.py`
- Modify: `backend/app/sporttery/repository.py`
- Modify: `backend/tests/test_storage.py`
- Modify: `backend/tests/test_database_api.py`
- Modify: `backend/tests/test_sporttery_repository.py`

**Interfaces:**
- Produces: 数据表 `sporttery_preview_sources(match_id, dataset, status, request_url, local_path, sha256, status_code, fetched_at, imported_at)`
- Produces: `SportteryRepository.import_preview_source(match_id: int, dataset: str, status: str, raw: StoredResponse) -> None`
- Extends: `CoverageReport`，加入 `completed_preview`、`empty_preview`、`preview_by_dataset`。
- Consumes: Task 1 数据集代码、Task 2 状态语义和现有 `StoredResponse`。

- [ ] **Step 1: 编写迁移和仓储幂等性失败测试**

把预期迁移版本从 8 更新为 9，并在 `test_sporttery_repository.py` 增加：先导入比赛页，再对同一 `match_id + dataset` 两次调用 `import_preview_source`，断言审计表只有一行、`sporttery_requests` 只新增一条对应请求审计。未知比赛、未知数据集或非 `completed/empty` 状态必须抛出稳定 `ValueError`，且事务不留下半条记录。真实项目数据路径写入数据库时必须转换为相对 `data/raw/sporttery/...` 的可移植路径，不能泄露用户目录；临时测试目录允许保留其测试路径。

- [ ] **Step 2: 运行数据库测试并确认版本和表缺失**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_storage.py tests/test_database_api.py tests/test_sporttery_repository.py -v`

Expected: FAIL，期望版本 9 但实际为 8，且审计表不存在。

- [ ] **Step 3: 添加迁移与数据库就绪要求**

迁移 SQL 使用组合主键 `(match_id, dataset)`、比赛外键、数据集与状态 `CHECK` 约束，并插入迁移版本 9。把 `sporttery_preview_sources` 加入 `REQUIRED_TABLES`。

- [ ] **Step 4: 实现仓储写入、同步包装和覆盖率统计**

`import_preview_source` 在单个事务中验证比赛存在、插入来源审计并调用 `_insert_request(connection, f"preview:{dataset}", raw)`。真实项目数据路径通过 `PROJECT_ROOT` 转为仓库相对 POSIX 路径。`SynchronizedSportteryRepository` 暴露同名加锁方法。覆盖率按比赛所属年份统计 `completed`、`empty` 及每个数据集的两类数量；普通失败只存在检查点，不伪造为已取得的数据库响应。

- [ ] **Step 5: 运行数据库测试并提交**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_storage.py tests/test_database_api.py tests/test_sporttery_repository.py -v`

Expected: PASS。

```powershell
git add backend/app/migrations/009_sporttery_preview_sources.sql backend/app/storage.py backend/app/sporttery/repository.py backend/tests/test_storage.py backend/tests/test_database_api.py backend/tests/test_sporttery_repository.py
git commit -m "feat: audit sporttery preview sources"
```

### Task 4: 采集服务编排、失败隔离和恢复

**Files:**
- Modify: `backend/app/sporttery/service.py`
- Modify: `backend/tests/test_sporttery_service.py`

**Interfaces:**
- Extends: `SportteryCollectionService.__init__(..., include_preview: bool = False)`
- Produces: `_collect_previews(checkpoint, match_id, year) -> CollectionCheckpoint`
- Extends: `CollectionReport`，加入默认值兼容的 `completed_preview`、`empty_preview`、`failed_preview`、`preview_by_dataset`。
- Consumes: Task 1 `fetch_preview` / `classify_preview_payload`，Task 2 检查点助手，Task 3 `import_preview_source`。

- [ ] **Step 1: 扩展 FakeClient 和 FakeRepository 测试夹具**

让 `FakeClient.fetch_preview(dataset, match_id)` 记录 `preview:{dataset.code}:{match_id}`，默认返回合法有数据响应，并可按 `(dataset, match_id)` 注入 `SourceBusinessError` 或 `BlockedBySourceError`。测试仓储包装记录 `import_preview_source` 调用。

- [ ] **Step 2: 编写默认关闭和完整采集顺序的失败测试**

新增两个测试：默认构建服务时 `preview_calls == []`；启用后每个唯一比赛 ID 请求七类数据，且首场调用顺序为 `bonus:62373` 后紧跟七个 `preview:*:62373`。断言报告的完成数为 `比赛数 × 7`。

- [ ] **Step 3: 编写空数据、普通失败隔离和报告测试**

把 `match_player` 返回设为合法空响应，把一场的 `injury_suspension` 设为 `SourceBusinessError("business_missing")`。断言其他接口继续、报告为 `completed_with_errors`、完成/空/失败数量准确，并且对应检查点状态互斥。

- [ ] **Step 4: 编写缓存崩溃窗口和恢复测试**

预先通过 `RawResponseStore.write("previews", year, f"{match_id}/match_feature", payload)` 写入原始文件，但不写检查点。启用前瞻并 `--resume` 后断言该数据集没有网络调用，仓储获得重放，检查点补为完成。第二次完整恢复断言七类接口均不访问网络。

- [ ] **Step 5: 编写前瞻 HTTP 567 阻断测试**

让第三个前瞻接口抛出 `BlockedBySourceError("http_567")`，断言报告 `status == "blocked"`、`stopped_reason == "http_567"`，前两个数据集已完成，第三个未被误记为普通失败，后续接口没有请求。

- [ ] **Step 6: 运行服务测试并确认新能力缺失**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_service.py -v`

Expected: FAIL，构造器不接受 `include_preview` 或报告缺少前瞻字段。

- [ ] **Step 7: 实现逐数据集采集和统一状态更新**

每场固定奖金处理后，仅在 `include_preview=True` 时调用 `_collect_previews`。每个数据集先尝试加载 `previews/{year}/{match_id}/{dataset}.json`；缓存缺失时调用 `_pace()` 后请求并原子保存。分类成功后写仓储与对应检查点；普通来源错误只更新失败集合并继续；HTTP 567 原样抛给外层停止逻辑。每个状态变化后立即保存检查点并输出 `preview` 进度事件。

- [ ] **Step 8: 运行服务、存储和仓储回归测试并提交**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_service.py tests/test_sporttery_storage.py tests/test_sporttery_repository.py -v`

Expected: PASS。

```powershell
git add backend/app/sporttery/service.py backend/tests/test_sporttery_service.py
git commit -m "feat: collect sporttery previews with resume"
```

### Task 5: 命令行开关、报告输出和使用文档

**Files:**
- Modify: `backend/app/sporttery/cli.py`
- Modify: `backend/tests/test_sporttery_service.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `collect` 与 `collect-years` 的 `--include-preview` 布尔参数。
- Extends: `_build_service(..., include_preview: bool)`。
- Produces: `_coverage_payload(report: CoverageReport, checkpoint: CollectionCheckpoint) -> dict[str, object]`，合并数据库成功/空统计与检查点失败统计。
- Consumes: Task 4 扩展后的服务和报告。

- [ ] **Step 1: 编写命令行解析、传递和 dry-run 失败测试**

断言：

```python
args = parse_args([
    "collect", "--start", "2015-01-01", "--end", "2015-01-03",
    "--include-preview", "--resume",
])
assert args.include_preview is True
```

再通过 monkeypatch 或构建函数测试确认 `include_preview` 传入服务；`--dry-run --include-preview` 输出包含 `preview_datasets: 7` 和“网络请求仍为 0”的说明。不带开关时值为 `False`。为 `_coverage_payload` 构造数据库覆盖报告与含失败 ID 的检查点，断言最终 `completed_preview`、`empty_preview`、`failed_preview` 和逐数据集三类计数都存在；旧检查点应报告失败数 0。

- [ ] **Step 2: 运行 CLI 相关测试并确认参数未定义**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests/test_sporttery_service.py -k "cli or dry_run" -v`

Expected: FAIL，argparse 不认识 `--include-preview`。

- [ ] **Step 3: 实现参数和报告传递**

在公共采集控制参数中加入 `--include-preview`。单年与多年份服务构造都显式传递该值；JSON 最终采集报告通过 `asdict` 自动包含 Task 4 的前瞻统计。`report --year` 同时读取 `SportteryRepository.coverage_report(year)` 和 `CheckpointStore.load(year)`，通过 `_coverage_payload` 合并数据库中的成功/空响应与检查点中的失败状态。保持未开启时旧命令不变。

- [ ] **Step 4: 更新 README**

在“中国竞彩官方历史采集”章节补充完整命令、参数含义、请求量约增加七倍、原始目录、三个状态、HTTP 567 行为和训练时间证据限制。明确已有 2015 数据的补采命令仍使用 `--resume`，不会重新下载有效比赛列表和固定奖金文件。

- [ ] **Step 5: 运行完整后端测试并提交**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests -v`

Expected: 全部 PASS。

```powershell
git add backend/app/sporttery/cli.py backend/tests/test_sporttery_service.py README.md
git commit -m "docs: expose sporttery preview collection"
```

### Task 6: 真实小样本验收与证据记录

**Files:**
- Create: `docs/verification/2026-09-21-sporttery-preview-raw-collection.md`

**Interfaces:**
- Consumes: 已实现的 `collect --include-preview` 命令、原始目录和覆盖率报告。
- Produces: 不包含敏感信息的验收记录；不提交原始 JSON 或 DuckDB。

- [ ] **Step 1: 运行离线全套验证**

Run: `cd backend; C:\Users\24315\miniconda3\python.exe -m pytest tests -v`

Expected: 全部 PASS。

- [ ] **Step 2: 使用临时数据目录验证已知比赛接口**

先通过代码测试或受控的一场采集验证 `2041615` 的七类请求参数与响应分类，不修改用户正在使用的全年检查点。若官方接口已经返回 567，记录阻断并停止在线请求；不得通过并发、Cookie 或伪造身份绕过。

- [ ] **Step 3: 对 2015 年一个短日期窗口做恢复验收**

使用隔离的临时 DuckDB 和原始目录运行 1 至 3 天窗口两次：第一次带 `--include-preview` 采集，第二次带 `--resume`。记录七类接口完成、空和失败数，以及第二次是否全部命中缓存。若来源没有早期前瞻数据，合法空响应即为正确结果。

- [ ] **Step 4: 记录时间一致性观察**

对抽样响应记录：历史交锋和近期比赛日期是否全部早于目标比赛；未来赛程是否全部晚于目标比赛；积分榜、比赛特征、球员和伤停是否含可靠发布时间。无法证明的字段明确标为“不进入训练”。

- [ ] **Step 5: 写入验收文档并执行最终差异检查**

验收文档记录命令、日期范围、测试数量、在线结果、阻断情况、数据覆盖和训练可用性结论，不记录 Cookie、Token、本机隐私路径或整份来源响应。

Run: `git diff --check; git status --short`

Expected: 无空白错误；只包含本计划范围内的源码、测试、README 和验收文档。

- [ ] **Step 6: 提交验收记录**

```powershell
git add docs/verification/2026-09-21-sporttery-preview-raw-collection.md
git commit -m "test: verify sporttery preview collection"
```
