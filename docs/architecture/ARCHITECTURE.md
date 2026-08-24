# 架构文档 · `mhxy-gui-automation`（Phase 3 技术搭建）

> 作者：程基岩（engineering-lead）｜ 阶段：Phase 3 技术搭建（ARCH-001）
> 基准：`core/` 当前快照（task_engine.py ≈ 2488 行，已拆 3 个 Mixin）+ 全量 `docs/` + `library/` + `tasks/library/` + `models/`
> 配套文档：`docs/architecture/adr/ADR-0001..0005`、`REVIEW.md`、`CONTROL_CHECKLIST.md`
> 关系：**整合**既有 `docs/code_quality_audit.md`、`docs/team_engineering_standards.md`、`docs/全项目优化报告.md`、`docs/梦幻主线程Hook可行性分析.md`、`docs/location_container_usage.md`，不重复其结论，仅把「系统级缺陷」落到架构决策（ADR）与门禁（CONTROL_CHECKLIST）。

---

## 0. 文档约定

- **坐标体系**（全项目唯一事实）：所有 GUI / 输入 / 截图统一使用「**客户区坐标**」（client-area），由 `window_manager.get_client_rect()` 对齐（`docs/team_engineering_standards.md` 七.Q；`core/input_controller.py:727-739` 的 `_make_mouse_lparam`）。屏幕坐标仅在 `client_to_screen` 转换时短暂出现（`input_controller._sync_cursor` `core/input_controller.py:812`）。
- **证据格式**：`文件:行号`。行号来自本次通读时的快照，若后续重构导致偏移，以「函数名 + 语义」为准。
- **单例清单**：`window_manager`、`input_controller`、`task_library`、`task_engine`、`jhrw_controller`、`get_global_location_container()`、`OCREngineManager`、各 `map_packs` 模块级状态（`_JITTER_MODE`）。

---

## 1. 系统总览

一个《梦幻西游》**GUI 自动化 / 客户端逆向工程工具**：不侵入游戏内存地址（内存路线已被证不可靠，见 `tasks/library/JHRW.py:5-6` 注释），改用「**截图 → 字模/模板/YOLO 识别 → 解析任务数据 → 后台 PostMessage 模拟点击/键盘 → galaxy2d 客户端响应**」的闭环。

技术栈：Python 3 + PyQt5（GUI/信号槽）+ OpenCV（模板匹配/字模）+ ultralytics YOLO（模型 `models/active.pt`）+ frida gateway（`mhxy-mcp-gateway`，外部进程，直连游戏 Lua 态）+ win32 PostMessage（后台输入）。**所有核心模块为单例**（审计 strengths 已确认此点用得对）。

逆向补充路线：主线程 Hook 已做可行性验证（`docs/梦幻主线程Hook可行性分析.md`），但**当前生产路径未启用**——生产路径是纯视觉 + 后台点击。

---

## 2. 模块拓扑

