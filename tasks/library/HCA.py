# -*- coding: utf-8 -*-
"""
HCA - 回长安函数包（跨地图传送 + 指定坐标）
================================================================
功能: 无论角色在哪张地图，跨图回长安并瞬移到指定坐标（默认 240,101）

实现: 复用 SYHS 的跨图+瞬移+画面定格逻辑（target_location='长安' 固定），
     目标地图 ID=1001（实测长安），传送阵/切图/服务器同步全部走已验证链路。

跨图原理（SYHS 2026-08-20 实测）:
  ① 瞬移到"当前图→长安"传送阵(1002同步) → ② 等服务器校验位置 →
  ③ 发 1003 {"说明"="当前图传送长安"} → ④ 等切图/画面定格 → ⑤ 瞬移到目标坐标

使用方式:
  from HCA import HCA
  r = HCA()                        # 回长安 (240, 101)
  r = HCA(240, 101)                # 显式坐标
  r = HCA(x=300, y=200)            # 关键字坐标
"""
import json
import os
import sys
import urllib.request
from typing import Optional

try:
    from utils.logger import logger
except Exception:  # 独立运行
    import logging
    logger = logging.getLogger("HCA")
    logging.basicConfig(level=logging.INFO)

# 同目录模块（SYHS）导入支持
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from SYHS import SYHS  # noqa: E402

# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# ============================================================
__function_meta__ = {
    "HCA": {
        "title": "回长安: 跨图传送回长安并瞬移到坐标（默认 240,101）",
        "args": {
            "x": "长安地图坐标 X（默认 240）",
            "y": "长安地图坐标 Y（默认 101）",
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "sync": "True=自动发 1002 同步服务端（默认），False=只改画面",
            "verbose": "是否打印过程日志",
            "wait_stable": "True=到达后等画面定格再结束（默认），False=固定等待",
            "stable_timeout": "画面定格等待超时秒数（默认 20）",
            "stable_frames": "连续 N 帧/次稳定才算定格（默认 3）",
            "stable_threshold": "截屏帧间平均像素差阈值（默认 8，越小越严）",
            "stable_min_settle": "坐标稳定后再等的渲染窗口秒数（默认 3.5，跨图 5s）",
        },
    },
}

# 默认网关地址
DEFAULT_GATEWAY = "http://127.0.0.1:18082"
# 回长安默认落点（用户指定: 长安 240,101）
DEFAULT_COORD = (240, 101)


def _probe_map_id(gateway: str):
    """读 tp.当前地图（地图ID），调试用。失败返回 '?'。"""
    try:
        req = urllib.request.Request(
            gateway.rstrip("/") + "/api/lua",
            data=json.dumps({
                "code": "_G.__out = tostring(tp.当前地图)"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=5).read())
        return d.get("result", {}).get("value") or "?"
    except Exception:
        return "?"


def HCA(
    x: Optional[int] = None,
    y: Optional[int] = None,
    gateway: str = DEFAULT_GATEWAY,
    sync: bool = True,
    verbose: bool = False,
    wait_stable: bool = True,
    stable_timeout: float = 20.0,
    stable_frames: int = 3,
    stable_threshold: float = 8.0,
    stable_min_settle: float = 3.5,
):
    """回长安：跨图传送回长安（目标地图固定=长安 1001）并瞬移到坐标。

    任何地图调用都会先跨图到长安（若不在长安），再瞬移到目标坐标。
    坐标缺省时使用默认落点 (240, 101)。

    :param x/y: 长安地图坐标（默认 240,101）
    :param gateway: 网关地址
    :param sync: True=自动 1002 同步服务端
    :param verbose: 打印过程日志
    :param wait_stable: 到达后等画面定格再结束
    :return: dict {ok, target_coord, internal_coord, map_switch, scene_stable, message, detail}
    """
    # 解析坐标（缺省用默认落点）
    try:
        tx = int(float(x)) if x is not None else DEFAULT_COORD[0]
        ty = int(float(y)) if y is not None else DEFAULT_COORD[1]
    except (TypeError, ValueError) as e:
        return {
            "ok": False, "target_coord": None, "internal_coord": None,
            "message": f"坐标解析失败: {e}（收到 x={x!r} y={y!r}）", "detail": None,
        }

    if verbose:
        logger.info(
            f"HCA: 回长安 ({tx},{ty}) 当前图={_probe_map_id(gateway)} → 目标 1001(长安)")

    # 复用 SYHS 完整链路: 跨图(如需要) + 瞬移 + 1002同步 + 画面定格
    return SYHS(
        (tx, ty),
        target_location="长安",
        gateway=gateway,
        sync=sync,
        verbose=verbose,
        wait_stable=wait_stable,
        stable_timeout=stable_timeout,
        stable_frames=stable_frames,
        stable_threshold=stable_threshold,
        stable_min_settle=stable_min_settle,
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="回长安（HCA）")
    ap.add_argument("x", nargs="?", type=int, default=DEFAULT_COORD[0],
                    help=f"长安X（默认 {DEFAULT_COORD[0]}）")
    ap.add_argument("y", nargs="?", type=int, default=DEFAULT_COORD[1],
                    help=f"长安Y（默认 {DEFAULT_COORD[1]}）")
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY, help="网关地址")
    args = ap.parse_args()
    r = HCA(args.x, args.y, gateway=args.gateway, verbose=True)
    print(json.dumps(r, ensure_ascii=False, indent=1))
