# S2 · A/B 执行手册（T5 完成判定 × T7 jitter）

> 版本：v1 · 2026-09-03 · 负责人：quality-lead（严守真）
> 读者：主理人/操作者。本文是**照着跑**的操作文档，所有命令均为 PowerShell 可直接复制。
> 前置阅读：`S0-observability.md`（口径与统计纪律）、`S1-coord-jitter.md`（(327,345) 用途与 A/B 设计依据）
> 安全铁律：全程后台操作；Ctrl+C 只按一次（优雅停）；背包保持打开；禁止托管。

---

## 0. 两个 A/B 的载体区别（先记住这张表）

| | T5 完成判定 A/B | T7 jitter ABBA |
|---|---|---|
| 验证命题 | #3 任务栏刷新滞后 → timeout=20s 不够 | 事件2 (327,345) 的 ±6/±5 jitter 是否有害 |
| 载体 | `run_unlimited_test.py`（ZGUI 链路） | **GUI 任务序列**（jitter 只存在于事件点击，run_unlimited_test 不含事件2） |
| 切组方式 | 命令行参数 `--timeout/--wait-dialog` | 改 `data/task_sequence_autosave.json` 的 jitter_x/jitter_y |
| 数据 | `test_data/*.jsonl`（自动落盘） | `logs/automation.log`（需手动按时间段截取统计） |
| 统计工具 | `tools/zhuagui_stats.py --by-config` | 本文 §3.5 的 PowerShell 统计命令 |

**共性前提（每次跑批前逐项确认）**：
1. 游戏已开、网关已绑定（GUI 正常运行即视为已绑）
2. 角色窗口：二号美人，**客户区尺寸不变**（T7 的 (327,345) 是客户区像素，改分辨率=作废全部数据）
3. 背包保持打开
4. 一次会话只改一个变量

---

## 1. T5 · 完成判定 A/B（timeout × wait_dialog）

### 1.1 分组设计

| 组 | timeout | wait_dialog | tag | 假设 |
|---|---|---|---|---|
| A | 20 | 1.2 | `t5A` | 现状基线 |
| B1 | 35 | 1.2 | `t5B1` | 刷新滞后：只加大等待窗口 |
| B2 | 35 | 2.0 | `t5B2` | 混合：对话框也慢一档 |

一次只验证一个假设：先跑 A vs B1；若 B1 有效再跑 B2 分离 wait_dialog 的贡献。

### 1.2 冒烟预检（每次会话开始前，1 分钟）

```powershell
cd E:\DS\mhxy-gui-automation

# ① 确认角色窗口在
python run_unlimited_test.py --list-roles

# ② 干跑：验证网关通、内存探针可读（零点击）
python run_unlimited_test.py --dry-run
```

`--dry-run` 输出 `内存快照: null` → 网关没通，先解决网关再跑，不要硬跑。

### 1.3 每组的跑批命令（照抄即可）

```powershell
# 组 A：基线，30 轮
python run_unlimited_test.py --rounds 30 --timeout 20 --wait-dialog 1.2 --tag t5A1

# 组 B1：加大 timeout
python run_unlimited_test.py --rounds 30 --timeout 35 --wait-dialog 1.2 --tag t5B1

# 组 B2：混合（可选，第二阶段）
python run_unlimited_test.py --rounds 30 --timeout 35 --wait-dialog 2.0 --tag t5B2
```

说明：
- `--min-interval 15 --max-interval 30` 用默认值（15~30s/轮），**不要改**，保证组间节奏一致。
- 中途停止：**Ctrl+C 按一次**，当前轮跑完自动落盘退出；连按两次=强杀（会产生半轮脏数据，避免）。
- jsonl 实时落盘，崩溃不丢已完成轮次；跑批中可另开终端随时 `Get-Content test_data\*.jsonl -Tail 1` 看最新一轮。

### 1.4 执行顺序（ABBA 抵消时段漂移）

| 腿 | 组 | tag | 何时跑 |
|---|---|---|---|
| 1 | A | t5A1 | 会话1 前半 |
| 2 | B1 | t5B1 | 会话1 后半 |
| 3 | B1 | t5B2 | 会话2 前半（第二轮 B，与腿2 同参数，仅 tag 区分时段） |
| 4 | A | t5A2 | 会话2 后半 |

- 单腿 30 轮约 30×(20~45s+间隔) ≈ 25~40 分钟。会话1 约 1~1.5 小时。
- 腿与腿之间**必须**重新跑 §1.2 预检（网关可能掉）。