```
┌──────────────────────────────────────────────────────────────────────────┐
│                               GUI 层 (PyQt5)                                │
│  main.py → gui/ (config_panel / status_panel / task_library /              │
│          event_editor / param_pages / subflow_editor / window_selector)    │
│  职责：配置事件/序列、呈现日志、落盘 data/current_quest.json              │
└───────────────┬──────────────────────────────────────────┬───────────────┘
                │ 构造 TaskSequence(Event[])                  │ 用户点击"启动"
                ▼                                              ▼
┌─────────────────────────────────── 核心引擎层 (core/) ───────────────────────────────────┐
│  TaskEngine(QObject, 单例) ── 继承 (ClickMixin, YoloMixin, SwitchMixin)                    │
│   │  _execute_event → _dispatch_with_retry → _execute_*（click/image/yolo/                 │
│   │        function/condition/wait/key）                                                        │
│   │  _run_sequence / _run_task（循环调度，task_engine.py:446-502）                            │
│   │                                                                                          │
│   ├─ 变量与跨事件引用 ── _var_context(VarContext) + _last_result + _location_container       │
│   │     _resolve_value(task_engine.py:529) / _save_to_context(:693) /                        │
│   │     _search_var_for_field(:1539) / _search_var_for_path(:1594)                           │
│   │                                                                                          │
│   ├─ 识别子系统 ── image_recognition / glyph_recognizer / glyph_coord_reader /               │
│   │     jhrw_controller / sect_task_recognizer / yolo_detector                                │
│   ├─ 到达验证 ── arrival_verifier（_calc_distance 曼哈顿，:583；按距离估算超时）             │
│   ├─ 输入 ── input_controller（_post_click / _post_double_click / _post_message）            │
│   ├─ 窗口 ── window_manager（单例，client_rect/client_size，坐标转换）                       │
│   ├─ 网关自愈 ── gateway_guard（ensure_gateway，attach 游戏 PID）                            │
│   └─ 任务库 ── task_library_manager（单例，加载 library/ 下模块）                            │
└───────────┬──────────────────────┬──────────────────────┬───────────────────┬──────────────┘
            │ 调用函数              │ 读任务追踪栏          │ 自愈/attach         │ 后台点击
            ▼                      ▼                      ▼                     ▼
┌──────────────────┐  ┌────────────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐
│ library/ 任务库   │  │ tasks/library/ 任务序列  │  │ mhxy-mcp-gateway │  │ 游戏客户端 (十年一梦.exe) │
│  map_packs ×10    │  │  JHRW/JHRW1/SYBUZ2/      │  │  (外部进程, frida)│  │  galaxy2d.dll 自绘引擎   │
│  (ALG..ZZG+MPCG)  │  │  HCA/SYHS              │  │  :18082 REST      │  │  ← PostMessage WM_*      │
│  _click_background│  │  复用上述事件类型        │  │  lua 态捕获       │  │  ← GetCursorPos 命中检测 │
│  + _JITTER_MODE   │  │                        │  │                  │  │    (光标同步默认关闭)    │
└──────────────────┘  └────────────────────────┘  └──────────────────┘  └─────────────────────────┘
            │                      │                        │                     ▲
            └──────────────────────┴──────── 坐标文件 data/地图坐标.txt ────────┘
                                  （JHRW 读任务坐标 → 下游 JYC/JNYW/DHW 等按此执行，
                                   见 task_engine.py:1899 _set_map_jitter_mode 跨包置位）
```

**关键目录事实（本次通读确认）**：
- `library/map_packs/` 共 **10** 个包：`ALG/BXG/CAC/CSC/DHW/JNYW/JYC/MPCG/XLNR/ZZG`。其中 **9 个含 `_click_background`**（ALG/BXG/CAC/CSC/DHW/JNYW/JYC/XLNR/ZZG，`library/map_packs/ALG.py:153` 等），`MPCG` 是识别包不含点击。
- `tasks/library/`：**5** 个序列：`HCA/JHRW/JHRW1/SYBUZ2/SYHS`。
- `gateway/` 目录**不在本仓库**（grep 确认）；`mhxy-mcp-gateway` 是项目外独立进程（`core/gateway_guard.py:31` `GATEWAY_DIR = r"E:\DS\mhxy-mcp-gateway"`），经 `127.0.0.1:18082` REST 通信。

---

## 3. 关键数据流

### 3.1 主任务闭环（任务引擎 ↔ 识别 ↔ 输入 ↔ 客户端）
```
用户启动 → TaskEngine.start()
  → _run_sequence(task_engine.py:446) 循环 task.events
    → _execute_event(:796) → _dispatch_with_retry(:832)
      → _execute_function_call(:1951)  // JHRW 读任务
         → task_library.call_function → library/tasks JHRW/JHRW1
           → jhrw_controller.read_state → glyph_coord_reader 读任务追踪栏(837,120,159,116)
         → _auto_store_location(:1930)  // 写入 _location_container
         → _maybe_emit_quest_detail(:721) → quest_detail_signal → StatusPanel → data/current_quest.json  ★IPC 门控点
         → result_validate / _check_auto_wait_arrival（arrival_verifier）  // 验证/重试门控（不阻断上报）
      → _save_to_context(:693)  // 写入 _var_context[var_name]
    → 下游 click/image/condition 事件引用 ${JHRW.target_coord.0} 等
    → _do_click(click_mixin.py:35) → input_controller._post_click(:860)
      → PostMessage(WM_LBUTTONDOWN/UP) → 游戏客户端响应
```
> ⚠️ **IPC 门控边界**：上报（`_maybe_emit_quest_detail`）在验证/重试**之前**发出（`task_engine.py:2026-2030` 注释明确："必须在 validate 之前，否则验证失败/重试耗尽时 result 永远不会到 StatusPanel"）。这是 ADR-0001 的核心约束。

