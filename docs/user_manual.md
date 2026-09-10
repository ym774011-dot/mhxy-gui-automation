# MHXY GUI 自动化脚本平台 - 用户操作手册

> **版本：v2.0**
> **更新日期：2026-09-10**
> **适用入口：`main.py`（函数专用 GUI）**

> **说明：本手册依据当前代码（main.py 与 gui/ 各模块）重写，所有菜单名、按钮名、文件路径、字段名均以代码为准。若本手册与代码实际行为不一致，以代码为准。**

---

## 目录

1. [概述](#1-概述)
2. [安装与依赖](#2-安装与依赖)
3. [启动应用](#3-启动应用)
4. [界面介绍](#4-界面介绍)
5. [菜单栏与工具栏](#5-菜单栏与工具栏)
6. [任务编辑流程](#6-任务编辑流程)
7. [任务库导入说明](#7-任务库导入说明)
8. [YOLO 模型配置](#8-yolo-模型配置)
9. [窗口绑定与输入模式](#9-窗口绑定与输入模式)
10. [配置文件说明](#10-配置文件说明)
11. [任务序列 JSON 格式](#11-任务序列-json-格式)
12. [常见问题](#12-常见问题)

---

## 1. 概述

### 1.1 项目简介

本项目是一套**梦幻西游**自动化任务编排平台，采用 **Python + PyQt5** 构建图形界面。
用户通过可视化界面编排「任务序列」（由若干「事件」按序组成），由 `core/task_engine.py`
驱动在绑定的游戏窗口上自动执行点击、按键、图像识别、函数调用、条件分支等操作。

> **重要：本项目包含两套 GUI，请勿混淆**
> - **函数专用 GUI（本文档描述对象）**：入口为仓库根目录 `main.py`，由 `gui/main_window.py`
>   承载主窗口，提供「主控制面板 / 任务编辑 / 任务库 / 配置」四个标签页，用于编排并执行
>   单个游戏账号的任务序列。配套启动脚本：`启动GUI.bat`、`start_group1.bat`、`start_group2.bat`、
>   `启动函数专用GUI.bat`。
> - **五开集成 GUI（PP GUI）**：入口为 `tools/pp_gui.py`，用于同时编排并驱动最多 5 个
>   账号（多进程）。其使用方式不在本文档范围内，详见仓库根目录 `README.md`。

### 1.2 核心能力

- 可视化编排任务序列：新建/打开/保存 JSON 格式的任务序列。
- 七种事件类型：点击、按键、等待、图像识别、YOLO 识别、函数调用、条件分支。
- 条件分支支持 `simple`（单条件判断）与 `switch`（多值匹配）两种模式，`switch` 的每个
  分支（case）和默认动作均可承载一段独立的子流程（SubFlow）。
- 任务库机制：导入 Python 脚本模块，作为「函数调用」事件的可选函数来源。
- YOLO 目标检测：基于 `ultralytics` 模型对游戏画面做目标类别检测并点击。
- 窗口绑定：通过 PID/角色名/窗口标题选择并锁定目标游戏窗口。
- 后台输入：通过 `window.input_mode` 配置，支持不抢占鼠标的前台/后台两种输入模式。
- 定时重新登录：可配置定时杀掉旧客户端并启动新客户端自动登录，完成后自动恢复任务。
- 多组（多账号并行）：通过 `--group N` 启动多个独立 GUI 进程，各组有独立配置与网关。

### 1.3 技术栈

- 语言：Python 3
- GUI：PyQt5（`QMainWindow` / `QTabWidget` / `QDialog`）
- 目标检测（可选）：`ultralytics` + `torch`
- 窗口操作：自研 `core/window_manager.py`、`core/input_controller.py`
- 进程内 Lua 网关：经 frida attach 游戏进程并捕获 Lua state（组级网关独立）

---

## 2. 安装与依赖

### 2.1 系统要求

- Windows 操作系统（窗口绑定与输入依赖 Windows API）。
- 已安装 Python 3（建议 3.9+）。
- 已安装并登录梦幻西游客户端。

### 2.2 安装步骤

1. 克隆/解压本项目到本地目录（下文称「项目根目录」）。
2. 安装依赖（见 [2.3](#23-依赖列表说明)）。
3. 按需安装 YOLO 相关依赖（见 [2.4](#24-yolo-模型可选安装说明)）。
4. 如首次运行遇到 `torch`/`cv2` 因 MSVC 运行库冲突报错，启动脚本 `启动GUI.bat` 已内置
   `_preload_vcruntime()` 预加载处理，正常使用启动脚本即可。

### 2.3 依赖列表说明

核心依赖（来自 `requirements.txt` 或项目内声明）：

- `PyQt5`：界面框架。
- `numpy`：数值与图像数组处理。
- `opencv-python`（cv2）：模板匹配、图像比对。
- `pillow`：图像处理辅助。
- `ultralytics` / `torch`：仅 YOLO 事件需要（见 [2.4](#24-yolo-模型可选安装说明)）。

### 2.4 YOLO 模型可选安装说明

YOLO 事件为**可选功能**，使用实时导入（`core/yolo_detector` 在函数专用 GUI 中按需懒加载）。
仅当任务中实际使用「YOLO 识别」事件时才需要安装：

- `torch`
- `ultralytics`

并准备模型文件（默认路径见 [8.2](#82-模型文件)）。未安装时，涉及 YOLO 的事件会在执行时
报缺包错误，不影响其他事件类型的正常使用。

---

## 3. 启动应用

### 3.1 启动命令

本项目提供多个启动脚本，对应不同的启动方式（均在项目根目录）：

| 脚本 | 实际命令 | 说明 |
| --- | --- | --- |
| `启动GUI.bat` | `python main.py --group 1` | 启动组 1 函数专用 GUI（默认）。 |
| `start_group1.bat` | `set MHXY_NO_WATCHDOG=1` 后 `main.py --group 1` | 启动组 1，且**禁用验证码看门狗**。 |
| `start_group2.bat` | `set MHXY_NO_WATCHDOG=1` 后 `main.py --group 2` | 启动组 2（独立进程），且禁用验证码看门狗。 |
| `启动函数专用GUI.bat` | 启动 `函数专用/main.py` | 启动**子项目** `函数专用/` 下的另一套 GUI（与本文档的 `main.py` 不同）。 |

> 说明：
> - `main.py` 支持命令行参数 `--group N`（默认 1），相应设置环境变量 `MHXY_GROUP`。
>   不同组使用独立配置目录（见 [10.1](#101-文件位置)）与独立网关端口。
> - `start_group*.bat` 在启动前设置 `MHXY_NO_WATCHDOG=1`，用于**关闭验证码看门狗**
>   （即不自动启动 `core.captcha_link` 的 watchdog 进程）；`启动GUI.bat` 不设置该变量，
>   由 `main.py` 默认启动验证码看门狗。
> - 多组并行时，也可在已运行的 GUI 内点击工具栏「🚀 启动其他组」按钮，以独立子进程拉起
>   其他组的 GUI（见 [5.2](#52-工具栏)）。

直接用命令行启动：

```bat
python main.py --group 1
```

### 3.2 首次启动说明

- 首次启动会尝试加载 `config/settings.json`，若该文件不存在则使用 `gui/config_panel.py`
  中 `_DEFAULTS` 的默认值。
- 启动时自动从 `data/task_sequence_autosave.json`（组 1）或组配置对应的自动保存路径
  加载上次的任务序列；文件不存在则创建空序列。
- 若配置了 `window.auto_restore`（默认 `true`），启动时会尝试自动恢复上次绑定的游戏窗口。
- 主窗口标题会显示组号；绑定窗口后会追加已绑定的角色名。

---

## 4. 界面介绍

主窗口（`gui/main_window.py` 的 `MainWindow`）包含：菜单栏、工具栏、中央 `QTabWidget`
（四个标签页）、状态栏。

### 4.1 主控制面板（标签页 1，StatusPanel）

对应 `gui/status_panel.py`，包含：

- **执行状态**分组：
  - 当前任务
  - 执行状态（就绪 / 运行中 / 已暂停 / 已停止 / 已完成 / 正在停止，各状态有对应颜色）
  - 进度条（由 `task_engine.progress_signal` 驱动）
  - 当前事件
- **执行日志**分组：多色日志文本框（等宽字体 Consolas），按级别着色
  （DEBUG 灰、INFO 黑、WARNING 橙、ERROR 红、CRITICAL 暗红）。
  - 按钮：**清空日志**、**保存日志**
- 函数事件成功返回的游戏任务信息会导出为 `data/current_quest.json`
  （字段：task / status / progress{current,total} / map / coord / npc / loops / ts），
  供外部程序 IPC 读取。

### 4.2 任务编辑（标签页 2，TaskEditor）

对应 `gui/task_editor.py`，分左右两部分：

- **左侧·任务列表**分组：
  - 任务下拉框（combo，选择当前编辑的任务）
  - 按钮：**新建任务**、**删除任务**
  - 任务属性表单：名称、描述、**循环次数**（0=无限循环）、**循环间隔**（秒）
  - **序列循环（整体重复执行）**分组：循环次数（0=无限循环，默认 1）、循环间隔（秒）
    —— 控制整个任务序列执行完一轮后是否整体重来。
- **左侧·事件列表**分组（当前任务下的事件）：
  - 按钮：**添加事件**、**编辑事件**、**删除事件**、**上移**、**下移**、
    **复制选中事件**、**粘贴事件**
- **右侧·事件详情**：只读预览当前选中事件的参数（实际编辑在「编辑事件」弹出的
  `EventEditorDialog` 中完成）。

> 复制/粘贴：任务编辑器与条件分支的「子流程编辑器」共享同一套剪贴板
> （模块级 `_SUBFLOW_CLIPBOARD`），可在不同任务、不同子流程之间复制粘贴事件。

### 4.3 任务库（标签页 3，TaskLibraryPanel）

对应 `gui/task_library.py`：

- 顶部按钮：**导入脚本**、**刷新**、**保存配置**
- **模块列表**（左侧 `QListWidget`）：勾选框控制启用/禁用，按分类着色
  （built_in 蓝、custom 绿、map 橙）。
- 模块操作按钮（底部）：**启用**、**禁用**、**重新加载**、**移除**
- **函数列表**（右侧 `QListWidget`）：展示选中模块导出的函数。
- **函数详情**（右侧 `QTextEdit`）：展示函数签名与文档字符串。

### 4.4 配置（标签页 4，ConfigPanel）

对应 `gui/config_panel.py`，包含**三个分组**：

- **识别参数**分组：
  - 模板匹配阈值（0–1，步进 0.05）
  - YOLO 置信度（0–1）
  - YOLO 模型（路径 + 浏览按钮）
  - 截图间隔（0.1–10 秒，步进 0.1）
- **日志配置**分组：
  - 日志级别（DEBUG / INFO / WARNING / ERROR）
  - 日志文件（路径 + 浏览按钮）
  - 自动清理（天）（0–365）
- **定时重新登录**分组：
  - 启用定时重新登录（勾选）
  - 间隔（分钟）（1–43200）
  - 客户端 exe（路径 + 浏览按钮）
  - 登录点击坐标（每行 `x,y`）
  - 按钮：**🔁 立即重新登录**

> 注意：**窗口绑定不在配置面板内**。窗口绑定通过工具栏「🔗 绑定窗口」按钮弹出的
> `WindowSelectorDialog` 完成（见 [9.1](#91-绑定方式)）。

---

## 5. 菜单栏与工具栏

### 5.1 菜单栏

菜单栏由 `gui/main_window.py` 的 `_init_menu_bar()` 构建，共三个菜单：

**文件**
- 新建任务序列（`Ctrl+N`）：清空当前编辑器，创建空任务序列（若有未保存内容会先确认）。
- 打开任务序列...（`Ctrl+O`）：从 JSON 文件加载任务序列。
- 保存任务序列（`Ctrl+S`）：将当前任务序列保存为 JSON 文件。
- 退出（`Ctrl+Q`）：关闭程序（会先停止任务引擎与本组网关）。

**设置**
- 保存配置：将当前配置写入 `settings.json`。
- 重新加载配置：从 `settings.json` 重新加载配置并刷新窗口状态。

**帮助**
- 用户手册：提示 `docs/user_manual.md` 的文件路径（当前以消息框提示，未内置阅读器）。

### 5.2 工具栏

工具栏由 `_init_tool_bar()` 构建，从左到右依次为：

- **▶ 开始执行**：执行当前任务序列中**全部**任务。
- **▶ 执行当前任务**：仅执行任务下拉框当前选中的单个任务。
- **⏸ 暂停**：暂停执行。
- **⏹ 停止**：停止执行。
- （分隔符）
- **🔗 绑定窗口**：弹出游戏窗口选择对话框，绑定目标窗口（见 [9.1](#91-绑定方式)）。
- **窗口状态标签**（非按钮，实时文本）：显示「未绑定」或「已绑定: PID=...」。
- （分隔符）
- **🔄 定时重登**：立即触发一次重新登录（杀旧客户端→启新客户端→点击登录→恢复任务）。
- （分隔符）
- **🚀 启动其他组**：下拉按钮，点击拉起其他组的 GUI（组 2 / 组 3 / 组 4，排除当前组），
  以独立子进程运行 `main.py --group N`。

### 5.3 状态栏

状态栏由 `_init_status_bar()` 构建，常驻显示：

- **组徽章**（左侧永久部件）：格式「组N · x号 · 网关:port」，并实时刷新网关状态：
  - ●在线（绿）：HTTP 通 + 已 attach 本组游戏 PID + Lua 已捕获
  - ⚠启动中（橙）：网关在线但未就绪
  - ⚠pid不匹配（橙）：网关在线但 attach 的是别的进程
  - ○离线（灰）：HTTP 不通
- **运行状态文字**（右侧永久部件）：就绪 / 运行中 / 已暂停 / 已完成 / 已停止 等。
- **进度信息**（中间部件）：如「进度: 3/10 - 事件名」「任务已结束」等。

---

## 6. 任务编辑流程

### 6.1 新建任务序列

菜单 **文件 → 新建任务序列**（`Ctrl+N`），或直接启动后从自动保存继续编辑。

### 6.2 创建任务

在「任务编辑」标签页：
1. 点击 **新建任务**，输入任务名称。
2. 在任务列表中选中该任务。
3. 填写任务属性（名称、描述、循环次数、循环间隔）。

### 6.3 配置任务属性

- **名称 / 描述**：任务的基本信息。
- **循环次数**：该任务自身的循环次数，`0` 表示无限循环，默认 `1`。
- **循环间隔**：每轮任务循环之间的等待（秒）。
- **序列循环（整体重复执行）**：控制整个任务序列执行完一轮后是否整体重来，包含
  「循环次数」（0=无限，默认 1）与「循环间隔」。

### 6.4 添加事件

在「事件列表」分组点击 **添加事件**，弹出 `EventEditorDialog`，选择事件类型并填写参数。
支持的七种事件类型见 [6.5](#65-七种事件类型说明)。

### 6.5 七种事件类型说明

每个事件除各自参数外，还包含通用字段（见 [11.2](#112-事件-event-字段)）：`name`、
`event_type`、`pre_delay`、`post_delay`、`on_error`、`max_retries`、`retry_interval`、
`enabled`、`var_name`。其中 `var_name` 用于把本事件结果存入变量上下文，供后续事件通过
`${var_name.field}` 模板变量引用（例如函数调用事件返回的 `target_location`）。

#### 6.5.1 点击（click）

参数：`x`、`y`（可为整数，也可为含 `${...}` 的模板变量字符串）、`button`（left/right）、
`background`（是否后台点击）、`press_delay`（按下到弹起延迟，秒）、
`verify`（点击后是否做像素颜色验证确认生效）、`probe_x`、`probe_y`（验证采样点）、
`verify_retries`、`verify_threshold`。

#### 6.5.2 按键（key）

参数：`keys`（按键序列文本）、`text`（直接输入的文本）、`duration`（按住时长，秒）。

#### 6.5.3 等待（wait）

参数：`duration`（等待秒数）、`wait_for_image`（是否等待某图出现）、
`image_path`（目标图路径）、`timeout`（超时，秒）、
`region`（`[x, y, w, h]` 截图区域）。

#### 6.5.4 图像识别（image）

基于模板匹配，参数较多：

- 基础：`source_mode`（direct / dyn / batch）、`template_path`、`threshold`（匹配阈值）、
  `action`（click / none / ...）、`button`、`click_delay`、`region`（`[x,y,w,h]`）。
- 动态构建（source_mode=dyn）：`prefix`、`dir_path`、`suffix`、`dyn_field`
  （默认 `target_location`）、`dyn_custom_field`。
- 地图白名单：`allowed_maps`（字符串列表）。
- 识别重试：`recognize_retries`、`recognize_retry_interval`。
- 批量识别（source_mode=batch）：`batch_dir`、`batch_ext`、`batch_use_var`、
  `batch_var_field`、`batch_sort`、`batch_click_mode`。
- 附加点击：`additional_click_enabled`、`additional_mode`、`additional_x`、
  `additional_y`、`coord_file`、`match_field`（默认 `target_location`）、
  `match_custom_field`、`additional_button`、`additional_delay`。

#### 6.5.5 YOLO 识别（yolo）

基于 `ultralytics` 模型的目标检测，参数：

- 基础：`template_path`（兼容旧字段，单条存字符串）、`template_paths`（始终存列表）、
  `threshold`、`action`、`button`、`region`（`[x,y,w,h]`）。
- 模型增强：`target_class`（目标类别，可为英文类别名或空=不限）、
  `near_mode`（近距增强）、`near_radius`、`mid_radius`、
  `conf_near`、`conf_mid`、`conf_far`（近/中/远三档置信度）。
- 全局置信度来自「配置 → 识别参数 → YOLO 置信度」；模型文件来自
  「配置 → 识别参数 → YOLO 模型」（`recognition.yolo_model_path`），事件内不单独存模型路径。

#### 6.5.6 函数调用（function）

调用「任务库」中已启用模块的函数：

- 基础：`module`（模块名，含特殊值 `auto`=自动按地图匹配）、`function`（函数名）、
  `args`（JSON 数组）、`kwargs`（JSON 对象）。
- 结果验证：`result_validate_field`（默认 `target_location`）、
  `result_validate_whitelist`（白名单列表）、`result_validate_retries`、
  `result_validate_retry_interval`（勾选「启用结果验证」后生效）。
- 自动等待到达：`auto_wait_arrival`、`wait_arrival_timeout`、`wait_arrival_tolerance`、
  `wait_arrival_stop_confirm_s`、`wait_arrival_sample_interval`、`wait_arrival_retries`。

#### 6.5.7 条件分支（condition）

支持两种模式（由 `mode` 区分）：

- **simple 模式**：`variable`（变量名）、`operator`
  （支持 `==` / `!=` / `>` / `<` / `>=` / `<=`）、`value`、`true_branch`、`false_branch`。
- **switch 模式**：
  - `match_field`：匹配字段（可选 `target_location` / `quest_name` / `progress_num` /
    `map_name` / `__custom__`）。
  - `match_custom_field`：`match_field` 为 `__custom__` 时填写自定义字段名。
  - `source_var`：上游函数调用事件的变量名（留空=自动向上游搜索）。
  - `cases`：匹配分支列表，每项为 `{ "match_value": ..., "actions": [ 事件字典列表 ] }`；
    每个 case 的子流程通过「子流程编辑器」（`SubFlowEditorDialog`）编辑。
  - `default_action`：默认动作，取值 `none` / `click` / `file_lookup` / `subflow`：
    - `none`：不匹配时什么都不做；
    - `click`：点击固定坐标（`x`,`y`,`button`）；
    - `file_lookup`：查坐标文件点击（`coord_file`,`button`）；
    - `subflow`：执行一段子流程（`actions`）。
  - `true_branch` / `false_branch`：向后兼容字段。

### 6.6 编辑事件参数

在「事件列表」中选中事件后点击 **编辑事件**，弹出 `EventEditorDialog`。该对话框按事件类型
加载对应参数页，可修改全部参数（并非仅改名称）。确认后写回事件的 `params`。

### 6.7 事件重试机制

事件通用字段控制容错（来自 `models/event.py`）：

- `on_error`：出错时的处理，默认 `skip`（跳过继续）。
- `max_retries`：最大重试次数，默认 `3`。
- `retry_interval`：重试间隔（秒），默认 `1.0`。
- `pre_delay`：事件执行前延迟（秒），默认 `0`。
- `post_delay`：事件执行后延迟（秒），默认 `0.5`。
- `enabled`：是否启用，默认 `true`。

### 6.8 调整事件顺序

在「事件列表」中使用 **上移** / **下移** 调整事件执行顺序。

### 6.9 保存任务序列

- 自动保存：每次任务/事件增删改，自动写入自动保存路径（组 1 为
  `data/task_sequence_autosave.json`；组 2+ 为组配置指定的 `task_sequence` 路径或
  `data/task_sequence_autosave_gN.json`）。
- 手动保存：菜单 **文件 → 保存任务序列**（`Ctrl+S`），选择路径导出为 `.json`。

### 6.10 绑定游戏窗口

见 [9.1](#91-绑定方式)。

### 6.11 开始执行

- 工具栏 **▶ 开始执行**：执行任务序列全部任务。
- 工具栏 **▶ 执行当前任务**：仅执行任务下拉框当前选中的任务。
- 执行前需先绑定窗口（见 [9.1](#91-绑定方式)）。

### 6.12 监控执行

- 「主控制面板」实时显示执行状态、进度、当前事件与多色日志。
- 执行结束后弹窗提示「任务完成 / 任务终止」。

### 6.13 暂停 / 停止

- **⏸ 暂停**：暂停当前执行。
- **⏹ 停止**：停止当前执行。

---

## 7. 任务库导入说明

### 7.1 预置模块

预置模块列表定义在 `config/settings.json` 的 `task_library.modules` 字段，每个条目指向
`tasks/library/` 或 `library/map_packs/` 下的一个 Python 模块（以文件名作为模块名）。
默认包含约 19 个模块，例如：`SYHS`、`HCA`、`JHRW1`、`JNYW`、`CAC`、`DHW`、`CSC`、`XLNR`、
`BXG`、`ZZG`、`JYC`、`ALG`、`JHRW`、`MPCG`、`SYBUZ2`、`DSHNPC`、`BSHC`、`ZGUI`、`PZXY-ZG`。
（权威列表以 `settings.json` 为准。）

### 7.2 导入新脚本

在「任务库」标签页点击 **导入脚本**，选择本地 Python 文件，作为自定义（custom）模块加入。
导入后出现在模块列表中，勾选即启用。

### 7.3 模块管理

- **刷新**：重新从配置加载模块列表。
- **保存配置**：将当前模块启用状态写入 `settings.json`。
- **启用 / 禁用**：切换模块勾选状态（也可直接勾选列表项）。
- **重新加载**：重新导入模块（修改脚本后使用）。
- **移除**：从列表中移除自定义模块。

### 7.4 模块分类

模块按 `category` 着色：

- `built_in`：内置模块（蓝）
- `custom`：自定义导入模块（绿）
- `map`：地图包模块（橙）

### 7.5 函数调用

在「任务编辑」中添加「函数调用」事件，从 `module` 下拉选择已启用模块（含 `auto` 自动按
地图匹配），再从 `function` 下拉选择该模块导出的函数，填写 `args` / `kwargs`（JSON）。
函数执行结果（如 `target_location`）会进入变量上下文，供后续事件或条件分支引用。

---

## 8. YOLO 模型配置

### 8.1 配置位置

YOLO 相关配置位于「配置 → 识别参数」分组：

- **YOLO 置信度**：全局检测置信度阈值（0–1），作为事件 `conf_*` 档位的基准。
- **YOLO 模型**：模型文件路径，写入 `recognition.yolo_model_path`。

### 8.2 模型文件

默认模型路径为 `models/active.pt`（由 `recognition.yolo_model_path` 决定，可在配置面板
用浏览按钮修改）。

### 8.3 置信度阈值

事件内通过 `conf_near` / `conf_mid` / `conf_far` 三档置信度控制近/中/远目标的判定；
同时受全局「YOLO 置信度」约束。

### 8.4 使用方式

在「任务编辑」中添加「YOLO 识别」事件，填写 `target_class`、`region`、`action` 等参数
（见 [6.5.5](#655-yolo-识别yolo)）。需要 `torch` + `ultralytics` 已安装。

### 8.5 注意事项

- YOLO 依赖为可选，未安装时相关事件执行会报缺包错误。
- `core.yolo_detector` 为懒加载，仅在首次使用 YOLO 事件时导入，避免无谓占用显存。

---

## 9. 窗口绑定与输入模式

### 9.1 绑定方式

点击工具栏 **🔗 绑定窗口**，弹出 `WindowSelectorDialog`（`gui/window_selector.py`）。

对话框以表格列出当前游戏窗口，列为：**PID**、**角色名**、**状态**、**窗口标题**、**句柄**。

操作按钮：

- **锁定选中窗口**：绑定选中的窗口，将 `window.pid`（及标题）持久化到配置。
- **解除绑定**：解除当前绑定。
- **关闭**：关闭对话框。

绑定成功后，工具栏「窗口状态标签」变为「已绑定: PID=...」，并自动把网关换绑到该 PID。
启动时可配置 `window.auto_restore`（默认 `true`）自动恢复上次绑定。
多组环境下，绑定仅对当前组生效（绑定信息写入对应组的 `config/group<N>/settings.json`）。

### 9.2 输入模式

输入模式由配置文件 `window.input_mode` 控制（`core/input_controller.py` 读取，未配置默认
`foreground`）：

- `foreground`：前台输入（会操作真实鼠标/键盘）。
- `background`：后台输入（不抢占鼠标，默认 `background`）。

> 注意：输入模式**不在 GUI 配置面板中编辑**，需手动修改 `settings.json` 的
> `window.input_mode` 字段。`input_mode=background` 时，地图类函数会自动注入
> `background=True` 参数。

### 9.3 注意事项

- 绑定窗口后会立即同步网关到新 PID，使状态栏网关徽章变为「●在线」。
- 多开场景下请用 PID 区分不同账号窗口。
- 关闭 GUI 时会优雅停止任务引擎与本组网关（detach frida session），请勿直接任务管理器
  强杀，以免游戏闪退。

---

## 10. 配置文件说明

### 10.1 文件位置

- 默认配置：`config/settings.json`
- 多组配置：`config/group1/settings.json`、`config/group2/settings.json` ...（由 `MHXY_GROUP`
  决定，组 1 仍用根目录 `config/settings.json` 兼容历史）。
- 任务序列自动保存：
  - 组 1：`data/task_sequence_autosave.json`
  - 组 2+：`data/task_sequence_group<N>.json`（组配置 `task_sequence` 指定）或
    `data/task_sequence_autosave_g<N>.json`
- 运行期导出：`data/current_quest.json`（函数事件返回的游戏任务信息，供 IPC）

### 10.2 结构说明

`config/settings.json` 主要分区（以代码 `_DEFAULTS` 与实际文件为准）：

- `window`：`title`、`pid`、`input_mode`（默认 `background`）、`auto_restore` 等。
- `recognition`：`template_threshold`（默认 0.8）、`yolo_confidence`（默认 0.5）、
  `yolo_model_path`（默认 `models/active.pt`）、`screenshot_interval`（默认 0.5）、
  `jhrw_roi`（`[x,y,w,h]`）。
- `logging`：`level`（默认 INFO）、`file_path`（默认 `logs/automation.log`）、
  `auto_clean_days`（默认 7）。
- `task_library`：`modules`（模块列表）。
- `input`：`debug_click`、`cursor_sync_click`、`confirm_click_done`、`verify_retries`
  （默认 3）、`verify_threshold`（默认 30）、`verify_settle_delay`（默认 0.2）。
- `resolution`：`base_size`（`[1000,600]`）、`auto_scale`（默认 `true`）。
- `relogin`：`enabled`（默认 false）、`interval_min`（默认 180）、`client_path`、
  `click_points`（坐标列表）、`click_gap`（默认 1.2）。

### 10.3 字段说明

| 分区 | 字段 | 说明 | 默认值 |
| --- | --- | --- | --- |
| window | input_mode | 输入模式 | background |
| recognition | template_threshold | 模板匹配阈值 | 0.8 |
| recognition | yolo_confidence | YOLO 置信度 | 0.5 |
| recognition | yolo_model_path | YOLO 模型路径 | models/active.pt |
| recognition | screenshot_interval | 截图间隔(秒) | 0.5 |
| recognition | jhrw_roi | 节日任务 ROI | [840,156,150,77] |
| logging | level | 日志级别 | INFO |
| logging | auto_clean_days | 日志自动清理(天) | 7 |
| input | verify_retries | 点击验证重试 | 3 |
| input | verify_threshold | 点击验证阈值 | 30 |
| resolution | base_size | 基准分辨率 | [1000,600] |
| resolution | auto_scale | 自动缩放 | true |
| relogin | enabled | 定时重登开关 | false |
| relogin | interval_min | 重登间隔(分钟) | 180 |

### 10.4 手动编辑

可用菜单 **设置 → 重新加载配置** 重新读取修改后的 `settings.json`；修改后点击
**设置 → 保存配置** 可写回。手动编辑 JSON 后请确保格式合法。

---

## 11. 任务序列 JSON 格式

任务序列以 `.json` 文件保存，由 `models/task_sequence.py` 与 `models/task.py` /
`models/event.py` 序列化。

### 11.1 JSON 结构

顶层（`TaskSequence`）：

```json
{
  "id": "uuid",
  "name": "任务序列名称",
  "tasks": [ "Task 对象", ... ],
  "current_task_index": 0,
  "current_event_index": 0,
  "loop_count": 0,
  "loop_delay": 1.0
}
```

- `loop_count`：整个序列的循环次数，`0`=无限，默认 `1`。
- `loop_delay`：序列每轮循环间隔（秒），默认 `1.0`。

每个 `Task` 对象：

```json
{
  "id": "uuid",
  "name": "任务名称",
  "description": "任务描述",
  "events": [ "Event 对象", ... ],
  "loop_count": 1,
  "loop_delay": 1.0,
  "created_at": "2026-09-10 12:00:00",
  "updated_at": "2026-09-10 12:00:00"
}
```

- `loop_count`：该任务自身循环次数，`0`=无限，默认 `1`。
- `loop_delay`：任务每轮循环间隔（秒），默认 `1.0`。

### 11.2 事件（Event）字段

每个事件（`models/event.py` 的 `to_dict()`）：

```json
{
  "id": "uuid",
  "name": "事件名",
  "event_type": "click | key | wait | image | yolo | function | condition",
  "params": { },
  "pre_delay": 0,
  "post_delay": 0.5,
  "on_error": "skip",
  "max_retries": 3,
  "retry_interval": 1.0,
  "enabled": true,
  "var_name": ""
}
```

`params` 各事件类型的具体字段见 [6.5](#65-七种事件类型说明)。

### 11.3 完整示例

```json
{
  "id": "seq-001",
  "name": "示例序列",
  "tasks": [
    {
      "id": "task-001",
      "name": "抓鬼一轮",
      "description": "自动完成一轮抓鬼",
      "loop_count": 0,
      "loop_delay": 2.0,
      "created_at": "2026-09-10 12:00:00",
      "updated_at": "2026-09-10 12:00:00",
      "events": [
        {
          "id": "evt-001",
          "name": "点击领取",
          "event_type": "click",
          "params": {
            "x": 327, "y": 345, "button": "left", "background": true,
            "press_delay": 0.05, "verify": false,
            "probe_x": 0, "probe_y": 0,
            "verify_retries": 3, "verify_threshold": 30
          },
          "pre_delay": 0.2, "post_delay": 0.5,
          "on_error": "skip", "max_retries": 3,
          "retry_interval": 1.0, "enabled": true, "var_name": ""
        },
        {
          "id": "evt-002",
          "name": "调用寻路",
          "event_type": "function",
          "params": {
            "module": "JHRW", "function": "go_target",
            "args": [], "kwargs": {},
            "result_validate_field": "target_location",
            "result_validate_whitelist": null,
            "result_validate_retries": 3,
            "result_validate_retry_interval": 1.0,
            "auto_wait_arrival": true,
            "wait_arrival_timeout": 30.0,
            "wait_arrival_tolerance": 5,
            "wait_arrival_stop_confirm_s": 2.0,
            "wait_arrival_sample_interval": 0.5,
            "wait_arrival_retries": 3
          },
          "pre_delay": 0, "post_delay": 0.5,
          "on_error": "skip", "max_retries": 3,
          "retry_interval": 1.0, "enabled": true, "var_name": "JHRW"
        },
        {
          "id": "evt-003",
          "name": "按地图分流",
          "event_type": "condition",
          "params": {
            "mode": "switch",
            "match_field": "target_location",
            "match_custom_field": "",
            "source_var": "JHRW",
            "cases": [
              {
                "match_value": "长寿村",
                "actions": [
                  { "id": "sub-1", "name": "长寿动作",
                    "event_type": "click", "params": { "x": 100, "y": 200, "button": "left", "background": true },
                    "pre_delay": 0, "post_delay": 0.5, "on_error": "skip",
                    "max_retries": 3, "retry_interval": 1.0, "enabled": true, "var_name": "" }
                ]
              }
            ],
            "default_action": { "action": "none" },
            "true_branch": [], "false_branch": []
          },
          "pre_delay": 0, "post_delay": 0.5,
          "on_error": "skip", "max_retries": 3,
          "retry_interval": 1.0, "enabled": true, "var_name": ""
        }
      ]
    }
  ],
  "current_task_index": 0,
  "current_event_index": 0,
  "loop_count": 1,
  "loop_delay": 1.0
}
```

---

## 12. 常见问题

**Q1：函数专用 GUI 和 PP GUI 有什么区别？**
A：函数专用 GUI 入口为 `main.py`，编排并执行单个账号的任务序列（本文档描述对象）；
PP GUI 入口为 `tools/pp_gui.py`，用于五开多账号并行，详见根目录 `README.md`。

**Q2：启动后提示窗口未绑定？**
A：点击工具栏「🔗 绑定窗口」，在表格中选中目标游戏窗口并「锁定选中窗口」。若设置了
`window.auto_restore`（默认开启），下次启动会自动恢复。

**Q3：YOLO 事件报错缺包？**
A：未安装 `torch` / `ultralytics`。按 [2.4](#24-yolo-模型可选安装说明) 安装后重试。

**Q4：如何修改输入模式（前台/后台）？**
A：输入模式不在 GUI 配置面板内，需手动编辑 `settings.json` 的 `window.input_mode`
（`foreground` 或 `background`，默认 `background`）。

**Q5：任务序列会自动保存吗？**
A：会。每次增删改自动写入自动保存路径（见 [10.1](#101-文件位置)）；也可菜单
**文件 → 保存任务序列**（`Ctrl+S`）手动导出。

**Q6：条件分支支持几层嵌套？**
A：条件分支通过递归执行子流程实现，引擎按深度递归处理，没有固定的「最多 3 层」硬限制；
实际嵌套深度取决于任务编排。

**Q7：如何并行多开？**
A：使用 `start_group1.bat` / `start_group2.bat` 启动不同组（独立进程、独立配置与网关），
或在已运行 GUI 中点击工具栏「🚀 启动其他组」。

**Q8：验证码看门狗是什么？**
A：`main.py` 默认会启动验证码看门狗（`core.captcha_link.ensure_watchdog`）；而
`start_group*.bat` 通过环境变量 `MHXY_NO_WATCHDOG=1` 禁用它。

**Q9：定时重新登录如何配置？**
A：在「配置 → 定时重新登录」分组勾选「启用定时重新登录」，填写客户端路径、间隔与登录
点击坐标；也可点工具栏「🔄 定时重登」立即触发一次。

**Q10：函数调用结果怎么给后续事件用？**
A：给函数事件设置 `var_name`，其结果字段（如 `target_location`）会进入变量上下文，
后续事件坐标或条件分支 `source_var` 可用 `${var_name.field}` 或该变量名引用。

---

> 本手册依据当前代码重写，与代码不一致以代码为准。
