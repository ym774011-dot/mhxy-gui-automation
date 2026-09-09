# S-0 可观测性口径文档

> 维护：主理人（成员侧 Write 工具静默失败，本文档由主理人依成员交付的代码落盘）
> 代码事实来源：`run_unlimited_test.py`（schema v1）、`tools/zhuagui_stats.py`
> 日期：2026-09-03

---

## 1. 单轮成功的判定口径

**单轮 = 一次 `zhuagui_do_round(gateway, wait_dialog, timeout, verbose)` 调用**（`ZGUI.py:777`）。

**成功 ⇔ 该调用返回 `(True, msg)`**，即完成判定命中以下任一（`ZGUI.py:1213-1229`）：

| 判定 | 代码位置 | 含义 |
|------|----------|------|
| 次数递增 | `:1214` `cur_cnt != start_cnt` | 任务栏「第N次」变化 → 进入下一只 |
| 任务栏清空 | `:1216` `start_cnt > 0 and not count` | 本只完成（★注意：`start_cnt=0` 时此分支静默失效，见 S0-phase0-diagnosis.md 附带发现） |
| 超时复查命中 | `:1220-1229` | timeout 到期后最终复查一次 |

除上述之外的一切 `False` 返回均为失败。

---

## 2. 四类 result 的判据来源（`run_unlimited_test.py:205-210 classify`）

| result | 判据 | 实际含义 |
|--------|------|----------|
| `ok` | `do_round` 返回 `ok=True` | 单轮成功 |
| `inbattle` | 返回 `(False, msg)` 且 `msg` 含「超时未完成」 | ★历史命名；实际含义是**「完成判定超时」，并非「在战斗中」**。改名会打断历史数据连续性，故保留原名 |
| `other` | 返回 `(False, 其它 msg)` | 窗口未找到 / 任务未就绪 / 无野鬼目标等 |
| `error` | `do_round` 抛异常（`:400-402` 捕获） | 脚本本身出错，`msg` 前缀「异常:」 |

> 口径与项目历史数据连续，A/B 对比时 `OK 率 = ok / 总轮数`。

---

## 3. 日志字段字典（jsonl 每轮一条，`rec` @ `:433-455`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema` | int | 固定 `1`（`SCHEMA_VERSION`） |
| `timestamp` | ISO8601 | 轮次结束时刻（毫秒精度，含时区） |
| `run_id` | str | 本次启动的唯一标识 |
| `tag` | str | A/B 分组标签（`--tag`） |
| `round_index` | int | 轮次序号 |
| `role` | str | 角色（`--role`，默认二号美人） |
| `gateway` | str | 网关地址 |
| `result` / `ok` / `msg` | — | 见第 2 节 |
| `elapsed_s` | float | 本轮耗时（秒） |
| `timeout` / `wait_dialog` | float | 当轮参数（**A/B 对比关键列**） |
| `fail_stage` | str | 失败环节：接任务/瞬移/找鬼CALL/点回地府/完成判定/回长安/异常/未知（`infer_stage` @ `:178-193`，按 日志→msg→异常 三级匹配） |
| `task.name_before` | str | 轮次开始时任务目标怪名 |
| `task.start_count` / `end_count` | int | 任务栏「第N次」前后值（解析失败记 `-1`） |
| `task.changed` | bool | 计数是否变化 |
| `task.first_change_offset_s` | float | ★#3 关键观测量：计数**首次变化时刻**（相对轮开始，秒）。用于量化「任务栏刷新滞后」的真实分布 |
| `samples[]` | list | 过程采样（上限 400 条/轮），每条含 `t`（相对秒）+ 探针快照 |

### 探针快照字段（`_LUA_PROBE` @ `:72-97`，pcall 包裹、只读）

| 键 | 说明 |
|----|------|
| `战斗类存在` | `tp.战斗类` 是否存在（★该字段在本仓库历史代码中从未出现，字段存在性本身就是 #4 的证据） |
| `参战单位类型` / `参战单位pairs` | 类型与 pairs 计数（#4 核心观测量） |
| `敌方数量` / `背景显示` | 脱战残留垃圾数据的观测 |
| `战斗中` | 预期恒空（偏差 2 的持续验证） |
| `地图名称` | 传送门错位检测 |

---

## 4. 跑一轮验证

```bash
cd /e/DS/mhxy-gui-automation

# 列出已开游戏窗口与角色（不操作游戏）
python run_unlimited_test.py --list-roles

# 冒烟：不真跑（检查环境/配置加载）
python run_unlimited_test.py --rounds 1 --dry-run

# 真跑 3 轮（需游戏客户端与网关 http://127.0.0.1:18082 在线）
python run_unlimited_test.py --rounds 3 --verbose

# 无限模式，Ctrl+C 优雅停止（完成当前轮再退出）
python run_unlimited_test.py
```

日志落盘：`test_data/zhuagui_<run_id><tag>.jsonl`（文件名自动含 `t<timeout>_w<wait_dialog>` 便于分组）。

统计：

```bash
python tools/zhuagui_stats.py test_data/*.jsonl
```

---

## 5. 如何做 A/B 对比

1. 同条件跑两组，**只改一个变量**，用 `--tag` 区分：

```bash
# 组 A：基线
python run_unlimited_test.py --rounds 30 --tag A

# 组 B：改 timeout（示例）
python run_unlimited_test.py --rounds 30 --timeout 35 --wait-dialog 2.0 --tag B
```

2. 汇总对比：

```bash
python tools/zhuagui_stats.py test_data/*_A.jsonl test_data/*_B.jsonl
```

3. 判定有效性的最低门槛：每组 ≥30 轮（按 6~10% 基线，30 轮期望仅 2~3 个 ok，**样本量偏小，结论只能当趋势参考**；条件允许跑 50+ 轮）。
4. 注意硬约束：`--min-interval/--max-interval`（15~30s 随机节奏）两组必须一致，否则节奏差异会污染反外挂风险与数据。
5. 真战斗样本（T4）：`samples` 里的 `参战单位pairs` 在战斗时刻 >0 即为「参战单位可用」的直接证据；若全为 0 而战斗确实在进行，则现有判据漏判实锤。

---

## 6. 已知限制

- 本工具只做**测量**，不修任何业务逻辑；改 `ZGUI.py` 的任务（T3/T5/T6）用本工具做前后对比。
- `inbattle` 命名有历史歧义（见第 2 节），解读数据时以 msg 原文为准。
- `task.first_change_offset_s` 依赖采样间隔（默认 1.5s），精度 ±1.5s；如需更细可调 `--sample-interval`。