### 3.2 后台点击链路（PostMessage + IAT/光标同步）
```
_do_click(click_mixin.py:35)
  → window_manager.is_valid() 检查窗口
  → input_controller.click(:103) → _post_click(:860)  [后台模式]
     → _wait_prev_click_done(:754)   // SendMessageTimeout(WM_NULL) 确认上一次点击已处理
     → 发 4×WM_MOUSEMOVE(间隔15ms)    // 驱动客户端内部 hover 状态
     → WM_LBUTTONDOWN(MK_LBUTTON) + press_delay(默认50ms) + WM_LBUTTONUP
     → 可选光标借出/归还(_borrow_cursor/:817, 仅 input.cursor_sync_click=True)
  （地图包内 _click_background 走更重的序列：左键(原)→2s→左键(抖动)→2s→左键(点回原)→右键，
   见 library/map_packs/ALG.py:153-230 + 抖动逻辑 :186-196）
```
> **IAT Hook 现状**：`tools/iat_hook_test.py` 等逆向工具存在，但**生产路径已废弃 GetCursorPos IAT hook**——实测导致游戏闪退（`core/input_controller.py:797-799` 注释："galaxy2d.dll 的 GetCursorPos 是运行时 GetProcAddress 动态解析，无 IAT 可 hook"）。当前默认 **纯 PostMessage（光标完全不动）**，`cursor_sync_click` 默认 `False`（`:891`、`:895`）。此为 ADR-0004 固化项。

### 3.3 网关自愈链路（gateway ↔ 客户端）
```
tasks/library/JHRW1 或 SYBUZ2 调用网关失败（WinError 10061）
  → ensure_gateway(pid=window_manager.pid)  [core/gateway_guard.py:125]
     → _status() 探活 / _ready() 判就绪(HTTP通+attach PID+lua_state_captured+无script_status_error)
     → 不匹配则杀旧进程(_kill_pid) → _spawn(pid) 拉起 pythonw gateway.py <PID> --port 18082
     → 轮询等待就绪（默认 timeout 90s）
```
> 多开/守护场景**严禁 `--auto`**（`gateway_guard.py:133-134` 注释），必须显式 PID 以避免 attach 错实例。

---

## 4. 单例边界与生命周期

| 单例 | 定义处 | 生命周期 | 线程安全 | 备注 |
|---|---|---|---|---|
| `task_engine` | `TaskEngine`（QObject，Mixin 多继承） | 进程级，GUI 持有 | `should_stop`/`is_paused` 用可见性 bool（**非** threading.Event，审计 P3 已标为待改进） | 引擎主循环在 worker 线程 |
| `window_manager` | `core/window_manager.py:40`（`_instance`+`_lock`） | 进程级 | 构造加锁；运行时 `pid`/`hwnd` 无写锁 | 坐标权威源 |
| `input_controller` | `core/input_controller.py` | 进程级 | `_post_message` 无内部锁（靠 hwnd 单绑） | 后台点击实现 |
| `task_library` | `core/task_library_manager.py` | 进程级 | `_lock` 保护模块表 | 加载 library/ |
| `jhrw_controller` | `core/jhrw_controller.py:417` 双检锁 | 进程级 | `_quest_reader` 懒加载 | 字模读取入口 |
| `_location_container` | `core/location_data_container.py`（`get_global_location_container`） | 任务级：start 重置 / end 清空（`docs/location_container_usage.md` 生命周期） | 文档称线程安全 | 跨事件位置数据 |
| `_JITTER_MODE`（每包） | `library/map_packs/*:147` | 进程级模块级标志 | 引擎 `_set_map_jitter_mode` 遍历置位（`task_engine.py:1899`） | **跨包全局副作用**，ADR-0004 须收敛 |

> **生命周期风险点**：`TaskEngine` 的停止/暂停用裸 `bool`（`should_stop`/`is_paused`），非 `threading.Event`——审计 `team_engineering_standards.md` 一.线程安全 已要求改用 `threading.Event`。此为 P3 工程债，非本次阻塞，但列入 CONTROL_CHECKLIST 门禁。

---

## 5. 变量与跨事件引用机制

