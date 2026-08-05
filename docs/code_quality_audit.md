# 代码质量审计报告 · `mhxy-gui-automation`

> 审计基准:全量通读 `core / gui / models / utils / config` + `docs / examples / data`(约 1.27 万行业务代码)
> 审计角色:资深开发工程师(代码质量把控视角)
> 目的:为团队技术能力提升提供"标尺"和"整改清单",而非一次性修补。

---

## 一、项目 strengths(先说做得好的,别只挑刺)

- **架构分层清晰**:`main → gui → core → models/utils/config`,职责边界明确,新人能顺着依赖链读下来。
- **单例模式 + 线程隔离用得对**:核心模块统一单例,`screen_capture` 用 `threading.local` 隔离 mss 的 DC 句柄——这是桌面自动化里很容易踩的坑,作者避开了。
- **重依赖延迟导入**:`ultralytics`(YOLO)延迟导入且优雅降级,没拖垮启动速度。这是成熟的做法。
- **坐标体系统一**:全程"客户区坐标"对齐 `window_manager.get_client_rect()`,避免了前台/后台/截图坐标混用的经典灾难。
- **变量传递机制已实装**:`${函数调用3.target_coord.0}` 跨事件引用能跑通,有 `autosave.json` 实证。

**结论:底子不错,问题集中在"做了没接上""配置冗余""复制粘贴""缺测试"四类。**

---

## 二、质量发现(按优先级)

### P0 — 最高优先级(做了没接上 + 静默失败 bug)(最该先修,风险低收益高)

