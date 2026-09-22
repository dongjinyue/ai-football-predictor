# Sporttery 赛事前瞻原始采集验收

## 验证范围

本次只验证原始响应采集和可恢复状态，不把前瞻字段直接用于模型训练。采集器为每场比赛按以下顺序请求 7 组接口：

1. `match_feature`：近期表现特征
2. `result_history`：历史交锋结果
3. `match_tables`：积分榜和主客场排名
4. `match_result`：近期比赛结果
5. `future_matches`：未来赛程
6. `match_player`：球员信息
7. `injury_suspension`：伤停信息

## 离线测试

在 `backend` 目录执行：

```powershell
C:\Users\24315\miniconda3\python.exe -m pytest tests -q
```

结果：214 个测试（包含前瞻采集、命令行和 Windows 文件占用回归测试）全部通过。

## 受控接口验证

使用比赛 ID `2041615`，每个接口只请求一次，不写入用户正在使用的年度检查点。7 个接口均返回 HTTP 200，响应分类均为 `completed`：

```text
match_feature       200 completed
result_history      200 completed
match_tables        200 completed
match_result        200 completed
future_matches      200 completed
match_player        200 completed
injury_suspension   200 completed
```

## 落盘和恢复规则

- 原始文件：`data/raw/sporttery/previews/{年份}/{比赛ID}/{dataset}.json`
- 每个文件包含请求地址、HTTP 状态码、获取时间和 SHA-256 校验值。
- `emptyFlag=true`、`value=null` 或空对象/数组会记录为 `empty`，不会伪造默认值。
- 普通业务错误记录为 `failed` 并继续下一组数据；HTTP 567 会保存检查点并停止，下一次使用 `--resume`。
- 数据库表 `sporttery_preview_sources` 只记录来源审计信息和状态，重复导入保持幂等。

## 训练前限制

这些接口返回的是“当前可见的前瞻信息”，响应获取时间不一定等于比赛开始前的发布时间。历史交锋、积分榜、近期结果、未来赛程、球员和伤停数据必须先确认其发布日期早于目标比赛；无法证明时间的字段只能保存为原始数据，不能直接进入训练样本。赔率仍需使用固定奖金历史快照，并按 `T-24h/T-12h/T-6h/T-1h` 等时间点单独构造样本。
