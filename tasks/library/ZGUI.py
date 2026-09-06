# -*- coding: utf-8 -*-
"""
ZGUI - 抓鬼进战自动化（后台点击，不抢鼠标）
================================================================
功能: 读取抓鬼任务目标 → 定位当前地图野鬼 → 后台点击触发对话 →
     在"送你回地府"文字块内随机偏移点击 → 进战

已验证链路（2026-09-02 实测成功）:
  - 数据源: tp.窗口.任务栏.任务（抓鬼任务说明）、tp.地图.地图单位（野鬼坐标）、tp.屏幕.xy（偏移）
  - 交互: 全部 PostMessage 后台点击（WM_LBUTTONDOWN/UP），不移动真实鼠标
  - 定位: 客户区截图 + 红字检测（"送你回地府"为红色文字块）+ 块内随机偏移
  - 已验证成功完成一场抓鬼并领取奖励

依赖: mhxy-mcp-gateway 网关（frida 附加，HTTP 默认 18082）+ PIL
"""
import ctypes
import ctypes.wintypes
import json
import os
import random
import subprocess
import sys
import time
import urllib.request

try:
    from PIL import Image, ImageGrab
    _HAS_PIL = True
except Exception:  # 无 PIL 时红字检测不可用，仅保留 Lua 数据读取
    _HAS_PIL = False

try:
    from utils.logger import logger
except Exception:  # 独立运行
    import logging
    logger = logging.getLogger("ZGUI")
    logging.basicConfig(level=logging.INFO)

# ============================================================
# 函数中文元信息（GUI 下拉框显示用，逐个函数声明）
# ============================================================
__function_meta__ = {
    "ZGUI": {
        "title": "抓鬼 - 一键进战（CALL点野鬼 + 后台点选项）",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "tries": "点'送你回地府'的随机点击次数（默认1次）",
            "wait_dialog": "CALL后等待对话框出现的秒数（默认1.2）",
            "timeout": "等待进战超时秒数（默认8）",
            "verbose": "是否打印过程日志",
        },
    },
    "main": {
        "title": "一键进战：CALL点野鬼弹对话→点'送你回地府'→进战",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "tries": "点'送你回地府'的随机点击次数（默认1次）",
            "wait_dialog": "CALL后等待对话框出现的秒数（默认1.2）",
            "timeout": "等待进战超时秒数（默认8）",
            "verbose": "是否打印过程日志",
        },
    },
    "zhuagui_get_task": {
        "title": "读取抓鬼任务目标（目标鬼名 + 当前第几次）",
        "args": {"gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）"},
    },
    "zhuagui_take_task": {
        "title": "接抓鬼任务：点钟馗→点\"我来帮你抓鬼\"（需在长安城钟馗身边）",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "opt_x0": "\"我来帮你抓鬼\"文字块左x（默认116）",
            "opt_y0": "\"我来帮你抓鬼\"文字块上y（默认305）",
            "opt_x1": "\"我来帮你抓鬼\"文字块右x（默认195）",
            "opt_y1": "\"我来帮你抓鬼\"文字块下y（默认319）",
            "tries": "随机点击次数（默认4）",
        },
    },
    "zhuagui_find_ghost": {
        "title": "查找当前地图的野鬼（返回名称 + 屏幕坐标）",
        "args": {"gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）"},
    },
    "zhuagui_click_ghost": {
        "title": "CALL触发野鬼对话（等效点击野鬼，绕开地图边界换算）",
        "args": {"gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）"},
    },
    "zhuagui_detect_option": {
        "title": "红字检测定位\"送你回地府\"选项位置（辅助调试用）",
        "args": {"gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）"},
    },
    "zhuagui_click_option": {
        "title": "在\"送你回地府\"(116,307,180,320)内随机偏移后台点击",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "tries": "随机点击次数（默认1次）",
            "opt_x0": "\"送你回地府\"文字块左x（默认116）",
            "opt_y0": "\"送你回地府\"文字块上y（默认307）",
            "opt_x1": "\"送你回地府\"文字块右x（默认180）",
            "opt_y1": "\"送你回地府\"文字块下y（默认320）",
        },
    },
    "zhuagui_in_battle": {
        "title": "查询是否已进入战斗",
        "args": {"gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）"},
    },
    "zhuagui_enter_battle": {
        "title": "一键进战：CALL点野鬼→点'送你回地府'(116,307,180,320)→确认进战",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "wait_dialog": "CALL后等待对话框出现的秒数（默认1.2）",
            "timeout": "等待进战超时秒数（默认8）",
            "verbose": "是否打印过程日志",
        },
    },
    "zhuagui_loop": {
        "title": "人物列表批量抓鬼：默认只启动当前组角色(window.roles)→换绑网关→抓鬼",
        "args": {
            "roles": "角色名列表（逗号分隔，如：二号美人；缺省=当前组 roles 只跑本组）",
            "rounds": "每个角色连做几轮抓鬼（默认1）",
            "wait_dialog": "CALL后等待对话框出现的秒数（默认1.2）",
            "timeout": "等待进战超时秒数（默认8）",
            "verbose": "是否打印过程日志",
        },
    },
}

try:
    from core.group_config import gateway_url
    DEFAULT_GATEWAY = gateway_url()
except Exception:
    DEFAULT_GATEWAY = "http://127.0.0.1:18082"

user32 = ctypes.windll.user32
user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT,
                                ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
user32.PostMessageW.restype = ctypes.wintypes.BOOL

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205


# ============================================================
# 基础工具
# ============================================================
# ★2026-09-03 柔和化：Lua RPC 全局限速 + 随机抖动，避免机械高频调用
# 被反外挂检测（多次 attach/高频查询曾导致游戏掉线/卡死）。
import threading as _threading

_LUA_LOCK = _threading.Lock()
_LUA_LAST = [0.0]
_LUA_MIN_GAP = 0.10        # 两次 Lua RPC 最小间隔（秒）★2026-09-05 提速 0.15→0.10（file 通道为游戏内 worker，无 HTTP 开销）
_LUA_GAP_JITTER = 1.7      # 间隔抖动上限倍率（统一节奏易被判脚本）

# ★2026-09-03 取消任务冷却：本服接任务后 2 分钟内不能取消（游戏内提示
# "2分钟后才可取消此任务"，2026-09-03 OCR 实测定标；用户此前口头说1分钟，
# 以游戏提示为准=120s）。接任务/take 成功、以及完成一只进入下一只（次数递增）
# 都会刷新本时间戳；retake 取消前若距最近一次任务变动不足 120s，
# 需先等待补足，否则取消点击无效 → 任务残留 → 重试死循环空烧天眼符。
_CANCEL_COOLDOWN = 120.0     # 接任务后可取消的最短间隔（秒，游戏提示2分钟）
_task_ts = {}                # gateway -> 最近一次任务变动时间戳
_task_ts_lock = _threading.Lock()


def _task_ts_set(gateway, t=None):
    """记录 gateway 最近一次任务变动时间（接任务/次数递增）。"""
    with _task_ts_lock:
        _task_ts[gateway] = t if t else time.time()


def _task_ts_get(gateway):
    with _task_ts_lock:
        return _task_ts.get(gateway) or 0.0


def _wait_cancel_cooldown(gateway, cooldown=_CANCEL_COOLDOWN):
    """等待取消冷却：距最近一次任务变动不足 cooldown 秒则休眠补足。

    返回等待的秒数（0 表示无需等待/无记录）。
    """
    last = _task_ts_get(gateway)
    if last <= 0:
        return 0.0
    remain = float(cooldown) - (time.time() - last)
    if remain > 0:
        logger.info("取消冷却中：距任务变动 %.0fs，等待 %.0fs 后再取消"
                    % (float(cooldown) - remain, remain))
        time.sleep(remain + random.uniform(0.3, 0.8))
        return remain
    return 0.0


# 文件通道单例（gateway 传 "file://pzxy" 时启用，方案②：零 frida 依赖）
_FILE_WORKERS = {}  # ★2026-09-06 多开：worker名 -> PzxyWorker（file://pzxy_p<pid> 每实例独立通道）


def _worker_name_from_gateway(gateway):
    """file://pzxy → ''（默认通道）；file://pzxy_p12345 → 'p12345'；非 file 前缀 → None。"""
    s = str(gateway).strip()
    if not s.lower().startswith("file://"):
        return None
    rest = s[len("file://"):].strip("/")
    if rest.lower().startswith("pzxy"):
        rest = rest[len("pzxy"):]
    if rest.startswith("_"):
        rest = rest[1:]
    return rest


def _lua_call_file(code: str, timeout: float, gateway="file://pzxy"):
    """方案② 文件通道后端：经游戏内常驻 worker 执行 Lua（pzxy_ipc.py）。

    语义对齐网关：worker 返回 tostring(结果)，'nil' 归一为 None。
    worker 心跳停止（游戏重启/槽位被覆盖）→ 返回 None，与网关故障同型。
    ★2026-09-06 多开：gateway 形如 file://pzxy_p<pid> 时使用该实例专属
      worker（播种时 --name p<pid>），5 开互不串通道。
    """
    try:
        name = _worker_name_from_gateway(gateway) or ""
        w = _FILE_WORKERS.get(name)
        if w is None:
            _root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from library.pzxy_ipc import PzxyWorker
            w = PzxyWorker(name=name)
            _FILE_WORKERS[name] = w
        if not w.is_alive():
            return None
        ok, val = w.cmd(code, timeout=min(timeout, 5.0))
        if not ok or val == "nil":
            return None
        return val
    except Exception:
        return None


def _lua_call(gateway: str, code: str, timeout: float = 8.0):
    """调网关 /api/lua 执行 Lua，返回 value 或 None（容错）。

    ★双通道（2026-09-05 方案②）：gateway 以 "file" 开头（如 file://pzxy）时
    走文件通道（游戏内常驻 worker，零 frida 依赖）；否则走 HTTP 网关。

    柔和限速：每次调用前等待 >= MIN_GAP 且带随机抖动，让操作更接近人工节奏。
    """
    try:
        wait = _LUA_LAST[0] + _LUA_MIN_GAP * random.uniform(1.0, _LUA_GAP_JITTER) - time.time()
        if wait > 0:
            time.sleep(wait)
    except Exception:
        pass
    with _LUA_LOCK:
        _LUA_LAST[0] = time.time()
        try:
            if str(gateway).lower().startswith("file"):
                return _lua_call_file(code, timeout, gateway)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            body = json.dumps({"code": code, "result_var": "__out"}).encode("utf-8")
            req = urllib.request.Request(gateway + "/api/lua", data=body,
                                         headers={"Content-Type": "application/json"})
            with opener.open(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if d.get("ok"):
                return d.get("result", {}).get("value")
            return None
        except Exception:
            return None


_HWND_CACHE = [0, 0.0]  # [hwnd, 时刻] ★2026-09-05 提速：3s TTL 缓存（窗口句柄只在游戏重启时变化，
#             原实现每轮起 5~7 次 PowerShell 子进程，每次 0.3~0.8s，单轮浪费 2~4s）
_HWND_TTL = 3.0
_PINNED_HWNW = [0]  # ★2026-09-06 多开：跑批器按角色钉住目标窗口，get_hwnd 优先返回它


def set_target_hwnd(hwnd):
    """多开必用：把后续 get_hwnd() 钉到指定窗口（5 开下"取第一个窗口"会点错号）。"""
    _PINNED_HWNW[0] = int(hwnd or 0)


def get_hwnd():
    """获取游戏主窗口句柄（胖子西游）。优先返回 set_target_hwnd 钉住的窗口；
    未钉住时带 3s TTL 缓存走 PowerShell 探测（取第一个带标题的进程窗口）。"""
    if _PINNED_HWNW[0]:
        return _PINNED_HWNW[0]
    now = time.time()
    if _HWND_CACHE[0] and now - _HWND_CACHE[1] < _HWND_TTL:
        return _HWND_CACHE[0]
    try:
        out = subprocess.check_output(
            'powershell -NoProfile -c "(Get-Process -Name 胖子西游 | Where-Object {$_.MainWindowTitle} | Select-Object -First 1).MainWindowHandle"',
            shell=True).decode().strip()
        hwnd = int(out) if out.isdigit() else 0
    except Exception:
        hwnd = 0
    if hwnd:
        _HWND_CACHE[0] = hwnd
        _HWND_CACHE[1] = now
    return hwnd


def _lp(x, y):
    return (y << 16) | (x & 0xFFFF)


# ============================================================
# ★2026-09-03 柔和轨迹点击：从当前鼠标位置沿贝塞尔曲线滑到目标再点击，
# 避免 WM_MOUSEMOVE 瞬移（机械瞬移易被反外挂识别为脚本）。
# ============================================================
_last_mouse = [400, 300]  # 客户区坐标缓存（上次点击终点，近似当前引擎鼠标位）
_last_mouse_ts = [0.0]    # ★2026-09-05 提速：鼠标位读取节流（1.5s 内复用缓存，省一次 Lua RPC）
_call_guard = {"gid": "", "ts": 0.0}  # ★2026-09-03 防重复 CALL 目标冷却（多 call 弹框防护）


def _read_engine_mouse(gateway):
    """读取游戏引擎当前鼠标位置（客户区逻辑坐标）作为轨迹起点。

    ★2026-09-05 提速：1.5s 内已读过则直接复用 _last_mouse（上次点击终点），
    轨迹起点精度足够，省一次 Lua RPC（单轮 5~6 次点击共省 ~1.2s）。
    """
    if time.time() - _last_mouse_ts[0] < 1.5:
        return
    try:
        r = _lua_call(gateway, '__out = tostring(鼠标.x)..","..tostring(鼠标.y)')
        if r and "," in r:
            a, b = r.split(",")
            _last_mouse[:] = [int(a), int(b)]
            _last_mouse_ts[0] = time.time()
    except Exception:
        pass


def _move_traj(hwnd, x0, y0, x1, y1):
    """沿二次贝塞尔曲线逐步发 WM_MOUSEMOVE，模拟人类移动轨迹。

    - 控制点取连线中点 + 垂直方向的随机偏移（偏移随距离增大，带弧形感）
    - 采样点数量随距离变化（加大步长→点数减少），步进间隔缩短 →
      ★2026-09-03 用户要求加速：整体移动耗时约减半，但仍保留末端自然减速。
    """
    import math
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 4:
        # 原地微调：直接过去
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(x1, y1))
        time.sleep(random.uniform(0.02, 0.05))
        return
    # 控制点：中点 + 垂直偏移（随机方向，偏移量=min(距离*0.18, 45)）
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    offset = min(dist * random.uniform(0.05, 0.18), 45.0)
    if abs(x1 - x0) + abs(y1 - y0) < 1e-6:
        ox, oy = 0.0, 0.0
    else:
        # 垂直于连线方向的单位向量
        ux, uy = -(y1 - y0) / max(dist, 1e-6), (x1 - x0) / max(dist, 1e-6)
        ox, oy = ux * offset, uy * offset
    if random.random() < 0.5:
        ox, oy = -ox, -oy
    # ★2026-09-03 加速：步长加大（每 13~19px 一个点，原 9~14），点数上限 14
    n = max(4, min(int(dist / random.uniform(13.0, 19.0)), 14))
    if n < 2:
        n = 2
    for i in range(1, n + 1):
        t = i / float(n)
        # 二次贝塞尔: B(t) = (1-t)^2 P0 + 2(1-t)t P1 + t^2 P2
        px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * (mx + ox) + t ** 2 * x1
        py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * (my + oy) + t ** 2 * y1
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(int(px), int(py)))
        # 末端减速：离目标越近间隔越大（基准缩短，保留减速感）
        step = random.uniform(5, 12) + t * random.uniform(0, 9)
        time.sleep(step / 1000.0)
    # 到达后小幅停顿再点击
    time.sleep(random.uniform(0.02, 0.06))


def post_click(hwnd, x, y, gateway=None):
    """后台点击（客户区坐标），PostMessage 不抢真实鼠标。

    柔和化：先按贝塞尔轨迹滑到目标，再 DOWN/UP 点击。gateway 提供时
    先读引擎当前鼠标位作轨迹起点（更真实），否则用缓存起点。
    """
    if gateway:
        _read_engine_mouse(gateway)
    _move_traj(hwnd, _last_mouse[0], _last_mouse[1], x, y)
    time.sleep(random.uniform(0.03, 0.09))
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, _lp(x, y))
    time.sleep(random.uniform(0.04, 0.09))
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(x, y))
    _last_mouse[:] = [x, y]
    _last_mouse_ts[0] = time.time()


