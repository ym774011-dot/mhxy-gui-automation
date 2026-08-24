# -*- coding: utf-8 -*-
"""
SYHS - 瞬移函数包（基于 mhxy-mcp-gateway 的 /api/act/teleport）
================================================================
功能: 输入游戏逻辑坐标（地图坐标）→ 调用网关瞬移 → 服务器同步

原理（2026-08-20 实测确认）:
  1. 内部坐标 = 地图坐标 × 20（每格 20 像素）
  2. 改 tp.角色坐标 只动客户端画面，服务端不认账（NPC 距离判定按旧坐标）
  3. 需伪造 1002 位置上报包（复用 MD5 签名算法）→ 服务端认账 ✅

依赖: mhxy-mcp-gateway 网关（frida 附加游戏进程，HTTP 端口默认 18082）
      gateway.py --auto / <PID> --port 18082

使用方式:
  import sys; sys.path.insert(0, <mhxy>/tasks/library)
  from SYHS import SYHS
  result = SYHS((187, 36))                 # 瞬移到地图坐标 (187,36)
  result = SYHS((187, 36), gateway="http://127.0.0.1:18082")
  result = SYHS((187, 36), verbose=True)

接受 JHRW 任务信息:
  # JHRW 输出 dict 含 target_coord / target_location
  jhrw_result = JHRW()
  result = SYHS(jhrw_result.get("target_coord"))
"""
import json
import os
import sys
import time
import urllib.request
from typing import Optional, Tuple, Union

try:
    from utils.logger import logger
except Exception:  # 独立运行
    import logging
    logger = logging.getLogger("SYHS")
    logging.basicConfig(level=logging.INFO)

# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# ============================================================
__function_meta__ = {
    "SYHS": {
        "title": "瞬移: 传送到地图坐标（网关 teleport，服务器同步）",
        "args": {
            "target_coord": "(gx, gy) 游戏逻辑坐标，如 (187, 36)；或 JHRW 输出 dict（自动取 target_coord）；事件编辑器拆传时可省略",
            "x": "地图坐标 X（事件编辑器拆传时用，与 y 搭配；自动覆盖无价值 target_coord）",
            "y": "地图坐标 Y（事件编辑器拆传时用）",
            "target_location": "目标地图名（仅记录/校验，不参与瞬移坐标）",
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "raw": "True=直接传内部坐标(×20 前的值)，False=地图坐标自动×20（默认）",
            "sync": "True=自动发 1002 同步服务端（默认），False=只改客户端画面",
            "verbose": "是否打印过程日志",
            "wait_stable": "True=瞬移/跨图后等画面定格再结束（默认，识别画面停止），False=固定等待",
            "stable_timeout": "画面定格等待超时秒数（默认 15）",
            "stable_frames": "连续 N 帧/次稳定才算定格（默认 3）",
            "stable_threshold": "截屏帧间平均像素差阈值（默认 8，越小越严）",
            "stable_min_settle": "坐标稳定后再等的渲染窗口秒数（默认 1.5，跨图自动放大到 3s）",
        },
    },
}

# 默认网关地址（可被 GUI/任务参数覆盖）
DEFAULT_GATEWAY = "http://127.0.0.1:18082"

# ============================================================
# 地图跨图拓扑（2026-08-20 实测构建，可扩充）
# key=地图名, value=可直接传送到达的地图名列表
# ★注意: 传送条目命名不统一——长安用"长安传送X"、建邺城用"建邺城进X"
#   匹配用"目标名子串"，desc 直接用条目原始切换串（最接近真实请求）
# ============================================================
_MAP_ID = {
    "长安": 1001, "长安城": 1001,
    "江南野外": 1193,
    "建邺城": 1501,
    "东海湾": 1506,
    "长寿村": 1070, "长寿郊外": 1070,
}
_MAP_ROUTES = {
    "长安": ["江南野外", "大唐国境"],
    "江南野外": ["建邺城", "长安"],
    "建邺城": ["东海湾"],
    "东海湾": ["建邺城", "东海海底"],
    "大唐国境": ["长安"],
    "长寿村": ["长安"],
}