- 每个事件执行成功后写 `_var_context[event.var_name]`（`_save_to_context` `task_engine.py:693-719`）；`var_name` 缺省由事件名生成。
- 解析 `${a.b.c}`：`_resolve_value`（`:529`）→ 根对象判定：`location.*`→位置容器（`:556`）；`last_result`/`result`→`self._last_result`（`:592`）；否则 `_var_context` 或位置容器。
- 分支专用：switch/condition 支持 `source_var`（`switch_mixin.py:52`）显式指定来源变量，避免 `_search_var_for_field`（`:1539`）在多个变量中"碰运气"取错值。
- **陷阱**：`switch`/`condition` 事件的结果 dict（`{"matched":..,"match_value":..}`）会覆盖 `self._last_result`（`:475` 每事件后赋值、`:717/719` `_save_to_context` 也写）。故 switch 之后 `${result.target_coord.0}` 会解析失败——必须用显式 `${JHRW.target_coord.0}`。**此为 ADR-0002 固化项。**

---

## 6. 已知缺陷与对策（映射 ADR）

| # | 缺陷（带证据） | 严重度 | 对策 ADR | 现状 |
|---|---|---|---|---|
| 1 | `verification_monitor` 未接入引擎：`core/verification_monitor.py` **不存在**（grep 仅命中 `docs/code_quality_audit.md` + `logs/automation.log`；审计 P0#1 确认该模块 2026-08-03 整体移除）。日志显示旧接线 `VerificationMonitor.start() got an unexpected keyword argument 'log_callback'` 数千次——**从未真正工作** | 高（安全网缺失） | **ADR-0003** | 待重接入决策 |
| 2 | `_last_result` 被 switch 覆盖陷阱：`task_engine.py:475 / :717 / :719`（写）与 `:592/593`（读）；switch 结果 dict 覆盖上游结果 | 中（约定依赖） | **ADR-0002** | `source_var` 机制已部分缓解（switch_mixin.py:52） |
| 3 | IPC 数据流门控：`_maybe_emit_quest_detail` 已在验证前 emit（`task_engine.py:2026-2030`），数据流稳定 | 已固化 | **ADR-0001** | ✅ 已正确 |
| 4 | 内存距离评分不可跨类别复用：距评对同类灵、跨类失灵（静态 quest 对象 vs live quest 字符串可能距离反转）；现有评分均按类别隔离（`arrival_verifier._calc_distance` `:583` 仅用于到达；`sect_task_recognizer._match_map_template` `:167` 仅地图名；`yolo_detector` 按类距离升序 `:292`） | 中（潜在） | **ADR-0005** | 设计约束，尚无统一 quest 匹配器 |
| 5 | 后台点击坐标系统一：9 个地图包各自实现 `_click_background` + `_JITTER_MODE` 抖动（`library/map_packs/ALG.py:147,153,186-196`），存在各包各自为政风险 | 中（复制/漂移） | **ADR-0004** | 抖动约定已收敛，但实现未集中 |

> 另：审计报告 P1#4（两套重试计数 `_dispatch_with_retry` 不消费 verify 的 `retry_times`）、P3（核心识别模块零单测）等作为工程债并入 CONTROL_CHECKLIST，不在此重复。

---

## 7. 测试与可观测性现状

- **单测**：`docs/全项目优化报告.md` 报告 **217 passed**（5 个失败为陈旧：`test_input_key_map ×4` 缺 `_KEY_NAME_TO_VK`、`test_jhrw_coord_fallback ×1` 跨行坐标已知遗留）。`core` 识别/坐标模块（image_recognition/glyph_recognizer/glyph_coord_reader/jhrw_controller/arrival_verifier/game_coord_reader）**零单测覆盖**（审计 P1 扩展末段）——回归风险高。
- **可观测性**：唯一手段是 `utils.logger.Logger`（带 PyQt 信号），任务路径须能从彩色日志完整还原（`team_engineering_standards.md` 四）。`quest_detail_signal → data/current_quest.json` 是脚本↔外部进程的 IPC 落盘通道（`task_engine.py:721-791`）。
- **坐标体系一致性**：已统一客户区坐标（审计 strengths），但 `config.map_coord_file` 三级回退（`全项目优化报告.md` 问题3）须保证 `data/地图坐标.txt` 存在。

---

## 8. 与 Phase 4/5 的接口

- Phase 4（实现）应先消费本目录 ADR-0001..0005 的「决策」与「风险与缓解」，并在 PR 中对照 CONTROL_CHECKLIST 勾选。
- Phase 5（验证）须补 `core` 识别/坐标模块单测（审计 P3），并把 `_last_result`/`source_var` 约定写进 GUI 提示（ADR-0002）。
- **禁止项**：本次 Phase 3 仅产出文档，**未修改任何业务代码**（符合约束）。
