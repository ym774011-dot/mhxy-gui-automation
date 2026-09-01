# -*- coding: utf-8 -*-
"""
BSHC - 共享背包宝石/精魄灵石自动合成函数
================================================================
功能: 遍历共享背包指定分类（宝石 / 杂货）的 1~10 分页，
     自动「取出 → 合成 → 一键全存」，只合成同 名称+等级+属性(类型) 的灵石，
     自动跳过钟灵石。

合成规则（2026-08-31 用户定案）:
  - 精魄灵石必须 名称+等级+类型(伤害/灵力/气血/防御) 三者相同才合成，
    不能只看等级（同名称同等级存在不同属性，混合是错的）
  - 宝石同理: 名称+等级分组
  - 「钟灵石」一律跳过
  - ★10 级（含）以上宝石不再合成（2026-09-01 用户定案）

全程 PostMessage 后台鼠标（不抢前台、零崩溃风险），窗口自动固定到标准位。

使用方式（GUI 里选择左上角模块 BSHC → 函数「宝石合成」→ 填参数 → 执行）:
  - cat:    分类，'宝石' 或 '杂货'（需游戏里已手动点到该大分类标签）
  - pages:  'all'=遍历1~10页；'1'=只处理第1页
  - gateway: mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）
"""
import time
import json
import ctypes
import urllib.request
from collections import defaultdict

DEFAULT_GATEWAY = "http://127.0.0.1:18082"

# ---- 权威标定（2026-08-31 用户+截图核验），相对「共享背包首格中心 c1」----
PAGE1_REL = (-14, 405)     # 页码1 = c1 + PAGE1_REL
PAGE_STEP_X = 30
STORE_REL = (6, 441)       # 一键全存 = c1 + STORE_REL

# ---- 标准布局（用户固化）----
BAG_CELL1_TARGET = (105, 225)
SHARED_CELL1_TARGET = (382, 109)

PM_GAP = 0.18        # 右键间隙（后台 PostMessage）
STORE_GAP = 1.0      # 一键全存后等待
MAX_PAGE = 10
TOTAL_ROUNDS = 300   # 每页总操作轮保护


# ======================================================================
# Lua 通信
# ======================================================================
def _lua(gateway, expr):
    req = urllib.request.Request(
        gateway.rstrip("/") + "/api/lua/expr",
        json.dumps({"expr": expr}).encode(),
        {"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace"))
    except Exception as e:
        return {"error": repr(e)}


def _v(gateway, expr):
    r = _lua(gateway, expr)
    if isinstance(r.get("result"), dict):
        return r["result"].get("value")
    return r


# ======================================================================
# 窗口查找
# ======================================================================
def _find_game_hwnd(pid):
    hwnds = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32 = ctypes.windll.user32

    def cb(hwnd, _):
        tid_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(tid_pid))
        if tid_pid.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 512)
            if buf.value:
                hwnds.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return hwnds


# ======================================================================
# PostMessage 后台操作
# ======================================================================
def _pm_click(hwnd, cx, cy, btn="right", gap=PM_GAP):
    """拟人化 PostMessage 点击：MOUSEMOVE → 随机小延迟 → down/up"""
    import random
    jx = cx + random.randint(-2, 2)
    jy = cy + random.randint(-2, 2)
    lp = ((jy & 0xFFFF) << 16) | (jx & 0xFFFF)
    dn, up, wp = (0x0204, 0x0205, 0) if btn == "right" else (0x0201, 0x0202, 1)
    u = ctypes.windll.user32
    u.PostMessageW(ctypes.c_void_p(hwnd), 0x0200, 0, lp)      # MOUSEMOVE 先到
    time.sleep(random.uniform(0.02, 0.05))
    u.PostMessageW(ctypes.c_void_p(hwnd), dn, wp, lp)
    time.sleep(random.uniform(0.04, 0.07))
    u.PostMessageW(ctypes.c_void_p(hwnd), up, 0, lp)
    time.sleep(gap)