# ============================================================
# ★一步跨图直达表（2026-08-21 实测突破）
# 服务器不校验 1003 desc 的"起点图"是否等于当前图——只查起点图的
# 传送表里有没有这个终点，有就切图。所以任意图→目标图只需一条
# 任意合法条目 desc，一次 1003 直达（不需要多跳/传送阵/report_pos）。
# key=目标图名, value=任意一条能到该图的 desc 条目
# ============================================================
_ONE_HOP = {
    "长安": "江南野外传送长安",      # 实测 ✅
    "江南野外": "长安传送江南野外",  # 实测 ✅
    "建邺城": "江南野外传送建邺城",  # 实测 ✅
    "东海湾": "建邺城进东海湾新",    # 实测 ✅
    "东海海底": "东海湾进东海海底",  # 实测 ✅
    "长寿村": "大唐国境传送长寿郊外",
    "大唐国境": "长安传送大唐国境",
}


def _find_route(start: str, target: str):
    """BFS 找跨图路径，返回 [start, mid..., target] 或 None（不可达）。"""
    if start == target:
        return [start]
    from collections import deque
    q = deque([[start]])
    visited = {start}
    while q:
        path = q.popleft()
        cur = path[-1]
        for nxt in _MAP_ROUTES.get(cur, []):
            if nxt in visited:
                continue
            if nxt == target:
                return path + [nxt]
            visited.add(nxt)
            q.append(path + [nxt])
    return None


def _find_hop_teleport(gateway: str, target_name: str):
    """在当前图传送表里找能到 target_name 的传送条目。

    兼容两种命名: "长安传送江南野外"（传送）和 "建邺城进东海湾新"（进）。
    返回 (切换串原样, 世界坐标x, 世界坐标y) 或 None。
    """
    code = (
        'local out = "" '
        'local t = tp.场景.传送 '
        'for i = 1, #t do '
        '  local s = tostring(t[i].切换 or "") '
        '  if string.find(s, "%s") then '
        '    if t[i].坐标 then '
        '      out = s .. "|" .. tostring(t[i].坐标.x) .. "," .. tostring(t[i].坐标.y) '
        '    end '
        '    break '
        '  end '
        'end '
        '_G.__out = out'
    ) % str(target_name).strip()
    v = _http_json(gateway.rstrip("/") + "/api/lua", {"code": code})["result"]["value"]
    if v and "|" in v and "," in v:
        desc_part, xy = v.split("|", 1)
        x, y = xy.split(",")
        return desc_part, int(float(x)), int(float(y))
    return None


