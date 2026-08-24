# ADR-0001 · IPC 数据流门控边界

- **状态**：已采纳（Accepted）— 现有实现已符合，需固化以防回归
- **范围**：任务引擎所有「成功后才执行 X」链路的出向动作（上报 / 落盘 / 广播）
- **关联缺陷**：已知缺陷 #3
- **证据**：`core/task_engine.py:2026-2030`、`core/task_engine.py:721-791`（`_maybe_emit_quest_detail`）、`docs/code_quality_audit.md` P0#1

## 背景（Context）
任何"成功后才执行 X"的链路都要警惕 **"验证 / 重试阻断数据流"**：
- 验证（result_validate）/ 到达等待（_check_auto_wait_arrival）只应决定是否**重试**，不该决定是否**上报**。
- 历史实现中 `_maybe_emit_quest_detail` 已在 `_execute_function_call` 的验证**之前** emit（`task_engine.py:2026-2030` 注释明确："必须在 validate 之前，否则验证失败/重试耗尽时 result 永远不会到 StatusPanel"），保证数据流稳定。
- 但若未来新增"图像识别成功→落盘""到达成功→通知"等出向动作，容易重犯"放在重试循环尾部"的错误，导致外部进程（StatusPanel / 读 `data/current_quest.json` 的脚本）饿死。

## 决策（Decision）
固化**门控边界**：**上报 / 落盘 / 广播（所有 IPC 出向）必须发生在任何验证 / 重试 / 到达等待门控之前。**
1. 函数调用成功后顺序固定为：`_auto_store_location` → `_maybe_emit_quest_detail`（上报）→ 再做 `result_validate` / `_check_auto_wait_arrival`（门控）。
2. 任何新增出向动作（写文件、发信号、推外部进程）一律置于重试 / 验证循环体**首部**，而非尾部。
3. 验证失败的 result 也**带数据进 IPC**（便于用户观察"函数本身能跑出啥"），重试用最新 result 覆盖。
4. 门控只影响"是否重试 / 是否继续"，**绝不**影响"是否上报"。

## 后果（Consequences）
- ✅ 数据流与重试解耦：外部进程始终能拿到最新一次成功结果，不会因验证 / 到达失败而饿死。
- ⚠️ 可能**多次 emit** 同类数据（重试时覆盖）——接收方（`StatusPanel`、读取 `current_quest.json` 的脚本）须**幂等**（用"最新覆盖"语义）。
- ⚠️ 约束需靠 PR review 守住，否则随代码增长被遗忘。

## 风险与缓解（Risks & Mitigations）
| 风险 | 缓解 |
|---|---|
| R1 重复 emit 导致接收方抖动 | `current_quest.json` 用"最新覆盖"语义；StatusPanel 仅渲染、不累加 |
| R2 未来新增链路遗忘此约束 | CONTROL_CHECKLIST 增「新增出向动作须在门控前」勾选项；code review 必查 `task_engine.py` `_execute_*` 的 emit 顺序 |
| R3 验证失败仍 emit 造成"假成功"误读 | emit 字段仅含原始识别结果，不含"已验证通过"标记；是否通过由后续到达验证单独体现 |

## 后续
- 本 ADR 不要求改代码（已实现正确）；仅要求 Phase 4/5 在 CONTROL_CHECKLIST 与 GUI/手册中固化。