> 🔴 **2026-08-03 资深复审补充**:原审计遗漏一条**静默失败**隐藏 bug(P0 #2 `bound_pid`),不报错但让「自动到达等待」整条链路失效,已修复。复审还新增 P1 #5~#10(见 §二.P1 扩展)。

| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| 1 | **验证码监控"接了但接错签名、静默失效"** | `core/task_engine.py` 的 `start()` 已调用 `VerificationMonitor`(L163-173),但 `vm.start(log_callback=...)` 传了**非法关键字参数**——`VerificationMonitor.start()` 无参,回调须用 `set_log_callback()` 单独设置。该 `TypeError` 被 `except Exception: pass` 吞掉 → 监控线程从未真正启动;同时 `verification_monitor._notify`(L389)也有 `except: pass` 吞回调异常 | 任务运行时遇验证码弹窗会卡死/失控;且 `grep verification_monitor`(小写单例名)会**漏掉** `VerificationMonitor`(类名)形式的调用,导致原审计误判为"完全没接"——这是 grep 下结论的反面教材 | 拆成 `vm.set_log_callback(cb)` + `vm.start()`;`stop()` 收紧 `self._vm_started and self._vm is not None` guards;`__init__` 显式初始化 `self._vm/_vm_started`。**✅ 已修复 2026-08-03(烟雾测试通过:线程起停正常、回调触发)**；⚠️ **该 `verification_monitor` 模块已于 2026-08-03 按用户要求整体移除**(含 `core/verification_monitor.py` 模块、`task_engine` 三处接线、`config/settings.json` 的 `verification` 配置块、`tests/test_verification_monitor.py`),后期将重新实现 |
| 2 | **`window_manager.bound_pid` 隐藏失效(静默失败)** | `core/task_engine.py` L2051 / L2165 引用**不存在**的属性 `window_manager.bound_pid`(实际属性名为 `pid`),且被 `except Exception: pass` 吞掉 | `pid` 恒为 `None` → 自动内存坐标读取器永远连不上 → 「自动到达等待」形同虚设;**不报错但功能死掉**,极难排查 | 改为 `int(getattr(window_manager, "pid", 0) or 0)`(与 `task_library_manager.py` L509 一致写法),空 `except` 改 `logger.warning`。**✅ 已修复 2026-08-03** |

> 🔴 **复审更正(P0 #1)**:原审计称"task_engine 和 main_window 都没调用",系 `grep verification_monitor`(小写单例名)漏掉 `VerificationMonitor`(类名)调用所致的**误判**。真实情况是**接了但签名错、被静默 except 吞掉**。教训:**用 grep 一个名字下"未调用"结论会漏掉同名异形式的引用;判断"是否真的接上"必须读调用点的实参签名,而非仅搜名字。**（注：当前 `VerificationMonitor` 模块已整体移除,见 P0 #1 收尾说明。）

### P1 — 名不副实 / 死配置

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 2 | **`EventType.YOLO` 实际走的是模板匹配** | `core/task_engine.py` 的 `_execute_yolo_detect` | **✅ 已修复 2026-08-03**：原审计误判"从未调用 yolo_detector"——代码其实调了 `yolo.detect()`，但**成功分支无视 `action`、永当 record** 才是真缺口。已抽出 `_execute_yolo_action`/`_yolo_pick_target`：YOLO 推理成功后按 `action`(click/wait/record) 执行，`click` 点最佳目标中心（支持 `target_class` 过滤 + 附加点击），`wait` 轮询检测命中后可选点击；仅当模型真不可用时降级模板匹配。新增 `tests/test_yolo_executor.py`(5 passed) |
| 3 | **condition 事件没有真正的分支控制流** | `_execute_condition` | **✅ 已修复（前序"任务分流改造"已落地，2026-08-03 复审确认）**：simple 模式据条件结果递归执行 `true_branch`/`false_branch` 事件序列；switch 模式匹配 case 后由 `_execute_switch_actions` 跑完整 `actions` 子流程（每个 action 是完整 Event 经引擎递归执行），并兼容旧式单 `click`/`file_lookup`。**原审计为过时快照**。新增 `tests/test_condition_branch_runtime.py`(3 passed) 运行时验证 simple true/false 与 switch 子流程确实被调度执行 |
| 4 | **两套重试计数互不相干** | `models/event.py` 有 `max_retries`;`gui/event_editor.py` 的 `_default_verify` 又写了 `retry_times/retry_interval` 并写入引擎,但 `_dispatch_with_retry` **完全不消费** verify 的 `retry_times` | 冗余死配置,reviewer 会误以为 verify 重试生效,实则无效 |

### P1 扩展 — 2026-08-03 资深复审新增(静默风险 / 坏味道 / 类型缺口)

> 以下问题为本次全量复审新发现,原审计未覆盖。严重程度低于 P0,但均为"高杠杆、可逐步消除"的团队技术债。

| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| 5 | **`input_controller` 两套 VK 映射重复** | `core/input_controller.py` L294-320(`KEY_MAP` 用 hex 字面量) vs L507-539(`_SPECIAL_VK` 用 `win32con`) | 同一份按键语义定义两次,增删按键须改两处,已存在漂移风险 | 合并为单一权威映射 + 两个发送后端共享;加表驱动测试（✅ 已修复 2026-08-03,新增 tests/test_input_key_map.py 表驱动测试 7 例全过） |
| 6 | **`gui/event_editor.py` 上帝类(约 3402 行)** | 整个文件,尤其 `_load_image_params` / `_build_condition_page`(L1731) / `_on_preset_cases_from_file`(L2048) | 单类承担 7 种参数页 + 子流程 + 地图坐标加载,改动牵一发动全身(shotgun surgery) | 抽 `BaseParamPage` + 每事件类型子类(策略模式);子流程独立模块。**✅ PR #8 已彻底收口 2026-08-03**：`gui/param_pages.py` 含 `BaseParamPage` + 全部 7 个真实 `ParamPage` 子类（Click/Key/Wait/Image/Yolo/Function/Condition），`LegacyParamPage` 适配器与所有旧 `_build_*/_load_*/_apply_*` 方法已删除；`SubFlowEditorDialog` 独立为 `gui/subflow_editor.py`；`event_editor.py` 瘦身为 dialog shell（通用属性 + 参数区路由 + 跨页共享辅助 + 加载/写回调度 + accept）。全部 7 页 build/load/apply 零行为变化；新增 `tests/test_event_editor_pages.py`（9 passed），整库 124 passed（yolo 测试因 torch DLL 环境故障单独跳过，与本重构无关）。** |
| 7 | **硬编码绝对路径污染代码与持久化数据** | `gui/task_editor.py` L99;`gui/event_editor.py` L950/952/1896/2053/2325;并写入 `tasks/*.json`、`data/task_sequence_autosave.json` | 换机/换目录即失效,且坏味道已扩散到用户数据文件 | 抽 `config.map_coord_file`,运行时 `os.path` 解析;迁移脚本清理已有 JSON | **✅ 已修复 2026-08-03**:`Config` 新增 `map_coord_file` 属性(自定义→项目内 `data/地图坐标.txt`→旧路径兜底且只告警一次);6 处 GUI 字面量 + 3 处引擎读取点(`or config.map_coord_file`)全部接上;保存时默认值存空串从源头停止新污染。存量绝对路径 JSON 因 truthy 不触发回退,**向后兼容**。剩余:已有 JSON 的清理需迁移脚本(见下) |
| 8 | **`verification_monitor._notify` 吞掉回调异常** | `core/verification_monitor.py` L392-394 `try: self.log_callback(...) except Exception: pass` | 监控线程日志回调一旦抛错无声无息,排障黑洞 | `logger.error` 记录 + 保留不冒泡语义（✅ 已修复 2026-08-03）；⚠️ **该模块已于 2026-08-03 整体移除**(见 P0 #1 收尾说明) |
| 9 | **`ocr_coord_reader` 裸模块全局 + 无锁延迟初始化** | `core/ocr_coord_reader.py` L29-30、L35(`global _ocr_engine, _ocr_engine_initialized`) | 多线程首调竞态,可能重复构造重量级 OCR 引擎 | 改类单例或加 `threading.Lock()` 保护;显式 `Union` 返回类型 | **✅ 已修复 2026-08-03**:抽 `OCREngineManager` 类单例(`threading.Lock` 双检锁延迟初始化),删裸 global 与 `global` 语句;模块级单例 `_ocr_engine_manager` + `_get_ocr_engine()` 兼容委托;公开 API(`read_coord_ocr`/`is_ocr_available`)签名不变。返回类型用 `Optional[Any]` + docstring 注明 3 种形态。新增 `tests/test_ocr_engine_manager.py`(并发12线程只初始化1次 + 缓存 + 委托),pytest 4 passed |
| 10 | **类型安全缺口:`permanent_coord_reader` 全文件无注解 / 模型构造器无注解** | `core/permanent_coord_reader.py`(整文件零注解,且经核实无外部调用方=孤儿模块);`models/task.py` L32、`models/task_sequence.py` L30 构造器无注解 | 核心 ctypes 读取逻辑零注解 + 模型构造器与 `event.py`(强注解)水平不一致,静态检查失效 | 补 `from __future__ import annotations` + `from typing import Optional`,全函数/构造器签名已注解(✅ 已修复 2026-08-03);`permanent_coord_reader` 无外部调用方,建议单独 cleanup PR 删除/移 `scratch/` |

> 核心识别/坐标模块(`image_recognition` / `glyph_recognizer` / `glyph_coord_reader` / `jhrw_controller` / `arrival_verifier` / `game_coord_reader`)**零单测覆盖**,详见 §二.P3;这些模块是"能否正确识别/定位/到达"的地基,回归风险高,优先补单测(见阶段 2)。

### P2 — 复制粘贴 / 散落文件

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 5 | **点击逻辑重复** | `_execute_image` 的"附加点击"与 `_execute_condition` 的 switch "动作执行"大量重复"点击 + 坐标文件查找"代码 | 改一处要改两处,易漏改 |
| 6 | **scratch 文件混在正式代码里** | 根目录 `_fix_image_page.py`(一次性 patch)、`logs/_sc_correct.py`、`logs/_wm_correct.py`(screen_capture / window_manager 的备份副本,不在 import 路径)、`examples/test_colored_text_offline.py` | 新人分不清哪些是要维护的;备份不该进仓库 |

### P3 — 工程化短板(团队提升的主战场)

- **零测试**:`core` 纯逻辑(变量解析、事件分发、坐标换算)没有任何 pytest,改一行全靠手点游戏验证。
- **几乎无类型注解**:核心函数签名缺 `typing`,IDE 不友好,调用方易传错。
- **单例过度使用**:所有模块全局单例,导致 `core` 逻辑难以单元测试(耦合全局状态)。
- **配置 schema 漂移**:`settings.json` 字段与 `config.py` 的读取路径靠人脑对齐,无校验、无文档约束。

---

## 三、整改示例(以 P0 #1 为例,show, don't tell)

`task_engine.py` 的 `start()` 里应这样接入:

```python
# 在 TaskEngine.start() 内,线程启动之前
from core.verification_monitor import VerificationMonitor
vm = VerificationMonitor()
if not getattr(self, "_vm_started", False):
    vm.start(log_callback=lambda lvl, msg: self.log_signal.emit(lvl, msg))
    self._vm_started = True

# 在 stop() 内
if getattr(self, "_vm_started", False):
    vm.stop()
    self._vm_started = False
```
> ⚠️ 上述示例引用的 `core.verification_monitor` 模块已于 2026-08-03 整体移除,此代码块仅作历史存档,切勿复制使用。

改动 < 10 行,风险极低,但让一个"写了没用"的模块立刻产生真实防卡死价值——这就是 senior review 该推动的"高性价比修复"。

---

## 四、团队提升路线图(分三阶段)

**阶段 1 · 立标尺(1–2 周)**
- 落地 `team_engineering_standards.md`(代码评审清单 + 分支/PR 约定 + 类型注解/日志/命名规范)
- 接入 pre-commit:`black` + `isort` + `flake8`(Python 项目零成本,立竿见影)
- 清理 P2 #6 的 scratch 文件(移出仓库或归档)

**阶段 2 · 修关键缺口(2–4 周)**
- 按本报告 P0/P1 顺序逐个修复(每修一个补一条 pytest)
- 给 `core` 的纯函数补单元测试(变量解析、坐标换算、事件分发优先)
- 统一点击逻辑(P2 #5)收敛到 `_do_click` / `_lookup_coord_from_file`

**阶段 3 · 架构演进(持续)**
- 让 `YOLO` 事件真正调用 `yolo_detector`(P1 #2),并可考虑两路并存(模板快、YOLO 准)
- 给 `condition` 加真正的分支控制流(P1 #3)——这是让序列从"线性"变"流程图"的关键能力跃迁
- 用依赖注入逐步解耦单例,让 `core` 可被测试

---

## 五、下一步

请选择优先启动的轨道(详见评审表与标准文档):
- **A. 先修 P0 验证码监控接入**(最小改动、立刻有用)
- **B. 先立工程规范 + pre-commit**(让团队从此有统一标尺)
- **C. 先补 `core` 单元测试**(用测试把现有逻辑锁住,再大改不慌)
- **D. 我直接给一个"YOLO 真推理 + condition 真分支"的架构改造方案**
