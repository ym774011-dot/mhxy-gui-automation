# -*- coding: utf-8 -*-
"""
定时重新登录游戏窗口（2026-09-01 新增）。

核心流程（全程后台操作，不抢前台焦点）：
    0. ★2026-09-01 用户定案：杀进程前必须先让角色进入战斗（战斗中角色
       掉线 → 队伍 1 分钟内不解散）。自动找最近怪柔和 CALL 进战斗；
       场景无怪则轮询等待有怪（如 10:00 无怪 → 等到 10:01 有怪拉战才继续）；
       等待超时则放弃本轮重登（等下轮定时）。
    1. 记录当前绑定 PID（window_manager.pid）与角色 ID 锚点
    2. 停止任务（GUI 层处理，本模块不碰 task_engine）
    3. 杀掉旧游戏进程（taskkill /T，只杀绑定 PID，不动多开器本体）
    4. 启动客户端 exe（Popen，直接在启动时拿到新 PID）
    5. 轮询按 PID 找窗口并绑定（多开器结构下自动选面积最大主窗口）
    6. 等登录界面加载（窗口出现后再给固定预载时间）
    7. 按可配置坐标序列后台 PostMessage 左键点击登录（客户区坐标按窗口尺寸等比缩放；
       点击间隔压缩，整体目标从进入战斗起 1 分钟内完成，防止组队解散）
    8. 进入游戏后右键一次关闭残留弹窗
    9. ensure_gateway 重新 attach 新游戏 PID（旧 session 随旧进程死亡，杀僵尸网关
       重新 attach 新进程 —— 项目既有安全路径）

依赖：window_manager（绑定）、gateway_guard（重连）、pywin32/psutil（进程操作）。
铁律：所有鼠标操作一律后台 PostMessage（WM_MOUSEMOVE/DOWN/UP），禁止前台输入。
"""

import ctypes
import json
import os
import subprocess
import time
import urllib.request

import win32gui
import win32process

from utils.logger import logger

# 默认登录点击坐标序列（客户区坐标，1000×600 基准），用户实测提供：
#   1 下一步(登录向导)  2 登录  3 下一步(角色选择向导)  4 选择角色  5 进入游戏
DEFAULT_CLICK_POINTS = [
    (701, 550),   # 下一步（推荐/向导第一页）
    (507, 420),   # 登录
    (705, 549),   # 下一步（向导第二页）
    (635, 284),   # 选择角色
    (699, 571),   # 进入游戏
]

# 登录点击坐标基准分辨率：用户实测坐标为 800×600 客户区坐标（2026-09-01 截图实锤：
# 登录窗口 800×600，「下一步」按钮在右侧 x≈700, y≈550 —— 与用户提供的 701,550 精确吻合）。
# 窗口以其他尺寸启动时按此基准等比缩放（如 1000×600 → 1.25×）。
BASE_CLIENT_SIZE = (800, 600)

# 流程超时（秒）
KILL_WAIT_MAX = 15      # 等旧进程退出的最长时长
WINDOW_WAIT_MAX = 90    # 等新窗口出现的轮询上限
LOGIN_PRELOAD = 2.5     # 窗口出现后、点击前的登录界面预载等待
# 战斗保护前置（2026-09-01 用户定案）：没进战斗不杀进程
BATTLE_ENTER_WAIT_MAX = 300  # 等角色进入战斗的最长时长（无怪时轮询）
BATTLE_SCAN_GAP = 5.0        # 场景无怪时的重扫间隔
BATTLE_DLG_GAP = 2.0         # CALL 后等对话装载的柔和间隔（对齐 farm 柔和 CALL）

# 已知纯传送/功能 NPC 关键词（CALL 只会弹传送/功能对话，不含战斗动作词，直接跳过）
_NPC_SKIP_KW = ("驿站", "车夫", "船夫", "仓库", "师门", "门派", "传送",
                "守卫", "商店", "商人", "老板", "掌柜", "店小二")
