# 架构评审门 · `mhxy-gui-automation`（Phase 3）

> 评审人：程基岩（engineering-lead）｜ 依据：`docs/architecture/ARCHITECTURE.md` + `adr/ADR-0001..0005` + 本次全量代码通读
> 评审对象：当前 `core/` 架构（task_engine 拆 3 Mixin 后）对 5 个已知系统级缺陷的应对
> 配套：Phase 4/5 门禁见 `CONTROL_CHECKLIST.md`

---

## 0. 判定

# ✅ PASS（带登记豁免 · 主理人终裁 2026-08-24）

**不是 FAIL**：无构建阻断、无启动崩溃、核心数据流（IPC 门控）已正确固化（ADR-0001 ✅）。
**B1 已决**：用户对 B1 显式豁免（2026-08-24），原阻断项消除，本评审升 **PASS（带登记豁免）**；C1–C3 为工程债，进入 Phase 4/5 排期（见 CONTROL_CHECKLIST）。

> 若主理人 / 用户对 **B1 显式豁免**（接受当前阶段不自动处理验证码、人工介入），则本评审可升为 **PASS（带登记豁免）**；豁免条件与重新启用触发点见 B1。

---

## 1. 阻断项（Blocking Items）— 须在主理人 / 用户处置前不得进入 Phase 4 收口

### B1 · `verification_monitor` 接入策略未决（缺陷 #1）
- **事实**：`core/verification_monitor.py` 已整体移除（审计 P0#1，2026-08-03），且移除前从未工作（`logs/automation.log` 数千条 `VerificationMonitor.start() got an unexpected keyword argument 'log_callback'`）。当前引擎**无任何验证码 / 防卡死监控**，遇验证码弹窗会卡死 / 失控。
- **为什么阻断**：这是 5 个缺陷中唯一的**功能缺失（安全网真空）**，其余 4 项均为"已存在须固化"。
- **处置二选一（由主理人 / 用户拍板）**：
  - **① 排期**：Phase 4 按 ADR-0003 推荐方案重接入（引擎内轻量探测 + 信号上报，禁用旧线程类，禁裸 `except`）。
  - **② 豁免**：显式登记"当前阶段不自动处理验证码、人工介入"，并在 `tasks.md` 建 issue 记录**重新启用触发条件**（如某次私服更新开始频繁弹验证码）。豁免后评审升 PASS。
- **证据**：`docs/code_quality_audit.md:29`、`:32`、`:51`；`logs/automation.log` 全局；`adr/ADR-0003-verification-monitor.md`。

---

## 2. 关注项（Concerns）— 不阻断收口，但须在 Phase 4/5 排期

### C1 · 核心识别 / 坐标模块零单测（审计 P3）
- `image_recognition` / `glyph_recognizer` / `glyph_coord_reader` / `jhrw_controller` / `arrival_verifier` / `game_coord_reader` **零单测覆盖**（审计 P1 扩展末段）。改一行全靠手点游戏验证，回归风险高。
- **建议**：Phase 5 优先补 `core` 纯函数单测（变量解析、坐标换算、事件分发、到达验证）。当前 `217 passed` 不含上述模块。

### C2 · 停止 / 暂停用裸 `bool` 非 `threading.Event`（审计 P3）
- `TaskEngine.should_stop` / `is_paused` 为裸 bool（`core/task_engine.py` 主循环 `:443/:460/:463` 等），非 `team_engineering_standards.md` 一.要求的 `threading.Event`（可见性更稳）。
- **建议**：Phase 4 低风险改为 `threading.Event`；属工程债，非本次阻断。

### C3 · `_last_result` 约定靠人守（缺陷 #2）
- `source_var` 机制已部分缓解（`switch_mixin.py:52`），但约定依赖人工遵守 + GUI 警告（ADR-0002 后续）。旧序列若用 `${result}` 跨分支会静默失败。
- **建议**：Phase 4 在 GUI 编辑器实现跨分支 `${result}` 警告；Phase 5 补 `_resolve_value` / `_search_var_for_path` 单测反例。

---

## 3. 已固化 / 通过项（Passed）

| 项 | 证据 | 结论 |
|---|---|---|
| IPC 数据流门控（缺陷 #3） | `task_engine.py:2026-2030` emit 在 validate 前 | ✅ 已实现正确，ADR-0001 固化 |
| 后台点击坐标系统一（缺陷 #5） | `ALG.py:186-196` 抖动收敛、`task_engine.py:1899` 跨包置位、`input_controller.py:891` 纯 PostMessage 默认 | ✅ 约定已收敛，ADR-0004 待集中重构 |
| 距离评分跨类别（缺陷 #4） | `arrival_verifier.py:583` / `sect_task_recognizer.py:167` / `yolo_detector.py:292` 均按类别隔离 | ✅ 已隔离，ADR-0005 防回归 |
| 架构分层 / 单例 / 坐标体系 | 审计 strengths；`window_manager` 单例；客户区坐标统一 | ✅ 底子良好 |
| 引擎巨型文件拆分 | `全项目优化报告.md` 问题2：task_engine 3331→2488 行，3 Mixin | ✅ 已完成，31/31 测试通过 |

---

## 4. 建议优先级（Phase 4/5 排期）

1. **P0（立即）**：B1 决策（排期 or 豁免登记）。
2. **P1（Phase 4）**：ADR-0004 抖动逻辑集中重构；C2 停止标志改 `threading.Event`；ADR-0002 GUI 跨分支警告。
3. **P2（Phase 5）**：C1 核心模块单测；ADR-0002 变量解析单测反例；ADR-0003 实现（若选排期）。
4. **持续**：CONTROL_CHECKLIST 门禁在每次 PR 对照勾选。

---

## 5. 评审方法说明（诚实性）
- 本次为**静态架构评审**：通读 `core/`、`library/`、`tasks/library/`、`models/`、`docs/`，未运行游戏端到端。
- 行号证据来自本次快照；如后续重构致偏移，以「函数名 + 语义」为准。
- 未修改任何业务代码（符合 Phase 3 约束）。

---

## 6. 门控终裁（主理人 · 游承峰 · 2026-08-24）

- **处置**：用户对 B1 **显式豁免**——接受当前阶段不自动处理验证码、依赖人工介入（用户已有独立 `captcha_monitor.py` 外部监控 + 手动解谜）。
- **终裁判定**：原 **CONCERNS → PASS（带登记豁免）**。
- **豁免理由**：个人私服脚本场景下，验证码由用户侧外部监控 + 手动解谜覆盖，引擎内未接入验证监控为可接受缺口。
- **重新启用触发条件**（已登记 `tasks.md` Issue VM-EXEMPT）：当某次私服更新开始频繁弹验证码、或 `captcha_monitor.py` 无法覆盖时，须按 ADR-0003 在 Phase 4 重接入引擎内轻量探测 + 信号上报。
- **其余 C1–C3**：工程债，不阻断，进入 Phase 4/5 排期（见 CONTROL_CHECKLIST）。