### 1.5 文件命名核对（每组跑完立刻做）

```powershell
Get-ChildItem test_data\*.jsonl | Sort-Object LastWriteTime | Select-Object Name, Length, LastWriteTime
```

核对要点：
- 文件名格式 `zhuagui_<YYYYmmdd_HHMMSS>_<tag>_t<timeout>_w<wait_dialog>.jsonl`，
  例如 `zhuagui_20260904_100000_t5A1_t20_w1.2.jsonl`
- **tag 与 t/w 值必须匹配**（如 t5A1 文件里应是 `t20_w1.2`）——不匹配说明参数没传对，该腿作废
- Length 应随轮次增长；跑完 30 轮通常 >50KB（含采样序列）
- 同目录还有同名 `.meta.json`（跑批条件快照），不用管它

### 1.6 统计与判读

```powershell
# 全部 T5 腿一起统计，--by-config 自动按 (timeout, wait_dialog) 分组
python tools\zhuagui_stats.py test_data\zhuagui_*_t5*.jsonl --by-config
```

判读规则（**顺序不可颠倒**）：
1. 先看 `A/B 分组对比` 表的 **95%CI 是否分离**，再看 OK 率点估计。
2. n=30/组时 CI 宽约 ±18pp——**两组 OK 率差异 <15pp 时不可下任何结论**，继续加跑（每组补到 50~100 轮，命令同 §1.3 换新 tag，如 t5A3）。
3. CI 分离且 B1 > A → 「刷新滞后」命题成立，新基线 timeout=35；此时看 A 组报告里的
   `★待办#3 任务栏刷新延迟`：若 A 组刷新 p90 接近 20s，因果链闭合。
4. CI 分离但 B1 ≈ A → 超时不是瓶颈，转向 T7/S1 的「弹窗未关→右键落地面」假设。
5. 同时看 `inbattle 轮中任务次数最终也未变化`：该数占 inbattle 比例高 → 失败是真的（不是刷新滞后）。

---

## 2. T7 · jitter ABBA（GUI 任务序列）

### 2.1 ★铁律：改 autosave.json 前必须关 GUI

`data/task_sequence_autosave.json` 是 GUI 自动保存文件，GUI 开着时手改会被回写覆盖，造成假对照。
**切组操作顺序永远是：关 GUI → 改 JSON → 开 GUI → 跑批。**

### 2.2 一次性准备（只做一次）

```powershell
cd E:\DS\mhxy-gui-automation

# 备份当前序列（jitter=6/5 的现状）
Copy-Item data\task_sequence_autosave.json data\task_sequence_autosave.json.bak_jitter_ab
```

### 2.3 切组命令（关 GUI 后执行）

```powershell
# ── 切组 A：jitter 归零 ──
@'
import json
p = "data/task_sequence_autosave.json"
d = json.load(open(p, encoding="utf-8"))
ev = next(e for t in d["tasks"] if t["name"] == "抓鬼"
          for e in t["events"] if e.get("var_name") == "鼠标点击6")
ev["params"]["jitter_x"] = 0
ev["params"]["jitter_y"] = 0
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("OK: jitter -> 0/0")
'@ | python -
```

```powershell
# ── 切组 B：恢复现状 ±6/±5 ──
@'
import json
p = "data/task_sequence_autosave.json"
d = json.load(open(p, encoding="utf-8"))
ev = next(e for t in d["tasks"] if t["name"] == "抓鬼"
          for e in t["events"] if e.get("var_name") == "鼠标点击6")
ev["params"]["jitter_x"] = 6
ev["params"]["jitter_y"] = 5
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("OK: jitter -> 6/5")
'@ | python -
```

切完**开 GUI 前先肉眼确认**：记事本打开 `data/task_sequence_autosave.json`，搜 `jitter_x`，
组 A 应为 `0`，组 B 应为 `6`。

### 2.4 每腿跑批步骤（GUI 操作）

1. 开 GUI，确认已绑定二号美人窗口
2. 任务序列选「抓鬼」→ 启动
3. **记下启动时刻**（如 `2026-09-04 10:00`，后面统计要用）
4. 跑满 30 轮（观察每轮结束回到「函数调用5 接任务」即一轮）→ 停止
5. **记下结束时刻**；把两个时刻抄进下面的记录表

记录表模板（照抄到笔记本）：

