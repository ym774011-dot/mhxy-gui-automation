# P1 #2 / P1 #3 收口概览

## 复验（先校正过时审计，避免白做）
| 审计项 | 原结论 | 实际代码 | 处置 |
|---|---|---|---|
| **P1 #3** condition 真分支 | 「true/false 从不被执行 / switch 直接点」 | simple 模式递归执行分支事件序列；switch 由 `_execute_switch_actions` 跑完整 `actions` 子流程（前序分流改造已落地） | **审计过时，已确认落地**，补运行时测试锁住 |
| **P1 #2** YOLO 真推理 | 「从未调用 yolo_detector」 | 代码确实调了 `yolo.detect()`，但成功分支**无视 `action`、永当 record** | **真缺口在"检测后不执行"**，已修 |

## P1 #2 修复（core/task_engine.py）
- 新增 `_yolo_pick_target(results, target_class)`：按 `target_class` 过滤取最高置信度目标。
- 新增 `_execute_yolo_action(yolo, results, params)`：
  - `click`：点最佳目标中心（`_do_click`）+ 可选附加点击（`_do_additional_click`）
  - `wait`：轮询检测直到目标出现，命中后可选 `click_on_found`
  - `record`/其它：返回检测结果
- `_execute_yolo_detect` 推理成功后改调 `_execute_yolo_action`；**仅当模型真不可用时**才降级模板匹配（修复前是"检测到即 return 结果"，action 永远无效）。

## 新增回归测试（8 passed）
- `tests/test_yolo_executor.py`（5）：mock yolo_detector 证明真推理路径被选中并按 action 点击/等待、target_class 过滤、record 返回、模型缺失降级。
- `tests/test_condition_branch_runtime.py`（3）：simple true/false 分支子流程执行 + switch 子流程执行（运行时验证分支内事件被真实调度）。

## 验证
- 整库 pytest **141 passed**（133 + 8；排除 `test_yolo_detector.py`——torch/c10.dll 环境 DLL 故障，与本修复无关）。
- 行为零变化：降级模板路径逻辑未动；condition 分支逻辑未动，仅新增测试锁住。

## 注意
- YOLO 在用户 GUI 环境仍可能因 torch DLL 冲突（重启 GUI 即恢复）而走降级——那是环境故障，非代码 bug。本修复保证：一旦模型真能加载，YOLO 事件将**检测并真正执行动作**，不再"选 YOLO 得模板匹配"。
- `click_on_found` 为新参数（wait 模式可选），编辑器 YoloParamPage 暂未暴露，按需再加。