def post_right_click(hwnd, x, y, gateway=None):
    """后台右键点击（客户区坐标），PostMessage 不抢真实鼠标。

    ★2026-09-03 新增：供"使用天眼"等道具右键操作使用。
    柔和化：先按贝塞尔轨迹滑到目标，再 DOWN/UP 点击。
    """
    if gateway:
        _read_engine_mouse(gateway)
    _move_traj(hwnd, _last_mouse[0], _last_mouse[1], x, y)
    time.sleep(random.uniform(0.03, 0.09))
    user32.PostMessageW(hwnd, WM_RBUTTONDOWN, 1, _lp(x, y))
    time.sleep(random.uniform(0.04, 0.09))
    user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, _lp(x, y))
    _last_mouse[:] = [x, y]
    _last_mouse_ts[0] = time.time()


def grab_client(hwnd):
    """截取客户区图像（含屏幕原点偏移修正），返回 (img, 原点, 尺寸)。"""
    r = ctypes.wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    cw, ch = r.right - r.left, r.bottom - r.top
    if cw <= 0 or ch <= 0:
        w = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(w))
        return ImageGrab.grab(bbox=(w.left, w.top, w.right, w.bottom)).convert("RGB"), (w.left, w.top), (w.right - w.left, w.bottom - w.top)
    img = ImageGrab.grab(bbox=(pt.x, pt.y, pt.x + cw, pt.y + ch)).convert("RGB")
    return img, (pt.x, pt.y), (cw, ch)


def _blind_mode(hwnd=None, threshold=30):
    """检测当前是否处于"黑屏盖屏"状态（星际黑屏/等效关屏）。

    ★2026-09-04 修复：黑屏工具用纯黑置顶窗口盖住屏幕 → PIL 截图（ImageGrab
      抓屏幕合成画面）得到全黑 → 所有红字截图检测（钟馗对话/送你回地府选项）
      恒失败 → 接任务/打鬼全挂（整夜空转 779 轮失败）。检测截图整体亮度，
      亮度极低（<threshold）即判定黑屏，上层走"盲操作"（固定坐标点击 + Lua
      任务栏验证，均不受黑屏影响）。

    Returns:
        bool: True=黑屏盖屏中（截图检测不可信）。
    """
    try:
        if hwnd is None:
            hwnd = get_hwnd()
        if not hwnd:
            return False
        img, _, _ = grab_client(hwnd)
        if img is None:
            return False
        gray = img.convert("L").resize((80, 60))
        px = list(gray.getdata())
        if not px:
            return False
        return (sum(px) / float(len(px))) < threshold
    except Exception:
        return False


# ============================================================
# 抓鬼核心接口（业务函数，GUI 可调用）
# ============================================================
def zhuagui_get_task(gateway=DEFAULT_GATEWAY, **kw):
    """读取抓鬼任务目标。

    目标怪名提取（2026-09-02 修复）：任务说明格式为
      '#w/近日有#r/卵时四刻勤奋僵尸#w/正在#r/江南野外（97,17)#w/附近作乱…'
    提取 '#r/...#' 段中的怪名（可为 "XX时XX刻XX鬼/僵尸/马面" 等任意名）。

    Returns:
        dict: {"name": 目标怪名, "count": 第N次}；无任务返回 {"name": "", "count": ""}
    """
    code = """
local t = tp.窗口.任务栏.任务
if type(t) ~= 'table' then __out = '' return end
for i=1,#t do
  local v = t[i]
  if type(v)=='table' and tostring(v.名称 or '')=='抓鬼任务' then
    local desc = tostring(v.说明 or '')
    -- 提取 '近日有#r/XXX#w/' 中的 XXX（怪名）
    local gname = desc:match('近日有#r/([^#]+)#w/') or ''
    gname = gname:gsub('^%s+', ''):gsub('%s+$', '')
    local cnt = desc:match('第(%d+)次') or ''
    __out = gname .. '|' .. cnt
    return
  end
end
__out = ''
"""
    r = _lua_call(gateway, code) or ""
    if "|" not in r:
        return {"name": "", "count": ""}
    n, c = r.split("|")
    return {"name": n, "count": c}


_SNAP_LUA = r"""
local res = {}
local m = tp.地图
res[1] = tostring(m and m.地图名称 or '')
local bt = 'false'
local b = tp.战斗类
if type(b) == 'table' then
  local u = b.参战单位
  if type(u) == 'table' then
    local n = 0
    for _ in pairs(u) do n = n + 1 end
    if n > 0 and tonumber(b.敌方数量 or 0) > 0 then bt = 'true' end
  end
end
res[2] = bt
local tn, tc, tm = '', '', ''
local t = tp.窗口.任务栏.任务
if type(t) == 'table' then
  for i = 1, #t do
    local v = t[i]
    if type(v) == 'table' and tostring(v.名称 or '') == '抓鬼任务' then
      local desc = tostring(v.说明 or '')
      tn = desc:match('近日有#r/([^#]+)#w/') or ''
      tn = tn:gsub('^%s+', ''):gsub('%s+$', '')
      tc = desc:match('第(%d+)次') or ''
      tm = desc:match('正在#r/([^#]+)') or ''
      local p = tm:find('（') or tm:find('%(')
      if p then tm = tm:sub(1, p - 1) end
      tm = tm:gsub('^%s+', ''):gsub('%s+$', '')
      break
    end
  end
end
res[3] = tn
res[4] = tc
res[5] = tm
__out = table.concat(res, '|')
"""


def _snapshot(gateway):
    """★2026-09-05 提速：一次 Lua RPC 同时读 地图名/战斗态/任务名/次数/目标地图。

    原流程单轮要为这些状态连发 5~6 次独立调用（每次限速 0.15~0.26s），
    合并为 2 次快照后单轮省 ~1s 且减少探测频率。
    """
    r = _lua_call(gateway, _SNAP_LUA) or ""
    parts = (r.split("|") + ["", "", "", "", ""])[:5]
    return {
        "map": parts[0],
        "battle": parts[1] == "true",
        "name": parts[2],
        "count": parts[3],
        "target_map": parts[4],
    }


def zhuagui_take_task(gateway=DEFAULT_GATEWAY,
                      opt_x0=116, opt_y0=305, opt_x1=195, opt_y1=319,
                      tries=1, **kw):
    """接抓鬼任务：点钟馗 → 在"我来帮你抓鬼"文字块内随机偏移后台点击一次。

    Args:
        opt_x0/opt_y0/opt_x1/opt_y1: "我来帮你抓鬼"文字块（游戏客户区坐标）。
          ★ 需按当前分辨率/对话框位置校准（本机实测 116,305,195,319 宽79高14）。
        tries: 随机偏移点击次数（默认1次，只点一次防止重复触发）。

    Returns:
        bool: 任务栏是否出现"抓鬼任务"。
    """
    hwnd = get_hwnd()
    if not hwnd:
        return False
    # 1. 点钟馗（从当前地图 npc 表定位）
    code = """
local t = tp.地图.npc
if type(t)~='table' then __out='' return end
local off = tp.屏幕.xy
local ox = off and off.x or 0
local oy = off and off.y or 0
for i=1,#t do
  local v=t[i] or {}
  if tostring(v.名称 or ''):find('钟馗') then
    local wx=tonumber(tostring(v.x or '')) or 0
    local wy=tonumber(tostring(v.y or '')) or 0
    __out=string.format('%d,%d', wx+ox, wy+oy)
    return
  end
end
__out=''
"""
    r = _lua_call(gateway, code) or ""
    if "," not in r:
        return False
    zx, zy = r.split(",")
    post_click(hwnd, int(zx), int(zy), gateway=gateway)
    _sleep(1.0)

    # 2. 在选项文字块内随机偏移点击一次
    cx = int(opt_x0) + random.randint(3, max(1, int(opt_x1) - int(opt_x0) - 3))
    cy = int(opt_y0) + random.randint(2, max(1, int(opt_y1) - int(opt_y0) - 2))
    post_click(hwnd, cx, cy, gateway=gateway)

    # 3. 验证任务栏出现抓鬼任务
    _sleep(1.5)
    t = zhuagui_get_task(gateway)
    return bool(t and t.get("name"))


def _sleep(sec):
    import time
    time.sleep(sec)


# ============================================================
# ★2026-09-03 钟馗对话引擎调用（事件解析，绕开固定坐标）
# ============================================================
def _call_zhongkui(gateway, tries=1):
    """点钟馗：从地图 npc 表定位，按"屏幕xy偏移"转客户区坐标并后台点击。

    ★2026-09-03 修复：钟馗在 tp.地图.npc 里"没有事件开始方法、无 metatable"，
    旧代码用 getmetatable(u).事件开始 触发永远返回 False（找不到该方法）。
    游戏里打开钟馗对话的真实方式是"点击驼身"（PostMessage 后台点击 NPC坐标）。
    本函数复用与 zhuagui_take_task 相同的坐标换算（世界坐标 + tp.屏幕.xy）
    加上相对玩家的方向偏移后后台点击。
    ★2026-09-03 追加：点击只执行一次（随机偏移 ±5px），避免连点被反外挂识别。

    Returns:
        bool: 是否已发出点钟馗的点击。
    """
    hwnd = get_hwnd()
    if not hwnd:
        return False
    code = r"""
local t = tp.地图.npc
if type(t) ~= 'table' then __out = '' return end
local off = tp.屏幕.xy
local ox = off and off.x or 0
local oy = off and off.y or 0
for i = 1, #t do
  local v = t[i] or {}
  if tostring(v.名称 or ''):find('钟馗') then
    local wx = tonumber(tostring(v.x or '')) or 0
    local wy = tonumber(tostring(v.y or '')) or 0
    __out = string.format('%d,%d', wx + ox, wy + oy)
    return
  end
end
__out = ''
"""
    r = _lua_call(gateway, code) or ""
    if "," not in r:
        return False
    zx, zy = r.split(",")
    n = max(1, int(tries))
    for i in range(n):
        jx = int(zx) + random.randint(-5, 5)
        jy = int(zy) + random.randint(-5, 5)
        post_click(hwnd, jx, jy, gateway=gateway)
        _sleep(random.uniform(0.45, 0.8))  # ★09-05 提速 0.6~1.0 → 0.45~0.8
    return True


def _zhongkui_dialog_options(gateway):
    """读钟馗当前对话栏选项列表: [(index, text, link), ...]。"""
    code = r"""
local opts = tp.窗口.对话栏 and tp.窗口.对话栏.选项
local out = {}
if type(opts) == "table" then
  for i = 1, 20 do
    local o = opts[i]
    if type(o) ~= "table" then break end
    local text = tostring(o.基本内容 or "") .. "|" .. tostring(o.文字 or o.标签 or "")
    local link = tostring(o.跳转链接 or "")
    out[#out+1] = i .. "|" .. text .. "|" .. link
  end
end
__out = table.concat(out, "\n")
"""
    r = _lua_call(gateway, code) or ""
    opts = []
    for line in r.splitlines():
        parts = line.split("|", 2)
        if len(parts) >= 3 and parts[0].isdigit():
            opts.append({"idx": int(parts[0]), "text": parts[1], "link": parts[2]})
    return opts


def _zhongkui_click_option(gateway, keyword):
    """事件解析触发钟馗对话中文本含 keyword 的选项。返回 bool。"""
    code = r"""
local opts = tp.窗口.对话栏 and tp.窗口.对话栏.选项
if type(opts) ~= "table" then __out = 'nodlg' return end
local kw = '"' + string.gsub("KW", '"', '\\"') + '"'
local hit = nil
for i = 1, 20 do
  local o = opts[i]
  if type(o) ~= "table" then break end
  local text = tostring(o.基本内容 or "") .. tostring(o.文字 or o.标签 or "") .. tostring(o.跳转链接 or "")
  if string.find(text, "KW", 1, true) then hit = o break end
end
if not hit then __out = 'miss' return end
local link = tostring(hit.跳转链接 or "")
if link == "" then __out = 'nolink' return end
local okr, ret = pcall(function() return tp.窗口.对话栏:事件解析(link) end)
__out = (okr and "clicked" or "fail")
"""
    code = code.replace('"KW"', '"' + keyword + '"').replace('"KW", 1, true', '"' + keyword + '", 1, true')
    r = _lua_call(gateway, code)
    return r in ("clicked", "fail") and r == "clicked"


def zhuagui_read_dialog(gateway=DEFAULT_GATEWAY, **kw):
    """点钟馗并报告其对话选项位置（辅助诊断/校准用，不点击）。

    2026-09-03 实测：钟馗对话数据不暴露在 tp.窗口.对话栏（引擎里无此字段），
    事件解析方案读不到选项。因此图内无法按文字识别选项，改用红字检测
    返回三个选项红字行的像素位置，供后台点击落点。
    """
    if not _zhongkui_dialog_open(gateway):
        if not _call_zhongkui(gateway):
            return "未找到钟馗或无法打开对话（可能不在长安）"
        _sleep(0.8)
        if not _zhongkui_dialog_open(gateway):
            return "对话未弹出或未检测到红字选项"
    rows = _zhongkui_detect_rows(gateway)
    names = ["我来帮你抓鬼", "取消抓鬼任务", "我是路过的"]
    out = []
    for i, r in enumerate(rows[:3], 1):
        name = names[i - 1] if i <= len(names) else "?"
        out.append("[%d] %s x[%d,%d] y[%d,%d]" % (i, name, r["x0"], r["x1"], r["y0"], r["y1"]))
    return "钟馗对话选项(红字检测):\n" + "\n".join(out)


# 钟馗对话三个选项红字行的相对位置（客户区像素，2026-09-03 实测：
# 行1"我来帮你抓鬼"y305-319 x[37,196]（点击区取正下方 y313-318）
# 行2"取消抓鬼任务"y320-333：红字主段 x[114,196]，左端仅"取消"嵌 x[40,65]，
#    中间 x[66,113] 空隙——点击区必须从 x>=114 起，否则随机点会落空白区
# 行3"我是路过的"y335-348：红字仅主段 x[114,182]，点击区 x[114,182]
# ★take 已实测成功；cancel/close 2026-09-03 修复 x 起点对齐红字主段）
_ZHONGKUI_ROWS = [
    {"key": "take",   "name": "我来帮你抓鬼", "x0": 110, "x1": 190, "y0": 313, "y1": 318},
    {"key": "cancel", "name": "取消抓鬼任务", "x0": 114, "x1": 195, "y0": 320, "y1": 332},
    {"key": "close",  "name": "我是路过的",   "x0": 114, "x1": 182, "y0": 335, "y1": 348},
]


def _zhongkui_dialog_open(gateway, min_close=120, min_take=300):
    """判定钟馗对话框是否真打开（三带红字密度，背包红字物品不误判）。

    2026-09-03 修复：背包面板打开时，物品栏里红色物品名（y304-330 内
    4 段式等距分布）会让旧"有红块就当作对话"逻辑误判对话框已开，
    导致点击落在空处。对话框打开的判据（2026-09-03 实测定标）：
      - take 带 y[305,319]：行1"我来帮你抓鬼"红字（实测757，背包更高→仅最低校验）
      - close 带 y[335,348]：行3"我是路过的"红字（实测308，背包≈0）★核心判据
    背包红字只打在 y304-330，close 带几乎无红 → 不会误判。
    min_close 是主判据；min_take 仅作兜底（防画面异常）。
    """
    if not _HAS_PIL:
        return False
    hwnd = get_hwnd()
    if not hwnd:
        return False
    # ★2026-09-04 黑屏盲模式：截图全黑时红字检测恒失败，
    #   直接视为"对话已开"，交由上层固定坐标点击 + Lua 任务栏验证。
    if _blind_mode(hwnd):
        return True
    img, _, _ = grab_client(hwnd)
    px = img.load()
    n_take = 0
    n_close = 0
    for y in range(305, 320):
        for x in range(30, 210):
            R, G, B = px[x, y]
            if R > 110 and (R - G) > 55 and (R - B) > 55:
                n_take += 1
    for y in range(335, 349):
        for x in range(30, 210):
            R, G, B = px[x, y]
            if R > 110 and (R - G) > 55 and (R - B) > 55:
                n_close += 1
    return n_close >= min_close and n_take >= min_take


