# -*- coding: utf-8 -*-
"""多组并行配置（2026-08-25）。

GUI 支持多实例并行，每组一套独立进程栈（GUI + 网关 + monitor + 配置）。
本模块集中管理"组"的定义：组号、角色关键词、网关端口、任务序列文件、
窗口标题/配色，供 main.py / MainWindow / 任务库统一读取。

用法:
  python main.py --group 1     # 启动组 1（默认组号 0/1）
  python main.py --group 2     # 启动组 2

组配置存储: config/group<N>/settings.json（含 gateway.port / window.title /
            window.roles / task_sequence 等覆盖项）；缺省回退主 config/settings.json。
"""
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")

# 组配色（标题栏 QSS 区分，组1蓝 / 组2绿，可扩展）
GROUP_STYLE = {
    1: {"color": "#2d7dd2", "name": "蓝组", "accent": "#2d7dd2"},
    2: {"color": "#3a9d5d", "name": "绿组", "accent": "#3a9d5d"},
    3: {"color": "#c97b2d", "name": "橙组", "accent": "#c97b2d"},
    4: {"color": "#8e4fc9", "name": "紫组", "accent": "#8e4fc9"},
}

# 默认网关端口：组1=18082（历史兼容），组2+=18080+组号
def _default_port(group: int) -> int:
    return 18082 if group <= 1 else 18080 + group


def load_group_config(group: int) -> dict:
    """加载指定组的配置（组专属覆盖 + 主配置合并）。返回 dict。"""
    merged = {}
    # 1) 主配置
    main_cfg = os.path.join(CONFIG_DIR, "settings.json")
    if os.path.exists(main_cfg):
        try:
            with open(main_cfg, encoding="utf-8") as f:
                merged.update(json.load(f))
        except Exception:
            pass
    # 2) 组专属配置覆盖
    group_cfg = os.path.join(CONFIG_DIR, f"group{group}", "settings.json")
    if os.path.exists(group_cfg):
        try:
            with open(group_cfg, encoding="utf-8") as f:
                _deep_merge(merged, json.load(f))
        except Exception:
            pass
    return merged


def _deep_merge(base: dict, override: dict):
    """递归合并 override 到 base（dict 深合并，其他直接覆盖）。"""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def group_title(group: int, roles: list = None, task_name: str = "") -> str:
    """生成窗口标题: 'MHXY GUI [组1] - 角色A,B,C - 任务名'."""
    st = GROUP_STYLE.get(group, {})
    parts = [f"MHXY GUI [组{group}]{st.get('name', '')}"]
    if roles:
        parts.append("角色:" + ",".join(str(r) for r in roles[:5]))
    if task_name:
        parts.append(task_name)
    return " - ".join(parts)


def group_status_text(group: int, port: int, role_count: int) -> str:
    """状态栏常驻文本: '组1 · 5号 · 网关:18082'."""
    return f"组{group} · {role_count}号 · 网关:{port}"
