#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
防回档自检脚本 —— 一键检查 mhxy-gui-automation 所有关键修复点是否完好。

背景（2026-08-05 00:35 用户要求"完美修复、不再回档"）：
    项目多次出现修复被回档的现象（main_window 绑定对话框、config_panel 扫描 UI、
    game_coord_reader 内存版、arrival_verifier 内存逻辑、window_manager bound/
    unbind/list_game_windows、event_editor 重复 SubFlowEditorDialog 等）。
    本脚本逐项检查关键修复特征，全部命中即视为"未回档"。

用法：
    E:/py/python.exe tools/check_fixes.py

退出码：0 = 全部通过；1 = 存在回档。
"""
import json
import os
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 每条检查: (描述, 相对路径, 类型, 参数)
#   类型 "regex"    → 参数 = (pattern, negative)
#   类型 "json_len" → 参数 = 最小 entries 数
#   类型 "json_no"  → 参数 = 不允许存在的 hash 前缀
CHECKS = [
    # 1. 窗口绑定升级（列表式 WindowSelectorDialog）
    ("窗口绑定: window_selector.py 存在", "gui/window_selector.py", "regex", (r".+", False)),
    ("窗口绑定: main_window 调用 WindowSelectorDialog", "gui/main_window.py", "regex", (r"WindowSelectorDialog", False)),
    ("窗口绑定: window_manager bound/unbind/list_game_windows", "core/window_manager.py",
     "regex", (r"def bound|def unbind|def list_game_windows", False)),

    # 2. 内存读取全移除
    ("内存移除: config_panel 无扫描 UI", "gui/config_panel.py", "regex",
     (r"_on_scan_coord_addresses|btn_scan_coord", True)),
    ("内存移除: game_coord_reader 无 pymem 代码(仅代码特征)", "core/game_coord_reader.py", "regex",
     (r"^import pymem|^from pymem|def find_coord_addresses|ReadProcessMemory\(|VirtualQueryEx\(", True)),
    ("内存移除: arrival_verifier 无内存逻辑", "core/arrival_verifier.py", "regex",
     (r"find_coord_addresses|garbage_coord_count|ocr_fallback_active", True)),

    # 3. 字模坐标核心修复
    ("字模: 相邻同字符去重", "core/glyph_coord_reader.py", "regex", (r"_dedupe_neighbor_same_char", False)),
    ("字模: 地图名模糊归一化", "core/glyph_coord_reader.py", "regex", (r"_normalize_map_name", False)),
    ("字模: 坐标跨行续接", "core/glyph_coord_reader.py", "regex", (r"cp_is_virtual", False)),
    ("字模: 画面异常检测(旋转/动画)", "core/glyph_coord_reader.py", "regex", (r"画面异常", False)),
    ("字模: [1 粘连块垂直切分", "core/glyph_coord_reader.py", "regex", (r"粘连块", False)),

    # 4. GUI 编辑器修复
    ("GUI: param_pages sender() 修复", "gui/param_pages.py", "regex",
     (r"functools\.partial\(self\._on_edit_case_subflow", False)),
    ("GUI: subflow_editor 复制/粘贴", "gui/subflow_editor.py", "regex",
     (r"_copy_subflow_events|复制选中事件", False)),
    ("GUI: event_editor 无重复 SubFlowEditorDialog", "gui/event_editor.py", "regex",
     (r"class SubFlowEditorDialog", True)),
    ("GUI: task_editor 复制/粘贴", "gui/task_editor.py", "regex",
     (r"_on_copy_event|复制选中事件", False)),

    # 5. 输入与任务引擎
    ("输入: KEYEVENTF_KEYUP 定义", "core/input_controller.py", "regex", (r"KEYEVENTF_KEYUP", False)),
    # 2026-08-10 引擎拆分后 region 校验迁入 mixins/yolo_mixin.py
    ("引擎: task_engine region 校验", "core/task_engine_mixins/yolo_mixin.py", "regex",
     (r"_rw <= 0 or _rh <= 0", False)),

    # 2026-08-16 方案 A：PostMessage 点击前光标同步（SetCursorPos 解决命中检测）
    ("光标同步: input_controller 有 _sync_cursor", "core/input_controller.py", "regex",
     (r"def _sync_cursor", False)),
    ("光标同步: 函数包点击前同步光标", "library/map_packs/JYC.py", "regex",
     (r"_sync_cursor\(cx, cy\)", False)),
    # 2026-08-16 真后台鼠标：GetCursorPos IAT hook（伪造坐标，物理光标不动）
    ("光标同步: hook 注入工具存在", "tools/hook_cursor_pos.py", "regex",
     (r"GetCursorPos IAT|build_fake", False)),
    ("光标同步: hook 客户端存在", "tools/hook_cursor_client.py", "regex",
     (r"def set_cursor|def is_hooked", False)),
    ("光标同步: input_controller hook 优先", "core/input_controller.py", "regex",
     (r"hook_cursor_client|is_hooked", False)),

    # 2026-08-05 click_delay 必须在主点击和附加点击之间（不是附加后）。
    # regex 故意包含注释以让 check_fixes 的非注释过滤不影响判定
    # （只要 _do_click 后到 _do_additional_click 前出现 time.sleep 就 OK）
    ("附加点击: 主点击→click_delay→附加点击 顺序", "core/task_engine.py", "regex",
     (r"_do_click\([^)]+\)\s*[\r\n]+\s*if click_delay_ms > 0:\s*time\.sleep[\s\S]{0,100}?_do_additional_click\(", False)),

    # 2026-08-05 UI 遮挡避让（大地图/任务追踪面板点击失效）
    ("UI避让: map_ui_block 模块存在", "core/map_ui_block.py", "regex",
     (r"def map_coord_ui_avoid", False)),
    ("UI避让: 接入 _avoid_no_go_zone", "core/task_library_manager.py", "regex",
     (r"map_coord_ui_avoid", False)),
    ("UI避让: 数据文件存在", "data/map_ui_blocks.json", "exists", None),
    ("UI避让: 校准工具存在", "tools/calibrate_ui_blocks.py", "regex",
     (r"def wait_point", False)),

    # 2026-08-05 全后台化：input_mode=background + 地图函数注入 background=True
    ("后台化: settings input_mode=background", "config/settings.json", "regex",
     (r"\"input_mode\": \"background\"", False)),
    ("后台化: _inject_background_mode 存在", "core/task_library_manager.py", "regex",
     (r"def _inject_background_mode", False)),
    ("后台化: call_function 接入注入", "core/task_library_manager.py", "regex",
     (r"_inject_background_mode\(", False)),
    # 2026-08-05 修复：win32gui 没有 PostMessageW（正确 API 是 PostMessage），
    # 后台模式全崩在 AttributeError。禁止 PostMessageW 再次出现。
    ("后台化: 无 win32gui.PostMessageW 误用", "core/input_controller.py", "regex",
     (r"win32gui\.PostMessageW", True)),
    # 2026-08-05 后台点击补右键：9 个地图函数包的 _click_background 必须含右键消息
    ("后台化: 地图函数后台点击含右键", "E:/DS/梦幻西游脚本函数包/地图数据/JNYW.py", "regex",
     (r"WM_RBUTTONDOWN", False)),
    # 2026-08-05 GUI 简化：移除"窗口配置"组（PID/绑定/输入模式/状态）
    ("GUI: config_panel 已移除窗口配置", "gui/config_panel.py", "regex",
     (r"_build_window_group", True)),
    ("GUI: 日志配置含自动清理天数", "gui/config_panel.py", "regex",
     (r"auto_clean_spin", False)),
    # 2026-08-05 日志清理函数存在
    ("日志: cleanup_old_logs 函数存在", "utils/logger.py", "regex",
     (r"def cleanup_old_logs", False)),
    # 2026-08-05 后台点击 wparam 修复：DOWN 消息必须带 MK_ 标志（否则游戏忽略）
    ("后台化: 点击 DOWN 带 MK_ 标志", "core/input_controller.py", "regex",
     (r"_MOUSE_DOWN_WPARAM", False)),
    ("后台化: _post_click 用 down_wparam", "core/input_controller.py", "regex",
     (r"down_wparam", False)),
    # 2026-08-05 后台点击先发 WM_MOUSEMOVE（hover 悬停位置，与地图函数包一致；
    # 部分 UI 需 hover 状态才可点，如传送菜单项）
    ("后台化: 点击前先发 WM_MOUSEMOVE", "core/input_controller.py", "regex",
     (r"WM_MOUSEMOVE, 0, lparam\)", False)),
    # 2026-08-05 ALT 组合键修复：伴随 ALT 的 SYSKEYDOWN lparam 必须带 bit29(0x20000000)
    ("后台化: SYSKEYDOWN 带 Alt bit29", "core/input_controller.py", "regex",
     (r"0x20000000", False)),
    # 2026-08-05 ALT 组合键根治：PostMessage 不更新键盘状态表 → 降级 keybd_event
    ("后台化: ALT 组合键降级 keybd_event", "core/input_controller.py", "regex",
     (r"降级 keybd_event|_press_key_foreground\(keys\)", False)),
    # 2026-08-06 抖动逻辑移入地图函数包：引擎层不再抖动（negative 检查），函数包内 +1~6
    ("到达重试: 引擎层无抖动(已移入函数包)", "core/task_engine.py", "regex",
     (r"random\.uniform\(-2\.0|到达重试.*重新点击", True)),
    ("到达重试: 函数包内抖动 +1~6", "library/map_packs/JYC.py", "regex",
     (r"random\.uniform\(1\.0, 6\.0\)|MAP_MAX_GAME_COORD", False)),
    # 2026-08-06 到达失败才抖动：引擎置位 _JITTER_MODE（False=第一次不随机）
    ("到达重试: 引擎按到达结果置位 _JITTER_MODE", "core/task_engine.py", "regex",
     (r"_set_map_jitter_mode\(True\)|_set_map_jitter_mode\(False\)", False)),
    ("到达重试: 函数包 _JITTER_MODE 标志存在", "library/map_packs/JYC.py", "regex",
     (r"_JITTER_MODE = False|if _JITTER_MODE:", False)),
    # 2026-08-05 子流程列表显示 enabled 状态：之前 disabled 项与 enabled 视觉一样
    # 无法判断"哪个没启用"，导致用户以为修改不了
    ("子流程: 显示 [已禁用] 标签", "gui/subflow_editor.py", "regex",
     (r"\[已禁用\]", False)),

    # 2026-08-05 等待到达期间隐藏鼠标（防遮挡 YOLO/模板识别目标）
    ("隐藏鼠标: arrival_verifier 有 _move_mouse_away", "core/arrival_verifier.py", "regex",
     (r"def _move_mouse_away", False)),
    ("隐藏鼠标: wait_for_arrival 有 hide_mouse 参数", "core/arrival_verifier.py", "regex",
     (r"hide_mouse: bool = True", False)),
    ("隐藏鼠标: task_engine 透传 wait_arrival_hide_mouse", "core/task_engine.py", "regex",
     (r"wait_arrival_hide_mouse", False)),

    # 2026-08-05 地图禁区规避（传送热点/陷阱）
    ("禁区: map_no_go.py 存在", "core/map_no_go.py", "regex", (r"def resolve_safe_coord", False)),
    ("禁区: 数据表 map_no_go_zones.json 存在", "data/map_no_go_zones.json", "regex",
     (r"建邺城", False)),
    ("禁区: task_library_manager 接入 _avoid_no_go_zone", "core/task_library_manager.py", "regex",
     (r"_avoid_no_go_zone", False)),

    # 5.5 DLL 环境修复（torch c10.dll 1114）
    ("环境: main.py 预加载 vcruntime140.dll", "main.py", "regex",
     (r"_preload_vcruntime|vcruntime140\.dll", False)),

    # 5.6 事件驱动到达判定（2026-08-05 重构）
    ("到达: 静止确认秒数 stop_confirm_s", "core/arrival_verifier.py", "regex",
     (r"stop_confirm_s", False)),
    ("到达: 停止失败观察 stop_fail_confirm_s", "core/arrival_verifier.py", "regex",
     (r"stop_fail_confirm_s", False)),
    ("到达: 移动兜底自动估算 MOVE_SPEED_LOWER_BOUND", "core/arrival_verifier.py", "regex",
     (r"MOVE_SPEED_LOWER_BOUND", False)),
    ("到达: 无旧 OCR 无条件兜底残留", "core/arrival_verifier.py", "regex",
     (r"memory_arrived", True)),

    # 5.7 JHRW ROI 配置化 + 全括号坐标扫描（2026-08-05）
    ("ROI: settings.json 含 jhrw_roi", "config/settings.json", "regex",
     (r"jhrw_roi", False)),
    ("ROI: glyph_coord_reader get_jhrw_roi()", "core/glyph_coord_reader.py", "regex",
     (r"def get_jhrw_roi", False)),
    ("坐标: extract_coord_global 全括号扫描", "core/glyph_coord_reader.py", "regex",
     (r"def extract_coord_global|def _extract_coord_global_from_glyphs", False)),
    ("坐标: JHRW 接线优先 global", "core/glyph_coord_reader.py", "regex",
     (r"extract_coord_global\(\[", False)),
    ("坐标: 无逗号最大间隙分界", "core/glyph_coord_reader.py", "regex",
     (r"gap_is_real", False)),
    ("坐标: UNKNOWN 窄块补位(0变体)", "core/glyph_coord_reader.py", "regex",
     (r"num_with_q", False)),

    # 6. 字模库完整性
    ("字模库: entries >= 100", "data/glyph_library.json", "json_len", 100),
    ("字模库: 无窄高 1 碰撞样本 cbb8f957", "data/glyph_library.json", "json_no", "cbb8f957"),
]


def _check(desc: str, path: str, kind: str, arg) -> bool:
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return False
    try:
        if kind == "json_len":
            data = json.load(open(full, encoding="utf-8"))
            return len(data.get("entries", {})) >= arg
        if kind == "json_no":
            data = json.load(open(full, encoding="utf-8"))
            return all(not h.startswith(arg) for h in data.get("entries", {}))
        if kind == "exists":
            return True  # 文件存在已在上面 os.path.exists 判定
        # regex：跳过注释行后匹配（docstring 纯文本行不含代码特征）
        pattern, negative = arg
        with open(full, "r", encoding="utf-8") as f:
            lines = f.readlines()
        code_lines = [
            ln for ln in lines
            if not ln.strip().startswith("#")
            and not ln.strip().startswith('"""')
            and not ln.strip().startswith("'''")
        ]
        content = "".join(code_lines)
        hit = bool(re.search(pattern, content, re.MULTILINE))
        return (not hit) if negative else hit
    except Exception:
        return False


def main() -> int:
    print("=" * 60)
    print(" mhxy-gui-automation 防回档自检")
    print("=" * 60)
    all_pass = True
    fails = []
    for desc, path, kind, arg in CHECKS:
        ok = _check(desc, path, kind, arg)
        if not ok:
            all_pass = False
            fails.append(desc)
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    print("=" * 60)
    if all_pass:
        print("  ✅ 全部修复点完好，未回档")
        return 0
    print("  ❌ 存在回档，FAIL 项：")
    for d in fails:
        print(f"     - {d}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