# 对话选项中的战斗动作词（对齐 farm _call_and_fight 的 soft 词表）
_BATTLE_ACTION_WORDS = ("杀", "灭", "打", "战", "应战", "教训", "领教",
                        "收拾", "降服", "制服", "消毒", "口罩")
# CALL 距离阈值：超过此格数需先瞬移贴近（对齐 farm CALL_SKIP_DIST=15）
CALL_SKIP_DIST_MAX = 15.0


def _gw_url() -> str:
    """当前组网关地址（与任务库同源）。"""
    try:
        from core.group_config import gateway_url
        return gateway_url()
    except Exception:
        return "http://127.0.0.1:18082"


def _http_json(path: str, data: dict = None, timeout: float = 6.0) -> dict:
    """POST JSON 到网关。"""
    gw = _gw_url()
    try:
        body = json.dumps(data).encode() if data is not None else b"{}"
        req = urllib.request.Request(
            gw + path, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _lua(code: str, result_var: str = "__out") -> str:
    """经网关执行 Lua 语句块，返回 result_var 值字符串。"""
    r = _http_json("/api/lua", {"code": code, "result_var": result_var})
    try:
        return str(r.get("result", {}).get("value") or "")
    except Exception:
        return ""


def _lua_expr(expr: str) -> str:
    """经网关执行单个表达式。"""
    r = _http_json("/api/lua/expr", {"expr": expr})
    try:
        return str(r.get("result", {}).get("value") or "")
    except Exception:
        return ""


def _in_battle() -> bool:
    """角色当前是否在战斗中。"""
    try:
        return _lua_expr("tostring(tp.战斗中 or false)") == "true"
    except Exception:
        return False


def _role_grid():
    """读角色网格坐标（内部坐标 ÷20）。失败返回 None。"""
    try:
        v = _lua_expr('tostring(tp.角色坐标.x)..","..tostring(tp.角色坐标.y)')
        xs, ys = v.split(",", 1)
        return float(xs) / 20.0, float(ys) / 20.0
    except Exception:
        return None


def _grid_dist(rg, gx: float, gy: float) -> float:
    if rg is None:
        return 999.0
    return ((rg[0] - gx) ** 2 + (rg[1] - gy) ** 2) ** 0.5


def _gw_teleport(x: int, y: int) -> dict:
    """瞬移到地图网格坐标 (x,y)（对齐 farm，网关 ×20 发内部坐标 + 1002 同步）。"""
    return _http_json("/api/act/teleport",
                      {"x": int(x), "y": int(y), "sync": True, "jump": True},
                      timeout=15.0)


def _lua_str_list(items) -> str:
    """序列化字符串列表为 Lua table 字面量。"""
    def esc(s):
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return "{" + ", ".join(f'"{esc(str(x))}"' for x in items) + "}"


def _dialog_options() -> list:
    """读当前对话栏选项（基本内容|跳转链接|文字）。"""
    code = r'''
local out = {}
local opts = (tp.窗口.对话栏 or {}).选项
if opts then
  for i = 1, 20 do
    local o = opts[i]
    if type(o) ~= "table" then break end
    out[#out+1] = string.format("%s|%s|%s",
      tostring(o.基本内容 or ""),
      tostring(o.跳转链接 or ""),
      tostring(o.文字 or o.标签 or ""))
  end
end
_G.__out = table.concat(out, "\n")
'''
    raw = _lua(code)
    opts = []
    for line in (raw or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) >= 2:
            opts.append({"text": parts[0], "link": parts[1],
                         "label": parts[2] if len(parts) > 2 else ""})
    return opts


def _find_nearest_foe():
    """
    扫描场景找最近的"可攻击"实体（排除纯传送/功能 NPC 关键词）。

    :return: {"id": uid, "bsid": bsid, "name": name, "gx": gx, "gy": gy}
             或 None（场景无可用目标）
    """
    skip_lit = _lua_str_list(_NPC_SKIP_KW)
    code = f'''
collectgarbage("collect", 0)
local skip = {skip_lit}
local function is_skip(name)
  for _, w in ipairs(skip) do
    if w ~= "" and string.find(name, w, 1, true) then return true end
  end
  return false
end
local best, best_d = nil, 1e18
local px = tonumber(tp.角色坐标.x) or 0
local py = tonumber(tp.角色坐标.y) or 0
local function scan(tbl)
  if type(tbl) ~= "table" then return end
  for id, u in pairs(tbl) do
    if type(u) == "table" then
      local name = tostring(u.名称 or u.名字 or "")
      if name ~= "" and not is_skip(name) then
        local mt = getmetatable(u)
        local ev = (mt and mt.__index and mt.__index.事件开始) or u["事件开始"]
        if type(ev) == "function" then
          local gx = tonumber(u.格子x) or ((tonumber(u.x) or 0) / 20)
          local gy = tonumber(u.格子y) or ((tonumber(u.y) or 0) / 20)
          local d = math.abs((gx or 0) - px) + math.abs((gy or 0) - py)
          if d < best_d then
            best_d = d
            best = string.format("%s|%s|%s|%s|%s",
              tostring(id), tostring(u.标识 or ""), name, gx, gy)
          end
        end
      end
    end
  end
end
scan(tp.场景.场景人物)
scan(tp.临时Npc)
_G.__out = best or ""
'''
    raw = _lua(code)
    if not raw:
        return None
    parts = raw.split("|")
    if len(parts) < 3:
        return None
    return {"id": parts[0], "bsid": parts[1], "name": parts[2],
            "gx": parts[3], "gy": parts[4]}


def _call_foe(uid: str, bsid: str) -> str:
    """柔和 CALL 指定实体的事件开始（不读对话，第二步由 _click_battle 处理）。"""
    bsid_lit = (bsid or "").replace('"', "")
    code = f'''
local u = nil
if "{bsid_lit}" ~= "" then
  local pools = {{tp.场景.场景人物, tp.临时Npc}}
  for _, t in ipairs(pools) do
    if type(t) == "table" then
      for _, e in pairs(t) do
        if type(e) == "table" and tostring(e.标识 or "") == "{bsid_lit}" then u = e; break end
      end
      if u then break end
    end
  end
end
if not u then
  local n = tonumber("{uid}")
  local t = tp.场景.场景人物 or {{}}
  if n then u = t[n] end
  if not u then u = t["{uid}"] or (tp.临时Npc or {{}})["{uid}"] end
end
if not u or type(u) ~= "table" then _G.__out = "gone"; return end
local mt = getmetatable(u)
local ev = (mt and mt.__index and mt.__index.事件开始) or u["事件开始"]
if type(ev) ~= "function" then _G.__out = "nofn"; return end
pcall(function() return ev(u) end)
_G.__out = "called"
'''
    return _lua(code)


def _click_battle_option() -> str:
    """对话栏选项中匹配战斗动作词并事件解析（原子 chunk，无崩溃间隙）。

    :return: "clicked"|"nodlg"|"miss"|"gone"
    """
    kws = _lua_str_list(_BATTLE_ACTION_WORDS)
    code = f'''
local kws = {kws}
local dlg = tp.窗口.对话栏
if not (dlg and dlg.可视) then _G.__out = "nodlg"; return end
local opts = dlg.选项
local function opt_text(o)
  return tostring(o.基本内容 or "") .. "|" .. tostring(o.文字 or o.标签 or "") .. "|" .. tostring(o.跳转链接 or "")
end
local hit_i = nil
for i = 1, 20 do
  local o = opts[i]
  if type(o) ~= "table" then break end
  local text = opt_text(o)
  if tostring(o.跳转链接 or "") ~= "" then
    for _, w in ipairs(kws) do
      if string.find(text, w, 1, true) then hit_i = i; break end
    end
  end
  if hit_i then break end
end
if not hit_i then _G.__out = "miss"; return end
local link = tostring(opts[hit_i].跳转链接 or "")
if link == "" then _G.__out = "miss"; return end
local okr, ret = pcall(function() return dlg:事件解析(link) end)
_G.__out = (okr and "clicked" or "miss")
'''
    return _lua(code)


def _enter_battle_once(verbose=True) -> bool:
    """
    尝试拉一次战斗：找最近怪 →（过远则瞬移贴近）→ 柔和 CALL → 点战斗选项 → 等战斗态。

    ★2026-09-01 实机发现：角色距目标 70 格时远程 CALL 无反应（farm 同理，
    CALL 要求 ≤15 格）。先对齐 farm 兜底链路：目标过远 → 瞬移到目标周边
    （3~8 格环带，不重叠）→ 落地稳定 0.9s →
    再重新扫描 + 柔和 CALL 进战斗。

    :return: True=已进入战斗 / False=失败（无怪或对话无战斗选项）
    """
    foe = _find_nearest_foe()
    if not foe:
        if verbose:
            print("[重登] 场景暂无可用攻击目标，等待下一轮扫描", flush=True)
        return False

    # ---- 0. 距角色过远 → 瞬移到目标周边环带（对齐 farm 环带兜底） ----
    try:
        import random
        rg = _role_grid()
        _d = _grid_dist(rg, float(foe["gx"]), float(foe["gy"])) if rg else 999.0
    except Exception:
        _d = 999.0
    if _d > CALL_SKIP_DIST_MAX:   # 超过可 CALL 距离才瞬移
        if verbose:
            print(f"[重登] 距目标 {_d:.0f} 格（>{CALL_SKIP_DIST_MAX:.0f}），"
                  f"先瞬移贴近再 CALL", flush=True)
        _moved = _teleport_near_foe(foe, verbose)
        # 瞬移后重取目标（怪可能因落地刷新/远离）
        if _moved:
            time.sleep(0.9)   # 瞬移落地稳定窗（对齐 farm）
            foe = _find_nearest_foe() or foe
            if verbose:
                print(f"[重登] 瞬移后最近目标: {foe['name']}"
                      f"({foe['gx']},{foe['gy']})", flush=True)

    # 第一步：CALL（只发起事件，不读对话）
    st = _call_foe(str(foe["id"]), str(foe["bsid"] or ""))
    if verbose:
        print(f"[重登] CALL 最近目标 {foe['name']}({foe['gx']},{foe['gy']}) → {st}",
              flush=True)
    if st == "gone":
        # CALL 后目标消失（落地瞬移导致旧槽位失效）→ 重新扫描一次再试
        foe = _find_nearest_foe()
        if not foe:
            return False
        st = _call_foe(str(foe["id"]), str(foe["bsid"] or ""))
        if verbose:
            print(f"[重登] 重试 CALL 新目标 {foe['name']} → {st}", flush=True)
    if st == "gone":
        return False
    if _in_battle():   # CALL 期间直接进入战斗（罕见但存在）
        return True

    # 柔和间隔：等引擎装载对话脚本（对齐 farm 柔和 CALL，防崩）
    time.sleep(BATTLE_DLG_GAP)

    # 轮询等待对话栏弹出（对齐 farm _wait_dialog_ready：从 CALL 到对话可读
    # 有装载窗口，2s 睡完偶有未就绪，最多再补 3s 轮询）
    t0 = time.time()
    while True:
        if _in_battle():
            return True
        opts = _dialog_options()
        if opts:
            break
        if time.time() - t0 > BATTLE_DLG_GAP + 3.0:
            if verbose:
                print("[重登] 对话栏未弹出，放弃本轮尝试", flush=True)
            return False
        time.sleep(0.5)

    # 第二步：读对话 + 点战斗选项
    st2 = _click_battle_option()
    if verbose:
        print(f"[重登] 战斗选项点击 → {st2}", flush=True)
    if st2 == "clicked":
        # 等战斗态确认（柔和：进入战斗通常 1~2s 内）
        t0 = time.time()
        while time.time() - t0 < 6.0:
            if _in_battle():
                return True
            time.sleep(0.5)
    return False


def _teleport_near_foe(foe: dict, verbose=True) -> bool:
    """
    瞬移到目标周边环带（3~8 格随机角度，不重叠目标；对齐 farm 环带兜底）。
    返回是否成功发起瞬移。
    """
    import random
    import math
    fx = max(0, int(round(float(foe["gx"]))))
    fy = max(0, int(round(float(foe["gy"]))))
    ang = random.uniform(0.0, math.tau)
    d = random.uniform(3.0, 8.0)
    if math.hypot(math.cos(ang), math.sin(ang)) * d < 2.0:
        ang += 0.7
    tx = max(0, int(round(fx + math.cos(ang) * d)))
    ty = max(0, int(round(fy + math.sin(ang) * d)))
    if verbose:
        print(f"[重登] → 瞬移到目标周边 ({tx},{ty})（距目标≈{d:.1f}格）", flush=True)
    try:
        r = _gw_teleport(tx, ty)
        return bool(r and r.get("ok", r.get("success", True)))
    except Exception as e:
        if verbose:
            print(f"[重登] 瞬移失败: {e}", flush=True)
        return False


def _ensure_in_battle(wait_max: float = None, verbose=True) -> bool:
    """
    重登前置：确保角色进入战斗（队伍保护）。
      - 已在战斗中 → 立即返回 True
      - 不在 → 反复「找最近怪 CALL 进战斗」，无怪则每 BATTLE_SCAN_GAP 重扫
      - wait_max 内仍无法进战斗 → False（放弃本轮重登，等下轮定时）
    """
    wait_max = wait_max if wait_max is not None else BATTLE_ENTER_WAIT_MAX
    t0 = time.time()
    while True:
        if _in_battle():
            if verbose:
                print("[重登] 已在战斗中，直接进入杀进程重启", flush=True)
            return True
        if verbose:
            print(f"[重登] 尝试拉怪进战斗（剩余 {max(0, wait_max - (time.time() - t0)):.0f}s）",
                  flush=True)
        if _enter_battle_once(verbose):
            return True
        if time.time() - t0 >= wait_max:
            if verbose:
                print(f"[重登] 等待进战斗超时（{wait_max:.0f}s），放弃本轮重登",
                      flush=True)
            return False
        time.sleep(BATTLE_SCAN_GAP)


def _pid_alive(pid: int) -> bool:
    """PID 是否存活（psutil 优先，回退 ctypes）。"""
    if not pid or pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            from ctypes import wintypes
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _kill_pid(pid: int, verbose=True) -> bool:
    """杀掉指定游戏进程（/T 连带子进程）。返回是否成功。"""
    if not pid or pid <= 0 or not _pid_alive(pid):
        if verbose:
            print(f"[重登] 旧进程 PID={pid} 无需杀（不存在或已退出）", flush=True)
        return True
    try:
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True, timeout=KILL_WAIT_MAX)
        ok = r.returncode == 0
        if verbose:
            print(f"[重登] 杀旧进程 PID={pid} → {'成功' if ok else '失败'}: "
                  f"{r.stderr.decode('gbk', 'ignore').strip()[-120:]}", flush=True)
        # 等真正退出
        t0 = time.time()
        while _pid_alive(pid) and time.time() - t0 < KILL_WAIT_MAX:
            time.sleep(0.3)
        return not _pid_alive(pid)
    except Exception as e:
        if verbose:
            print(f"[重登] 杀进程异常: {e}", flush=True)
        return False