def _zhongkui_detect_rows(gateway):
    """红字检测钟馗对话三个选项行的实际像素坐标。

    返回 [ {x0,x1,y0,y1}, ... ] 自上而下。检测不到（对话未弹出/无红字）返回 []。
    用于诊断与校验；正式点击走固定相对行 _ZHONGKUI_ROWS（对话框位置稳定）。
    """
    if not _HAS_PIL:
        return []
    hwnd = get_hwnd()
    if not hwnd:
        return []
    img, _, _ = grab_client(hwnd)
    px = img.load()
    counts = {}
    for y in range(298, 357):
        c = 0
        for x in range(30, 210):
            R, G, B = px[x, y]
            if R > 110 and (R - G) > 55 and (R - B) > 55:
                c += 1
        if c >= 10:
            counts[y] = c
    blks = []
    cur = None
    for y in sorted(counts):
        if cur and (y - cur["y1"]) <= 2:
            cur["y1"] = y
            cur["c"] += counts[y]
        else:
            if cur:
                blks.append(cur)
            cur = {"y0": y, "y1": y, "c": counts[y]}
    if cur:
        blks.append(cur)
    res = []
    for b in blks:
        x0, x1, n = 999, -1, 0
        for y in range(b["y0"], b["y1"] + 1):
            for x in range(30, 210):
                R, G, B = px[x, y]
                if R > 110 and (R - G) > 55 and (R - B) > 55:
                    x0 = min(x0, x)
                    x1 = max(x1, x)
                    n += 1
        if n >= 30:
            res.append({"x0": x0, "x1": x1, "y0": b["y0"], "y1": b["y1"]})
    return res


def _zhongkui_click_row(gateway, row_key, hwnd=None):
    """在钟馗对话中点击指定选项行（红字行固定相对坐标 + 随机偏移）。返回 bool。"""
    if hwnd is None:
        hwnd = get_hwnd()
    if not hwnd:
        return False
    row = next((r for r in _ZHONGKUI_ROWS if r["key"] == row_key), None)
    if not row:
        return False
    cx = row["x0"] + random.randint(5, max(1, row["x1"] - row["x0"] - 5))
    cy = row["y0"] + random.randint(2, max(1, row["y1"] - row["y0"] - 2))
    post_click(hwnd, cx, cy, gateway=gateway)
    _sleep(random.uniform(0.35, 0.7))  # ★09-05 提速 0.5~0.9 → 0.35~0.7
    return True


def zhuagui_cancel_task(gateway=DEFAULT_GATEWAY, **kw):
    """在钟馗处取消当前抓鬼任务（红字检测后台点击）。

    机制（2026-09-03 用户确认）：本服无法在任务栏取消抓鬼任务，
    只能打开钟馗对话，在同一弹窗里点"取消抓鬼任务"选项。
    ★2026-09-03 修复：钟馗对话数据不在 tp.窗口.对话栏（引擎无此字段），
    旧`事件解析`读不到选项永远失败；改为对第2行红字后台点击。

    Returns:
        (bool, str): (是否成功取消, 信息)
    """
    # ★对话框可能已打开（close带红字判定）就直接点击；否则先 CALL 钟馗打开。
    # ★2026-09-03 修复：对话框弹出动画约需 1.5s+，旧代码 0.8s 判定太短，
    # 判定 False 后再次点钟馗会点到已开对话框导致状态错乱。改为轮询等待
    # 对话框出现（最长 ~4s），确认弹出后再点击取消选项。
    if not _zhongkui_dialog_open(gateway):
        if not _call_zhongkui(gateway):
            return False, "未找到钟馗（可能不在长安）"
        for _ in range(6):
            _sleep(random.uniform(0.6, 0.8))
            if _zhongkui_dialog_open(gateway):
                break
        if not _zhongkui_dialog_open(gateway):
            return False, "钟馗对话未弹出（红字检测无结果）"
    _zhongkui_click_row(gateway, "cancel")
    _sleep(1.2)
    has_task = bool(zhuagui_get_task(gateway).get("name"))
    if not has_task:
        return True, "已取消抓鬼任务（任务栏已清空）"
    return False, "点击'取消抓鬼任务'后任务仍在"


def _bag_item_zones(gateway):
    """背包物品图标坐标禁区（右键落点需避开，否则会误点/误用物品）。

    ★2026-09-03 关键修复：_zhongkui_close_dialog 曾用 y[300,400] 的候选
    右键点，而天眼符(实测232,354)/合成旗(186,302)等道具图标都在该带内，
    右键"关闭对话框"会直接误用天眼符 → 天眼神秘耗尽。本函数返回当前背包
    所有物品的小动画坐标，供关闭对话框时动态避让。
    """
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
if type(j) ~= 'table' then __out = '' return end
local pd = j[3] and j[3].物品数据
if type(pd) ~= 'table' then __out = '' return end
local out = {}
for k, it in pairs(pd) do
  if type(it) == 'table' then
    local sa = it.小动画
    if type(sa) == 'table' then
      local x = tonumber(sa.x); local y = tonumber(sa.y)
      if x and y and x > 0 and y > 0 then
        out[#out+1] = string.format('%d,%d', x, y)
      end
    end
  end
end
__out = table.concat(out, '|')
"""
    r = _lua_call(gateway, code) or ""
    zones = []
    for part in r.split("|"):
        if "," in part:
            try:
                a, b = part.split(",")
                zones.append((int(a), int(b)))
            except Exception:
                pass
    return zones


def _zhongkui_close_dialog(gateway, tries=2):
    """右键关闭钟馗对话/任务指引弹窗（对话框内任意位置右键即可关闭）。

    ★2026-09-03 实测：接完抓鬼任务后弹出任务指引弹窗（"近日有XX正在
    地图(x,y)处作恶…"），需在对话框内空白处右键关闭。对话框约
    x[11,650] y[240,520]；文字行 y[414,454] 内右键可能点中链接不关闭，
    故避开文字行取对话框上方空白区随机右键，失败则换点位重试。
    ★2026-09-03 修复（天眼符神秘耗尽根因）：旧候选点含 y[300,400]，
    恰好覆盖背包天眼符(232,354)/合成旗(186,302)图标 → 右键关框=误用道具。
    现改为：候选点全部落在对话框上部空白带 y[255,298]（避开物品带 y≥300
    与文字行 y414+），并额外按背包物品坐标动态避让（gap≥25px）。

    Returns:
        bool: 是否已发出右键关闭点击。
    """
    hwnd = get_hwnd()
    if not hwnd:
        return False
    n = max(1, int(tries))
    zones = _bag_item_zones(gateway)

    def _safe(x, y, gap=25):
        for zx, zy in zones:
            if abs(x - zx) < gap and abs(y - zy) < gap:
                return False
        return True

    cands = []
    for _ in range(16):
        x = random.randint(120, 620)
        y = random.randint(255, 298)
        if _safe(x, y):
            cands.append((x, y))
    if not cands:
        cands = [(random.randint(260, 460), random.randint(255, 290)),
                 (random.randint(120, 300), random.randint(256, 292)),
                 (random.randint(480, 600), random.randint(255, 290))]
    for i in range(n):
        x, y = cands[i % len(cands)]
        jx = x + random.randint(-5, 5)
        jy = y + random.randint(-3, 3)
        post_right_click(hwnd, jx, jy, gateway=gateway)
        _sleep(random.uniform(0.5, 0.8))
        if not _zhongkui_dialog_open(gateway):
            return True
    return False


def zhuagui_take_task_v2(gateway=DEFAULT_GATEWAY, close_dialog=True, **kw):
    """接抓鬼任务（红字检测后台点击）：点钟馗 → 点第1行"我来帮你抓鬼"。

    2026-09-03 修复：钟馗对话数据不暴露于 tp.窗口.对话栏，旧`事件解析`
    读不到选项。改为红字检测确认对话弹出后，点击第1行红字。
    ★2026-09-03 追加：接任务后弹任务指引弹窗，需在对话框内右键关闭
    （close_dialog=True 默认执行），否则弹窗遮挡后续天眼瞬移。

    Returns:
        bool: 任务栏是否出现"抓鬼任务"。
    """
    # ★对话框可能已打开就直接点击；否则先 CALL 钟馗打开。
    # ★2026-09-03 修复：对话框弹出动画约需 1.5s+，旧代码 0.8s 判定太短，
    # 判定 False 后再次点钟馗会点到已开对话框导致状态错乱。改为轮询等待
    # 对话框出现（最长 ~4s），确认弹出后再点击选项。
    # ★2026-09-04 黑屏盲模式：红字检测恒失败，改为固定链路
    #   「点钟馗→等待→点take行→Lua任务栏验证」，与截图无关。
    hwnd = get_hwnd()
    if _blind_mode(hwnd):
        for attempt in range(2):
            if not _call_zhongkui(gateway):
                _sleep(random.uniform(0.6, 0.9))
            _sleep(random.uniform(0.9, 1.4))   # 等对话弹出动画（★09-05 提速 1.2~1.8 → 0.9~1.4）
            _zhongkui_click_row(gateway, "take", hwnd=hwnd)
            _sleep(0.9)                        # ★09-05 提速 1.2 → 0.9
            ok = bool(zhuagui_get_task(gateway).get("name"))
            if ok:
                _task_ts_set(gateway)
                if close_dialog:
                    _zhongkui_close_dialog(gateway)
                return True
            # 失败：可能没弹对话/点到空处，关闭对话框后重试一次
            _zhongkui_close_dialog(gateway)
            _sleep(random.uniform(0.5, 0.9))
        logger.warning("黑屏盲模式：接任务失败（点钟馗/点选项后任务栏无任务）")
        return False
    if not _zhongkui_dialog_open(gateway):
        if not _call_zhongkui(gateway):
            return False
        for _ in range(6):
            _sleep(random.uniform(0.6, 0.8))
            if _zhongkui_dialog_open(gateway):
                break
        if not _zhongkui_dialog_open(gateway):
            logger.warning("钟馗对话未弹出（红字检测无结果），无法接任务")
            return False
    _zhongkui_click_row(gateway, "take")
    _sleep(1.2)
    ok = bool(zhuagui_get_task(gateway).get("name"))
    if ok:
        # ★接任务成功 → 刷新取消冷却时间戳（接任务后 2 分钟内不能取消）
        _task_ts_set(gateway)
        if close_dialog:
            _zhongkui_close_dialog(gateway)
    return ok


def zhuagui_retake_task(gateway=DEFAULT_GATEWAY, **kw):
    """取消当前抓鬼任务并重新接（钟馗弹窗，红字检测后台点击）。

    ★2026-09-03 修复：本服接任务后 1 分钟内不能取消，直接点'取消抓鬼任务'
      无效且任务残留 → 重试死循环。取消前先等待取消冷却（_wait_cancel_cooldown）。

    Returns:
        (bool, str): (是否重接成功, 信息)
    """
    _wait_cancel_cooldown(gateway)
    ok_c, msg_c = zhuagui_cancel_task(gateway)
    if not ok_c:
        # ★2026-09-03 兜底：进程重启后本地冷却时间戳丢失（_task_ts 为空），
        # cancel 在冷却期内必然失败（任务残留）。等待一个冷却周期后重试取消一次。
        if _task_ts_get(gateway) <= 0:
            logger.info("retake: 无本地任务变动记录，取消失败；等待 %.0fs 冷却后重试取消"
                        % _CANCEL_COOLDOWN)
            time.sleep(_CANCEL_COOLDOWN + random.uniform(0.5, 1.5))
            ok_c, msg_c = zhuagui_cancel_task(gateway)
        if not ok_c:
            return ok_c, "取消: " + msg_c
    if zhuagui_take_task_v2(gateway):
        return True, "已重新接抓鬼任务"
    return False, "取消成功但重接失败"


def _dialog_options_flat(gateway):
    """读对话栏选项: [(idx, text, link, cx, cy), ...]。

    ★移植自 MPCG._dialog_options，改文件通道单行协议（' ;; ' 分隔——
    out 文件按行读，Lua 结果含 \\n 会被截断只剩首行，实测坑）。
    cx/cy=『选中判断』中心客户区坐标（分辨率无关），未就绪为空串。
    """
    code = r"""
local d = tp.窗口.对话栏
local parts = {}
if type(d) == 'table' and type(d.选项) == 'table' then
  for i = 1, 20 do
    local o = d.选项[i]
    if type(o) ~= 'table' then break end
    local j = type(o.选中判断) == 'table' and o.选中判断 or nil
    local cx, cy = '', ''
    if j then
      local x = tonumber(j.x or 0); local x2 = tonumber(j.x2 or 0)
      local y = tonumber(j.y or 0); local y2 = tonumber(j.y2 or 0)
      if x and x2 and y and y2 and x2 > x and y2 > y and x > 15 and y > 15 then
        cx = tostring((x + x2) / 2); cy = tostring((y + y2) / 2)
      end
    end
    parts[#parts+1] = table.concat({tostring(i), tostring(o.文字 or ''),
      tostring(o.跳转 or o.跳转链接 or ''), cx, cy}, '|')
  end
end
__out = table.concat(parts, ' ;; ')
"""
    r = _lua_call(gateway, code) or ""
    opts = []
    for part in r.split(" ;; "):
        seg = part.split("|")
        if len(seg) >= 5 and seg[0].isdigit():
            opts.append((int(seg[0]), seg[1], seg[2], seg[3], seg[4]))
    return opts


def _npc_hop_map(gateway, hwnd, target_map, tries=2):
    """天眼落点错位兜底：找当前图 "<目标图>接引人" NPC，点击→对话→点"送我过去"跨图。

    ★2026-09-06 实测（用户现场教学）：天眼落点=任务坐标，鬼刷在地图边缘传送门
      旁时落地踩门被弹回相邻图（普陀山↔大唐国境 / 长寿村↔长寿郊外，实测各卡
      31/32 轮）。相邻图 npc 表里有 "<目标图>接引人"（如 大唐国境的"普陀山接引人"，
      tp.地图.npc 实锤），CALL 对话后点"送我过去"即跨回目标图。
    NPC 定位：tp.地图.npc（数组，x/y=世界坐标），屏幕坐标 = 世界 + tp.屏幕.xy
      （与 _call_zhongkui 同款换算）。匹配用 前缀锚定（名称以目标图名开头），
      防误中"长安城传送XX"类反向条目。
    成功（已到目标图）返回 True。
    """
    if not hwnd or not target_map:
        return False
    for _ in range(max(1, tries)):
        code = (
            "local t = tp.地图.npc\n"
            "if type(t) ~= 'table' then __out = '' return end\n"
            "local off = tp.屏幕.xy\n"
            "local ox = off and off.x or 0\n"
            "local oy = off and off.y or 0\n"
            "for i = 1, #t do\n"
            "  local v = t[i] or {}\n"
            "  local nm = tostring(v.名称 or '')\n"
            "  local cz = tostring(v.称谓 or '')\n"
            "  -- 前缀锚定名称（普陀山接引人）或称谓含目标图名（土地公公|凌波城传送）\n"
            "  if nm:find('" + target_map + "', 1, true) == 1 or cz:find('" + target_map + "', 1, true) then\n"
            "    local wx = tonumber(tostring(v.x or '')) or 0\n"
            "    local wy = tonumber(tostring(v.y or '')) or 0\n"
            "    __out = nm .. '|' .. (wx + ox) .. ',' .. (wy + oy)\n"
            "    return\n"
            "  end\n"
            "end\n"
            "__out = ''\n"
        )
        r = _lua_call(gateway, code) or ""
        if "|" not in r:
            return False  # 本图没有去目标图的接引人
        nx, nxy = r.split("|", 1)
        sx, sy = nxy.split(",")
        post_click(hwnd, int(sx) + random.randint(-3, 3),
                   int(sy) + random.randint(-3, 3), gateway=gateway)
        _sleep(random.uniform(0.8, 1.2))
        # ★2026-09-06 截图实锤（test_data/npc_click_1s.png）：接引人对话与钟馗
        # 同款 UI，红字选项不进 tp.窗口.对话栏.选项（读到 0 条）——必须走红字
        # 像素检测。首行=「送我过去」（行2=取消），点首行红字块中心。
        clicked = False
        for _ in range(5):
            rows = _zhongkui_detect_rows(gateway)
            if rows:
                b = rows[0]
                post_click(hwnd, random.randint(b["x0"] + 3, max(b["x0"] + 4, b["x1"] - 3)),
                           random.randint(b["y0"], b["y1"]), gateway=gateway)
                clicked = True
                break
            _sleep(random.uniform(0.4, 0.6))
        if not clicked:
            continue  # 对话没弹出 → 重新点 NPC
        # 等跨图完成（含走路+切换），轮询校验地图
        for _ in range(8):
            _sleep(random.uniform(0.5, 0.8))
            cur = _lua_call(gateway,
                            r'''local m=tp.地图; __out=tostring(m and m.地图名称 or "")''') or ""
            if cur and (cur == target_map or target_map in cur or cur in target_map):
                return True
        # 跨图未生效：若对话还开着点第2行「取消」收尾，防残留对话挡后续点击
        rows = _zhongkui_detect_rows(gateway)
        if len(rows) >= 2:
            b = rows[1]
            post_click(hwnd, random.randint(b["x0"] + 3, max(b["x0"] + 4, b["x1"] - 3)),
                       random.randint(b["y0"], b["y1"]), gateway=gateway)
            _sleep(random.uniform(0.4, 0.7))
    return False


_MISMATCH = {"task": "", "n": 0, "ts": 0.0}  # ★2026-09-06 同一鬼"天眼落点被弹回"累计（防循环烧天眼）

# ★2026-09-06 地图编号→名称 学习表（传送圈.目标 存的是地图编号，需译回名称）。
#   已知种子来自 MPCG/实测；其余在各实例跑图时由 _learn_map_id 自动补全。
_MAP_ID_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "data", "pzxy_map_ids.json")


def _load_map_ids():
    try:
        import json as _json
        with open(_MAP_ID_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {"1140": "普陀山", "1142": "女儿村", "1512": "魔王寨", "1513": "盘丝洞"}


def _save_map_ids(d):
    try:
        import json as _json
        os.makedirs(os.path.dirname(_MAP_ID_FILE), exist_ok=True)
        _tmp = _MAP_ID_FILE + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as f:
            _json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(_tmp, _MAP_ID_FILE)
    except Exception:
        pass


def _learn_map_id(gateway):
    """把当前 地图编号→地图名称 记入学习表（传送圈跨图的译码基础，幂等）。"""
    try:
        r = _lua_call(gateway,
                      r'''local m=tp.地图
__out=tostring(m and m.地图编号 or '')..'|'..tostring(m and m.地图名称 or '')''') or ""
        mid, name = r.split("|", 1)
        if not mid.isdigit() or not name:
            return
        d = _load_map_ids()
        if str(d.get(mid)) != name:
            d[mid] = name
            _save_map_ids(d)
            logger.info("地图ID学习：%s=%s" % (mid, name))
    except Exception:
        pass


def _portal_walk_back(gateway, hwnd, target_map, max_wait=25.0):
    """传送圈走回（零消耗跨图）：当前图 传送圈 里找 目标==target_map 的门，
    点击 所在xy（世界坐标+屏幕偏移，与 NPC 点击同款换算）走回门上自动跨图。

    ★2026-09-06 实锤：tp.地图.传递数据.传送圈[k] = {所在x,所在y,目标(地图编号),
      目标x,目标y,显示,参数}——即本图全部传送门。天眼被弹回后角色就站在门旁，
      点门即回，不依赖接引人、不动任务、不耗道具。
    ★传递数据可能滞留旧图（合成旗飞城不重建场景，实测长安挂着大唐境外数据），
      故 传递数据.名称 必须等于当前地图名才可用。
    成功（已到目标图）返回 True。
    """
    if not hwnd or not target_map:
        return False
    ids = _load_map_ids()
    tid = None
    for k, v in ids.items():
        if v == target_map or str(v).find(target_map) >= 0 or target_map.find(str(v)) >= 0:
            tid = str(k)
            break
    if not tid:
        return False  # 目标图编号未知（等 _learn_map_id 学到后下轮可用）
    code = r"""
