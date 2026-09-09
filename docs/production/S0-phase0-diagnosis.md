# Phase 0 阶段诊断报告 · 胖子西游抓鬼自动化

> 主理人：游承峰（team-lead） | 日期：2026-09-03 | 团队：mhxy-zhuagui-polish
> 仓库根：`E:\DS\mhxy-gui-automation`
> 核心模块：`tasks/library/ZGUI.py`（1416 行）

---

## 一、阶段判定

项目位于 **Phase 5（制作）收尾 → Phase 6（打磨）** 的交界。

**Phase 5→6 门控判定：FAIL**

Phase 1-4 产物齐全，无需重跑：

| 阶段 | 产物 | 路径 |
|------|------|------|
| Phase 3 技术搭建 | ARCHITECTURE / REVIEW / CONTROL_CHECKLIST / ADR-0001~0005 | `docs/architecture/` |
| Phase 5 测试框架 | 20+ 测试文件 | `tests/` |
| 工程规范 | CODE_WIKI / team_engineering_standards / user_manual | `docs/` |

---

## 二、门控阻塞项

| # | 阻塞项 | 证据 | 级别 | 状态 |
|---|--------|------|------|------|
| B1 | 可观测性缺失 | `run_unlimited_test.py` 与 `test_data/*.jsonl` 在 `E:\DS`（maxdepth 4）全盘搜不到 | P0 | 打回重做中 |
| B2 | 版本基线缺失 | `tasks/library/ZGUI.py` 曾为 `??` 未纳管；另 9 个文件改动未提交 | P0 | 核心操作已完成 |
| B3 | 背包判据未落地 | `ZGUI.py:794-810`，`_bag_visible` 仍用「物品数据计数 > 0」 | P1 | 待办（T3） |

### B2 处理结果（已验证）

| 项 | 结果 | 验证命令 |
|----|------|----------|
| 提交 | `2677663a6509afdbb93deb7a7e646b8b43a80d3b` | `git log -1 --stat` → `tasks/library/ZGUI.py \| 1417 +++`，1 file changed |
| 备份 | `backup/ZGUI.py.bak_20260903_1847`（58036 字节） | `ls -la backup/` |
| 边界 | 8 个改动文件全部仍为 `M` 未提交 | `git status --short` |

> ⚠️ 成员回传时把备份名误报为 `ZGUI.py.bak_20260903_1850`（不存在），实际为 `_1847`。commit message 中记录的是正确值。

---

## 三、★ 一致性偏差（主理人独立核查发现）

以下三条为「用户文档认知」与「代码实际」不符，是本轮最高价值发现。

### 偏差 1（P0）：「战斗中禁止 CALL 目标」防护在代码中不存在

**文档声称**（待办清单第四条）：
> zhuagui_click_ghost 开头查战斗，战斗中直接返回 False 不发包；zhuagui_enter_battle 的 CALL 轮询/重 CALL 前都查战斗；zhuagui_go_back_changan 开头战斗中等结束再回城。

**代码实际**：

`zhuagui_in_battle` 全文件仅 3 处出现，抓鬼链路中 **零调用**：

| 行号 | 出现形式 | 性质 |
|------|----------|------|
| `:99` | `"zhuagui_in_battle": {` | 函数导出表中的字符串 |
| `:1161` | `def zhuagui_in_battle(...)` | 定义 |
| `:1417` | `print("战斗中:", zhuagui_in_battle())` | `if __name__` 调试代码 |

`zhuagui_click_ghost`（`:1045-1084`）内部为直筒逻辑，无任何战斗判据：
```
查 tp.地图.地图单位 → 任务目标怪名双向匹配 → 客户端:发送数据(0,3,6,标识,1)
```

**影响**：用户反馈的「战斗中弹 call 目标提示框」问题，防护从未真正生效过。

### 偏差 2（P0）：`zhuagui_in_battle` 读的是恒空字段

```python
# ZGUI.py:1163
def zhuagui_in_battle(gateway=DEFAULT_GATEWAY, **kw):
    """是否已进入战斗。"""
    return _lua_call(gateway, '__out = tostring(tp.战斗中)') == "true"
```

`tp.战斗中` 正是用户判定为「本服恒空、永远 false、不可用」的字段。
**即使接上调用点，该函数也恒返回 False，防护等于没有。**

