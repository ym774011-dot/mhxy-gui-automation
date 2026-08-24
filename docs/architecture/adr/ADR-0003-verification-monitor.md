# ADR-0003 · `verification_monitor`（验证码监控）接入策略

- **状态**：提议（Proposed）— **待主理人 / 用户豁免或排期**（当前为阻断项，见 REVIEW.md）
- **范围**：验证码 / 防卡死监控的接入方式与生命周期
- **关联缺陷**：已知缺陷 #1
- **证据**：`core/verification_monitor.py` **不存在**（grep 仅命中 `docs/code_quality_audit.md` + `logs/automation.log`）；审计 P0#1（2026-08-03 整体移除）；`logs/automation.log` 数千条 `验证码监控启动失败: VerificationMonitor.start() got an unexpected keyword argument 'log_callback'`

## 背景（Context）
- `core/verification_monitor.py` 模块已**整体移除**（审计 P0#1，`docs/code_quality_audit.md:29` 收尾说明）。移除前它**从未真正工作**——`task_engine.py` 旧 `start()` 调 `vm.start(log_callback=...)` 传了非法关键字参数，且被 `except Exception: pass` 吞掉，导致监控线程从未启动（`logs/automation.log` 自 2026-07-31 起数千条启动失败）。
- **现状**：当前引擎**没有任何**验证码 / 防卡死监控。任务运行时遇验证码弹窗会**卡死 / 失控**（审计 P0#1 影响列）。
- 这是 5 个已知缺陷中唯一**功能缺失（安全网真空）**项，其余 4 项均为"已存在但需固化/收敛"。

## 决策（Decision，推荐方案，待定）
**重接入，但重写为"引擎内轻量探测 + 信号上报"模型，而非旧独立线程模块：**
1. **不**在 `core/` 重建旧 `VerificationMonitor` 线程类；改为在 `TaskEngine` 主循环或独立守护线程中，周期性探测验证码弹窗（基于 `image_recognition` 模板 / 状态识别），命中即通过专用 signal 上报 GUI，由 GUI 决策点击或暂停。
2. **与 `gateway_guard` 解耦**：验证码是客户端 UI 态，不依赖 frida gateway。
3. **接入点**：`TaskEngine.start()` 内启动、`stop()` 内停止；状态用 `threading.Event`（非裸 bool）；回调经 `log_signal`；**禁止裸 `except:` 吞异常**（审计 P0#8）。
4. **启动自检日志**：接入即打印"验证码监控已启动 / 已禁用"，不再静默失败。
5. **若用户接受"当前阶段不自动处理验证码、人工介入即可"**：显式标记为**已知豁免**，REVIEW 标 CONCERNS 而非 FAIL，并记录豁免理由与重新启用触发条件。

## 后果（Consequences）
- ✅ 恢复防卡死安全网，避免验证码弹窗导致整条任务链失控。
- ⚠️ 新增识别 / 状态探测逻辑与对应单测（核心识别模块当前零单测，审计 P3）。
- ⚠️ 若选"已知豁免"，则运行期遇验证码需人工介入，自动化连续性下降。

## 风险与缓解（Risks & Mitigations）
| 风险 | 缓解 |
|---|---|
| R1 重蹈旧覆辙（签名错被 `except` 吞） | 接入即补单测 + 启动自检日志；禁止空 `except`（`team_engineering_standards.md` 一.异常不吞） |
| R2 误判弹窗导致误点 | 命中阈值保守 + GUI 确认开关；首次命中先暂停待用户确认 |
| R3 与 `arrival_verifier` 职责重叠 | 职责分清：验证码=UI 态探测；到达=坐标态验证，互不替代 |
| R4 用户选择豁免后长期遗忘 | REVIEW 阻断项 + 在 `tasks.md` 建 issue 跟踪重新启用触发条件 |

## 后续
- **阻塞项**：本 ADR 不决，REVIEW 不得给 PASS（见 REVIEW.md Blocking Items B1）。
- 主理人 / 用户须二选一：① 排期 Phase 4 实现推荐方案；② 显式豁免并登记触发条件。