def _launch_client(client_path: str, verbose=True):
    """启动客户端 exe。返回 (proc, new_pid)。失败返回 (None, None)。"""
    if not client_path or not os.path.isfile(client_path):
        if verbose:
            print(f"[重登] 客户端路径无效: {client_path!r}", flush=True)
        return None, None
    try:
        proc = subprocess.Popen(
            [client_path],
            cwd=os.path.dirname(client_path) or ".",
            close_fds=True,
        )
        if verbose:
            print(f"[重登] 已启动客户端 {os.path.basename(client_path)} "
                  f"→ PID={proc.pid}", flush=True)
        return proc, int(proc.pid)
    except Exception as e:
        if verbose:
            print(f"[重登] 启动客户端失败: {e}", flush=True)
        return None, None


def _wait_bind_by_pid(new_pid: int, old_pid: int = 0,
                      wait_max: float = WINDOW_WAIT_MAX, verbose=True) -> bool:
    """
    轮询按新 PID 找窗口并绑定（多开器结构下自动选面积最大主窗口）。

    兜底：若 60s 内 new_pid 仍无窗口（Popen 拿到的可能是启动器 PID），
    则用 list_game_windows 枚举，排除 old_pid 后找标题含角色 ID 的新窗口。
    """
    from core.window_manager import WindowManager, _ROLE_ID_RE
    wm = WindowManager()

    t0 = time.time()
    while time.time() - t0 < wait_max:
        if new_pid > 0 and wm.find_by_pid(new_pid):
            if verbose:
                print(f"[重登] 已绑定新窗口 hwnd=0x{wm.hwnd:X} "
                      f"title={wm.window_title!r}", flush=True)
            return True
        time.sleep(0.5)

    # 兜底：按角色 ID 锚点在新进程里找（排除 old_pid）
    try:
        old_title = getattr(wm, "window_title", "") or ""
        m = _ROLE_ID_RE.search(old_title)
        token = f"[{m.group(1)}]" if m else None
        for hwnd, title, pid, visible in WindowManager.list_game_windows():
            if not pid or pid == old_pid:
                continue
            if token and token in (title or ""):
                if wm.find_by_pid(pid):
                    if verbose:
                        print(f"[重登] 兜底按角色锚点绑定: {token} → PID={pid}", flush=True)
                    return True
    except Exception as e:
        if verbose:
            print(f"[重登] 锚点兜底异常: {e}", flush=True)
    return False