> 注：`:1166` 的 `zhuagui_enter_battle` docstring 标注「2026-09-03 判据修复」，但修复的是**完成判定**（改为任务栏次数递增/清空），`in_battle` 本身未修。

### 偏差 3（P1）：`_wait_task_done` 抽取未落地

- 全文件 grep `_wait_task_done` → **无匹配**
- 完成判定逻辑内联在 `zhuagui_enter_battle` 的 `:1207-1230` while 循环内
- 后果：其它需要完成判定的位置（如 `zhuagui_go_back_changan`）无法复用

### 附带发现（P2）：完成判定的「任务栏清空」分支可能被静默跳过

```python
# :1214-1217
if cur_cnt and cur_cnt != start_cnt:
    return True, "抓鬼完成"
if start_cnt > 0 and not (cur or {}).get("count"):
    return True, "抓鬼完成(任务栏已清空)"
```

`:1194-1196` 中 `start_cnt` 解析异常时置 0。当 `start_cnt == 0`，第二条判定的 `start_cnt > 0` 恒不成立 → **「任务栏清空」这条路直接死掉**，只剩「次数递增」一条路。

这可能是待办 #3「超时未完成」高频的隐藏放大器。

> 该隐患由 quality-lead-2 独立发现，与主理人独立核查结论一致。

### 偏差 4（P0，T2 收尾阶段补充）：「可靠战斗判据」引用的字段全仓库不存在

**文档声称**（待办清单第三节）：
> 可靠判据 zhuagui_in_battle()：tp.战斗类.参战单位 非空 且 敌方数量>0（脱战实测 参战单位 pairs=0 → false，已生效）。

**代码实际**：`tp.战斗类` / `参战单位` / `敌方数量` / `背景显示` 四个字段在业务代码中 **grep 零命中**（主理人复核确认；仅 T2 新建的测量工具 `run_unlimited_test.py`、`tools/zhuagui_stats.py` 引用它们——探针按「字段可能不存在」用 pcall 包裹设计）。

**含义**：用户文档第三节描述的「可靠判据」**从未在本仓库落地过**，可能来自其它项目口径（MPCG？网关侧？）或记忆中的计划。结合偏差 1+2（`zhuagui_in_battle` 用恒空字段 `tp.战斗中` 且抓鬼链路零调用），**「战斗判定」一节描述的是设想中的代码，不是 ZGUI.py 里存在的代码**。

**对 T4 的影响**：实测要回答的第一问题是「`tp.战斗类` 这组字段在本服客户端（胖子西游）是否根本不存在」。探针把「字段存在性」本身记录为观测结果，第一轮实测即可定性。若不存在，需从 `tp.窗口.*` / `tp.场景.*` 等已知存在的命名空间里另找战斗信号。

### 其它次要不一致（T2 收尾发现，P2）

| 项 | 文档/提示 | 代码实际 |
|----|-----------|----------|
| timeout 默认值 | GUI `__function_meta__` 描述写「默认8」（:47/57/73/108） | 签名默认 20.0（:777）——GUI 用户看到的是过时提示 |
| 接任务两套并存 | — | `zhuagui_take_task`(:339，旧版固定坐标) 与 `zhuagui_take_task_v2`(:690，红字检测)；链路实际走 v2，旧版仍可被 GUI 单独调用 |
| 完成判定可复用性 | 「战斗中也可复用」 | 内联于 `zhuagui_enter_battle`，无公共函数（同偏差 3） |
| 跑批与 zhuagui_loop 关系 | — | `zhuagui_loop`(:1294) 内置失败重试（回长安+取消重接，max_retry=3）；跑批启动器有意绕开它直接调 `do_round`，保证每轮测量独立——**这是正确设计** |
| fail_stage 盲区 | — | `zhuagui_click_option` 恒返回 True → 「点回地府」永远不会被记为失败环节，点空的后果一律表现为「完成判定」超时 |

---

## 四、任务看板

| ID | 任务 | 优先级 | 依赖 | 状态 |
|----|------|--------|------|------|
| T1 | 版本基线：备份 + git 纳管 ZGUI.py | P0 | — | ✅ 已关闭 |
| T2 | 可观测性：启动器 + jsonl 日志 + 统计 + 口径 | P0 | — | ✅ 已关闭（口径文档由主理人依成员代码兜底落盘） |
| T3 | 背包判据：`_bag_visible` 改用本类开关 | P1 | T1, T2 | 待启动 |
| T4 | 战斗判据：真战斗中参战单位实测 | P1 | T2 | 待启动（关键路径） |
| T5 | 完成判定：修复超时误判 + A/B 验证 | P1 | T2 | 待启动 |
| T6 | 战斗防护：把判据真正接入抓鬼链路 | P0 | T4 | 待启动 |
| T7 | 抓鬼坐标点 (327,345) 与 jitter 抖动 A/B 验证 | P1 | T2 | 待启动（**建议优先于 T5**） |