| 腿 | 组 | jitter | 开始 | 结束 | 轮数 |
|---|---|---|---|---|---|
| 1 | A | 0/0 | | | 30 |
| 2 | B | 6/5 | | | 30 |
| 3 | B | 6/5 | | | 30 |
| 4 | A | 0/0 | | | 30 |

腿 1→2、2→3 之间切组（关 GUI → §2.3 → 开 GUI）；腿 3→4 同理。会话 1 = 腿 1+2，会话 2 = 腿 3+4（分两天跑，抵消时段漂移）。

### 2.5 统计命令（每腿跑完执行，替换时间窗）

```powershell
cd E:\DS\mhxy-gui-automation
$from = "2026-09-04 10:00"   # ← 腿的开始时刻
$to   = "2026-09-04 11:00"   # ← 腿的结束时刻

# ① 事件2 实际落点分布（验证 jitter 生效：A 组应全部 327,345；B 组应散布 321~333×340~350）
Select-String -Path logs\automation.log -Pattern '点击执行: \(\d+,\d+\) button=right' |
  Where-Object { $_.Line -ge $from -and $_.Line -le $to } |
  ForEach-Object { $_.Matches[0].Value } | Group-Object | Sort-Object Count -Descending |
  Format-Table Count, Name -AutoSize

# ② 开始轮数 = 事件2 执行次数
(Select-String -Path logs\automation.log -Pattern '点击执行: \(\d+,\d+\) button=right' |
  Where-Object { $_.Line -ge $from -and $_.Line -le $to }).Count

# ③ 完成轮数 = 事件6 回长安红点 (312,229) 点击次数
(Select-String -Path logs\automation.log -Pattern '点击执行: \(312,229\) button=left' |
  Where-Object { $_.Line -ge $from -and $_.Line -le $to }).Count

# ④ 失败线索分布
(Select-String -Path logs\automation.log -Pattern '超时未完成' |
  Where-Object { $_.Line -ge $from -and $_.Line -le $to }).Count
(Select-String -Path logs\automation.log -Pattern '无野鬼目标' |
  Where-Object { $_.Line -ge $from -and $_.Line -le $to }).Count
```

**轮完成率 = ③ ÷ ②**，这就是 T7 的核心指标。

### 2.6 判读

1. 四腿各算轮完成率，A = (腿1+腿4)/60，B = (腿2+腿3)/60。
2. 差异 <15pp → CI 必然重叠（n=30 时）→ **jitter 对该点无害**（与 S1 §3.2 先验一致），保持 jitter 开启（防反外挂）。
3. 差异 ≥15pp 且 B 明显更差 → jitter 有害 → 长期改用 ±2/±2 折中（S1 §4.5），不要全归零。
4. **无论谁赢，必须分层**（这是本 A/B 最有价值的产出）：
   - ① 里 A 组落点全是 (327,345) 但轮完成率仍低 → jitter 无辜，失败在下游；
   - ④ 里「超时未完成」占比高且事件2 后紧跟异常 → 指向 S1 §3.3-1「弹窗未关时右键落地面」；
   - 「无野鬼目标」占比高 → 指向天眼瞬移没生效（事件3），与 jitter 无关。

---

## 3. 通用判读纪律（两个 A/B 都适用）

1. **先 CI 分离，后点估计。** n=30/组，Wilson 95%CI 宽约 ±18pp；OK 率差异 <15pp 时禁止下结论，只能加样本。
2. **一次只动一个变量。** T5 动 timeout 就别动 wait_dialog；T7 动 jitter 就别动 GUI 里任何其它事件参数。
3. **别在 GUI 事件编辑器里改 `ZGUI.main` 的 timeout/wait_dialog**（GUI 提示「默认8」是过时的，实际代码默认 20.0/1.2，见 S0 §3）。A/B 期间这些参数一律不碰。
4. 每腿之前必须重跑预检（网关/窗口/背包），网关掉线时跑出来的轮全是 error，会污染分组。
5. 数据文件只增不删：jsonl 按时间戳命名永不覆盖；automation.log 按 auto_clean_days=7 自动清理，**统计要在清理前做完**（或提前 `Copy-Item logs\automation.log logs\automation_backup_YYYYMMDD.log`）。

## 4. 变更记录

| 日期 | 版本 | 说明 |
|---|---|---|
| 2026-09-03 | v1 | 依据 S0/S1 定稿的操作手册；游戏/网关离线期间未做任何实机操作 |