def _scale_coords(points, client_size):
    """客户区坐标按窗口实际尺寸等比缩放。基准 1000×600。"""
    w, h = client_size or BASE_CLIENT_SIZE
    if not w or not h:
        return list(points)
    bw, bh = BASE_CLIENT_SIZE
    sx, sy = w / bw, h / bh
    return [(int(x * sx), int(y * sy)) for x, y in points]


def _post_click(hwnd: int, cx: int, cy: int, verbose=True):
    """后台 PostMessage 左键单击客户区坐标（不抢焦点、光标不动）。"""
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
        user32.PostMessageW(hwnd, 0x0200, 0, lp)  # WM_MOUSEMOVE
        time.sleep(0.05)
        user32.PostMessageW(hwnd, 0x0201, 1, lp)  # WM_LBUTTONDOWN
        time.sleep(0.05)
        user32.PostMessageW(hwnd, 0x0202, 0, lp)  # WM_LBUTTONUP
        return True
    except Exception as e:
        if verbose:
            print(f"[重登] 后台点击失败 ({cx},{cy}): {e}", flush=True)
        return False


def _post_rightclick_close(hwnd: int, verbose=True):
    """★2026-09-01 用户定案：进入游戏后后台右键一次关闭残留弹窗。

    对齐 WORLD_BOSS._rightclick_close_center 的成熟链路：后台
    PostMessage（WM_RBUTTONDOWN/UP）右键客户区中心偏上位置（避开底部
    主菜单栏/频道栏），关闭登录后弹出的公告/系统提示等对话框。
    """
    if not hwnd:
        return False
    try:
        import win32gui
        try:
            rect = win32gui.GetClientRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
        except Exception:
            return False
        if not w or not h:
            return False
        cx, cy = int(w / 2), int(h / 12)
        user32 = ctypes.windll.user32
        lp = (cy << 16) | (cx & 0xFFFF)
        user32.PostMessageW(hwnd, 0x0204, 1, lp)  # WM_RBUTTONDOWN
        time.sleep(0.06)
        user32.PostMessageW(hwnd, 0x0205, 0, lp)  # WM_RBUTTONUP
        if verbose:
            print(f"[重登] 已右键画面中心关闭残留弹窗 @ 客户区({cx},{cy})",
                  flush=True)
        return True
    except Exception as e:
        if verbose:
            print(f"[重登] 右键关弹窗失败: {e}", flush=True)
        return False


