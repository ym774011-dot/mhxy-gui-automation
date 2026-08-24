# 控制清单 · 合并 / 评审 / 门控（Phase 4/5 用）

> 依据：`docs/architecture/ARCHITECTURE.md` + `adr/ADR-0001..0005` + `docs/team_engineering_standards.md` + `docs/code_quality_audit.md`
> 用法：每次 PR / 合并前逐条勾选；涉及 `core/task_engine.py` 的改动须 senior 复核（standards 二）。

---

## A. 架构一致性（每次改动必查）

- [ ] 新增模块 / 函数**有调用方**，或注明 TODO + 建 issue（禁止"写了没接上"）。
- [ ] 命名诚实：类型 / 函数名反映真实行为（如 `YOLO` 事件不偷偷走模板匹配）。
- [ ] 无死配置：params 字段必须被消费，否则删或实现。
- [ ] 不复制粘贴：>~15 行重复逻辑抽 `_do_xxx` / 公共模块。
- [ ] 坐标体系一致：GUI / 输入 / 截图统一**客户区坐标**，禁止混用屏幕坐标。
- [ ] 无 scratch 文件进 `main`（一次性 patch / 备份副本移 `scratch/` 或删）。
- [ ] 类型注解 + docstring：公开函数签名加 `typing`。

---

## B. 门控专项（对应 5 个 ADR）

### B1 · IPC 数据流门控（ADR-0001）— 任何"成功后才 X"链路
- [ ] 上报 / 落盘 / 广播（IPC 出向）在**验证 / 重试 / 到达等待之前**发出（`task_engine.py:2026-2030` 模式）。
- [ ] 新增出向动作置于重试 / 验证循环体**首部**，非尾部。
- [ ] 接收方（`StatusPanel` / 读 `current_quest.json`）对重复 emit **幂等**。
- [ ] code review 必查 `_execute_*` 的 emit 顺序。

### B2 · 变量作用域（ADR-0002）— 跨事件引用
- [ ] 上游函数事件设 `var_name`；下游用显式 `${<var_name>.field.sub}`（如 `${JHRW.target_coord.0}`）。
- [ ] 分支 / 函数链后**禁止**裸 `${result}`/`${last_result}` 取上游结构体字段。
- [ ] switch/condition 显式传 `source_var`（`switch_mixin.py:52`），不依赖通用搜索兜底。
- [ ] GUI 编辑器对"跨分支用 `${result}`"给出**警告**。

### B3 · 验证码监控（ADR-0003）— 若实现
- [ ] 引擎内轻量探测 + 信号上报，**不**重建旧 `VerificationMonitor` 线程类。
- [ ] `TaskEngine.start()` 启 / `stop()` 停；状态用 `threading.Event`。
- [ ] 禁止裸 `except:` 吞异常；启动有自检日志（不再静默失败）。
- [ ] 与 `gateway_guard` 解耦（验证码是 UI 态，不依赖 frida）。
- [ ] 接入即补单测；命中阈值保守 + GUI 确认开关。

### B4 · 坐标与抖动（ADR-0004）— 后台点击
- [ ] 后台点击经统一入口（`_do_click`→`input_controller._post_click` 或包内 `_click_background`），不绕过。
- [ ] 抖动偏移在**游戏坐标**域计算，落点转客户区像素再 PostMessage。
- [ ] 抖动逻辑已集中（无 9 份复制）；`cursor_sync_click` 默认 `False`，IAT hook 作废。
- [ ] 跨包置位经**共享状态**，非遍历各模块 `_JITTER_MODE`。

### B5 · 距离评分（ADR-0005）— 匹配逻辑
- [ ] 新增 quest / 字段匹配**按类别隔离**匹配策略（map/npc/coord 各自独立），不混一。
- [ ] 跨字段匹配须**字段对齐**，不靠"整体距离最小即命中"。
- [ ] 附单测覆盖"地图相近但 NPC 不同"反例。
- [ ] `_calc_distance` docstring 标明"仅坐标到达验证用途"。

---

## C. 线程安全与可观测性

- [ ] 跨线程共享状态用 `Lock`/`RLock`；停止 / 暂停标志用 `threading.Event`（**非裸 bool**，见 C2 / REVIEW）。
- [ ] 异常不吞：`try/except` 至少 `logger.error` 或向上抛；禁止空 `except:`。
- [ ] 任务路径可从彩色日志完整还原（唯一运行时可观测性）。
- [ ] `quest_detail_signal → data/current_quest.json` 链路不被破坏。

---

## D. 测试门槛（Phase 5）

- [ ] `core` 纯函数补单测：变量解析、坐标换算、事件分发、到达验证（C1）。
- [ ] 新增 / 修改核心逻辑附最小验证（游戏相关手写验证清单即可）。
- [ ] `pytest` 全绿（既有陈旧失败 `test_input_key_map ×4` / `test_jhrw_coord_fallback ×1` 须先修或标注已知）。
- [ ] 涉及 `core/task_engine.py` 改动：senior 复核通过。

---

## E. 合并 / PR 约定（standards 二）

- [ ] `main` 受保护，禁止直接 push；功能分支 `feat/fix/refactor/*`。
- [ ] PR 关联 issue + 改动动机 + 最小验证步骤。
- [ ] ≥1 reviewer 通过；`core/task_engine.py` 改动需 senior 复核。
- [ ] pre-commit（black + isort + flake8）通过。

---

## F. 豁免登记（REVIEW B1）

- [ ] 若对验证码监控**豁免**：在 `tasks.md` 建 issue，记录豁免理由 + **重新启用触发条件**。
- [ ] 豁免后 REVIEW 判定可升 PASS（带登记豁免）；否则维持 CONCERNS 直至 B1 处置。