**关键路径说明**：

1. T6（修复偏差 1+2）依赖 T4 的实测结论——不知道正确的战斗判据就动手改，等于引入新的漏判。因此 T4 优先级高于原待办排序。
2. **T7 建议排在 T5 之前**：T5 调 timeout 只是缓解「任务栏刷新滞后」的表象；若根因是坐标点偏（本该成功的轮次直接失败），调 timeout 永远治不好。

---

## 五、已知风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 成员侧 Write 工具静默失败（返回 success 但磁盘无变化，已复现 3 次） | 成员声称完成但文件未落盘 | 主理人独立核查文件存在性 + 时间戳，未落盘一律打回；改走 PowerShell `Set-Content` 绕过 |
| 调度层 `engineering-lead` / `quality-lead` agent 类型不可用 | 专业角色无法直接 spawn | 改用 general-purpose + prompt 内注入角色指令 |
| 调度层 general-purpose 无 Bash 工具 | 命令操作失败 | 改用 PowerShell 工具 |
| 改 `_bag_visible` 可能误触发 `_bag_ensure_open/close` 点击背包按钮 | 违反「背包保持打开」硬约束 | T3 交付需评估该影响 |
| 加大 timeout 使节奏规律化 | 反外挂识别导致掉线 | T5 需保持 15~30s/轮随机节奏 |
| 为验证 T7 而关闭 jitter 却不补随机化 | 反外挂识别导致掉线 | T7 需权衡「点击精度」与「反外挂」，不可简单归零 |

---

## 五·补 现存代码高危项（T1 顺带发现，待用户拍板）

详见 `S0-version-baseline.md` 第 4 节。以下两条为 🔴 最高危，**属于现存代码问题，与本次提交决策无关**：

1. **`WORLD_BOSS._dismiss_offline_dialog()` 会误点全系统窗口**
   收集标题为「下线通知」「验证错误」**或 `t.strip() == "确定"`** 的全系统窗口。正常路径按 `game_pid` 过滤；但**兜底分支（PID 未绑定时）**会对所有命中窗口发 `WM_COMMAND`/`BM_CLICK`/回车 → 误点其它程序的「确定」按钮。
   *建议*：兜底前先判 `game_pid` 有效性，或限定窗口类名/进程名。

2. **`core/relogin.py` 未纳入版本库，但被顶层 import**
   `gui/config_panel.py:53` 顶层 `from core.relogin import DEFAULT_CLICK_POINTS as _DEFAULT_RELOGIN_POINTS`，而 `core/relogin.py` 当前为 `??` 未跟踪。二者不同时进版本库 → 任何 `git clone`/回滚/切分支后**启动 GUI 即 ImportError 崩溃**。
   *建议*：三个文件（`core/relogin.py` + `gui/config_panel.py` + `gui/main_window.py`）同进同出，或先都不提交。

另需注意：`data/task_sequence_autosave.json` 是运行时自动存档却已被 git 跟踪；两个 `settings.json` 混入了窗口标题/PID/角色名等运行时状态。二者建议后续移出版本库或加 `.gitignore`。

---

## 六、硬性约束（所有成员遵守）

- 只能后台操作（PostMessage / WM_MOUSEMOVE 贝塞尔轨迹），**禁止抢前台真实鼠标**
- **禁止使用「托管」功能**
- 背包保持打开，不得关闭
- 关闭对话框只右键一次（最多 2 次换位）
- 鼠标点击必须随机偏移，节奏 15~30s/轮
- Lua RPC 间隔 ≥0.15s 随机抖动；`发送客户端:发送数据` 前加 0.2~0.6s 延迟且只发一次
- 天眼瞬移落点需校验 `tp.地图.地图名称 == 目标地图`，不等则回长安重接
- ★禁用 `tp.战斗中` 判成功或判战斗（本服恒空）
- 组队规则：二号美人 = 队长；组员用 `member_mode=True`，不碰钟馗不退队