def _click_login(hwnd: int, points, click_gap: float = 1.5, verbose=True):
    """
    按坐标序列依次后台点击登录。坐标已按窗口缩放。

    ★ 1 分钟内完成的约束：登录点击序列整体耗时 =
       LOGIN_PRELOAD(2.5s) + n × (click_gap + 0.1s)。5 步 × 1.5s ≈ 10.5s，
     加上启动+绑定（约 20~40s），总控制在 60s 内，不会导致组队解散。
    """
    for i, (cx, cy) in enumerate(points, start=1):
        if not win32gui.IsWindow(hwnd):
            if verbose:
                print(f"[重登] 窗口已失效，点击 {i}/{len(points)} 中止", flush=True)
            return False
        _post_click(hwnd, cx, cy, verbose)
        if verbose:
            print(f"[重登] 登录点击 {i}/{len(points)}: ({cx},{cy})", flush=True)
        if i < len(points):
            time.sleep(click_gap)
    return True


def relogin_client(client_path: str, click_points=None, old_pid: int = 0,
                   click_gap: float = 1.2, verbose: bool = True,
                   battle_wait: float = None, skip_battle_guard: bool = False):
    """
    完整重新登录流程（阻塞执行，建议放独立线程）。

    流程（2026-09-01 用户定案：先保护队伍再重启）：
        0. 先进战斗（战斗中掉线队伍 1 分钟内不解散）——
           已在战斗直接通过；不在则自动找最近怪 CALL 进战斗；
           场景无怪每 5s 轮询等有怪（如 10:00 无怪 → 等到 10:01 有怪拉战才继续）；
           battle_wait 秒内仍无法进战斗 → 放弃本轮（等下轮定时）。
           ★2026-09-02 下线自愈场景（skip_battle_guard=True）：角色已被强制
           下线（「下线通知」弹窗），场景无怪，进战斗保护只会白等 300s →
           直接跳过该步杀进程重启。
        1. 杀旧进程 → 2. 启动客户端 → 3. 等窗绑定 → 4. 登录点击
        → 5. 右键关弹窗 → 6. 网关重连

    :param client_path: 客户端 exe 路径（GUI 自定义）
    :param click_points: 登录坐标序列（客户区坐标），None=默认 5 步
    :param old_pid: 旧游戏 PID（None/0=用 window_manager.pid）
    :param click_gap: 相邻点击间隔（秒），默认 1.2s（压缩到 1 分钟内登录）
    :param verbose: 打印进度
    :param battle_wait: 等待进战斗的最长秒数（None=默认 300s）
    :param skip_battle_guard: 跳过进战斗保护前置（下线自愈场景专用，直接重启）
    :return: (ok, message, new_pid)
    """
    from core.window_manager import WindowManager
    wm = WindowManager()
    points = list(click_points) if click_points else list(DEFAULT_CLICK_POINTS)

    # ---- 0. 确定旧 PID ----
    if not old_pid:
        old_pid = getattr(wm, "pid", 0) or 0
    role_label = getattr(wm, "window_title", "") or ""
    if verbose:
        print(f"[重登] 开始重新登录流程: 旧PID={old_pid} "
              f"title={role_label[:40]!r}...", flush=True)

    # ---- 0.5 ★用户定案：先进战斗保护队伍（战斗中断线 → 队伍 1 分钟不解散）----
    if skip_battle_guard:
        if verbose:
            print("[重登] 跳过战斗保护（下线自愈场景：角色已掉线，直接杀进程重启）",
                  flush=True)
    elif old_pid and _pid_alive(old_pid):
        if _in_battle():
            if verbose:
                print("[重登] 已在战斗中，直接开始重启", flush=True)
        else:
            if verbose:
                print("[重登] 未在战斗中：先拉怪进战斗保护队伍，再杀进程", flush=True)
            ok_battle = _ensure_in_battle(wait_max=battle_wait, verbose=verbose)
            if not ok_battle:
                return False, "等待进入战斗超时（场景持续无怪），放弃本轮重登", old_pid
    else:
        if verbose:
            print("[重登] 旧进程已不在运行，跳过战斗保护前置", flush=True)

    # ---- 1. 杀旧进程 ----
    if not _kill_pid(old_pid, verbose):
        if verbose:
            print("[重登] 旧进程未退出，继续尝试（不阻断）", flush=True)

    # ---- 2. 启动客户端 ----
    proc, new_pid = _launch_client(client_path, verbose)
    if new_pid is None:
        return False, "客户端启动失败（路径无效或异常）", 0
    try:
        new_pid = int(proc.pid or new_pid)
    except Exception:
        pass

    # ---- 3. 等窗口出现并绑定 ----
    if not _wait_bind_by_pid(new_pid, old_pid, verbose=verbose):
        return False, f"等待新窗口超时（PID={new_pid}）", new_pid

    hwnd = int(getattr(wm, "hwnd", 0) or 0)
    if not hwnd:
        return False, "绑定成功但无有效 hwnd", new_pid

    # ---- 4. 登录界面预载 + 坐标缩放 ----
    time.sleep(LOGIN_PRELOAD)
    try:
        size = wm.get_client_size() or BASE_CLIENT_SIZE
    except Exception:
        size = BASE_CLIENT_SIZE
    scaled = _scale_coords(points, tuple(size))
    if verbose:
        print(f"[重登] 客户区 {size}，缩放后点击序列: {scaled}", flush=True)

    # ---- 5. 后台连续点击登录（目标 1 分钟内完成） ----
    if not _click_login(hwnd, scaled, click_gap=click_gap, verbose=verbose):
        return False, "登录点击中止（窗口失效）", new_pid

    # ---- 6. 等进入角色画面（给客户端加载时间，随后交给网关探测） ----
    time.sleep(3.0)

    # ---- 6.5 ★2026-09-01 用户定案：进入游戏后先右键一次关闭残留弹窗 ----
    #     登录后可能弹出公告/系统提示等对话框，先右键画面中心关闭，
    #     避免残留弹窗挡住后续 farm 的 CALL/走路（对齐 WORLD_BOSS 成熟链路）。
    _post_rightclick_close(hwnd, verbose=verbose)

    # ---- 7. 网关重新 attach 新 PID ----
    try:
        from core.gateway_guard import ensure_gateway
        ok, info = ensure_gateway(pid=new_pid, timeout=120, verbose=verbose)
        action = (info or {}).get("action", "?") if isinstance(info, dict) else "?"
        if ok:
            print(f"[重登] 网关已就绪（{action}），重登完成", flush=True)
        else:
            print(f"[重登] 网关未就绪: {info}", flush=True)
    except Exception as e:
        print(f"[重登] 网关重连异常（游戏内自愈可稍后接管）: {e}", flush=True)

    return True, f"重新登录完成 → 新PID={new_pid}", new_pid


if __name__ == "__main__":
    # 命令行冒烟：python core/relogin.py "E:\path\客户端.exe" 701,550 507,420 ...
    import sys
    # 已绑定 game（window_manager）→ CLI 手动立即重登
    ok, msg, pid = relogin_client(
        sys.argv[1] if len(sys.argv) > 1 else r"G:\00\快乐西游.exe",
        click_points=DEFAULT_CLICK_POINTS,
    )
    print(f"[重登] 结果: ok={ok}, msg={msg}, new_pid={pid}", flush=True)