def _http_json(url: str, data: Optional[dict] = None, timeout: float = 10.0) -> dict:
    """向网关发 HTTP 请求（GET/POST JSON）。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# ============================================================
# 画面定格检测（2026-08-20 用户要求: 识别画面停止后再结束本函数）
# 双通道: ① 截屏帧间差（视觉，需窗口已绑定）② 游戏坐标稳定（网关，随时可用）
# ============================================================
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_capture_deps = None  # lazy 缓存截屏依赖（只初始化一次）


def _get_capture_deps():
    """加载截屏依赖（core.screen_capture / window_manager），失败返回空 dict。"""
    global _capture_deps
    if _capture_deps is None:
        try:
            if _PROJECT_ROOT not in sys.path:
                sys.path.insert(0, _PROJECT_ROOT)
            from core.window_manager import window_manager
            from core.screen_capture import screen_capture
            import win32gui
            _capture_deps = {
                "wm": window_manager, "sc": screen_capture, "win32gui": win32gui,
            }
        except Exception:
            _capture_deps = {}
    return _capture_deps


def _capture_frame():
    """截客户区画面（numpy 数组）。窗口未绑定/截图失败返回 None。"""
    deps = _get_capture_deps()
    if not deps or not deps["wm"].hwnd:
        return None
    try:
        win32gui = deps["win32gui"]
        rect = win32gui.GetClientRect(deps["wm"].hwnd)
        w, h = rect[2], rect[3]
        if w <= 0 or h <= 0:
            return None
        return deps["sc"].capture_region(0, 0, w, h)
    except Exception:
        return None


def _frame_diff(a, b):
    """两帧平均像素差（0~255）。帧无效/尺寸不同返回 None。"""
    if a is None or b is None:
        return None
    try:
        if a.shape != b.shape:
            return None
        import numpy as np
        return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean())
    except Exception:
        return None


def _wait_map_switch(gateway: str, target_map_id: int, timeout: float = 15.0,
                     verbose: bool = False):
    """轮询等待跨图完成：tp.当前地图 变为 target_map_id。

    ★2026-08-21 时序修正（用户反馈"先传入口再传目标"）：
      旧流程跨图后 sleep(2)+等画面定格(5s+)，人物明晃晃停在入口，看起来
      就是"先传送到地图入口，再传送到目标坐标"。实测跨图切换仅需 ~340ms，
      改为轮询地图 ID 一切换立即返回，让下游 teleport 马上跟上，入口停留
      压到 <0.5s，视觉上一步直达目标坐标。

    :return: (bool, float) (是否切换成功, 切换耗时毫秒)；超时返回 (False, 耗时)
    """
    t0 = time.time()
    cur = None
    while time.time() - t0 < timeout:
        try:
            cur = int(_http_json(gateway.rstrip("/") + "/api/lua/expr",
                                 {"expr": "tp.当前地图"}, timeout=5.0)
                      .get("result", {}).get("value"))
        except Exception:
            cur = None
        if cur == target_map_id:
            ms = round((time.time() - t0) * 1000)
            if verbose:
                logger.info(f"SYHS: 跨图完成 地图={cur} 耗时{ms}ms")
            return True, ms
        time.sleep(0.3)
    ms = round((time.time() - t0) * 1000)
    if verbose:
        logger.warning(f"SYHS: 跨图等待超时({timeout:.0f}s) 当前地图={cur}")
    return False, ms


def _probe_coord(gateway: str):
    """读 tp.角色坐标（内部坐标），返回 (x, y) 或 None。"""
    try:
        r = _http_json(
            gateway.rstrip("/") + "/api/lua",
            {"code": "_G.__out = tostring(tp.角色坐标.x) .. ',' .. tostring(tp.角色坐标.y)"},
            timeout=5.0,
        )
        v = r.get("result", {}).get("value")
        if v and "," in v:
            fx, fy = v.split(",")
            return (float(fx), float(fy))
    except Exception:
        pass
    return None


def _wait_scene_stable(
    gateway: str,
    timeout: float = 15.0,
    settle_frames: int = 3,
    frame_threshold: float = 8.0,
    min_settle: float = 1.5,
    verbose: bool = False,
):
    """等待画面定格（任一通道确认即返回）。

    通道1（截屏）: 连续 settle_frames 帧平均像素差 < frame_threshold → 画面静止
                  ——渲染权威信号（角色插值动画/场景加载完成才会静止）
    通道2（坐标+渲染窗口）: tp.角色坐标 连续 settle_frames 次无变化后，
                 再等 min_settle 秒渲染窗口——★2026-08-20 修正：
                 数据坐标瞬移后立即到位，但渲染插值需要时间，坐标稳定
                 不等于画面到位（用户实测: 画面延迟很久才到指定位置）。
                 坐标稳定后再给渲染留 min_settle 秒。

    两个通道都不可用时（网关断+窗口未绑）→ 立即返回 False，不阻塞调用方。

    :return: (bool, str) (是否定格, 说明)
    """
    t0 = time.time()
    prev_frame = None
    prev_coord = None
    frame_hits = 0
    coord_hits = 0
    coord_stable_since = None  # 坐标首次稳定时刻（渲染窗口起点）
    last_diff = None
    while time.time() - t0 < timeout:
        # 通道1: 截屏帧间差（渲染权威）
        frame = _capture_frame()
        if frame is not None and prev_frame is not None:
            d = _frame_diff(prev_frame, frame)
            if d is not None:
                last_diff = d
                if d < frame_threshold:
                    frame_hits += 1
                    if frame_hits >= settle_frames:
                        if verbose:
                            logger.info(
                                f"SYHS: 画面定格(截屏 diff={d:.2f} 连续{frame_hits}帧)")
                        return True, f"截屏定格 diff={d:.2f} x{frame_hits}"
                else:
                    frame_hits = 0
        if frame is not None:
            prev_frame = frame
        # 通道2: 坐标稳定 + 渲染窗口
        coord = _probe_coord(gateway)
        if coord is not None:
            if prev_coord is not None and (
                abs(coord[0] - prev_coord[0]) < 1.0
                and abs(coord[1] - prev_coord[1]) < 1.0
            ):
                coord_hits += 1
                if coord_hits >= settle_frames and coord_stable_since is None:
                    coord_stable_since = time.time()
            else:
                coord_hits = 0
                coord_stable_since = None
            prev_coord = coord
            if coord_stable_since is not None:
                waited = time.time() - coord_stable_since
                if waited >= min_settle:
                    if verbose:
                        logger.info(
                            f"SYHS: 坐标稳定 + 渲染窗口 {waited:.1f}s "
                            f"({coord[0]:.0f},{coord[1]:.0f})")
                    return True, f"坐标稳定+渲染窗口{waited:.1f}s"
        time.sleep(0.5)
    return False, f"超时({timeout:.0f}s) 最后帧差={last_diff}"


def _walk_to_gather(hwnd: int, steps: int = 12, interval: float = 0.5,
                    settle: float = 5.0, verbose: bool = False):
    """★2026-08-21 队员归队：瞬移后真实走路，触发服务器 AI 把队员拉近到身边。

    实测机制（5 人队，私服多角色同窗）:
      - 队长瞬移(1002 位置跳变) → 只有支纵跟随（服务器瞬移跟随逻辑）
      - 队长真实走路(移动广播) → 服务器 AI 逐个拉近其他队员
        （丽俊/初凯心秋每走一段被拉近, 玉凝最后, 全员到队长周围阵型圈 ~5-14 格）
    实现: PostMessage 左键点击地面 12 次(屏幕中心附近小范围), 让角色真实走动,
    触发移动广播 → 服务器把队员拉过来; 最后 settle 秒等 AI 完成。
    """
    try:
        import win32gui
        import win32con
        cx, cy = 500, 310  # 屏幕中心附近（1000x620 客户区）
        for i in range(steps):
            px = cx + (i % 5 - 2) * 24
            py = cy + (i % 3 - 1) * 34
            lparam = (int(py) << 16) | (int(px) & 0xFFFF)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            time.sleep(interval)
        time.sleep(settle)
        if verbose:
            logger.info(f"SYHS: 走路拉人完成 {steps}步 等{settle}s")
        return True
    except Exception as e:
        if verbose:
            logger.warning(f"SYHS: 走路拉人失败(忽略): {e}")
        return False


def SYHS(
    target_coord: Union[Tuple[int, int], dict, None] = None,
    gateway: str = DEFAULT_GATEWAY,
    raw: bool = False,
    sync: bool = True,
    verbose: bool = False,
    x: Union[int, str, None] = None,
    y: Union[int, str, None] = None,
    target_location: Optional[str] = None,
    wait_stable: bool = True,
    stable_timeout: float = 20.0,
    stable_frames: int = 3,
    stable_threshold: float = 8.0,
    stable_min_settle: float = 3.5,
    gather_team: bool = False,
    gather_steps: int = 12,
    gather_settle: float = 5.0,
):
    """
    瞬移函数包：输入地图坐标 → 网关 teleport（改坐标 + 1002 同步）。

    兼容 JHRW 输出: 传 JHRW() 的 dict 结果会自动取 target_coord 字段。

    参数兼容（2026-08-20 GUI 事件实测修正）:
      - 事件编辑器可能把 x/y 拆成独立关键字传 → x/y 参数组装成 target_coord
      - 事件编辑器可能只传 target_location(地图名) → 此时无坐标则失败并明确提示

    画面定格（2026-08-20 用户要求）:
      - 跨图/瞬移完成后，等待画面真正静止（截屏帧间差 + 游戏坐标稳定双通道）
        才结束本函数——避免下游 YOLO/点击打到加载中的画面
      - wait_stable=False 可关闭（恢复固定 sleep 行为）

    跨图时序（2026-08-21 修正，用户反馈"先传入口再传目标"）:
      - 旧流程: 跨图 → sleep(2) → 等画面定格(5s+) → teleport。
        人物明晃晃停在地图入口 ~5 秒，看起来就是"先传送到入口再传目标"。
      - 新流程: 跨图 → 轮询 tp.当前地图 一切换(实测 ~340ms) → 立即 teleport
        → 统一等画面定格。入口停留 <0.5s，视觉上一步直达目标坐标。

    :param target_coord: (gx, gy) 地图坐标 或 JHRW dict（含 target_coord）
    :param gateway: 网关 HTTP 地址
    :param raw: True=传内部坐标(已×20)，False=地图坐标自动×20
    :param sync: True=自动 1002 同步服务端（推荐），False=只改画面
    :param verbose: 是否打印详细日志
    :param x/y: 独立坐标分量（事件编辑器拆传时使用）
    :param target_location: 目标地图名（用于跨图判断）
    :param wait_stable: True=瞬移后等画面定格再返回（默认），False=固定 sleep
    :param stable_timeout: 定格等待超时（秒，默认 20）
    :param stable_frames: 连续 N 帧/次稳定才算定格（默认 3）
    :param stable_threshold: 截屏帧间平均像素差阈值（默认 8，越小越严）
    :param stable_min_settle: 坐标稳定后再等的渲染窗口秒数（默认 3.5，
        ★2026-08-20 实测: 同图瞬移后画面 ~3.2s 才真正静止(diff<2)，
        1.5s 时画面还在加载(diff≈45) → 点击必歪；跨图自动放大到 5s）
    :param gather_team: True=瞬移后真实走路拉队员归队（默认 False；
        ★2026-08-21 实测: 5 人队队长瞬移只有 1 个队员跟随，走路触发
        服务器 AI 逐个拉近其他队员到队长周围阵型圈）
    :param gather_steps: 拉人走路步数（默认 12）
    :param gather_settle: 拉人后等 AI 完成秒数（默认 5）
    :return: dict {ok, target_coord, internal_coord, message, detail}
    """
    t0 = time.time()

    # ---- 解包：支持 (x,y) / JHRW dict / None / 独立 x/y 分量 ----
    if isinstance(target_coord, dict):
        # JHRW 输出直接传入
        tc = target_coord.get("target_coord")
        if not tc:
            return {
                "ok": False,
                "target_coord": None,
                "internal_coord": None,
                "message": f"JHRW dict 无 target_coord: {target_coord.get('message', '')}",
                "detail": target_coord,
            }
        target_coord = tc
        if verbose:
            logger.info(f"SYHS: 从 JHRW dict 取到 target_coord={target_coord}")

    # 事件编辑器拆传 x/y 时组装
    if target_coord is None and x is not None and y is not None:
        try:
            target_coord = (int(float(x)), int(float(y)))
            if verbose:
                logger.info(f"SYHS: 从 x/y 参数组装 target_coord={target_coord}")
        except (TypeError, ValueError):
            pass

    if target_coord is None:
        return {
            "ok": False, "target_coord": None, "internal_coord": None,
            "message": (
                f"缺少坐标（收到 target_coord={target_coord!r}, "
                f"x={x!r}, y={y!r}, target_location={target_location!r}）"
                "——事件里请传 target_coord=(x,y) 或 x/y 分量"
            ),
            "detail": None,
        }

    # ---- 坐标解析（兼容字符串/浮点）----
    try:
        if isinstance(target_coord, (list, tuple)) and len(target_coord) >= 2:
            gx, gy = int(float(target_coord[0])), int(float(target_coord[1]))
        elif isinstance(target_coord, dict) and "x" in target_coord and "y" in target_coord:
            gx, gy = int(float(target_coord["x"])), int(float(target_coord["y"]))
        elif x is not None and y is not None:
            # 事件编辑器拆传 x/y（target_coord 可能是地图名字符串等无价值值）
            gx, gy = int(float(x)), int(float(y))
            if verbose:
                logger.info(f"SYHS: 用 x/y 分量 ({gx},{gy}) 覆盖 target_coord={target_coord!r}")
            # ★2026-08-20 兼容: target_coord 收到地图名字符串时自动当 target_location
            #   避免用户在 GUI 误把"地图名"填到位置参数(target_coord)导致跨图判断跳过
            if isinstance(target_coord, str) and not target_location:
                target_location = target_coord.strip()
                logger.warning(
                    f"SYHS: target_coord 收到字符串 {target_location!r}（疑似地图名），"
                    f"自动作为 target_location——建议改 GUI 把地图名填到关键字参数 "
                    f"'target_location'（不要填到位置参数 target_coord）"
                )
        else:
            raise ValueError(f"无法解析 target_coord: {target_coord!r}")
    except (TypeError, ValueError, IndexError) as e:
        return {
            "ok": False, "target_coord": None, "internal_coord": None,
            "message": f"target_coord 解析失败: {e}（收到 {target_coord!r}）", "detail": None,
        }

    # ---- 跨图判断（target_location 提供时）----
    # ★2026-08-21 实测突破：服务器不校验 1003 desc 的起点图是否等于当前图，
    #   只查"起点图传送表里有没有该终点"，有就切图。所以任意图→目标图
    #   只需一条任意合法条目 desc，一次 1003 直达（无需多跳/传送阵/report_pos）。
    #   旧方案（多跳 BFS + 先到传送阵 + report_pos）保留作 _ONE_HOP 未收录时的兜底。
    map_switch_info = None
    if target_location:
        try:
            cur_map_id = int(_http_json(gateway.rstrip("/") + "/api/lua", {
                "code": "_G.__out = tostring(tp.当前地图)"})["result"]["value"])
            target_name = str(target_location).strip()
            target_id = _MAP_ID.get(target_name)
            if target_id is not None and cur_map_id != target_id:
                one_hop_desc = _ONE_HOP.get(target_name)
                if one_hop_desc:
                    # ---- 一步直达（★主路径，2026-08-21）----
                    if verbose:
                        logger.info(
                            f"SYHS: 一步跨图 {cur_map_id}→{target_id}({target_name}) "
                            f"desc={one_hop_desc}")
                    ms_resp = _http_json(gateway.rstrip("/") + "/api/act/map_switch",
                                         {"desc": one_hop_desc})
                    map_switch_info = {
                        "mode": "one_hop",
                        "desc": one_hop_desc,
                        "map_switch": ms_resp.get("result", ms_resp),
                    }
                    # ★2026-08-21 时序修正：不再 sleep(2)+等画面定格（入口停留 5s+），
                    #   改为轮询 tp.当前地图 一切换立即返回 → 下游 teleport 马上跟上，
                    #   入口停留 <0.5s，视觉上一步直达目标坐标。
                    map_ok, map_ms = _wait_map_switch(
                        gateway, target_id, timeout=stable_timeout, verbose=verbose)
                    map_switch_info["map_changed_ok"] = map_ok
                    map_switch_info["map_changed_ms"] = map_ms
                else:
                    # ---- 兜底：BFS 多跳（_ONE_HOP 未收录时）----
                    if verbose:
                        logger.warning(
                            f"SYHS: {target_name} 不在 _ONE_HOP 直达表，走多跳兜底")
                    _NAME_BY_ID = {v: k for k, v in _MAP_ID.items()}
                    cur_name = _NAME_BY_ID.get(cur_map_id)
                    if cur_name is None:
                        sw = _http_json(gateway.rstrip("/") + "/api/lua", {
                            "code": "_G.__out = tostring(tp.场景.传送[1] and tp.场景.传送[1].切换 or '')"
                        })["result"]["value"]
                        cur_name = str(sw or "").split("传送")[0].split("进")[0].strip() or str(cur_map_id)
                    route = _find_route(cur_name, target_name)
                    if route is None:
                        if verbose:
                            logger.warning(
                                f"SYHS: 无 {cur_name} → {target_name} 的跨图路径"
                                f"（_MAP_ROUTES 未收录），跳过跨图直接瞬移")
                    else:
                        hops = []
                        if verbose:
                            logger.info(f"SYHS: 多跳路径 {' → '.join(route)}")
                        for hi in range(len(route) - 1):
                            hop_from, hop_to = route[hi], route[hi + 1]
                            hop = _find_hop_teleport(gateway, hop_to)
                            if hop is None:
                                if verbose:
                                    logger.warning(
                                        f"SYHS: 跳 {hop_from}→{hop_to} 未找到传送阵，中止跨图")
                                break
                            desc_orig, ax, ay = hop
                            # 只上报传送阵坐标（画面不动）+ 立即 1003（零跳变）
                            tp_resp = _http_json(
                                gateway.rstrip("/") + "/api/act/report_pos",
                                {"proto": "1002", "x": ax, "y": ay})
                            if verbose:
                                logger.info(
                                    f"SYHS: 跳{hi + 1}/{len(route) - 1} {hop_from}→{hop_to} "
                                    f"传送阵({ax},{ay}) desc={desc_orig}")
                            ms_resp = _http_json(gateway.rstrip("/") + "/api/act/map_switch",
                                                 {"desc": desc_orig})
                            hops.append({
                                "from": hop_from, "to": hop_to,
                                "desc": desc_orig, "teleport_to_array": [ax, ay],
                                "report_pos_result": tp_resp,
                                "map_switch": ms_resp.get("result", ms_resp),
                            })
                            # ★2026-08-21：每跳同样轮询切图完成（不等定格），
                            #   减少中间图入口停留；轮询不可用才退回固定等待
                            hop_target_id = _MAP_ID.get(hop_to)
                            if hop_target_id:
                                hop_ok, hop_ms = _wait_map_switch(
                                    gateway, hop_target_id,
                                    timeout=stable_timeout, verbose=verbose)
                                hops[-1]["map_changed_ok"] = hop_ok
                                hops[-1]["map_changed_ms"] = hop_ms
                            else:
                                time.sleep(2.0)
                                if wait_stable:
                                    _stable, _note = _wait_scene_stable(
                                        gateway, timeout=stable_timeout,
                                        settle_frames=stable_frames,
                                        frame_threshold=stable_threshold,
                                        min_settle=max(stable_min_settle, 5.0),
                                        verbose=verbose)
                                    if verbose:
                                        logger.info(
                                            f"SYHS: 跳{hi + 1}切图后画面定格 -> {_note}")
                                    hops[-1]["scene_stable"] = {
                                        "ok": _stable, "note": _note}
                                else:
                                    time.sleep(2.0)
                        map_switch_info = {
                            "mode": "multi_hop",
                            "route": route,
                            "hops": hops,
                            "hops_done": len(hops),
                            "hops_total": len(route) - 1,
                        }
        except Exception as e:
            if verbose:
                logger.warning(f"SYHS: 跨图逻辑异常（忽略，继续瞬移）: {e}")

    # ---- 调用网关 teleport（最终目标）----
    body = {"x": gx, "y": gy, "raw": bool(raw), "sync": bool(sync)}
    url = gateway.rstrip("/") + "/api/act/teleport"
    try:
        resp = _http_json(url, body)
    except Exception as e:
        return {
            "ok": False, "target_coord": (gx, gy), "internal_coord": None,
            "message": f"网关调用失败: {e}（网关是否运行？{url}）", "detail": None,
        }

    if not resp.get("ok"):
        return {
            "ok": False, "target_coord": (gx, gy), "internal_coord": None,
            "message": f"网关返回失败: {resp.get('error', resp)}", "detail": resp,
        }

    r = resp.get("result", {})
    internal = r.get("internal_coord")
    sync_info = r.get("server_sync")
    # 同步被 skip 时提示（游戏待机不发包 → socket 缓存空）
    sync_ok = True
    if isinstance(sync_info, str) and sync_info.startswith("skip"):
        sync_ok = False

    if verbose:
        logger.info(
            f"SYHS 瞬移: 地图{internal and f'({gx},{gy})→内部{internal}'} "
            f"同步={sync_info}"
        )

    # ---- 画面定格等待（用户要求: 识别画面停止后再结束本函数）----
    scene_stable = None
    if wait_stable:
        stable_ok, stable_note = _wait_scene_stable(
            gateway, timeout=stable_timeout,
            settle_frames=stable_frames,
            frame_threshold=stable_threshold,
            min_settle=stable_min_settle,
            verbose=verbose)
        scene_stable = {"ok": stable_ok, "note": stable_note}
        if verbose:
            logger.info(f"SYHS: 瞬移后画面定格 -> {stable_note}")

    # ---- ★2026-08-21 队员归队（gather_team=True 时）----
    # 队长瞬移只有支纵跟随, 其他队员(丽俊/初凯心秋/玉凝)留原地——
    # 服务器 AI 只在队长"真实走路"时逐个拉近队员。这里瞬移后
    # PostMessage 点击地面走路 12 步, 触发全员拉近到队长周围阵型圈。
    team_gather = None
    if gather_team:
        try:
            from core.window_manager import window_manager
            hwnd = window_manager.hwnd
            if not hwnd:
                window_manager.find_by_pid(17852)  # 默认游戏 PID（独立运行时）
                hwnd = window_manager.hwnd
            if hwnd:
                ok = _walk_to_gather(hwnd, steps=gather_steps,
                                     settle=gather_settle, verbose=verbose)
                team_gather = {"ok": ok, "steps": gather_steps, "settle": gather_settle}
            else:
                team_gather = {"ok": False, "note": "no hwnd(窗口未绑定), 跳过拉人"}
        except Exception as e:
            team_gather = {"ok": False, "note": str(e)}

    return {
        "ok": True,
        "target_coord": (gx, gy),
        "internal_coord": internal,
        "sync_ok": sync_ok,
        "server_sync": sync_info,
        "map_switch": map_switch_info,
        "scene_stable": scene_stable,
        "team_gather": team_gather,
        "message": (
            f"{'跨图+' if map_switch_info else ''}瞬移成功 ({gx},{gy}) 内部{internal} "
            f"服务器同步={'✓' if sync_ok else '✗(待走动/心跳后重试)'}"
            + (f" 画面定格={'✓' if scene_stable and scene_stable['ok'] else '✗超时'}"
               if scene_stable else "")
            + (f" 队员归队={'✓' if team_gather and team_gather.get('ok') else '✗'}"
               if team_gather else "")
            if sync_ok else
            f"瞬移画面成功但服务器未同步 ({gx},{gy})——请在游戏内走一步再重试，或稍后重试"
        ),
        "detail": r,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        # python SYHS.py 187,36  [gateway]
        c = sys.argv[1]
        gx, gy = c.split(",")
        gw = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_GATEWAY
        print(json.dumps(SYHS((int(gx), int(gy)), gateway=gw), ensure_ascii=False, indent=1))
    else:
        print("用法: python SYHS.py 187,36 [gateway_url]")
        print("示例: python SYHS.py 187,36")