def _pm_drag(hwnd, gx, gy, dx, dy):
    """PostMessage 拖拽（down->move序列->up），引擎响应（已验证）
    慢速版：各节点加延迟，确保引擎完整处理拖拽"""
    WM_LB = 0x0201; WM_LU = 0x0202; WM_MM = 0x0200

    def pm(msg, wp, x, y, gap):
        lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), msg, wp, lp)
        time.sleep(gap)

    pm(WM_LB, 1, gx, gy, 1.0)                       # 按下后等 1s
    steps = 10
    for i in range(1, steps + 1):
        pm(WM_MM, 1, gx + dx * i // steps, gy + dy * i // steps, 0.25)  # 每步 0.25s
    pm(WM_MM, 1, gx + dx, gy + dy, 0.5)             # 终点再停 0.5s
    pm(WM_LU, 0, gx + dx, gy + dy, 1.0)             # 释放后等 1s
    time.sleep(2.5)                                 # 窗口稳定+数据刷新


# ======================================================================
# Lua 读取
# ======================================================================
def _scan_gems(gateway, which):
    """读取宝石/灵石列表：which='shared'|'bag'（含 名称|等级|类型|坐标）"""
    t = "G.物品" if which == "shared" else "B.物品"
    win = "G = tp.窗口.共享道具" if which == "shared" else "B = tp.窗口.道具行囊"
    raw = _v(gateway, r"""
    (function()
    local %(win)s
    local out = {}
    local items = %(t)s
    if type(items) == 'table' then
      for i = 1, 96 do
        local cell = items[i]
        if type(cell) == 'table' and type(cell.物品) == 'table' and cell.物品.级别限制 ~= nil then
          local it = cell.物品
          out[#out+1] = tostring(i)..'|'..tostring(it.名称)..'|'..tostring(it.级别限制)..'|'..tostring(it.类型 or '')..'|'..tostring(cell.x)..'|'..tostring(cell.y)..'|'..tostring(it.识别码)
        end
      end
    end
    return table.concat(out, ';')
    end)()
    """ % {"win": win, "t": t})
    out = []
    for part in (raw or "").split(";"):
        if part:
            f = part.split("|")
            out.append({"idx": int(f[0]), "name": f[1], "lvl": int(f[2]), "kind": f[3],
                        "x": int(f[4]), "y": int(f[5]), "id": f[6]})
    return out


def _shared_c1(gateway):
    """共享背包首格中心（Lua cell，实时可靠）"""
    s = _v(gateway, "(function() local G=tp.窗口.共享道具; local c=G.物品 and G.物品[1]; "
                     "if type(c)=='table' then return tostring(c.x)..','..tostring(c.y) end; return '' end)()")
    if s:
        x, y = s.split(",")
        return int(x) + 26, int(y) + 26
    return None


def _bag_c1(gateway):
    """行囊首格中心"""
    s = _v(gateway, "(function() local B=tp.窗口.道具行囊; local c=B.物品 and B.物品[1]; "
                     "if type(c)=='table' then return tostring(c.x)..','..tostring(c.y) end; return '' end)()")
    if s:
        x, y = s.split(",")
        return int(x) + 26, int(y) + 26
    return None


def _cur_page(gateway):
    val = _v(gateway, "(function() return tonumber(tp.窗口.共享道具.页数) end)()")
    try:
        return int(val)
    except Exception:
        return -1


def _shared_ok(gateway):
    """共享背包窗口是否可读"""
    s = _v(gateway, "(function() local G=tp.窗口.共享道具; return (type(G)=='table' and type(G.物品)=='table') and '1' or '0' end)()")
    return s == "1"


def _bag_readable(gateway):
    """行囊物品数据可读"""
    return _v(gateway, "(function() local B=tp.窗口.道具行囊; "
                       "return (type(B)=='table' and type(B.物品)=='table') and '1' or '0' end)()") == "1"


def _bag_count_all(gateway):
    """行囊全部物品数"""
    n = _v(gateway, r"""
    (function()
    local B = tp.窗口.道具行囊
    local n = 0
    local items = B.物品
    if type(items) == 'table' then
      for i = 1, 48 do
        local c = items[i]
        if type(c) == 'table' and type(c.物品) == 'table' then n = n + 1 end
      end
    end
    return tostring(n)
    end)()
    """)
    try:
        return int(n)
    except Exception:
        return None


def _goto_page(gateway, hwnd, page, tries=3):
    """切到指定子页（权威坐标：页n = 首格中心 + (-14+30*(n-1), 405)）"""
    for _ in range(tries):
        if _cur_page(gateway) == page:
            return True
        c1 = _shared_c1(gateway)
        if not c1:
            time.sleep(0.5)
            continue
        bx = c1[0] + PAGE1_REL[0] + PAGE_STEP_X * (page - 1)
        by = c1[1] + PAGE1_REL[1]
        _pm_click(hwnd, bx, by, "left", gap=0.9)
        time.sleep(0.3)
    return _cur_page(gateway) == page


def _store_all(gateway, hwnd):
    """一键全存"""
    c1 = _shared_c1(gateway)
    if not c1:
        return
    _pm_click(hwnd, c1[0] + STORE_REL[0], c1[1] + STORE_REL[1], "left", gap=STORE_GAP)


# ======================================================================
# 窗口标准布局（拖拽固定到标准位）
# ======================================================================
def _grab_above(gateway, resp_btn):
    """取按钮正上方标题栏空白（按钮本身会点中标签，上方才是窗口可拖区）"""
    s = _v(gateway, "(function() local b=%s; if type(b)=='table' then return tostring(b.x)..','..tostring(b.y)..','..tostring(b.宽 or 0) end; return '' end)()" % resp_btn)
    if s:
        p = s.split(",")
        return int(p[0]) + int(p[2]) // 2, int(p[1]) - 16
    return None


def _grab_title(gateway, resp_table):
    """窗口资源组(背景表)左上角空白作为拖拽抓点（恒位于窗口顶部）"""
    s = _v(gateway, "(function() local b=%s; if type(b)=='table' then return tostring(b.x)..','..tostring(b.y) end; return '' end)()" % resp_table)
    if s:
        x, y = s.split(",")
        return int(x) + 20, int(y) + 8
    return None


def _standardize_layouts(gateway, hwnd, tries=3):
    """固定两窗口到标准位（PostMessage 拖拽，动态抓点）
    顺序（用户定案）：先行囊到位 → 等 1s → 再共享到位；
    每次拖拽前先左键单击抓点激活窗口（置前）"""
    def move(c1_fn, target, tag, grab_fn):
        cur = c1_fn()
        if not cur:
            print("[%s] 无法读锚点，跳过固定" % tag)
            return
        for _ in range(tries):
            dx, dy = target[0] - cur[0], target[1] - cur[1]
            if abs(dx) <= 5 and abs(dy) <= 5:
                print("[%s] 已到位 %s" % (tag, cur))
                return
            g = grab_fn()
            if not g:
                print("[%s] 无法读抓点" % tag)
                return
            print("[%s] 拖拽 %s -> %s" % (tag, cur, target))
            _pm_click(hwnd, g[0], g[1], "left", gap=0.1)   # 先左键激活置前
            _pm_drag(hwnd, g[0], g[1], dx, dy)
            cur = c1_fn()
            if not cur:
                return
        print("[%s] 固定完成（当前%s，目标%s）" % (tag, cur, target))

    move(lambda: _bag_c1(gateway), BAG_CELL1_TARGET, "行囊",
         lambda: _grab_above(gateway, "tp.窗口.道具行囊.资源组 and tp.窗口.道具行囊.资源组[9].按钮"))
    time.sleep(1.0)  # 用户要求：拖完行囊与拖共享之间间隔 1s
    move(lambda: _shared_c1(gateway), SHARED_CELL1_TARGET, "共享背包",
         lambda: _grab_title(gateway, "tp.窗口.共享道具.资源组 and tp.窗口.共享道具.资源组[1]"))


# ======================================================================
# 单页处理
# ======================================================================
def _process_page(gateway, hwnd, page):
    """处理一页：取出->连点合成->全存，直到该页(含行囊)无可合成。返回本页合成次数"""
    total = 0
    if not _bag_readable(gateway):
        return -1   # 行囊不可读：整脚本中止
    for _ in range(TOTAL_ROUNDS):
        # 行囊可能被取出操作误关 → 每轮循环前再次确保
        if not _bag_readable(gateway):
            return -1
        sg = _scan_gems(gateway, "shared")
        bg = _scan_gems(gateway, "bag")
        if _cur_page(gateway) != page:
            _goto_page(gateway, hwnd, page)
            sg = _scan_gems(gateway, "shared")
        grp = defaultdict(list)
        for g in sg + bg:
            grp[(g["name"], g["lvl"], g["kind"])].append(g)
        cands = sorted(((k, lst) for k, lst in grp.items()
                        if len(lst) >= 2 and "钟灵石" not in k[0]
                        and k[1] < 10),   # ★2026-09-01 用户定案：10 级（含）以上宝石不再合成
                       key=lambda c: (c[0][1], c[0][0], c[0][2]))
        if not cands:
            break
        (name, lvl, kind), _ = cands[0]
        # 取出共享中该组（行囊空位内；带失败检测）
        bag_n0 = _bag_count_all(gateway)
        capacity = (20 - bag_n0) if bag_n0 is not None else 0
        if capacity <= 0:
            _store_all(gateway, hwnd)
            continue
        shared_this = [g for g in _scan_gems(gateway, "shared")
                       if g["name"] == name and g["lvl"] == lvl and g["kind"] == kind]
        take_n = min(len(shared_this), capacity)
        took = 0
        for i in range(take_n):
            t = next((g for g in _scan_gems(gateway, "shared")
                      if g["name"] == name and g["lvl"] == lvl and g["kind"] == kind), None)
            if not t:
                break
            _pm_click(hwnd, t["x"] + 26, t["y"] + 26, "right")
            time.sleep(0.15)
            bn = _bag_count_all(gateway)
            if bn is None or bn <= bag_n0:
                # 行囊没增加（满了/弹窗）→ 一键全存清空后继续
                _store_all(gateway, hwnd)
                bag_n0 = _bag_count_all(gateway)
                if bag_n0 is None or bag_n0 >= 20:
                    print("  行囊仍无空间，中止本组取出")
                    break
                continue
            bag_n0 = bn
            took += 1
        time.sleep(0.5)
        # 行囊合成：逐次重读「该组当前第一颗」右键（合成会改格子内容）
        merges_grp = 0
        stall = 0
        while True:
            def _cnt():
                return len([g for g in _scan_gems(gateway, "bag")
                            if g["name"] == name and g["lvl"] == lvl and g["kind"] == kind])
            b = [g for g in _scan_gems(gateway, "bag")
                 if g["name"] == name and g["lvl"] == lvl and g["kind"] == kind]
            if len(b) < 2:
                break
            before = len(b)
            _pm_click(hwnd, b[0]["x"] + 26, b[0]["y"] + 26, "right")
            time.sleep(0.18)
            nb = _cnt()
            if nb == before:
                time.sleep(0.12)
                nb = _cnt()
            if nb == before:
                stall += 1
                if stall >= 3:
                    print("   合成停滞（该组无变化），退出")
                    break
                continue
            merges_grp += 1
            stall = 0
        total += merges_grp
        if merges_grp:
            print("   本组合成 %d 次" % merges_grp)
    # 页末：行囊有余 -> 全存
    if len(_scan_gems(gateway, "bag")) > 0:
        _store_all(gateway, hwnd)
    return total


# ======================================================================
# 主函数（GUI 入口）
# ======================================================================
__function_meta__ = {
    "宝石合成": {
        "title": "宝石合成: 遍历共享背包宝石/精魄灵石分页自动合成（跳过钟灵石）",
        "args": {
            "cat": "分类：'宝石' 或 '杂货'（精魄灵石在杂货下；游戏里需先手动点到对应大分类标签）",
            "pages": "'all'=遍历1~10页全量合成；'1'=只处理第1页",
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
        },
    },
}


def 宝石合成(
    cat: str = "宝石",
    pages: str = "all",
    gateway: str = DEFAULT_GATEWAY,
):
    """共享背包宝石/精魄灵石自动合成。

    规则：名称+等级+类型(属性) 三者相同才合成；钟灵石跳过；
        ★10 级（含）以上宝石不再合成（2026-09-01 用户定案）。
    流程：固定窗口标准布局 → 按页遍历（取出→合成→全存）。

    :param cat: '宝石' 或 '杂货'（需游戏里先手动点到该大分类标签）
    :param pages: 'all'=遍历1~10页；'1'=只第1页
    :param gateway: 网关地址
    :return: dict {ok, merges, message}
    """
    # 动态发现最新游戏进程
    try:
        import psutil
        pids = [p.info["pid"] for p in psutil.process_iter(attrs=["pid", "name"])
                if "十年一梦" in p.info["name"]]
    except Exception:
        pids = []
    if not pids:
        return {"ok": False, "merges": 0, "message": "找不到游戏进程"}
    pid = max(pids)

    hwnds = _find_game_hwnd(pid)
    if not hwnds:
        return {"ok": False, "merges": 0, "message": "找不到游戏窗口"}
    hwnd = hwnds[0][0]
    print("HWND=0x%X  PID=%d" % (hwnd, pid))

    if not _shared_ok(gateway):
        return {"ok": False, "merges": 0,
                "message": "共享背包窗口不可读（请打开共享背包+停在%s分页+不重叠布局）" % cat}
    typ = _v(gateway, "(function() return tostring(tp.窗口.共享道具.类型) end)()")
    if typ != cat:
        return {"ok": False, "merges": 0,
                "message": "当前分类=%s，需要%s：请先在游戏中手动点击「%s」大分类标签后重试" % (typ, cat, cat)}
    if not _bag_readable(gateway):
        return {"ok": False, "merges": 0,
                "message": "行囊数据不可读：请先在游戏里按 Alt+E 打开行囊后重新运行"}

    print("处理分类: %s；先固定窗口位置..." % cat)
    _standardize_layouts(gateway, hwnd)

    grand = 0
    page_list = [1] if str(pages).strip().lower() in ("1", "once", "demo") else range(1, MAX_PAGE + 1)
    need_stop = False
    for page in page_list:
        if not _goto_page(gateway, hwnd, page):
            print("无法切到第%d页" % page)
            continue
        time.sleep(0.6)
        n = _process_page(gateway, hwnd, page)
        if n == -1:
            print("中止：行囊数据不可读，请在游戏里按 Alt+E 打开行囊后重新运行")
            need_stop = True
            break
        if n:
            print("第%d页完成：合成 %d 次" % (page, n))
        grand += n

    msg = "（本分类完成，详见上方日志）" if not need_stop else "中止：行囊不可读"
    print("全部完成：共合成 %d 次" % grand)
    return {"ok": not need_stop, "merges": grand, "message": msg, "cat": cat, "pages": str(pages)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="宝石/精魄灵石自动合成")
    ap.add_argument("--cat", default="宝石", help="分类：宝石/杂货")
    ap.add_argument("--all", action="store_true", help="遍历1~10页")
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY, help="网关地址")
    args = ap.parse_args()
    r = 宝石合成(cat=args.cat, pages="all" if args.all else "1", gateway=args.gateway)
    print(json.dumps(r, ensure_ascii=False, indent=1))