local m = tp.地图
local td = m and m.传递数据
if type(td) ~= 'table' then __out = 'N' return end
local parts = {}
parts[#parts+1] = tostring(m.地图名称 or '')
parts[#parts+1] = tostring(m.地图编号 or '')
parts[#parts+1] = tostring(td.名称 or '')
local tc = td.传送圈
if type(tc) == 'table' then
  for k, v in pairs(tc) do
    if type(v) == 'table' then
      parts[#parts+1] = tostring(v.目标 or '') .. '|' ..
        tostring(v.所在x or '') .. ',' .. tostring(v.所在y or '')
    end
  end
end
__out = table.concat(parts, ' ;; ')
"""
    r = _lua_call(gateway, code) or ""
    segs = r.split(" ;; ")
    if len(segs) < 4 or segs[2] != segs[0]:
        return False  # 传递数据滞留旧图（与当前图名不符），不可用
    off = _lua_call(gateway,
                    r'''local o=tp.屏幕.xy __out=tostring(o and o.x or 0)..','..tostring(o and o.y or 0)''') or "0,0"
    try:
        ox, oy = [int(float(v)) for v in off.split(",")]
    except Exception:
        ox = oy = 0
    for seg in segs[3:]:
        p = seg.split("|")
        if len(p) != 2 or p[0] != tid:
            continue
        try:
            ax, ay = [int(float(v)) for v in p[1].split(",")]
        except Exception:
            continue
        post_click(hwnd, ax + ox + random.randint(-3, 3),
                   ay + oy + random.randint(-3, 3), gateway=gateway)
        _sleep(random.uniform(0.8, 1.2))
        # 走路+跨图轮询（按编号判到达，名称兜底）
        t0 = time.time()
        while time.time() - t0 < max_wait:
            _sleep(random.uniform(0.8, 1.2))
            rr = _lua_call(gateway,
                           r'''local m=tp.地图
__out=tostring(m and m.地图编号 or '')..'|'..tostring(m and m.地图名称 or '')''') or ""
            cur_id, cur_name = (rr.split("|", 1) + [""])[:2]
            if cur_id == tid or (cur_name and (cur_name == target_map
                                               or target_map in cur_name)):
                _learn_map_id(gateway)
                return True
        return False
    return False


def zhuagui_ensure_task_ready(gateway=DEFAULT_GATEWAY, member_mode=False, **kw):
    """确保当前角色有抓鬼任务且已在正确地图（可 CALL 目标）位置。

    闭环（2026-09-03 实测各环节均已验证）:
      1) 先看任务栏：已有抓鬼任务 → 直接进 [3]
      2) 无任务 → 保证在长安城（zhuagui_go_back_changan）→ 接任务
      3) 使用天眼符瞬移到目标怪位置
    ★注意：天眼符每次任务都要用（本服天眼瞬移落点=目标坐标）。
    ★2026-09-03 组员模式（member_mode=True）：
      队伍中只有队长能接/取消任务，组员点击会提示"队员已有任务"而失效。
      组员无需接任务（队伍任务同步生效，任务栏仍会显示第N次/目标名），
      故跳过"回长安+接任务"，直接天眼瞬移+地图校验即可参与打鬼。

    Returns:
        bool: 是否就绪（已瞬移到目标地图/可打鬼）。
    """
    hwnd = get_hwnd()
    if not hwnd:
        return False
    # ★2026-09-03 战斗保护：战斗中 UI 锁定（背包/道具点击无效），先等战斗结束。
    #   战斗自动进行（自动起始>0）；等待最多 ~20s，期间柔和轮询战斗态。
    # ★2026-09-05 提速：入口改用 _snapshot，1 次调用同时拿 战斗态+任务态（原 2 次）
    snap = _snapshot(gateway)
    if snap["battle"]:
        logger.warning("确保任务：战斗中，等待战斗结束再继续...")
        t_wait = 0.0
        while zhuagui_in_battle(gateway) and t_wait < 20.0:
            _sleep(random.uniform(1.2, 1.8))
            t_wait += 1.5
        if zhuagui_in_battle(gateway):
            logger.warning("确保任务：战斗超时仍未结束，返回失败（等下一轮）")
            return False
    task = {"name": snap["name"], "count": snap["count"]}
    if not task.get("name") and not member_mode:
        # 无任务（非组员）：回长安接取
        mm = _lua_call(gateway, r'''local m=tp.地图; __out=tostring(m and m.地图名称 or "")''')
        if mm != "长安城":
            if not zhuagui_go_back_changan(gateway):
                logger.warning("确保任务：回长安失败")
                return False
        if not zhuagui_take_task_v2(gateway, close_dialog=False):
            # 可能对话框未关，重试一次
            _zhongkui_close_dialog(gateway)
            time.sleep(random.uniform(0.5, 0.9))
            if not zhuagui_take_task_v2(gateway, close_dialog=False):
                logger.warning("确保任务：接任务失败")
                return False
        task = zhuagui_get_task(gateway) or {}
    if not task.get("name"):
        if member_mode:
            # ★组员模式：任务栏无抓鬼任务条目 = 队伍当前无任务（队长未接/已清空）。
            # 此时不消耗天眼瞬移（没有目标坐标），直接返回等待队长处理。
            logger.warning("确保任务：组员模式但任务栏无抓鬼任务（等队长接任务）")
        return False
    # ★2026-09-06 省天眼决策树 v2（用户要求：不能循环烧天眼；且队伍中取消任务
    #   需全员退队重组，重接不可用——只能"不动任务"零消耗回跨）：
    #   异图 → ①接引人跨图（免费）→ ②传送圈走回（免费，读 传递数据.传送圈 点门）
    #   → 都不行才天眼（常规：落点=鬼坐标）
    #   → 天眼被弹回（鬼在传送门旁实锤）→ 再 ①→②
    #   → 同一鬼错位>=2次后限流：每 4 分钟才允许烧 1 次天眼（等鬼自己走开，
    #     实测 ~14min 鬼换位后自愈），其余轮次零消耗空转等待。
    def _mis(a, b):
        return bool(a and b and a != b and b not in a and a not in b)

    global _MISMATCH
    _learn_map_id(gateway)  # 顺手学习 地图编号→名称（传送圈译码用）
    tname = task.get("name") or ""
    if _MISMATCH["task"] != tname:
        _MISMATCH = {"task": tname, "n": 0, "ts": 0.0}  # 换鬼重置计数

    target_map0 = snap.get("target_map") or ""
    cur_map0 = snap.get("map") or ""
    if _mis(cur_map0, target_map0):
        # 异图：先走免费通道（接引人 → 传送圈），成功 = 0 消耗
        if _npc_hop_map(gateway, hwnd, target_map0):
            logger.info("确保任务：异图(%s→%s)接引人跨图成功（省1个天眼符）"
                        % (cur_map0, target_map0))
            _sleep(random.uniform(0.8, 1.4))
            return True
        if _portal_walk_back(gateway, hwnd, target_map0):
            logger.info("确保任务：异图(%s→%s)传送圈走回成功（省1个天眼符）"
                        % (cur_map0, target_map0))
            _sleep(random.uniform(0.8, 1.4))
            return True
        if _MISMATCH["n"] >= 2 and (time.time() - _MISMATCH["ts"]) < 240.0:
            # 该鬼已实证反复错位且两条免费通道都不可用 → 限流：4 分钟内不烧符
            logger.info("确保任务：鬼 %s 卡传送门（错位%d次），限流等待鬼走开（%.0fs 内不烧符）"
                        % (tname, _MISMATCH["n"], 240.0 - (time.time() - _MISMATCH["ts"])))
            return False
    # 天眼瞬移（同图直达鬼坐标 / 异图免费通道都不可用时的常规手段）
    if not zhuagui_use_tianyan(gateway):
        logger.warning("确保任务：使用天眼失败")
        return False
    _sleep(random.uniform(1.2, 1.8))  # ★2026-09-05 提速 2.0~3.0 → 1.2~1.8（天眼瞬移本身瞬时生效）
    # 瞬移后校验目标地图：天眼落点=任务目标坐标，若该坐标恰为地图传送门
    # （乾坤殿↔五庄观 等实锤），角色踩门被自动弹回相邻图。
    snap2 = _snapshot(gateway)
    target_map = snap2["target_map"] or target_map0
    cur_map = snap2["map"] or ""
    if _mis(cur_map, target_map):
        _MISMATCH["n"] += 1
        _MISMATCH["ts"] = time.time()
        # 落点被弹回 = 鬼在传送门旁实锤 → 免费通道跨回
        if _npc_hop_map(gateway, hwnd, target_map):
            logger.info("确保任务：落点错位（目标=%s 实际=%s），接引人跨图回目标图成功"
                        % (target_map, cur_map))
            _sleep(random.uniform(0.8, 1.4))  # 落地稳定
            return True
        if _portal_walk_back(gateway, hwnd, target_map):
            logger.info("确保任务：落点错位（目标=%s 实际=%s），传送圈走回目标图成功"
                        % (target_map, cur_map))
            _sleep(random.uniform(0.8, 1.4))
            return True
        logger.warning("确保任务：落点错位（目标=%s 实际=%s）且两条免费通道不可用，"
                       "限流等待鬼走开（错位计数=%d）" % (target_map, cur_map, _MISMATCH["n"]))
        return False
    return True


def _task_target_map(gateway):
    """从抓鬼任务说明解析目标地图名。

    任务说明格式: '#w/近日有#r/XX怪#w/正在#r/大唐境外（633,36)#w/附近作乱…'
    提取'正在#r/'后的地图名（'大唐境外'）。无任务/解析失败返回 ""。
    """
    import re as _re_local
    code = r"""
local t = tp.窗口.任务栏.任务
if type(t) ~= 'table' then __out = '' return end
for i=1,#t do
  local v = t[i]
  if type(v)=='table' and tostring(v.名称 or '')=='抓鬼任务' then
    __out = tostring(v.说明 or '') return
  end
end
__out = ''
"""
    desc = _lua_call(gateway, code) or ""
    if not desc:
        return ""
    m = _re_local.search(r"正在#r/([^#（(]+)[（(]\s*[\-0-9]+", desc)
    if m:
        return m.group(1).strip()
    return ""


_LAST_ROUND_STAGES = {}  # ★2026-09-05 提速观测：最近一轮的分段耗时（秒），run_unlimited_test 写入 jsonl

# ============================================================
# ★2026-09-06 顺手打稀有怪：抓鬼完成判定后、回长安前，扫一次本图单位，
#   命中稀有名单（知了王/星宿/远古系）就 CALL 开打，打完继续原流程。
#   只管本图、不跨图、不追公告；MHXY_ZG_BONUS=0 可整体关闭。
# ============================================================
_BONUS_NAMES = ("知了王", "星宿", "远古")   # ★2026-09-06 定案：知了王/远古按名称命中；星宿名称多变（尾火虎等），按 称谓='星宿' 命中
_BONUS_MAX_KILLS = 3                        # 单轮最多顺手打几只（防连环刷体）
# ★2026-09-06 用户实测标定的"进入战斗"选项矩形（客户区坐标 x0,y0,x1,y1）：
#   星宿对话（名上带"星宿"称谓）→ (118,308)-(175,318)；知了王对话 → (121,322)-(219,333)。
#   远古无标定范围，退回红字首行检测。CALL 出对话后按矩形随机取点直点，
#   不再依赖 _zhongkui_detect_rows（其首行对这些对话会点偏导致被跳过）。
_BONUS_CLICK_RECT = {
    "知了王": (121, 322, 219, 333),
    "星宿": (118, 308, 175, 318),
}
_BONUS_ENABLED = os.environ.get("MHXY_ZG_BONUS", "1") != "0"


def zhuagui_bonus_battle(gateway=DEFAULT_GATEWAY, verbose=False,
                         max_battle_wait=180.0, hwnd=None, **kw):
    """扫本图稀有怪并顺手打一只。命中并打完返回怪名，未命中/未进战返回 None。

    复用抓鬼 CALL 通道 `客户端:发送数据(0,3,6,标识,1)` 与 _call_guard 防重冷却。
    ★2026-09-06 修复（用户实测：CALL 出了对话框但没点击进战斗）：知了王/星宿/
    远古 CALL 后弹出"是否挑战"对话，必须点对话选项才进战——旧逻辑只干等 8s。
    ★2026-09-06 二次修复（用户标定）：星宿/知了王的"进入战斗"选项位置固定，
    存入 _BONUS_CLICK_RECT 按矩形随机取点直点；星宿检测改按 称谓='星宿'
    （名称多变：尾火虎等，不能按名称判），知了王/远古仍按名称。远古无标定
    范围退回红字首行。点击前自动存截图到 test_data/bonus_dialog_*.png 留证。
    "我正在战斗中，请勿扰。"=怪被占用，无可点选项，等进战超时跳过即可。
    进战后挂机等战斗结束（自动战斗），上限 max_battle_wait。
    """
    if not _BONUS_ENABLED:
        return None
    if hwnd is None:
        hwnd = get_hwnd()
    code = r"""
local t = tp.地图.地图单位
if type(t) ~= 'table' then __out = '' return end
for _, v in pairs(t) do
  if type(v) == 'table' then
    local name = tostring(v.名称 or '')
    local title = tostring(v.称谓 or '')
    local kind = ''
    if name:find('知了王') then kind = '知了王'
    elseif title:find('星宿') then kind = '星宿'
    elseif name:find('远古') then kind = '远古'
    end
    if kind ~= '' and v.标识 then
      __out = name .. '|' .. tostring(v.标识) .. '|' .. kind
      return
    end
  end
end
__out = ''
"""
    r = _lua_call(gateway, code) or ""
    if "|" not in r:
        return None
    parts = r.split("|")
    if len(parts) < 2:
        return None
    bname, gid = parts[0], parts[1]
    if not gid.isdigit():
        return None
    # 星宿名称多变（尾火虎等），kind 以称谓判定；旧格式无第三段时按名称兜底
    bkind = parts[2] if len(parts) >= 3 else (
        "知了王" if "知了王" in bname else ("星宿" if "星宿" in bname else "远古"))
    # 防重复 CALL：复用抓鬼目标的 8s 冷却
    _now = time.time()
    if gid == _call_guard["gid"] and _now - _call_guard["ts"] < 8.0:
        return None
    if verbose:
        logger.info("发现稀有怪 %s（%s），顺手 CALL 开打..." % (bname, bkind))
    _sleep(random.uniform(0.15, 0.4))
    _lua_call(gateway, "客户端:发送数据(0,3,6," + gid + ",1)")
    _call_guard["gid"] = gid
    _call_guard["ts"] = _now
    # ★CALL 后等对话弹出 → 点"进入战斗"选项 → 等进战
    # ★2026-09-06 用户实测标定：星宿/知了王的进战斗选项位置固定，直接按
    #   _BONUS_CLICK_RECT 矩形随机取点直点（红字首行检测对这些对话会点偏，
    #   是此前"CALL 出对话却没进战被跳过"的根因之一）。远古无标定范围，
    #   退回红字首行检测。另有一种"我正在战斗中，请勿扰。"对话（怪被别的
    #   队伍占用，无可点选项）——点矩形无效果，等进战超时跳过即可。
    def _bonus_shot(tag):
        try:
            _img, _, _ = grab_client(hwnd)
            _root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            _shot = os.path.join(_root, "test_data",
                                 "bonus_%s_%s.png" % (tag, time.strftime("%Y%m%d_%H%M%S")))
            os.makedirs(os.path.dirname(_shot), exist_ok=True)
            _img.save(_shot)
            return _shot
        except Exception:
            return ""

    rect = _BONUS_CLICK_RECT.get(bkind)
    clicked = False
    t_dlg = time.time()
    while time.time() - t_dlg < 5.0:
        if zhuagui_in_battle(gateway):
            break
        if rect:
            # 有标定矩形：等对话渲染一小会再按矩形点，截图留证
            if time.time() - t_dlg < random.uniform(0.7, 1.0):
                _sleep(0.2)
                continue
            _shot = _bonus_shot("dialog")
            if _shot:
                logger.info("稀有怪对话截图：%s" % _shot)
            x0, y0, x1, y1 = rect
            post_click(hwnd, random.randint(x0, x1), random.randint(y0, y1),
                       gateway=gateway)
            clicked = True
            if verbose:
                logger.info("已按标定矩形点稀有怪对话 (x%d-%d,y%d-%d)"
                            % (x0, x1, y0, y1))
            break
        rows = _zhongkui_detect_rows(gateway) if hwnd else []
        if rows:
            _shot = _bonus_shot("dialog")
            if _shot:
                logger.info("稀有怪对话截图：%s" % _shot)
            b = rows[0]
            post_click(hwnd, random.randint(b["x0"] + 3, max(b["x0"] + 4, b["x1"] - 3)),
                       random.randint(b["y0"], b["y1"]), gateway=gateway)
            clicked = True
            if verbose:
                logger.info("已点稀有怪对话首行 (x%d-%d,y%d-%d)"
                            % (b["x0"], b["x1"], b["y0"], b["y1"]))
            break
        _sleep(random.uniform(0.4, 0.6))
    # 等进战（点了对话给足进战加载时间；没对话则维持原 8s 放弃逻辑）
    t0 = time.time()
    battle_wait = 12.0 if clicked else 8.0
    while time.time() - t0 < battle_wait:
        if zhuagui_in_battle(gateway):
            break
        _sleep(random.uniform(0.5, 0.8))
    if not zhuagui_in_battle(gateway):
        if clicked:
            logger.info("稀有怪 %s 已点进战斗选项仍未进战（选项可能点错/距离远/被占用），跳过" % bname)
        else:
            _shot = _bonus_shot("skip")
            logger.info("稀有怪 %s 无可点选项（大概率正被其他队伍占用'请勿扰'），跳过%s"
                        % (bname, ("，截图:%s" % _shot) if _shot else ""))
        return None
    # 战斗挂机等结束
    t1 = time.time()
    while zhuagui_in_battle(gateway) and time.time() - t1 < float(max_battle_wait):
        _sleep(random.uniform(1.2, 1.8))
    ok_end = not zhuagui_in_battle(gateway)
    logger.info("稀有怪 %s 战斗%s（耗时%.0fs）"
                % (bname, "结束" if ok_end else "超时", time.time() - t1))
    return bname if ok_end else None


# ============================================================
# ★2026-09-06 自动出售垃圾装备：回长安接任务前，点选装备 → 点"出售"二字
#   （用户实测交互：左键点装备拿起 → 左键点"出售"卖出，非拖拽）。
#   判据：类型=武器/装备（bag_dump_20260906_004411 实锤，天眼符=功能/
#   合成旗=杂货 天然隔离）+ 名称含"上古锻造图策"（用户指定）+ 介绍含
#   "装备角色"兜底。MHXY_ZG_SELL=0 可整体关闭。
# ============================================================
_SELL_POS = (211, 415, 242, 429)   # "出售"二字客户区坐标块（用户 2026-09-06 实测标定）
_SELL_MAX_ITEMS = 10               # 单次最多卖几件（防拖时长）
_SELL_NEVER = ("天眼", "合成旗")   # 绝对保护名单（双保险，判据已天然隔离）
_SELL_MIN_BAG_COUNT = 12           # 背包(20格)占用达到该格数才触发出售（12=留8格缓冲）


def _bag_used_count(gateway):
    """背包格（格子id<=20，不含装备栏）已用格数；面板关闭/查询失败返回 -1（跳过本轮出售）。

    ★面板关闭时 界面数据[3].物品数据 不是 table —— 此时无法计数，跳过即可：
    跑批流程里天眼/合成旗前 _bag_ensure_open 会把包打开且不再关闭，
    下一轮战斗结束后计数恢复正常。
    """
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
local pd = type(j) == 'table' and type(j[3]) == 'table' and j[3].物品数据
if type(pd) ~= 'table' then __out = '-1' return end
local n = 0
for i = 1, 100 do
  local it = pd[i]
  if type(it) == 'table' then
    local gidn = tonumber(it.格子id) or i
    if gidn <= 20 then n = n + 1 end
  end
end
__out = tostring(n)
"""
    try:
        v = int(_lua_call(gateway, code) or "-1")
        return v if v >= 0 else -1
    except Exception:
        return -1


def _sellable_items(gateway):
    """列出可出售物品：[(格子id, x, y, 名称), ...]（最多 _SELL_MAX_ITEMS 件）。"""
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
local pd = type(j) == 'table' and type(j[3]) == 'table' and j[3].物品数据
if type(pd) ~= 'table' then __out = '' return end
local function deep_concat(v, depth)
  if depth > 4 then return '' end
  local tv = type(v)
  if tv == 'string' then return v end
  if tv ~= 'table' then return tostring(v) end
  local acc = {}
  for _, v2 in pairs(v) do acc[#acc+1] = deep_concat(v2, depth + 1) end
  return table.concat(acc, '')
end
    local parts = {}
    for i = 1, 100 do
      local it = pd[i]
      if type(it) == 'table' then
        local name = tostring(it.名称 or '')
        local itype = tostring(it.类型 or '')
        local cat = tostring(it.分类 or '')
        local desc = deep_concat(it.说明, 0)
        -- ★2026-09-06 队长满包20格0可售实锤修正：装备的 类型=具体部位
        --   （头盔/衣服/鞋子/腰带/项链/武器...），'武器'/'装备'一个都匹配不上；
        --   装备的 **分类** 字段才是 '武器'/'防具'。主判据改分类，类型作兼容。
        local sell = (cat == '武器') or (cat == '防具')
        if not sell then sell = (itype == '武器') or (itype == '装备') end
        if not sell then sell = (name:find('上古锻造图策') ~= nil) end
        if not sell then sell = (desc:find('装备角色') ~= nil) end
    if sell then
      local sa = it.小动画
      local x = type(sa) == 'table' and tonumber(sa.x) or 0
      local y = type(sa) == 'table' and tonumber(sa.y) or 0
      local gidn = tonumber(it.格子id) or i
      -- ★身上穿的装备也在 物品数据 里（紫电青霜实锤：背包类型=包裹、格子id=21、
      --   小动画 y≈84 在装备栏区），绝不能碰。背包格判据：格子id<=20 且 y>=195。
      if x and y and x > 0 and y >= 195 and gidn <= 20 then
        parts[#parts+1] = tostring(gidn) .. '|' .. x .. '|' .. y .. '|' .. name
      end
    end
  end
end
__out = table.concat(parts, ' ;; ')
"""
    r = _lua_call(gateway, code) or ""
    items = []
    for part in r.split(" ;; "):
        seg = part.split("|")
        if len(seg) == 4 and any(n in seg[3] for n in _SELL_NEVER):
            continue  # 保护名单双保险
        if len(seg) == 4 and seg[0].isdigit():
            items.append((int(seg[0]), int(seg[1]), int(seg[2]), seg[3]))
        if len(items) >= _SELL_MAX_ITEMS:
            break
    return items


def _bag_pick_state(gateway):
    """读面板3 的拿起对象（0/空=未拿起）。"""
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
local v = type(j) == 'table' and type(j[3]) == 'table' and j[3].拿起对象
__out = tostring(v or '0')
"""
    return (_lua_call(gateway, code) or "0")


def zhuagui_sell_junk(gateway=DEFAULT_GATEWAY, hwnd=None, verbose=False, **kw):
    """出售背包垃圾装备。返回出售件数；背包未开/无可卖/关闭开关返回 0。

    交互（用户实测）：左键点装备（拿起）→ 左键点"出售"（卖出）。
    ★2026-09-06 复核加固（队员实测：面板开着时 物品数据 可能不刷新）：
      - 先看拿起对象：手未空=卖出未生效，点原格子放回并中止；
      - 手已空=物品已脱手，但先关包再开包**强制重建物品数据**再复核
        （按同名数量是否减少判定，防格子位移误判），
        避免"旧数据仍列该格→误判未卖→点原格子反拿起新物品"。
      - tried 集合防同一物品反复重试。
    """
    if os.environ.get("MHXY_ZG_SELL", "1") == "0":
        return 0
    if hwnd is None:
        hwnd = get_hwnd()
    if not hwnd:
        return 0
    if not _bag_ensure_open(gateway, hwnd):
        logger.warning("出售装备：背包无法打开")
        return 0
    sx0, sy0, sx1, sy1 = _SELL_POS
    sold = 0
    tried = set()
    for _ in range(_SELL_MAX_ITEMS):
        items = [it for it in _sellable_items(gateway)
                 if (it[0], it[3]) not in tried]
        if not items:
            break
        gid, ix, iy, iname = items[0]
        tried.add((gid, iname))
        same_before = sum(1 for it in items if it[3] == iname)
        post_click(hwnd, ix + random.randint(-2, 2), iy + random.randint(-2, 2),
                   gateway=gateway)
        _sleep(random.uniform(0.25, 0.45))
        pick = _bag_pick_state(gateway)
        if pick in ("0", "", "nil"):
            logger.info("出售装备：点选 %s(格子%s) 未拿起，跳过" % (iname, gid))
            continue
        scx = random.randint(sx0 + 3, max(sx0 + 4, sx1 - 3))
        scy = random.randint(sy0 + 2, max(sy0 + 3, sy1 - 2))
        post_click(hwnd, scx, scy, gateway=gateway)
        _sleep(random.uniform(0.35, 0.6))
        # 手未空 = 卖出未生效 → 放回并中止
        if _bag_pick_state(gateway) not in ("0", "", "nil"):
            logger.warning("出售装备：%s(格子%s) 点出售未生效，放回并中止" % (iname, gid))
            post_click(hwnd, ix, iy, gateway=gateway)
            _sleep(random.uniform(0.25, 0.45))
            break
        # 手已空 → 关包再开包强制刷新物品数据，按同名数量复核
        if not (_bag_ensure_close(gateway, hwnd) and _bag_ensure_open(gateway, hwnd)):
            logger.warning("出售装备：卖出后刷新背包失败，按已卖出计并中止")
            sold += 1
            break
        now_items = _sellable_items(gateway)
        same_after = sum(1 for it in now_items if it[3] == iname)
        if same_after < same_before:
            sold += 1
            if verbose:
                logger.info("出售装备：%s(格子%s) 已卖出 (%d/%d)"
                            % (iname, gid, sold, _SELL_MAX_ITEMS))
        else:
            logger.warning("出售装备：%s(格子%s) 手已空但数量未减，跳过该物品" % (iname, gid))
    if sold:
        logger.info("出售装备：本次共卖出 %d 件" % sold)
    return sold


def zhuagui_do_round(gateway=DEFAULT_GATEWAY, wait_dialog=1.2, timeout=20.0,
                     verbose=False, member_mode=False, **kw):
    """单轮完整抓鬼：确保接任务→瞬移→找鬼→进战→确认完成。

    Args:
        member_mode: 组员模式（队伍中非队长）。组员无法接/取消任务，
          跳过接任务流程，直接天眼瞬移后打鬼；失败也不走取消重接。

    Returns:
        (bool, str): (是否完成本轮, 信息)
    """
    _LAST_ROUND_STAGES.clear()
    _t_round0 = time.time()
    hwnd = get_hwnd()
    if not hwnd:
        return False, "未找到游戏窗口"
    if not zhuagui_ensure_task_ready(gateway, member_mode=member_mode):
        _LAST_ROUND_STAGES["ensure_task_ready"] = round(time.time() - _t_round0, 2)
        return False, "任务未就绪（接任务/瞬移失败）"
    _LAST_ROUND_STAGES["ensure_task_ready"] = round(time.time() - _t_round0, 2)
    _t_b0 = time.time()
    ok, msg = zhuagui_enter_battle(gateway, wait_dialog=wait_dialog,
                                   timeout=timeout, verbose=verbose, hwnd=hwnd)
    _LAST_ROUND_STAGES["enter_battle"] = round(time.time() - _t_b0, 2)
    # ★2026-09-06 顺手打稀有怪：本轮完成后、回长安前，本图扫 知了王/星宿/远古
    if ok:
        # ★2026-09-06 顺手清背包：所有角色（含队员）战斗结束后统一出售。
        #   队员不接任务、不走回长安分支，这里是队员唯一出售时机。
        #   出售不依赖商店（背包自带"出售"绑定，任意地图可用）。
        #   背包占用 < 阈值时只花一次查询，不拖节奏。
        _t_sell = time.time()
        try:
            if _bag_used_count(gateway) >= _SELL_MIN_BAG_COUNT:
                n_sold = zhuagui_sell_junk(gateway, hwnd=hwnd)
                if n_sold:
                    _LAST_ROUND_STAGES["sell_junk"] = round(time.time() - _t_sell, 2)
        except Exception as e:
            logger.warning("出售装备异常（不影响主流程）: %s" % e)
        _t_bn = time.time()
        killed = []
        try:
            for _ in range(max(1, _BONUS_MAX_KILLS)):
                bname = zhuagui_bonus_battle(gateway, verbose=verbose)
                if not bname:
                    break
                killed.append(bname)
        except Exception as e:
            logger.warning("顺手打稀有怪异常（不影响抓鬼主流程）: %s" % e)
        if killed:
            _LAST_ROUND_STAGES["bonus_battle"] = round(time.time() - _t_bn, 2)
            msg = msg + " 顺手打:" + "+".join(killed)
    if ok:
        # ★2026-09-06 本轮成功 = 错位循环已解除，重置防烧符计数
        global _MISMATCH
        _MISMATCH = {"task": "", "n": 0, "ts": 0.0}
    return ok, msg


def _bag_visible(gateway) -> bool:
    """查询道具背包面板是否可见（用 Lua 直接判定）。

    ★2026-09-03 修复：改用 `tp.主界面.界面数据[3]` 行囊面板的 `本类开关` 字段
      直接判定（true=打开）。旧判据"物品数据计数>0"在面板关闭后数据可能残留
      （恒 true），不可靠。面板3 为道具行囊（状态=道具、当前类型=包裹），
      其余"包裹"类面板(14/52/53) 本类开关=false，不会混淆。
      兼容网关序列化：布尔 true 或字符串 'true' 都视为开。
    """
    code = (
        "local p = tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[3]\n"
        "if type(p) ~= 'table' then __out = 'false' return end\n"
        "local sw = p.本类开关\n"
        "__out = (sw == true or tostring(sw) == 'true') and 'true' or 'false'\n"
    )
    return (_lua_call(gateway, code) or "") == "true"


def _bag_button_pos(hwnd):
    """背包开关按钮客户区坐标（底栏背包图标）。

    ★2026-09-03 用户实测确认 (492,588)，后台点击双向开关已验证：
      背包关时点它=打开，开时点它=关闭（配合 _bag_visible 本类开关判据）。
      此前 (0.915,0.943) 等比推算 (732,565) 实测无效（落在快捷栏空档）。
    """
    try:
        import win32gui
        _rect = win32gui.GetClientRect(hwnd)
        _w, _h = _rect[2], _rect[3]
        # 实测基准 @800x600 → 0.615, 0.98；按客户区等比换算
        return int(_w * (492.0 / 800.0)), int(_h * (588.0 / 600.0))
    except Exception:
        return 492, 588


def _bag_ensure_open(gateway, hwnd, tries=5) -> bool:
    """点击右下角背包按钮确保背包打开（真实点击开包最稳，兼容 MPCG._open_bag）。"""
    if _bag_visible(gateway):
        return True
    for _ in range(max(1, int(tries))):
        bx, by = _bag_button_pos(hwnd)
        post_click(hwnd, bx, by, gateway=gateway)
        for _ in range(4):
            _sleep(random.uniform(0.15, 0.3))
            if _bag_visible(gateway):
                return True
    return _bag_visible(gateway)


def _bag_ensure_close(gateway, hwnd, tries=3) -> bool:
    """若背包面板仍打开则再次点击按钮将其关闭。"""
    if not _bag_visible(gateway):
        return True
    for _ in range(max(1, int(tries))):
        bx, by = _bag_button_pos(hwnd)
        post_click(hwnd, bx, by, gateway=gateway)
        for _ in range(4):
            _sleep(random.uniform(0.15, 0.3))
            if not _bag_visible(gateway):
                return True
    return not _bag_visible(gateway)


# ============================================================
# ★2026-09-06 自动组队（用户 20:06 手动演示 + 20:11 标定全流程）
#   主队图标 (570,583) 左键 → 点角色身体：队长点自己身体=创建队伍；
#   队员点队长身体=发入队申请。队长再点图标 → "请求列表"
#   (460,140)-(509,152) 打开申请列表 → 点申请者卡片 → "允许"
#   (514,370)-(541,378)。允许后面板自动关闭，必须重开（图标→请求
#   列表）循环，直到 4 名队员全部入队。
#   数据面复用 界面数据[7]：队伍数据=成员表(仅队长端有值)，申请列表=入队申请。
#   ★tp 依赖：全部走 tp.主界面/tp.屏幕；tp 被服务器事件抹除时（2026-09-06
#   20:28 实证，换图不恢复、仅重登重建）整套自动化同死，属同一运维事件。
# ============================================================
_TEAM_ICON_POS = (570, 583)                 # 主队图标（客户区，用户标定；快捷键 ALT+T）
_TEAM_REQLIST_RECT = (460, 140, 509, 152)   # "请求列表"按钮（用户标定）
_TEAM_ALLOW_RECT = (514, 370, 541, 378)     # 申请列表"允许"（用户标定）
# 申请者卡片选中点（用户 21:44 标定 (162,166) 实测选中成功；卡距~112）
# ★注意：点名字行(y≈287)/头像下部都不选中，必须点头像上部 (162,166)
_TEAM_APPLY_SLOTS = ((162, 166), (274, 166), (386, 166), (498, 166))
_TEAM_BODY_LIFT = 35                        # 身体点击：世界脚底锚点上移量（半身高，实测命中）

_TEAM_STATS_LUA = r"""
if type(tp) ~= 'table' then __out = '-' return end
local j = tp.主界面 and tp.主界面.界面数据
local p7 = type(j) == 'table' and j[7]
if type(p7) ~= 'table' then __out = '-' return end
local td = p7.队伍数据
local mem, leader = 0, ''
if type(td) == 'table' then
  for _, v in pairs(td) do
    if type(v) == 'table' then
      mem = mem + 1
      if v.队长 then leader = tostring(v.名称 or '') end
    end
  end
end
local app = 0
if type(p7.申请列表) == 'table' then
  for _ in pairs(p7.申请列表) do app = app + 1 end
end
__out = mem .. '|' .. app .. '|' .. leader
"""


def _team_stats(gateway):
    """队伍面板统计 → (成员数, 申请数, 队长名)；tp/面板不可用返回 None。"""
    r = _lua_call(gateway, _TEAM_STATS_LUA)
    if not r or r == "-":
        return None
    try:
        mem, app, leader = r.split("|", 2)
        return int(mem), int(app), leader
    except ValueError:
        return None


def _team_self_world_xy(gateway):
    """自身世界坐标（界面数据[7].队伍数据[1].地图数据，队长端读自条目）；无队伍返回 None。"""
    code = r"""
if type(tp) ~= 'table' then __out = '' return end
local j = tp.主界面 and tp.主界面.界面数据
local p7 = type(j) == 'table' and j[7]
local td = type(p7) == 'table' and p7.队伍数据
local v = type(td) == 'table' and td[1]
local md = type(v) == 'table' and v.地图数据
if type(md) ~= 'table' then __out = '' return end
__out = tostring(md.x) .. ',' .. tostring(md.y)
"""
    r = _lua_call(gateway, code) or ""
    if "," not in r:
        return None
    try:
        x, y = r.split(",", 1)
        return float(x), float(y)
    except ValueError:
        return None


def _screen_offset_xy(gateway):
    """tp.屏幕.xy（世界→屏幕换算偏移，客户端各自相机）；tp 不可用返回 None。"""
    code = r"""
if type(tp) ~= 'table' then __out = '' return end
local o = tp.屏幕 and tp.屏幕.xy
if type(o) ~= 'table' then __out = '' return end
__out = tostring(o.x) .. ',' .. tostring(o.y)
"""
    r = _lua_call(gateway, code) or ""
    if "," not in r:
        return None
    try:
        x, y = r.split(",", 1)
        return float(x), float(y)
    except ValueError:
        return None


def _team_click_icon(hwnd, gateway, tries=1):
    """点主队图标（用户流程：点一次图标进入选目标模式，下一次身体点击生效）。

    ★tries 默认 1：图标是模式开关，点两次=开又关（2026-09-06 实测建队
    3 连败的根因）。
    """
    for _ in range(max(1, tries)):
        post_click(hwnd, _TEAM_ICON_POS[0], _TEAM_ICON_POS[1], gateway=gateway)
        _sleep(random.uniform(0.45, 0.7))


def _team_click_body(hwnd, gateway, sx, sy, hover_pause=0.7):
    """点角色身体。

    ★(sx,sy) 是世界脚底锚点的屏幕坐标，角色精灵从脚底向上画，实际点击
    点要上移 _TEAM_BODY_LIFT（2026-09-06 实测：不抬会点在脚下地面=移动
    指令，角色走散）。hover_pause 供旗子光标（悬停目标才变旗）渲染。
    """
    tx, ty = sx + random.randint(-3, 3), sy - _TEAM_BODY_LIFT + random.randint(-3, 2)
    _move_traj(hwnd, _last_mouse[0], _last_mouse[1], tx, ty)
    _sleep(hover_pause)
    post_click(hwnd, tx, ty, gateway=gateway)
    _sleep(random.uniform(0.4, 0.7))


def zhuagui_team_create(gateway=DEFAULT_GATEWAY, hwnd=None, verbose=False,
                        world_xy=None, **kw):
    """队长创建队伍：点主队图标(旗子模式) → 光标移到自己身体 → 左键。

    world_xy: 队长当前世界坐标 (x,y)；缺省用屏幕点 (400,370) 兜底（脚底
    锚点≈相机中心带，再由 _team_click_body 上移）。
    ★队伍数据是面板懒加载：建队后头顶令牌即成功标志，但 Lua 读 队伍数据
    需先点一次图标打开队伍信息面板，故校验前补一次图标点击。
    ★2026-09-06 实测坑：解散前的旧懒加载快照会残留（如 (1,0,'二号美人')），
    stats 校验无法区分"真建队"与"脏数据"——本函数返回 True 只表示点击
    序列已执行，编排层应靠队员申请是否入列做最终裁决。
    创建成功返回 True。
    """
    if hwnd is None:
        hwnd = get_hwnd()
    off = _screen_offset_xy(gateway)
    if world_xy is not None and off is not None:
        sx, sy = int(world_xy[0] + off[0]), int(world_xy[1] + off[1])
    else:
        sx, sy = 400, 400
    for attempt in range(3):
        _team_click_icon(hwnd, gateway)
        _team_click_body(hwnd, gateway, sx, sy)
        for _ in range(6):
            _sleep(random.uniform(0.4, 0.6))
            st = _team_stats(gateway)
            if st and st[0] >= 1 and st[2]:
                if verbose:
                    logger.info("队伍创建成功：队长=%s 成员=%d（第%d次尝试）"
                                % (st[2], st[0], attempt + 1))
                return True
        # 面板懒加载：点图标打开队伍信息面板后再读
        _team_click_icon(hwnd, gateway)
        for _ in range(4):
            _sleep(random.uniform(0.4, 0.6))
            st = _team_stats(gateway)
            if st and st[0] >= 1 and st[2]:
                if verbose:
                    logger.info("队伍创建成功（开面板后确认）：队长=%s" % st[2])
                return True
        if verbose:
            logger.info("创建第%d次尝试未观察到队伍数据，重试" % (attempt + 1))
    return False


def zhuagui_team_join(gateway=DEFAULT_GATEWAY, hwnd=None, verbose=False,
                      leader_world_xy=None, **kw):
    """队员申请入队：点主队图标 → 点队长身体（世界坐标+本机屏幕偏移换算）。

    申请是否入列由队长端申请列表核对（编排器负责），本函数只管发出点击。
    """
    if hwnd is None:
        hwnd = get_hwnd()
    if leader_world_xy is None:
        logger.info("缺少队长世界坐标，无法申请入队")
        return False
    off = _screen_offset_xy(gateway)
    if off is None:
        logger.info("tp 不可用，无法换算队长屏幕位置")
        return False
    sx, sy = int(leader_world_xy[0] + off[0]), int(leader_world_xy[1] + off[1])
    _team_click_icon(hwnd, gateway)
    _team_click_body(hwnd, gateway, sx, sy)
    if verbose:
        logger.info("已点队长身体 (%d,%d) 发出入队申请" % (sx, sy))
    return True


def zhuagui_team_approve_all(gateway=DEFAULT_GATEWAY, hwnd=None, verbose=False,
                             expect_members=5, max_rounds=8, **kw):
    """队长循环批准入队申请，直到成员数达 expect_members 或申请清空。

    流程（用户 2026-09-06 手动演示实测）：第 1 轮点图标打开队伍信息面板，
    之后每轮点"请求列表"→点首个申请者卡片→"允许"；允许后申请列表自动
    关闭，下一轮重开即可（无需再点图标——图标会把面板关掉）。
    ★2026-09-06 22:20 全流程实测：p7.申请列表 计数恒为 0（数据结构里
    读不到申请），故不能以 app==0 判"申请清空"提前退出——那会在第 1 轮
    就放弃。改为只看成员数递增（1→2→…→expect），轮数耗尽即止。
    返回最终成员数（不可读=-1）。
    """
    if hwnd is None:
        hwnd = get_hwnd()
    rx = random.randint(_TEAM_REQLIST_RECT[0], _TEAM_REQLIST_RECT[2])
    ry = random.randint(_TEAM_REQLIST_RECT[1], _TEAM_REQLIST_RECT[3])
    ax = random.randint(_TEAM_ALLOW_RECT[0], _TEAM_ALLOW_RECT[2])
    ay = random.randint(_TEAM_ALLOW_RECT[1], _TEAM_ALLOW_RECT[3])
    for rnd in range(max(1, max_rounds)):
        if rnd == 0:
            _team_click_icon(hwnd, gateway)   # 打开队伍信息面板
        post_click(hwnd, rx, ry, gateway=gateway)            # "请求列表"
        _sleep(random.uniform(0.7, 1.0))
        st = _team_stats(gateway)                            # 面板已开，数据新鲜
        if st is None:
            logger.info("队伍面板不可读（tp 缺失?），中止审批")
            return -1
        mem, app, leader = st
        if mem >= expect_members:
            if verbose:
                logger.info("审批结束：成员=%d 申请=%d" % (mem, app))
            return mem
        slot = _TEAM_APPLY_SLOTS[0]                          # 每批总点首卡
        post_click(hwnd, slot[0], slot[1], gateway=gateway)  # 选中申请者
        _sleep(random.uniform(0.4, 0.6))
        post_click(hwnd, ax, ay, gateway=gateway)            # "允许"
        if verbose:
            logger.info("审批轮%d：已点申请者+允许（成员%d 申请%d）"
                        % (rnd + 1, mem, app))
        ok = False
        for _ in range(10):
            _sleep(random.uniform(0.5, 0.7))
            st2 = _team_stats(gateway)
            if st2 and (st2[0] > mem or st2[1] < app):
                ok = True
                break
        if not ok and verbose:
            logger.info("审批轮%d 未观察到成员/申请变化，继续下一轮" % (rnd + 1))
    st = _team_stats(gateway)
    return st[0] if st else -1


def tianyan_read_pos(gateway):
    """确认背包中存在天眼符，返回其图标中心坐标 (x,y)；未找到返回 (0,0)。

    ★2026-09-03 修复：天眼符（功能型道具）没有独立 x/y 坐标字段，旧代码
      误用固定槽位/网格推算导致点击落空。正确做法：读物品的**小动画对象**
      的 x,y —— 这就是图标加载后缓存的真实客户区坐标（实测天眼符格子id16
      =(232,354)）。合成旗在 y302 行、天眼在 y354 行，位置不同不会误点。

    Returns:
        tuple: (x, y)。存在天眼符则返回真实图标坐标；否则 (0,0)。
    """
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
if type(j) ~= 'table' then __out = '0,0' return end
local pd = j[3] and j[3].物品数据
if type(pd) ~= 'table' then __out = '0,0' return end
for k, it in pairs(pd) do
  if type(it) == 'table' and tostring(it.名称 or ''):find('天眼') then
    local sa = it.小动画
    if type(sa) == 'table' then
      local x = tonumber(sa.x)
      local y = tonumber(sa.y)
      if x and y and x > 0 and y > 0 then
        __out = string.format('%d,%d', x, y)
        return
      end
    end
  end
end
__out = '0,0'
"""
    r = _lua_call(gateway, code) or "0,0"
    if "," not in r:
        return 0, 0
    try:
        x, y = r.split(",")
        return int(round(float(x))), int(round(float(y)))
    except Exception:
        return 0, 0


def zhuagui_use_tianyan(gateway=DEFAULT_GATEWAY, **kw):
    """使用天眼通符：读取背包物品数据中天眼符的真实坐标，后台右键点击。

    ★2026-09-03 修复：旧"使用天眼"事件依赖图像模板在天眼.bmp 位置
      (258,378) 右键，但天眼符实际位于背包面板3 槽16 (271,264)。
    （面板3.x=0,y=0，物品坐标即客户区坐标；模板匹配误中同区域其它图标
      导致右键点到合成旗/其它道具 → 角色没瞬移到目标地图。）
    本函数直接读 `tp.主界面.界面数据[3].物品数据` 中名称含"天眼"的道具，
    取其实时坐标后台右键，不再依赖模板匹配。

    Returns:
        bool: 是否成功定位并使用天眼符。
    """
    hwnd = get_hwnd()
    if not hwnd:
        return False

    # ★2026-09-03 修复：天眼符在背包面板内，读坐标前必须保证背包已打开。
    # 读取目标是 `tp.主界面.界面数据[面板].物品数据`，背包未打开时该项为空表。
    # 此处后台点击右下角背包按钮开包并轮询确认（与 MPCG._open_bag 同理）。
    # ★2026-09-03 追加：游戏刚重启/背包数据未加载时坐标读取会短时失败，
    # 开包后轮询重读（最多 ~4s），避免瞬时失败误判"无天眼"。
    # ★2026-09-05 根治（与回长安同病灶）：面板关闭后物品数据有残留，
    # "先读坐标、读不到才开包"的顺序会让残留坐标直接通过 → 右键点空。
    # 改为读坐标前无条件确保背包打开（幂等，已开时仅一次 Lua 查询）。
    if not _bag_ensure_open(gateway, hwnd):
        logger.warning("天眼使用：背包无法打开")
        return False
    if tianyan_read_pos(gateway)[0] <= 0:
        if not _bag_ensure_open(gateway, hwnd):
            logger.warning("天眼符坐标读取失败（背包未打开或无天眼符）")
            return False
        x, y = 0, 0
        for _ in range(5):
            x, y = tianyan_read_pos(gateway)
            if x > 0 and y > 0:
                break
            _sleep(random.uniform(0.5, 0.9))
    else:
        x, y = tianyan_read_pos(gateway)
    if x <= 0 or y <= 0:
        logger.warning("天眼符坐标读取失败（背包未打开或无天眼符）")
        return False
    post_right_click(hwnd, int(x), int(y), gateway=gateway)
    # 柔和化：使用后短暂停顿，等待瞬移生效（★09-05 提速 0.8~1.4 → 0.6~1.0）
    _sleep(random.uniform(0.6, 1.0))
    # ★2026-09-03 用户明确要求：不要关闭背包！
    # 背包一旦关闭，背包面板数据消失，后续很难再定位并使用道具（天眼符等）。
    # 因此不再调用 _bag_ensure_close，保持背包打开状态。
    # ★2026-09-03 追加：把引擎光标移出背包（离开物品格），否则光标悬停在
    #   天眼符上 tooltip 常显，会遮挡/干扰后续点击（"鼠标一直停留在背包上"）。
    _mouse_clear(hwnd, gateway)
    return True


def zhuagui_go_back_changan(gateway=DEFAULT_GATEWAY, red_x=312, red_y=229, **kw):
    """从任意地图回长安城钟馗身边（合成旗地图红点）。

    ★2026-09-03 实测成功链路（打鬼完成后常用于回长安接下一只）:
      1) 右键背包中的红色合成旗 → 打开长安城传送大地图
      2) 点击"殷"字旁边红点 (312,229) → 角色飞到钟馗身边
    用户实测确认红点正确坐标 (312,229)（此前尝试 301/306 等偏移均无效）。

    Returns:
        bool: 是否已回长安城。
    """
    hwnd = get_hwnd()
    if not hwnd:
        return False
    # ★2026-09-03 战斗保护：战斗中右键合成旗/点红点无效，先等战斗结束（最多20s）
    if zhuagui_in_battle(gateway):
        logger.warning("回长安：战斗中，等待战斗结束再回城...")
        t_wait = 0.0
        while zhuagui_in_battle(gateway) and t_wait < 20.0:
            _sleep(random.uniform(1.2, 1.8))
            t_wait += 1.5
        if zhuagui_in_battle(gateway):
            logger.warning("回长安：战斗超时未结束")
            return False
    # 已在长安城直接成功
    if _lua_call(gateway, r'''local m=tp.地图; __out=tostring(m and m.地图名称 or "")''') == "长安城":
        return True
    # ★2026-09-05 修复（用户实拍）：背包关闭时 `界面数据[3].物品数据` 有残留，
    # _zhuagui_find_flag_pos 照样返回旧坐标 → 右键点在关着的背包上 → 大地图打不开
    # → "回长安失败"死循环。根治：读坐标前无条件确保背包打开（幂等，已开零开销）。
    if not _bag_ensure_open(gateway, hwnd):
        logger.warning("回长安：背包无法打开")
        return False
    # 1) 读合成旗位置并右键打开地图（合成旗图标在背包，先确保背包打开）
    # ★2026-09-03 追加：游戏刚重启/背包数据未加载时短时读不到，开包后轮询重读。
    flagpos = _zhuagui_find_flag_pos(gateway)
    if flagpos[0] <= 0:
        if not _bag_ensure_open(gateway, hwnd):
            logger.warning("回长安：背包无红色合成旗")
            return False
        for _ in range(5):
            flagpos = _zhuagui_find_flag_pos(gateway)
            if flagpos[0] > 0:
                break
            _sleep(random.uniform(0.5, 0.9))
    if flagpos[0] <= 0:
        logger.warning("回长安：找不到红色合成旗")
        return False
    post_right_click(hwnd, flagpos[0], flagpos[1], gateway=gateway)
    _sleep(random.uniform(1.0, 1.5))  # ★2026-09-05 提速 1.5~2.2 → 1.0~1.5（等大地图弹出）
    # ★2026-09-03 追加：右键旗子后移开光标（旗子在背包内，悬停会弹 tooltip）
    _mouse_clear(hwnd, gateway)
    # 2) 点击"殷"字旁红点 → 钟馗身边
    jx = red_x + random.randint(-3, 3)
    jy = red_y + random.randint(-3, 3)
    post_click(hwnd, jx, jy, gateway=gateway)
    _sleep(random.uniform(1.2, 1.8))  # ★2026-09-05 提速 1.8~2.5 → 1.2~1.8（飞行落地图弹出）
    _mouse_clear(hwnd, gateway)
    mm = _lua_call(gateway, r'''local m=tp.地图; __out=tostring(m and m.地图名称 or "")''')
    return mm == "长安城"


def _zhuagui_find_flag_pos(gateway):
    """背包中红色合成旗的图标坐标 (x,y)；无则返回 (0,0)。同天眼逻辑读小动画。

    ★2026-09-03 修复：原用 `pairs(pd)` 遍历，Lua 表遍历顺序不确定，偶发返回
      非旗子/错误坐标（充当坐标(475,566)）→ 右键落在空白处 → 长安地图打不开
      导致"回长安失败"死循环。改为按下标 1..N 顺序扫描（pd[i] 直接取值，
      空格为 nil 跳过），稳定返回第一个合成旗（实测 (186,302)）。
    """
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
if type(j) ~= 'table' then __out = '0,0' return end
local pd = j[3] and j[3].物品数据
if type(pd) ~= 'table' then __out = '0,0' return end
for i = 1, 100 do
  local it = pd[i]
  if type(it) == 'table' and tostring(it.名称 or ''):find('合成旗') then
    local sa = it.小动画
    if type(sa) == 'table' then
      local x = tonumber(sa.x); local y = tonumber(sa.y)
      if x and y and x > 0 and y > 0 then
        __out = string.format('%d,%d', x, y)
        return
      end
    end
  end
end
__out = '0,0'
"""
    r = _lua_call(gateway, code) or "0,0"
    if "," not in r:
        return 0, 0
    try:
        x, y = r.split(",")
        return int(round(float(x))), int(round(float(y)))
    except Exception:
        return 0, 0


def zhuagui_find_ghost(gateway=DEFAULT_GATEWAY, **kw):
    """找当前地图的抓鬼目标怪 → (名称, 屏幕x, 屏幕y)；无目标返回 None。

    匹配逻辑（2026-09-02 修复）：本服抓鬼怪名格式为"XX时XX刻XXX"
    （如 戌时四刻富有鬼 / 卵时四刻勤奋僵尸，造型马面/野鬼等，称谓不一定为"野鬼"）。
    因此优先用任务栏的抓鬼任务说明提取目标怪名，再用该名匹配地图单位；
    无任务说明时回退到"称谓=野鬼 或 名称含鬼"。
    """
    # 1) 从任务说明提取目标怪名
    task = zhuagui_get_task(gateway)
    target_name = (task or {}).get("name") or ""

    code = (
        "local t = tp.地图.地图单位\n"
        "if type(t) ~= 'table' then __out = '' return end\n"
        "local off = tp.屏幕.xy\n"
        "local ox = off and off.x or 0\n"
        "local oy = off and off.y or 0\n"
        "local target = '" + target_name + "'\n"
        # ★2026-09-03 修复：地图单位表可能为键值结构（#t=0 但 pairs 有内容），
        # 旧 for i=1,#t 会漏掉全部单位 → 找不到目标。改用 pairs 遍历。
        "for _, v in pairs(t) do\n"
        "  if type(v) == 'table' then\n"
        "  local name = tostring(v.名称 or '')\n"
        "  local cz = tostring(v.称谓 or '')\n"
        "  local match = false\n"
        "  if target ~= '' then\n"
        "    match = (name:find(target, 1, true) ~= nil) or (target:find(name, 1, true) ~= nil)\n"
        "  else\n"
        "    match = (cz == '野鬼') or (name:find('鬼') ~= nil)\n"
        "  end\n"
        "  if match and name ~= '' then\n"
        "    local wx = tonumber(tostring(v.坐标 and v.坐标.x or '')) or 0\n"
        "    local wy = tonumber(tostring(v.坐标 and v.坐标.y or '')) or 0\n"
        "    __out = name .. '|' .. (wx+ox) .. ',' .. (wy+oy)\n"
        "    return\n"
        "  end\n"
        "  end\n"
        "end\n"
        "__out = ''\n"
    )
    r = _lua_call(gateway, code) or ""
    if "|" not in r:
        return None
    n, xy = r.split("|")
    sx, sy = xy.split(",")
    return n, int(sx), int(sy)


def zhuagui_click_ghost(gateway=DEFAULT_GATEWAY, **kw):
    """CALL 触发目标鬼对话（模拟点击野鬼）。

    2026-09-03 改进（修复"CALL到别的NPC"）：
      - 点击野鬼在游戏内的全部效果就是一行
        ``客户端:发送数据(0,3,6,标识,1)``（点NPC发对话请求包）。
      - ★先用任务目标怪名双向匹配 地图单位，避免直接取 地图单位[1]
        （[1] 可能是天机星等其它NPC/单位，会 CALL 错对象）。
      - 无任务说明时回退"称谓=野鬼 或 名称含鬼"。

    ★2026-09-03 追加（用户反馈"战斗中弹 call 目标提示框"）：
      - 战斗保护：战斗中 UI 锁定，对地图目标发 CALL 会弹无意义提示框，
        直接返回 False 不打 CALL（战斗中不操作目标）。
      - 防重复 CALL：同一目标 8s 冷却（_call_guard），避免"对话框已弹出但
        红字检测 miss → 重 CALL"造成的多 call/重复弹框。

    Returns:
        bool: 是否成功触发对话请求。
    """
    # ★2026-09-05 提速：战斗检查+任务名提取+目标标识查找 原为 3 次独立 Lua 调用，
    #   合并为 1 次（服务端同一 Lua 态内顺序执行，语义不变）。
    code = r"""
local b = tp.战斗类
if type(b) == 'table' then
  local u = b.参战单位
  if type(u) == 'table' then
    local n = 0
    for _ in pairs(u) do n = n + 1 end
    if n > 0 and tonumber(b.敌方数量 or 0) > 0 then __out = 'BATTLE' return end
  end
end
local target = ''
local t = tp.窗口.任务栏.任务
if type(t) == 'table' then
  for i = 1, #t do
    local v = t[i]
    if type(v) == 'table' and tostring(v.名称 or '') == '抓鬼任务' then
      target = tostring(v.说明 or ''):match('近日有#r/([^#]+)#w/') or ''
      break
    end
  end
end
local un = tp.地图.地图单位
if type(un) ~= 'table' then __out = '' return end
for _, v in pairs(un) do
  if type(v) == 'table' then
    local name = tostring(v.名称 or '')
    local match = false
    if target ~= '' then
      match = (name:find(target, 1, true) ~= nil) or (target:find(name, 1, true) ~= nil)
    else
      local cz = tostring(v.称谓 or '')
      match = (cz == '野鬼') or (name:find('鬼') ~= nil)
    end
    if match and v.标识 then __out = tostring(v.标识) return end
  end
end
__out = ''
"""
    r = _lua_call(gateway, code) or ""
    if r == "BATTLE":
        return False  # 战斗中禁止 CALL（用户反馈战斗内弹提示框）
    gid = r
    if not gid.isdigit():
        return False
    # ★2026-09-03 防重复 CALL：同一目标 8s 冷却，避免多 call 重复弹框
    _now = time.time()
    if gid == _call_guard["gid"] and _now - _call_guard["ts"] < 8.0:
        return True  # 已触发过，本次视为成功（不再发包）
    # ★柔和化：CALL 前加 0.15~0.4s 随机延迟（★09-05 提速 0.2~0.6），避免瞬间机械发包；只发一次
    _sleep(random.uniform(0.15, 0.4))
    _lua_call(gateway, "客户端:发送数据(0,3,6," + gid + ",1)")
    _call_guard["gid"] = gid
    _call_guard["ts"] = _now
    return True


def zhuagui_detect_option(gateway=DEFAULT_GATEWAY, **kw):
    """红字检测定位"送你回地府"文字块。返回 dict 或 None。

    注：红字检测可能误判对话文本中的红字，2026-09-03 后主链路改为
    使用实测固定坐标 opt_x0/opt_y0/opt_x1/opt_y1（116,307,180,320），
    本函数仅保留作辅助/调试用。
    """
    if not _HAS_PIL:
        logger.warning("PIL 不可用，红字检测跳过")
        return None
    hwnd = get_hwnd()
    if not hwnd:
        return None
    img, _, _ = grab_client(hwnd)
    px = img.load()
    W, H = img.size
    rows = {}
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            R, G, B = px[x, y]
            if R > 110 and (R - G) > 55 and (R - B) > 55:
                rows.setdefault(y // 3, []).append(x)
    blocks = []
    cur, last_y = None, -99
    for k in sorted(rows):
        xs = rows[k]
        y = k * 3
        if not (220 <= y <= 520) or len(xs) < 8:
            continue
        x0, x1 = min(xs), max(xs)
        if cur and (y - last_y) <= 10 and x0 <= cur["x1"] and x1 >= cur["x0"] - 5:
            cur["y1"] = max(cur["y1"], y)
            cur["x0"] = min(cur["x0"], x0)
            cur["x1"] = max(cur["x1"], x1)
            cur["n"] += len(xs)
        else:
            if cur and cur["n"] >= 25:
                blocks.append(cur)
            cur = {"y0": y, "y1": y, "x0": x0, "x1": x1, "n": len(xs)}
        last_y = y
    if cur and cur["n"] >= 25:
        blocks.append(cur)
    if not blocks:
        return None
    return sorted(blocks, key=lambda b: (b["y0"], b["x0"]))[0]


def zhuagui_click_option(gateway=DEFAULT_GATEWAY, tries: int = 1, hwnd=None,
                         opt_x0=116, opt_y0=307, opt_x1=180, opt_y1=320, **kw):
    """在"送你回地府"文字块内随机偏移后台点击（默认只点一次）。

    Args:
        opt_x0/opt_y0/opt_x1/opt_y1: "送你回地府"文字块（游戏客户区坐标）。
          ★ 2026-09-03 实测：x[116,180] y[307,320]（宽64 高13），
            对话框位置固定时无需再红字检测（红字检测易误判对话文本红字）。
        tries: 点击次数（默认1次，防止重复触发）。
        hwnd: 目标窗口句柄（多开/批量时精确指定；缺省按进程名取第一个）。

    Returns:
        bool: 是否已发出点击。
    """
    if hwnd is None:
        hwnd = get_hwnd()
    if not hwnd:
        return False
    for _ in range(max(1, int(tries))):
        cx = opt_x0 + random.randint(3, max(1, opt_x1 - opt_x0 - 3))
        cy = opt_y0 + random.randint(2, max(1, opt_y1 - opt_y0 - 2))
        post_click(hwnd, cx, cy, gateway=gateway)
        # 柔和化：点击间隔随机化（★09-05 提速 0.5~0.9 → 0.3~0.6）
        time.sleep(random.uniform(0.3, 0.6))
    return True


def _option_visible(hwnd, opt_x0=116, opt_y0=307, opt_x1=180, opt_y1=320, min_red=40):
    """红字检测确认"送你回地府"选项块已弹出（对话框真实打开）。

    ★2026-09-03 用于 enter_battle：CALL 后先确认选项出现再点击，
    避免对话框未弹出就点选项导致点空（曾造成隔轮成交/天眼翻倍消耗）。
    无 PIL 时返回 True（直接点击兜底）。
    """
    if not _HAS_PIL:
        return True
    # ★2026-09-04 黑屏盲模式：截图全黑，红字检测恒失败，
    #   直接视为选项已弹出（点击用固定坐标，成败靠 Lua 任务栏验证）。
    if _blind_mode(hwnd):
        return True
    try:
        img, _, _ = grab_client(hwnd)
        px = img.load()
        n = 0
        for y in range(opt_y0, opt_y1 + 1):
            for x in range(opt_x0, opt_x1 + 1):
                R, G, B = px[x, y]
                if R > 110 and (R - G) > 55 and (R - B) > 55:
                    n += 1
        return n > min_red
    except Exception:
        return True


def zhuagui_in_battle(gateway=DEFAULT_GATEWAY, **kw):
    """是否已进入战斗（可靠判据）。

    ★2026-09-03 修复：旧判据读 `tp.战斗中` 本服恒为 nil（永远 False）；
      而 `tp.战斗类.背景显示=true` 在脱战后会**残留**（垃圾数据），不能单独使用。
      可靠判据：`tp.战斗类.参战单位` 存在且含单位表 且 敌方数量>0。
      实测脱战后 参战单位 为空表/nil → False。
    """
    r = _lua_call(gateway, r"""
local b = tp.战斗类
if type(b) ~= 'table' then __out = 'false' return end
local u = b.参战单位
if type(u) ~= 'table' then __out = 'false' return end
local n = 0
for _ in pairs(u) do n = n + 1 end
if n > 0 and tonumber(b.敌方数量 or 0) > 0 then __out = 'true' else __out = 'false' end
""")
    return r == "true"


def _mouse_clear(hwnd, gateway=None, x=415, y=160):
    """把引擎鼠标（游戏内光标）移到场景空白处，避免光标常驻背包/物品上。

    ★2026-09-03 修复：PostMessage 点击的终点即引擎光标位置。脚本循环里最后
      右键天眼(232,354) / 合成旗(186,302) 等都在背包面板内 → 光标一直停在
      背包上、物品 tooltip 常显（遮挡后续点击，视觉上"鼠标停留在背包"）。
      在"使用道具后"和"每轮结束后"调用本函数把光标移出界面，杜绝 tooltip。
    """
    try:
        _move_traj(hwnd, _last_mouse[0], _last_mouse[1], x, y)
        _last_mouse[:] = [x, y]
        _last_mouse_ts[0] = time.time()
    except Exception:
        pass


def zhuagui_enter_battle(gateway=DEFAULT_GATEWAY, wait_dialog=1.2, timeout=20.0, verbose=False,
                         tries=1, hwnd=None,
                         opt_x0=116, opt_y0=307, opt_x1=180, opt_y1=320, **kw):
    """一键进战：CALL 触发野鬼对话 → 点"送你回地府"一次 → 验证进战。

    链路（2026-09-03 实测成功）:
      1) CALL ``客户端:发送数据(0,3,6,标识,1)`` 打开野鬼对话框
         （等效于真实点击野鬼，绕开地图边界/精灵像素换算问题）
      2) 在"送你回地府"(116,307,180,320) 内随机偏移后台点击一次
      3) 轮询任务栏变化确认完成

    ★2026-09-03 判据修复：
      本版本点"送你回地府" = 直接秒杀 + 发放奖励，不会进入战斗场景。
      成功判据为任务栏"次数递增 或 清空"。但实测任务清空有 8~15s 延迟
      （点击后奖励结算动画结束后才更新任务栏），故 timeout 默认加大到 20s。

    Args:
        hwnd: 目标窗口句柄（多开/批量时精确指定；缺省按进程名取第一个）。

    Returns:
        (bool, str): (是否进战, 信息)
    """
    if hwnd is None:
        hwnd = get_hwnd()
    if not hwnd:
        return False, "未找到游戏窗口"
    # ★2026-09-05 提速：任务态+战斗态 2 次调用合并为 1 次快照
    snap = _snapshot(gateway)
    try:
        start_cnt = int((snap.get("count") or 0))
    except Exception:
        start_cnt = 0
    # ★2026-09-03 修复：目标怪会随刷新/被队伍击杀从单位列表暂时消失，或
    # 瞬移落点后怪尚未加载。click_ghost 一次找不到时，柔和轮询等待怪出现
    # （最长 ~12s，1.8~2.6s 间隔），出现即 CALL；避免一找不到就判失败。
    # ★2026-09-03 追加：轮询期间若已进战斗，立即停止 CALL（战斗中不许 CALL 目标）。
    ok_call = False
    if not snap["battle"]:
        ok_call = zhuagui_click_ghost(gateway)
        if not ok_call:
            if verbose:
                logger.info("目标怪暂未出现在单位列表，轮询等待刷新...")
            t_wait0 = 0.0
            while (not ok_call) and t_wait0 < 12.0:
                if zhuagui_in_battle(gateway):
                    ok_call = False
                    break
                time.sleep(random.uniform(1.5, 2.1))
                t_wait0 += 2.2
                ok_call = zhuagui_click_ghost(gateway)
    if not ok_call:
        if zhuagui_in_battle(gateway):
            # ★战斗中不 CALL：战斗本身已是出发点，直接走完成判定（结算后任务栏更新）
            logger.info("战斗中跳过 CALL 目标，直接等待抓鬼完成...")
            return _wait_task_done(gateway, start_cnt, timeout, verbose)
        return False, "无野鬼目标（先用天眼瞬移）"
    if verbose:
        logger.info("已CALL触发野鬼对话，等待对话框...")
    # ★2026-09-03 修复：CALL 后先轮询确认"送你回地府"选项出现再点击，
    # 避免对话框未弹出就点选项导致点空（曾造成隔轮成交/天眼翻倍消耗）。
    # 柔性重试：未出现则等 0.3~0.6s 后重 CALL 一次（最多2次）。
    # ★2026-09-04 黑屏盲模式：无红字检测，CALL 后固定等待对话弹出再点选项。
    if _blind_mode(hwnd):
        # ★2026-09-05 提速：CALL 到对话框弹出实测 <1s，等待 1.0~1.7 → 0.7~1.2
        time.sleep(random.uniform(0.7, 1.2))
        ok_dlg = True
        t_wait = 0.0
    else:
        ok_dlg = _option_visible(hwnd, opt_x0, opt_y0, opt_x1, opt_y1)
        t_wait = 0.0
        while not ok_dlg and t_wait < max(2.0, float(wait_dialog)):
            time.sleep(random.uniform(0.5, 0.7))
            t_wait += 0.6
            ok_dlg = _option_visible(hwnd, opt_x0, opt_y0, opt_x1, opt_y1)
        if not ok_dlg:
            # 重 CALL 一次（柔和间隔），再等待确认
            time.sleep(random.uniform(0.3, 0.6))
            if zhuagui_click_ghost(gateway):
                t_wait2 = 0.0
                while not ok_dlg and t_wait2 < 3.0:
                    time.sleep(random.uniform(0.5, 0.7))
                    t_wait2 += 0.6
                    ok_dlg = _option_visible(hwnd, opt_x0, opt_y0, opt_x1, opt_y1)
    if not ok_dlg:
        # 对话框仍未弹出（目标怪可能已在单位列表消失），本轮放弃，走失败容错
        logger.warning("CALL后'送你回地府'选项未出现（对话框未弹出）")
        return False, "对话框未弹出（CALL未生效）"
    if verbose:
        logger.info("对话框已弹出，点击'送你回地府'...")
    zhuagui_click_option(gateway, tries=tries, hwnd=hwnd,
                         opt_x0=opt_x0, opt_y0=opt_y0, opt_x1=opt_x1, opt_y1=opt_y1)
    # ★2026-09-03 追加：点选项后光标移到场景空白（选项在对话框内，悬停会拦截后续点击）
    _mouse_clear(hwnd, gateway)
    return _wait_task_done(gateway, start_cnt, timeout, verbose)


def _wait_task_done(gateway, start_cnt, timeout, verbose=False):
    """点击'送你回地府'后轮询任务栏直到完成（次数递增/清空），带超时与复查。

    ★2026-09-03 提取公共完成判定：点'送你回地府'=秒杀发奖（本服），但任务栏
      更新有 8~15s 延迟；战斗中（CALL 后直接进战斗的罕见分支）也可调用本函数，
      战斗结算后任务栏同样会更新。成功判据=次数递增 或 任务栏清空。
    """
    if verbose:
        logger.info("已点击'送你回地府'，检测抓鬼完成...")
    t0 = time.time()
    while time.time() - t0 < float(timeout):
        cur = zhuagui_get_task(gateway) or {}
        try:
            cur_cnt = int((cur or {}).get("count") or 0)
        except Exception:
            cur_cnt = -1
        # 抓鬼完成的两种标志：次数递增（进入下一只）或任务栏清空（本只完成）
        if cur_cnt and cur_cnt != start_cnt:
            # ★任务变动（进入下一只）→ 刷新取消冷却时间戳
            _LAST_ROUND_STAGES["wait_task_done"] = round(time.time() - t0, 2)
            _task_ts_set(gateway)
            return True, "抓鬼完成"
        if start_cnt > 0 and not (cur or {}).get("count"):
            # ★任务栏清空（本只完成）→ 刷新时间戳（下一只需要重新接/再瞬移）
            _LAST_ROUND_STAGES["wait_task_done"] = round(time.time() - t0, 2)
            _task_ts_set(gateway)
            return True, "抓鬼完成(任务栏已清空)"
        # 柔和化：轮询间隔随机抖动，避免固定频率探测（★09-05 提速 0.6~1.0 → 0.4~0.7）
        time.sleep(random.uniform(0.4, 0.7))
    # ★2026-09-03 超时后最终复查：任务栏可能刚更新（延迟清空/递增）。
    #   实测本服"第N次递增"只在回长安重接钟馗任务时才体现，点'送你回地府'
    #   后任务栏并不会立即变化，故这里只做一次复查，不额外拖长轮次。
    cur = zhuagui_get_task(gateway) or {}
    try:
        cur_cnt = int((cur or {}).get("count") or 0)
    except Exception:
        cur_cnt = -1
    if cur_cnt and cur_cnt != start_cnt:
        _task_ts_set(gateway)
        return True, "抓鬼完成(复查,次数递增)"
    if start_cnt > 0 and not (cur or {}).get("count"):
        _task_ts_set(gateway)
        return True, "抓鬼完成(复查,任务栏已清空)"
    return False, "超时未完成"


# ============================================================
# ★2026-09-03 人物列表批量抓鬼（GUI 组配置 window.roles 驱动）
# ============================================================
import re as _re
import glob as _glob
import os as _os


def _roles_from_groups():
    """聚合 GUI 各组的人物列表: [(角色名, 组号), ...]，按组序去重。"""
    res = []
    try:
        from core.group_config import CONFIG_DIR
    except Exception:
        try:
            CONFIG_DIR = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "config")
        except Exception:
            return res
    for g in sorted(_glob.glob(_os.path.join(CONFIG_DIR, "group*", "settings.json"))):
        try:
            gn = int(_os.path.basename(_os.path.dirname(g)).replace("group", ""))
        except Exception:
            continue
        try:
            with open(g, encoding="utf-8") as f:
                cfg = json.load(f)
            rs = ((cfg.get("window") or {}).get("roles")) or []
            for r in rs:
                if r and (r, gn) not in res:
                    res.append((r, gn))
        except Exception:
            continue
    return res


def _role_from_title(title):
    """从窗口标题提取角色名：'胖子西游- (二号美人[412646]) ...' → 二号美人。"""
    m = _re.search(r"[（(]([^()\[\]]+?)\[", title or "")
    return m.group(1).strip() if m else ""


def _role_group_map():
    return dict(_roles_from_groups())


def _find_role_window(role):
    """按角色名在已开游戏窗口中匹配，返回 (pid, hwnd) 或 None（多开/单开均可）。"""
    try:
        from core.window_manager import window_manager
        wins = window_manager.list_game_windows()
    except Exception:
        return None
    for hwnd, title, pid, _visible in (wins or []):
        if _role_from_title(title) == role:
            if pid:
                return (pid, hwnd)
    return None


def zhuagui_loop(gateway=None, roles=None, rounds=1, member_mode=False,
                 wait_dialog=1.2, timeout=20.0, max_retry=3, verbose=False, **kw):
    """按 GUI 人物列表批量抓鬼。

    流程（2026-09-03）:
      1) 角色列表 = 当前组 config/group<N>/settings.json 的 window.roles
         （默认只处理当前组人物，不遍历其它组；显式传 roles 可覆盖）
      2) 每个角色：按角色名从已开窗口匹配 (pid, hwnd)
      3) 切到该角色所在组 → ensure_gateway 换绑网关（优雅 detach 防闪退）
      4) 连做 rounds 轮 zhuagui_do_round（CALL目标→点"送你回地府"→等完成）
      5) ★2026-09-03 容错：某轮失败（找不到目标/瞬移错位等"类似问题"）
         自动在钟馗处取消当前任务并重新接（zhuagui_retake_task），
         再重试该轮，直至成功或耗尽 max_retry 次（"直接取消任务重新接任务循环"）。
      6) ★2026-09-03 组员模式（member_mode=True）：组员无法接/取消任务
         （提示"队员已有任务"），失败时跳过 cancel/retake（队伍机制拦截），
         仅回长安 + 休息后重试下一轮（由队长侧负责任务接取/取消）。

    Args:
        gateway: 显式网关 URL；缺省按角色所在组端口解析。
        roles: 显式角色名列表（["二号美人","凝宛寄静露"]）；缺省=当前组 roles。
        rounds: 每个角色连做几轮抓鬼（默认1）。
        member_mode: 组员模式（队伍中非队长）。默认 False（队长/单开流程）。
        max_retry: 单轮失败后重试的最大次数（默认3）。

    Returns:
        dict: {角色名: {"组":N, "窗口":bool, "网关":bool, "轮次":[bool,...], "说明":str}}
    """
    groups = _role_group_map()
    if roles is None:
        # 默认只启动当前组的人物（用户需求：只需要启动一个角色→当前组=二号美人）
        try:
            from core.group_config import current_group
            _g = int(current_group())
        except Exception:
            _g = 1
        roles = [r for r, gg in _roles_from_groups() if gg == _g]
    elif isinstance(roles, str):
        roles = [r.strip() for r in roles.split(",") if r.strip()]

    def _gw_for(group):
        try:
            from core.group_config import gateway_url
            return gateway_url(group)
        except Exception:
            return "http://127.0.0.1:%d" % (18082 if group <= 1 else 18080 + group)

    results = {}
    for role in roles:
        r_entry = {"组": groups.get(role, 1), "窗口": False, "网关": False,
                   "轮次": [], "说明": ""}
        results[role] = r_entry
        pw = _find_role_window(role)
        if pw is None:
            r_entry["说明"] = "未找到该角色的游戏窗口（多开器需先开号）"
            continue
        pid, hwnd = pw
        r_entry["窗口"] = True
        group = groups.get(role, 1)
        gw = gateway or _gw_for(group)
        if verbose:
            logger.info("人物列表抓鬼: 角色=%s 组=%d pid=%d hwnd=%d gw=%s 组员模式=%s"
                        % (role, group, pid, hwnd, gw, member_mode))
        # 切组 + 换绑网关（优雅 detach 旧会话，防游戏闪退）
        from core.gateway_guard import ensure_gateway
        _old = _os.environ.get("MHXY_GROUP")
        _os.environ["MHXY_GROUP"] = str(group)
        try:
            ok, info = ensure_gateway(pid=pid, timeout=60.0)
        finally:
            if _old is None:
                _os.environ.pop("MHXY_GROUP", None)
            else:
                _os.environ["MHXY_GROUP"] = _old
        r_entry["网关"] = bool(ok)
        if not ok:
            r_entry["说明"] = "网关换绑失败: %s" % (info,)
            continue
        for _rnd in range(max(1, int(rounds))):
            ok_b, msg_b = False, "未执行"
            n_retry = 0
            while True:
                ok_b, msg_b = zhuagui_do_round(gateway=gw, wait_dialog=wait_dialog,
                                               timeout=timeout, verbose=verbose,
                                               member_mode=member_mode)
                if ok_b:
                    break
                # ★2026-09-03 失败容错（组队机制限制，无取消可用）：
                #   - 队伍里若有队员挂任务，队长接不了新任务（游戏机制无法取消队员任务）；
                #   - 因此"取消任务重新接任务"在组队自动化中不可用，一律改为
                #     "回长安 + 休息后重试"（等队员自行清理 或 任务自然流转）。
                if n_retry >= max(0, int(max_retry)):
                    break
                n_retry += 1
                if verbose:
                    logger.info("  角色=%s 第%d轮失败(%s)，回长安休息后重试(%d/%d)"
                                % (role, _rnd + 1, msg_b, n_retry, max_retry))
                try:
                    zhuagui_go_back_changan(gateway=gw)
                except Exception as e:
                    if verbose:
                        logger.warning("  回长安异常: %s", e)
                # 休息拉长（接不上可能因队员挂任务，需等对方清理/任务流转）
                time.sleep(random.uniform(4.0, 8.0))
            r_entry["轮次"].append(ok_b)
            if verbose:
                logger.info("  角色=%s 第%d轮 -> %s %s" % (role, _rnd + 1, ok_b, msg_b))
            # 柔和化：轮间随机停顿，避免连续机械操作
            time.sleep(random.uniform(2.0, 4.0))
        r_entry["说明"] = "完成"
    return results


# 主函数别名（GUI 任务引擎按函数名调用）
def main(**kw):
    """GUI 入口：一键进战。args 可加 tries/wait_dialog/timeout/verbose。"""
    verbose = bool(kw.get("verbose", False))
    ok, msg = zhuagui_enter_battle(verbose=verbose, **kw)
    if verbose or not ok:
        logger.info(f"ZGUI 结果: {ok} {msg}")
    return ok


if __name__ == "__main__":
    print("hwnd:", get_hwnd())
    print("任务:", zhuagui_get_task())
    print("野鬼:", zhuagui_find_ghost())
    print("战斗中:", zhuagui_in_battle())