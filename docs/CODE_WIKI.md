# MHXY 游戏自动化项目 Code Wiki

> 本文档由代码分析生成（2026-08-29），用于沉淀项目知识，帮助快速理解、定位与运行。
> 范围：以 `e:\DS\mhxy-gui-automation`（WORLD_BOSS.py 所在主项目）为核心，顶部附工作区整体布局总览。

---

## 1. 工作区总览（e:\DS）

| 目录 | 归属 | 说明 |
|---|---|---|
| [mhxy-gui-automation](file:///e:/DS/mhxy-gui-automation) | ✅ 主项目 | 梦幻西游 GUI 自动化平台：任务编排/执行引擎、窗口管理、截图/OCR/字模识别、YOLO 检测、任务库（含 WORLD_BOSS.py） |
| [mhxy-mcp-gateway](file:///e:/DS/mhxy-mcp-gateway) | ✅ 依赖服务 | Frida 数据网关（gateway.py）：注入游戏 lua51.dll，暴露 HTTP/JSON 接口（/api/lua、/api/net/recvall 等），默认端口 18081，多实例 18080+N |
| [梦幻西游脚本函数包](file:///e:/DS/梦幻西游脚本函数包) | ⬅️ 旧资产 | JHRW.py（任务获取）、地图数据/ALG.py 等 9 个地图点击函数、图片数据（BMP 模板）——被主项目引用/复刻 |
| [mhxy-automation](file:///e:/DS/mhxy-automation) | ⬅️ 旧原型 | 早期 PyQt5 硬编码任务版（core/battle.py、skills.py、vision.py），已由主项目取代 |
| [mhxy-gui-automation 外其余目录](file:///e:/DS) | ⬜ 无关项目 | UUC/xddd/piecework-wage/aluminum 报表、Metin2-AI-Vision-Bot、res-downloader、test_clone2 等，与本项目无代码关系 |
| [备份与诊断](file:///e:/DS/backup_mhxy_20260805) | ⬜ 参考 | 旧版 JNYW.py/main.py 备份；根目录散落 *wb_run*.log 运行日志、WORLD_BOSS_FPS_亲和性诊断报告.md 等 |

---

## 2. 项目架构

### 2.1 分层视图

```
┌─────────────────────────────────────────────────────────────────┐
│ GUI 层 (gui/)：主窗口 / 任务编辑 / 事件编辑 / 任务库 / 配置 / 窗口选择 │
├─────────────────────────────────────────────────────────────────┤
│ 编排层 (models/ + config/)：事件/任务/任务序列模型、组配置、全局配置 │
├─────────────────────────────────────────────────────────────────┤
│ 执行层 (core/)                                                    │
│  TaskEngine(任务引擎) ← task_engine_mixins(点击/切换/YOLO 执行器)   │
│  TaskLibraryManager(动态导库+函数调用)  ↕  模型/字模/坐标/地图数据    │
│  WindowManager / ScreenCapture / InputController / YoloDetector    │
│  GatewayGuard / CaptchaV7 / LocationDataContainer / ArrivalVerifier│
├─────────────────────────────────────────────────────────────────┤
│ 任务库层 (library/ + tasks/)：地图函数包(MPCG/JYC/…)、任务脚本(WORLD_BOSS) │
├─────────────────────────────────────────────────────────────────┤
│ 外部服务：frida 网关 gateway.py (HTTP 18082) ── 游戏进程(lua51.dll)    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流（任务执行主链路）

1. 用户经 [main.py](file:///e:/DS/mhxy-gui-automation/main.py)（`--group N`）启动 GUI → [gui/main_window.py](file:///e:/DS/mhxy-gui-automation/gui/main_window.py) 加载组配置并异步重载网关
2. 在 GUI 中绑定游戏窗口 → [core/window_manager.py](file:///e:/DS/mhxy-gui-automation/core/window_manager.py) 记录 `hwnd/pid/标题/客户区`
3. 选择任务序列 + 点击执行 → [core/task_engine.py](file:///e:/DS/mhxy-gui-automation/core/task_engine.py) 启动 Worker 线程，逐事件执行
4. 事件类型：点击/键盘/等待/图像识别/YOLO/函数调用/条件分支/切换/子流程
   - 「函数调用」→ [core/task_library_manager.py](file:///e:/DS/mhxy-gui-automation/core/task_library_manager.py) 动态导入 library/ 或 tasks/ 下模块，调用如 `WORLD_BOSS_auto_farm`
   - 「点击/截图/识别」→ InputController / ScreenCapture / GlyphRecognizer / GameCoordReader 等
5. 库函数内部再调用 frida 网关 `/api/lua`、`/api/net/recvall` 读写游戏数据（坐标、任务、公告、战斗）
6. 异常/验证码 → TaskEngine 中的 captcha_v7 直解 + captcha_monitor 兜底；网关掉线 → gateway_guard 自愈拉起

---

## 3. 主要模块职责

### 3.1 入口层
| 文件 | 职责 |
|---|---|
| [main.py](file:///e:/DS/mhxy-gui-automation/main.py) | 入口：预加载 MSVC 运行库修复 PyQt5+cv2+torch DLL 冲突（WinError 1114）；解析 `--group`；启动验证码 watchdog；自动清理旧日志；启动 GUI；异步重载网关 |
| [start_group1.bat / start_group2.bat](file:///e:/DS/mhxy-gui-automation/start_group1.bat) | 以 `python main.py --group 1/2` 启动蓝/绿组 GUI（多开并行） |
| [启动GUI.bat](file:///e:/DS/mhxy-gui-automation/启动GUI.bat) | 组1 快捷启动，双击即用 |

### 3.2 core/ 核心能力层
| 文件 | 关键类/函数 | 职责 |
|---|---|---|
| [window_manager.py](file:///e:/DS/mhxy-gui-automation/core/window_manager.py) | `WindowManager`（单例） | 按 PID/标题 查找并绑定游戏窗口；持久化标题/PID（含角色 ID 锚点保护）；客户区矩形管理 |
| [screen_capture.py](file:///e:/DS/mhxy-gui-automation/core/screen_capture.py) | `ScreenCapture`（单例） | 线程隔离 mss 截图，返回 BGR 图像；任务识别/点击验证的数据来源 |
| [input_controller.py](file:///e:/DS/mhxy-gui-automation/core/input_controller.py) | `InputController` | 前台 PyAutoGUI / 后台 PostMessage 统一 `click()`；带像素变化验证的可靠点击（重试/阈值/稳定等待） |
| [task_engine.py](file:///e:/DS/mhxy-gui-automation/core/task_engine.py) | `TaskEngine(ClickMixin, YoloMixin, SwitchMixin, QObject)` | 任务序列执行引擎：Worker 线程、事件分发、停止/暂停/继续、验证码联动（captcha_v7 直解）、可中断 sleep |
| [task_library_manager.py](file:///e:/DS/mhxy-gui-automation/core/task_library_manager.py) | `TaskLibraryManager` | 从配置动态 import 任务库模块；执行函数调用事件（过滤不支持 kwargs、注入绑定 PID） |
| [group_config.py](file:///e:/DS/mhxy-gui-automation/core/group_config.py) | 组配置解析 | 按 `MHXY_GROUP` 解析组号与网关端口（组1=18082，组N=18080+N）；主 settings.json + config/groupN/settings.json 深合并 |
| [config.py](file:///e:/DS/mhxy-gui-automation/config/config.py) | `config` 单例 | settings.json 读写入口 |
| [gateway_guard.py](file:///e:/DS/mhxy-gui-automation/core/gateway_guard.py) | 网关自愈 | 确保网关在线并 attach 目标 PID：复用/PID 不匹配/进程死亡/端口占用/启动超时处理 |
| [game_coord_reader.py](file:///e:/DS/mhxy-gui-automation/core/game_coord_reader.py) | `GameCoordReader` | 读取游戏内目标游戏坐标 |
| [glyph_recognizer.py](file:///e:/DS/mhxy-gui-automation/core/glyph_recognizer.py) | `GlyphLibrary` / `GlyphRecognizer` / `ColorMaskRule` | 字模库识别（模板/掩码/颜色规则），用于任务栏文字、坐标读数 |
| [glyph_coord_reader.py](file:///e:/DS/mhxy-gui-automation/core/glyph_coord_reader.py) | `GlyphCoordReader` / `JHRWGlyphReader` | 基于字模的（J）游戏坐标读取器 |
| [ocr_coord_reader.py](file:///e:/DS/mhxy-gui-automation/core/ocr_coord_reader.py) | OCR 引擎管理 | 坐标识别的 OCR 与字模方案分发 |
| [sect_task_recognizer.py](file:///e:/DS/mhxy-gui-automation/core/sect_task_recognizer.py) | 门派闯关截图识别引擎 | MPCG 任务识别（回退引擎；MPCG.py 已改走 Lua 直读） |
| [image_recognition.py](file:///e:/DS/mhxy-gui-automation/core/image_recognition.py) | `ImageRecognition` | OpenCV 模板匹配（多尺度、阈值过滤） |
| [yolo_detector.py](file:///e:/DS/mhxy-gui-automation/core/yolo_detector.py) | `YoloDetector` | YOLO 目标检测（models/active.pt），返回类别/置信度/边界框 → 点击坐标 |
| [map_no_go.py](file:///e:/DS/mhxy-gui-automation/core/map_no_go.py) | 禁区数据 | 地图禁区读取/判定（data/map_no_go_zones.json） |
| [map_ui_block.py](file:///e:/DS/mhxy-gui-automation/core/map_ui_block.py) | UI 避让数据 | 大地图 UI 遮挡区钳制（data/map_ui_blocks.json） |
| [resolution.py](file:///e:/DS/mhxy-gui-automation/core/resolution.py) | 分辨率适配 | 坐标换算/分辨率缩放适配 |
| [interrupt.py](file:///e:/DS/mhxy-gui-automation/core/interrupt.py) | `TaskInterrupted` | 任务中断信号（BaseException） |
| [captcha_v7.py](file:///e:/DS/mhxy-gui-automation/core/captcha_v7.py) | 验证码直解 | 防脚本验证码自动识别/解除 |
| [captcha_link.py](file:///e:/DS/mhxy-gui-automation/core/captcha_link.py) | watchdog 联动 | 开机自启 watchdog + captcha_monitor 拉起（双保险） |
| [jhrw_controller.py](file:///e:/DS/mhxy-gui-automation/core/jhrw_controller.py) | `JHRWController` / `JHRWState` | 任务（JHRW）控制：接取/识别/状态 |
| [location_data_container.py](file:///e:/DS/mhxy-gui-automation/core/location_data_container.py) | `LocationDataContainer` | 全局位置数据容器（跨事件共享坐标） |
| [arrival_verifier.py](file:///e:/DS/mhxy-gui-automation/core/arrival_verifier.py) | `ArrivalVerifier` | 到达校验（点击后核实是否落位） |
| task_engine_mixins/ | `ClickMixin` / `YoloMixin` / `SwitchMixin` | TaskEngine 的事件执行器拆分（点击/切换/YOLO 事件） |

### 3.3 gui/ 界面层
| 文件 | 职责 |
|---|---|
| [main_window.py](file:///e:/DS/mhxy-gui-automation/gui/main_window.py) | 主窗口：组配置加载、菜单/工具栏/标签页/状态栏组装 |
| [status_panel.py](file:///e:/DS/mhxy-gui-automation/gui/status_panel.py) | 主控制面板：任务/状态/进度/日志实时显示 |
| [task_editor.py](file:///e:/DS/mhxy-gui-automation/gui/task_editor.py) | 任务序列可视化编辑（事件增删/排序/参数） |
| [event_editor.py](file:///e:/DS/mhxy-gui-automation/gui/event_editor.py) | 单事件编辑对话框（7 类事件参数） |
| [param_pages.py](file:///e:/DS/mhxy-gui-automation/gui/param_pages.py) | 事件参数页策略接口（各事件类型独立构建/加载/写回） |
| [task_library.py](file:///e:/DS/mhxy-gui-automation/gui/task_library.py) | 任务库管理面板：导入/启用禁用/重载/移除，展示可调用函数 |
| [config_panel.py](file:///e:/DS/mhxy-gui-automation/gui/config_panel.py) | 配置编辑：窗口绑定/输入模式/识别参数/日志 |
| [window_selector.py](file:///e:/DS/mhxy-gui-automation/gui/window_selector.py) | 游戏窗口选择对话框（按组角色过滤、锁定/解绑） |
| [subflow_editor.py](file:///e:/DS/mhxy-gui-automation/gui/subflow_editor.py) | 子流程编辑 |

### 3.4 models / data / utils
| 模块 | 内容 |
|---|---|
| [models/](file:///e:/DS/mhxy-gui-automation/models) | `event.py` / `task.py` / `task_sequence.py` / `var_context.py`：事件、任务、任务序列、变量上下文模型（JSON 序列化） |
| [data/](file:///e:/DS/mhxy-gui-automation/data) | 地图校准 JSON（6 图）、bigmap_calibration.json、字模库 glyph_library.json、禁区/UI 避让、传送路线 teleport_routes.json、地图坐标.txt、任务序列 JSON |
| [utils/](file:///e:/DS/mhxy-gui-automation/utils) | `logger.py`（日志+旧日志清理）、`helpers.py` |

### 3.5 library/ 任务库
| 文件 | 说明 |
|---|---|
| [library/map_packs/](file:///e:/DS/mhxy-gui-automation/library/map_packs) | 地图函数包：ALG/BXG/CAC/CSC/DHW/JNYW/JYC/XLNR/ZZG（各地图路径点击）、**MPCG.py**（门派闯关：识别/传送/CALL 护法/自动循环，默认走 Lua 网关直读，截图作回退） |
| [library/common/win_utils.py](file:///e:/DS/mhxy-gui-automation/library/common/win_utils.py) | Windows 窗口工具 |
| [library/custom / built_in](file:///e:/DS/mhxy-gui-automation/library/custom) | 自定义/内置库占位 |

### 3.6 tasks/ 任务序列与脚本库
| 文件 | 说明 |
|---|---|
| [tasks/library/WORLD_BOSS.py](file:///e:/DS/mhxy-gui-automation/tasks/library/WORLD_BOSS.py) | **世界 Boss 自动 farming 脚本**（详见 §4.2） |
| [tasks/library/JHRW.py / JHRW1.py](file:///e:/DS/mhxy-gui-automation/tasks/library/JHRW.py) | 任务获取/执行脚本 |
| [tasks/library/SYBUZ2.py / SYHS.py](file:///e:/DS/mhxy-gui-automation/tasks/library/SYBUZ2.py) | 副本类脚本 |
| [tasks/library/DSHNPC.py](file:///e:/DS/mhxy-gui-automation/tasks/library/DSHNPC.py) | 杜少海 NPC 脚本 |
| [tasks/门派闯关专用识别任务.json](file:///e:/DS/mhxy-gui-automation/tasks/门派闯关专用识别任务.json) 等 | 预置任务序列（引用 `${函数调用X.xxx}` 变量） |
| [tasks/library/WORLD_BOSS.py.bak_xxx](file:///e:/DS/mhxy-gui-automation/tasks/library/WORLD_BOSS.py.bak_pickboss_20260829) | WORLD_BOSS 迭代备份（pickboss/priority/starlord） |

### 3.7 tools/ 工具与实测入口
- 实测入口：[_test_wb_15232.py](file:///e:/DS/mhxy-gui-automation/tools/_test_wb_15232.py)（PID 15232 / 网关 18082）、_test_wb_19576.py、_test_wb_full_chain.py、_test_wb_one_boss.py 等
- 回归/诊断：_test_*_regress.py、probe_*.py（游戏数据探查）、dump_*.py（对话框/大地图/路由解析）、hook_*.py（输入钩子诊断）、build_*（字模/坐标库构建）
- 运行辅助：run_world_boss_test.py（旧 PID 入口）、mpcg_auto_loop.py（门派闯关自动循环）、accept_round.py 等

### 3.8 tests/ 测试
覆盖：任务引擎拆分回归、背景输入、条件分支、验证码联动、坐标转换/抖动、字模读取、禁区/UI 避让、YOLO、变量上下文、序列循环、JHRW 坐标回退等。运行方式：`pytest tests/`（见 [pytest.ini](file:///e:/DS/mhxy-gui-automation/pytest.ini)）。

---

## 4. 关键类与函数说明

### 4.1 核心类速览
| 类 | 位置 | 说明 |
|---|---|---|
| `WindowManager` | [core/window_manager.py](file:///e:/DS/mhxy-gui-automation/core/window_manager.py) | 单例；`find_by_pid/find_by_title/bind()`；保存 hwnd/pid/标题/客户区 |
| `ScreenCapture` | [core/screen_capture.py](file:///e:/DS/mhxy-gui-automation/core/screen_capture.py) | 单例；线程隔离 mss；`grab()` 返回 BGR |
| `InputController` | [core/input_controller.py](file:///e:/DS/mhxy-gui-automation/core/input_controller.py) | `click()`（前台/后台），带视觉验证与重试 |
| `TaskEngine` | [core/task_engine.py](file:///e:/DS/mhxy-gui-automation/core/task_engine.py) | 事件执行引擎；start/stop/pause；captcha 联动；可中断 sleep |
| `TaskLibraryManager` | [core/task_library_manager.py](file:///e:/DS/mhxy-gui-automation/core/task_library_manager.py) | 动态导库；`call_function()` 执行函数调用事件 |
| `GatewayGuard`（函数集） | [core/gateway_guard.py](file:///e:/DS/mhxy-gui-automation/core/gateway_guard.py) | `ensure_gateway()`：拉起+attach 游戏 PID；自愈 |
| `GlyphLibrary/GlyphRecognizer` | [core/glyph_recognizer.py](file:///e:/DS/mhxy-gui-automation/core/glyph_recognizer.py) | 字模库加载与识别（模板/掩码/颜色规则） |
| `GlyphCoordReader/JHRWGlyphReader` | [core/glyph_coord_reader.py](file:///e:/DS/mhxy-gui-automation/core/glyph_coord_reader.py) | 基于字模的坐标读取 |
| `YoloDetector` | [core/yolo_detector.py](file:///e:/DS/mhxy-gui-automation/core/yolo_detector.py) | YOLO 推理 → 目标框/置信度 |
| `ArrivalVerifier` | [core/arrival_verifier.py](file:///e:/DS/mhxy-gui-automation/core/arrival_verifier.py) | 点击后到达校验 |
| `JHRWController` | [core/jhrw_controller.py](file:///e:/DS/mhxy-gui-automation/core/jhrw_controller.py) | 任务接取/识别/状态 |
| `LocationDataContainer` | [core/location_data_container.py](file:///e:/DS/mhxy-gui-automation/core/location_data_container.py) | 跨事件共享位置数据 |

### 4.2 WORLD_BOSS.py 关键函数（[WORLD_BOSS.py](file:///e:/DS/mhxy-gui-automation/tasks/library/WORLD_BOSS.py)，约 3000 行）

**入口/调度**
- `WORLD_BOSS_auto_farm(max_runtime, verbose, gateway, ...)`（L2435）— 主入口：循环 扫描→CALL→战斗→击杀统计→（公告跨图/顶级目标抢占）→换图，`max_runtime=1800` 上限；返回累计击杀与耗时
- `WORLD_BOSS_wait_and_farm`（L2887）— 按刷新时刻表等待后开刷
- `WORLD_BOSS_captcha_gate`（L2423）— 验证码门禁封装
- `_next_schedule_time`（L2863）— 计算下个刷新时间点

**公告解析（数据来源 `/api/net/recvall`）**
- `fetch_recv_announcements(gateway, channel)`（L1367）— 拉取系统/传音公告，按频道去重、剥色码
- `parse_spawn_notification(text)`（L1467）— 解析单条公告 → `{boss, map, text}`；BOSS 别名展开、地图匹配、白名单过滤、星宿/多图随机选图
- `find_latest_spawn`（L1584）— 找出最新刷新
- `_is_chat_noise` / `_strip_colors`（L1337/L1355）— 去噪/去色码

**扫描与目标选择**
- `scan_scene_bosses`（L1614）— 实扫当前场景白名单怪（坐标列表）
- `_live_bosses`（L656）/ `_pick_target`（L642）— 目标过滤与优先级选点
- `_boss_priority`（L618）— 优先级档位判定（含**运行期目标名单兜底**：`WORLD_BOSS_auto_farm` 启动时把 `target_bosses` 登记进 `_RUN_TARGET_BOSSES`，名单内未映射档位的名字（如用户新增"新型冠状病毒"）自动归 `PRI_WHITELIST`，不再被当非目标剔除）
- `_pick_target(live, gx0, gy0, only_top=False, last_name=None)`（L656）— **平级交叉攻击**（2026-08-29）：跨档严格按 `BOSS_PRIORITY`；**优先级链（2026-08-29 用户定案）**：P0 三界财神爷 ＞ P1 二十八星宿 ＞ **P2 头领 = 统领 = 知了王（平级）** ＞ P3 其余白名单（灵猴 / 新型冠状病毒 / 十二生肖 / 天罡地煞）＞ P4 妖族杂鱼（妖魔 / 鬼怪 / 妖魔鬼怪）；同档内按名字分组各取最近代表，优先选与上一目标（`last_name`）异名的代表，异名相对同名多出的距离 ≤ `CROSS_NAME_NEAR_DIST`(6 格) 即切换 → 不再死磕单一名字，就近混合清怪（"新型冠状病毒"与"下凡的灵猴"同为 P3，路过就近交叉打）
- `_boss_priority`（L611 旧版位置）/ `_is_top_tier`（L641）— 优先级判定与顶级目标判断

**移动（走路贴近 vs 瞬移兜底）**
- `_approach_boss`（L2152）— 核心移动函数：优先校准走路（`_calibrated_walk`/`_walk_to`，点击大地图坐标+关图+CALL）；走路未启动（6s 坐标无变化）→ 随机环带瞬移兜底
- `_walk_and_call`（L2098）— 边走边 CALL
- `_gw_teleport`（L985）/`_gw_cross_map`（L1072）/`_find_hop_teleport`（L998）— 网关直传/跨图/寻路传送
- `_ensure_on_map`（L1933）/`_cur_map_name`（L1133）/`_role_grid`（L1970）— 地图与角色坐标读取
- `_bigmap_visible` / `_press_tab_if` / `_close_big_map`（L2001~L2098）— 大地图 TAB 开关与关闭

**战斗链路**
- `call_npc_event_start`（L1685）— 对场景假人「事件开始」
- `get_dialog_options`（L1728）/`call_dialog_battle`（L1762）— 读对话选项 + 按关键词点「请出招吧」等下战斗
- `_boss_battle_keywords`（L1832）/`BOSS_BATTLE_KEYWORDS`（L435）— 各 BOSS 战斗关键词表
- `_wait_battle_start`（L1865）/`_wait_battle_end`（L1897）— 战斗开始/结束轮询
- `close_dialog`（L1820）— 关闭无关弹窗
- `_farm_one_boss`（L2282）— 单只 BOSS 击杀闭环：原地 CALL → 走路贴近 → 落地补 CALL → 等待战斗结束；仍不命中（no_battle_option）→ 记录跳过
- `_dialog_is_too_far`（L2273）— 对话超距判定

**网关工具与自愈**
- `_http_json`（L790）/`_lua`（L891）/`_lua_expr`（L909）— 网关 HTTP/Lua 调用
- `_heal_gateway`（L859）/`_is_bridge_dead`（L882）— 网关掉线检测与自愈（跳新端口）
- `_in_battle`（L1143）/`_captcha_active`（L1150）/`_captcha_solve`（L1163）— 状态位读取与验证码避让

**其他**
- `_dismiss_engine_error_dialog`（L727）— 关错误弹窗
- `WORLD_BOSS_probe_chat`（L2951）/`WORLD_BOSS_chat_maintenance`（L2965）/`WORLD_BOSS_confirm_list`（L2986）— 聊天探测/聊天缓存清理/击杀确认清单

**关键常量**（L233-L281、L435-L470）
- `DEFAULT_TARGET_BOSSES`：白名单（三界财神爷、天降灵猴、下凡的灵猴、妖魔/鬼怪/头领/统领、知了王、星宿、十二生肖等）
- `DEFAULT_MONITORED_MAPS`：监控地图 10 张（东海湾/江南野外/建邺城/长寿村/长寿郊外/大唐国境/花果山/北俱芦洲/傲来国/大唐境外）
- `NO_BOSS_CITY_MAPS` / `BOSS_SPAWN_MAPS`：无 BOSS 城市 / 刷新地图映射

---

## 5. 依赖关系

### 5.1 第三方依赖（[requirements.txt](file:///e:/DS/mhxy-gui-automation/requirements.txt)）
`PyQt5`（GUI）、`opencv-python`（模板匹配/图像）、`pyautogui`（前台输入）、`ultralytics`（YOLO）、`mss`（截图）、`numpy`、`Pillow`、`pygetwindow`、`pywin32`（win32 后台消息）；测试：`pytest / pytest-cov / pytest-mock`。
运行环境另有 `frida`（见 e:\DS\.venv 或 E:/py，网关注入用）、`torch/onnx`（YOLO 推理）。

### 5.2 外部服务
- **frida 数据网关** [mhxy-mcp-gateway/gateway.py](file:///e:/DS/mhxy-mcp-gateway/gateway.py)：注入游戏 `lua51.dll`，提供 `/api/status`、`/api/globals`、`/api/lua`、`/api/lua/expr`、`/api/net/recvall` 等接口；**组1=端口 18082**（PID 15232 对应网关）
- **游戏客户端进程**（快乐西游/十年一梦等）：被 Frida attach
- **YOLO 模型** [models/active.pt](file:///e:/DS/mhxy-gui-automation/models/active.pt)

### 5.3 关键调用链
```
main.py → gui/main_window.py → core/{group_config, gateway_guard, captcha_link}
任务执行 → core/task_engine.py → core/task_library_manager.py
        → tasks/library/WORLD_BOSS.py → core/window_manager / core/gateway_guard
        → gateway.py(HTTP 18082) → 游戏 lua51.dll
识别链路: ScreenCapture → GlyphRecognizer / ImageRecognition / YoloDetector / GameCoordReader
```

### 5.4 运行纪律与已知约束（项目经验沉淀）
- **只连接本实例网关**：组1/PID 15232 → 18082；组N → 18080+N；禁止跨网关操作
- **禁止重复 gateway 注入同一进程**：重复注入会冗余 frida hook + 双 Lua 桥线程
- **验证码优先避让**：`captcha_active()` 时暂停一切点击，等待自动解除（约 60s 超时）
- **防脚本窗口会拦截后台输入**：目标被遮挡/缩放时后台点击可能失效 → 走路类操作需验证落位
- **运行若干预置任务前**：确认游戏窗口可见、目标 PID 已绑定、网关已 attach（gateway_guard 可自愈）

---

## 6. 项目运行方式

### 6.1 GUI 启动
```bash
cd e:\DS\mhxy-gui-automation
# 组1（默认）
python main.py --group 1
# 或双击 启动GUI.bat / start_group1.bat（组2 用 start_group2.bat）
```
依赖：游戏客户端已开、`pip install -r requirements.txt` 完毕；首次运行建议 `python main.py` 观察网关重载日志。

### 6.2 WORLD_BOSS 实机运行（目标 PID 15232 / 网关 18082）
```bash
cd e:\DS\mhxy-gui-automation
python tools\_test_wb_15232.py            # 硬绑 PID 15232 + 网关 18082 + max_runtime=1800
# 输出重定向留档示例：
python tools\_test_wb_15232.py *> e:\DS\wb_run_15232_<时间戳>.log
```
其他入口：`tools/_test_wb_19576.py`（另一 PID）、`tools/run_world_boss_test.py`（旧 PID 1468，网关 18083）。脚本内部：`WORLD_BOSS_auto_farm(max_runtime=1800, verbose=True, gateway="http://127.0.0.1:18082")`；完成后打印 `=== RESULT ===` + 汇总 dict。

### 6.3 网关启动（需要时）
```bash
cd e:\DS\mhxy-mcp-gateway
E:/py/python.exe gateway.py --auto            # 自动找进程，端口 18081
E:/py/python.exe gateway.py <PID> --port 18082 # 指定 PID + 端口（组1实例）
```
说明：正常情况下 GUI 的 gateway_guard 会自动拉起/自愈；手动启动需管理员权限。

### 6.4 测试运行
```bash
cd e:\DS\mhxy-gui-automation
python -m pytest tests/ -q          # 全量（多为离线/模拟，不触发实机操作）
```

### 6.5 环境要求
- Windows + 游戏客户端（私服，进程名如「快乐西游」）
- Python 3.x（e:\DS\.venv 或 E:/py，含 frida/torch/ultralytics；注意 PyQt5+cv2+torch DLL 冲突已在 main.py 预加载修复）
- 管理员权限（Frida attach 需要）

---

## 7. 运行记录

> 本节留档每次实机运行摘要（时间、PID、网关、结果、问题）。

| 时间 | PID | 网关 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-08-29 17:03:11 ~ 17:33:30（1819s） | 15232 | 18082 | **ok=True，击杀 47，0 失败/跳过，exit 0** | WORLD_BOSS_auto_farm 完整运行，日志 `e:\DS\wb_run_15232_20260829_170311.log`。走路通道失效：46 次走路尝试中 21 次"6s 无位移"空转、25 次瞬移兜底、边走边CALL 命中 0 次（根因见 7.1）；所有击杀经原地 CALL 命中或瞬移落地补 CALL 达成 |
| 2026-08-29 17:38:20 ~ 17:43:51（331s） | 15232 | 18082 | **ok=True，击杀 9，0 失败，exit 0** | 走路通道修复后验证运行，日志 `e:\DS\wb_run_15232_20260829_173820_validate.log`：12 次走路尝试 0 失败、边走边CALL 命中 5 次、瞬移兜底 0 次、0 WARNING |
| 2026-08-29 17:58:51 ~ 18:03:55（304s） | 15232 | 18082 | **ok=True，击杀 7，0 失败，exit 0** | 平级交叉攻击验证运行，日志 `e:\DS\wb_run_15232_20260829_175851_cross.log`：五庄观 4 只 P1 星宿击杀顺序 胃土雉→觜火猴→胃土雉→奎木狼（同档异名交叉），长寿郊外优先打 P4 灵猴而非 P5 妖魔/鬼怪（跨档链未变） |
| 2026-08-29 18:16:13 ~ 18:21:31（318s） | 15232 | 18082 | **ok=True，击杀 9，0 失败，exit 0** | 新优先级链（头领=统领=知了王 P2）验证运行，日志 `e:\DS\wb_run_15232_20260829_181613_priority.log`：长寿郊外 P3 灵猴优先于 P4 妖魔/鬼怪；财神爷公告抢占 P0 正常 |
| 2026-08-29 18:24:27 ~ 18:29:40（313s） | 15232 | 18082 | **ok=True，击杀 8，0 失败，exit 0** | 新链+新冠入名单验证运行，日志 `e:\DS\wb_run_15232_20260829_182427_priority2.log`：花果山（仅 P4 杂鱼在场）正常清杂鱼；大唐国境 37 只混合怪只打 P3 灵猴不碰 P4。本轮场景未刷"新型冠状病毒"（已入 `DEFAULT_TARGET_BOSSES` + `BOSS_PRIORITY` P3，桩测确认） |

### 7.1 2026-08-29 检修行结论（走路通道根因与修复）

**根因（现场取证）**：PID 15232 的真实游戏主视图是**多开器容器（其他进程）的子窗口**（1000×620，标题含角色锚点"鲜衣怒马 - 然学[701529]"）。`window_manager._find_pid_windows` 第 1 轮只匹配"可见且有标题"的顶层窗口，命中附属的「 聊天窗口」（248×650）后即早退返回，第 2 轮子窗口回退扫描永远不执行 → 绑错窗口 → PostMessage 后台 TAB/点击全部打在聊天栏 → 大地图开不了、寻路点击无效 → 走路永远"未启动"→ 每次击杀退化服务端瞬移（Lua，不依赖窗口，故击杀本身正常）。

**修复（core/window_manager.py `_find_pid_windows`）**：去掉第 1 轮命中后的早退，两轮（顶层+全部子窗口）去重合并，由 `find_by_pid` 按客户区面积择大——主视图 620000 必压过聊天窗口 150282。绑定验证：现命中 0x7504BA（1000×620，角色标题），同 PID 下聊天窗口被正确降级。

**已采纳调整（2026-08-29 用户定案）**：世界BOSS 走路期 CALL 节拍 `WALK_CALL_INTERVAL` 0.5s→1.5s（WORLD_BOSS.py L500，文档串同步）。

**修复前后实测对比**（同一 PID/网关）：

| 指标 | 修复前（1819s，47杀） | 修复后（331s，9杀） |
|---|---|---|
| 走路尝试 | 46 | 12 |
| "6s 无位移"空转 | 21 | **0** |
| 边走边CALL 命中 | 0 | **5**（2.1/8.5/15.2 格处命中） |
| 瞬移兜底 | 25 | **0** |
| WARNING | 1 | **0** |