# -*- coding: utf-8 -*-
"""仓库存物品（用户 2026-09-12 定案；坐标全部实机标定）

流程（单角色；★组队下无法用仓库，调用方需先解散队伍）：
  1) 快捷菜单开关 (149,10)-(173,41) → 快捷传送 (269,45)-(322,58)
  2) 传送对话框 → 仓库（免费）(194,410) → 精确落地 长安 [355,33]
  3) tp.地图.npc 找 仓库管理员 → 点它 → 红字行首行（打开仓库）→ 面板开
  4) 逐件存：可叠物品（有 数量）需 >= _STORE_STACK_MIN(99) 才存；
     豁免 99（有多少存多少）：魔兽要诀/上古锻造图策/元宵；
     ★2026-09-17 修复：上古锻造图策 只看等级不看种类——**仅等级≥145 才存**
       （<145 或等级读不到均不存，低等级由出售链路卖）；
     保留（永不存）：第一排（格子id<=5）+ 天眼/合成旗/飞行旗/飞行符；
     同物品同分页：先在仓库里找同名物品所在分页，找不到用第一个未满分页
  5) 仓库满判定=功能判定：右键后行囊件数下降=成功；没降=满 → 换下一分页重试
  6) 退出 (646,408) 收面板

满包「先卖后存」（★2026-09-17 用户定案，zhuagui_bag_full_handle）：
  背包满时先遍历背包出售所有可售垃圾（含 内丹/百炼精铁 等白名单，保留内丹除外），
  出售结束后再存其余可存物；出售优先=既变现又腾空间，避免存仓因空间不足中断/误存垃圾。

Lua 依据（全部实测）：
  界面[14] 仓库面板：本类开关/当前仓库/仓库数量(容量恒26)/仓库按钮(26个带包围盒)
    物品数据=行囊侧物品（含 小动画{x,y}=点击坐标 / 数量 / 名称 / 格子id）
  仓库物品[1][i]=当前分页物品（含 名称/数量）→ 用于"同物品同分页"检索
"""

import random
import time

from . import ZGUI as _Z

# ---- 用户标定坐标（客户区）----
_MENU_TOGGLE = (149, 10, 173, 41)      # 快捷菜单开关
_TP_BTN = (269, 45, 322, 58)           # 快捷传送
_TP_WAREHOUSE = (194, 410)             # 传送对话框-仓库（免费）
_WH_QUIT = (646, 408)                  # 仓库面板-退出
_WH_BTN_X0, _WH_BTN_Y1, _WH_BTN_Y2 = 215, 395, 423   # 分页按钮起始/两排 y
_WH_BTN_DX, _WH_BTN_W, _WH_BTN_H = 25, 22, 23
_NPC_FALLBACK = (298, 305)             # 落点[355,33]时仓库管理员固定屏幕位（实测）

_STORE_STACK_MIN = 99                  # 可叠物品攒满 99 才存（用户定案）
# ★2026-09-15 用户定案：元宵不等 99，背包有多少存多少。
#   实测（pp_probe 22:24，队长 p12928）：元宵 类型=功能、
#   带 参数=防资/攻资等区分属性，同名不叠加各占一格，
#   实测数量仅 9/3/2/4/3 ① 99 门槛永远等不到 → 豁免 99。
#   匹配用“元宵”子串（覆盖芝麻/豆沙桂花等变体）。
_STORE_NO_STACK_MIN = ("魔兽要诀", "上古锻造图策", "元宵")  # ★2026-09-12 用户更正：魔兽要诀不可叠加
                                       # ★2026-09-14 上古锻造图策≥145 保留存仓库
                                       # （每本占一格）→ 不限 99，有多少存多少
                                       # ★2026-09-15 元宵同理：不等 99
# ★2026-09-15 用户定案：飞行符不存仓库（传送工具，常驻背包）。
#   实测队长背包 飞行符×151，数量 ≥ 99 会直接命中门槛被存走 → 必须保护。
_STORE_KEEP_NAMES = ("天眼", "合成旗", "飞行旗", "飞行符")   # 名称子串保护
_STORE_KEEP_SLOTS = 5                  # 第一排（格子id<=5）保留

# ★2026-09-17 用户定案：「满包先卖后存」的出售白名单/保留名单，取自 ZGUI 单一真源
#   （与全地图刷怪共用，不漂移）。先卖再存——见 zhuagui_bag_full_handle。
_BAG_FULL_EXTRA_SELL = _Z.SELL_EXTRA_JUNK      # 百炼精铁/制造指南书/钨金/内丹
_BAG_FULL_EXTRA_EXCLUDE = _Z.SELL_EXTRA_KEEP   # 内丹保留：矫健/迅敏/玉砥柱…

_PANEL_LUA = r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
if type(w) ~= 'table' then __out = '无' return end
local bag = 0
if type(w.物品数据) == 'table' then for _ in pairs(w.物品数据) do bag = bag + 1 end end
local wh = 0
local c = w.仓库物品 and w.仓库物品[1]
if type(c) == 'table' then for _ in pairs(c) do wh = wh + 1 end end
__out = '开=' .. tostring(w.本类开关) .. ' 分页=' .. tostring(w.当前仓库)
     .. ' 行囊=' .. bag .. ' 本页物品=' .. wh
'''


def _log(msg):
    _Z.logger.info("[存仓] " + msg)


def _click_box(hwnd, gw, box, tag="", readback=None):
    """点一个标定矩形。readback 给出时点后回读 [8].本类开关 是否等于该值，
    不等会带随机偏移再点一次。

    ★2026-09-15 新增（用户实测"菜单要开却关掉"类乱态防护）：菜单开关是
      切换式，被背包/队伍名条干扰后点一下可能反向，只发点不校验会把
      "关"当"开"。返回值仍为 (x, y) 不变，调用方无需改。
    """
    x0, y0, x1, y1 = box
    x = random.randint(x0 + 3, max(x0 + 4, x1 - 3))
    y = random.randint(y0 + 1, max(y0 + 2, y1 - 1))
    _Z.post_click(hwnd, x, y, gateway=gw)
    if readback is not None:
        time.sleep(0.7)
        if _quick_menu_on(gw) != readback:
            _Z.post_click(hwnd, x + random.randint(-10, 10),
                          y + random.randint(-4, 4), gateway=gw)
    return x, y


def _panel(hwnd, gw):
    """返回 dict：{'open':bool,'page':int,'bag':int,'wh':int}"""
    r = _Z._lua_call(gw, _PANEL_LUA) or ""
    d = {"open": False, "page": None, "bag": 0, "wh": 0}
    for seg in r.split(" "):
        if "=" not in seg:
            continue
        k, _, v = seg.partition("=")
        if k == "开":
            d["open"] = (v == "true")
        elif k == "分页":
            try:
                d["page"] = int(v)
            except ValueError:
                pass
        elif k == "行囊":
            try:
                d["bag"] = int(v)
            except ValueError:
                pass
        elif k == "本页物品":
            try:
                d["wh"] = int(v)
            except ValueError:
                pass
    return d


def _switch_page(hwnd, gw, page, tries=3):
    """点分页按钮并回读校验（点击→回读→重试）。"""
    for _ in range(tries):
        if page <= 8:
            x, y = _WH_BTN_X0 + (page - 1) * _WH_BTN_DX, _WH_BTN_Y1
        else:
            x, y = _WH_BTN_X0 + (page - 9) * _WH_BTN_DX, _WH_BTN_Y2
        _Z.post_click(hwnd, x + _WH_BTN_W // 2, y + _WH_BTN_H // 2, gateway=gw)
        time.sleep(random.uniform(1.0, 1.4))
        st = _panel(hwnd, gw)
        if st.get("page") == page:
            return True
    return False


def _page_items(hwnd, gw):
    """当前分页物品：[(名称, 数量)]（仓库物品[1] 容器）。"""
    r = _Z._lua_call(gw, r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
local c = w and w.仓库物品 and w.仓库物品[1]
if type(c) ~= 'table' then __out = '' return end
local out = {}
for _, v in pairs(c) do
  if type(v) == 'table' then
    out[#out+1] = tostring(v.名称 or '') .. '#' .. tostring(v.数量 or '')
  end
end
__out = table.concat(out, ',')
''') or ""
    res = []
    for seg in r.split(","):
        if "#" in seg:
            nm, _, qty = seg.partition("#")
            res.append((nm, qty))
    return res


def _bag_items(hwnd, gw):
    """行囊侧物品：[{'id','name','qty','x','y','lv'}]（小动画=点击坐标）。"""
    r = _Z._lua_call(gw, r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
local d = w and w.物品数据
if type(d) ~= 'table' then __out = '' return end
local out = {}
for _, v in pairs(d) do
  if type(v) == 'table' then
    local sa = v.小动画
    local x = type(sa) == 'table' and tonumber(sa.x) or 0
    local y = type(sa) == 'table' and tonumber(sa.y) or 0
    local lv = tonumber(v.等级)
    if not lv and type(v.数据) == 'table' then lv = tonumber(v.数据.等级) end
    out[#out+1] = string.format('%s|%s|%s|%d|%d|%s|%s',
      tostring(v.格子id or 0), tostring(v.名称 or ''), tostring(v.数量 or ''),
      x, y, tostring(v.类型 or ''), tostring(lv or ''))
  end
end
__out = table.concat(out, ' ;; ')
''') or ""
    res = []
    for seg in r.split(" ;; "):
        p = seg.split("|")
        if len(p) >= 5:
            it = {"id": _Z._coord_int(p[0]), "name": p[1], "qty": p[2],
                  "x": _Z._coord_int(p[3]), "y": _Z._coord_int(p[4]),
                  "type": p[5]}
            if len(p) >= 7:
                try:
                    it["lv"] = int(p[6])
                except ValueError:
                    it["lv"] = None
            res.append(it)
    return res


def _dialog_open(gw):
    """NPC 对话框是否打开（界面[8].本类开关）——功能性校验，不用像素。

    ★2026-09-18 统一到 `ZGUI.quick_dialog_on`（原来每个模块各抄一份同样的 Lua）。
    """
    return _Z.quick_dialog_on(gw) is True


def _quick_menu_on(gw):
    """快捷菜单/快捷传送界面（界面[8]）是否开着。None=通道失败状态未知。

    ★2026-09-18 统一到 `ZGUI.quick_dialog_on`（语义完全一致：读不到返回 None）。
    """
    return _Z.quick_dialog_on(gw)


def _go_warehouse(hwnd, gw):
    """快捷菜单 → 快捷传送 → 仓库（免费）。返回 True=已到长安仓库点。

    ★2026-09-12 改功能性校验：菜单开关是切换式且像素会被队友名条干扰，
      改为"点开关→点快捷传送→读界面8开关"配对重试（最多 4 轮），不再看图。
    ★2026-09-15 用户定案（点快捷传送前必须关背包）：背包面板开着会盖住
      左上角快捷菜单 (149,10)-(173,41)，点开关直接落进背包 → 4 轮全空转。
      与 run_unlimited_hunt._open_quick_dialog 同款先例。
      同时给菜单开关加"点后回读"：切换式按钮被干扰后可能反向，
      点完校验 [8].本类开关，菜单该开时确认真开、该收时确认真收到位。
    """
    # ★2026-09-15 先关背包（关不掉也继续：关包失败只告警，本轮仍尝试开菜单）
    try:
        if not _Z._bag_ensure_close(gw, hwnd):
            _log("点快捷传送前背包未确认关闭（继续尝试）")
    except Exception:
        pass
    time.sleep(0.3)
    if _quick_menu_on(gw) is True:
        _click_box(hwnd, gw, _MENU_TOGGLE, "菜单开关", readback=False)
        time.sleep(0.8)
    opened = False
    for _ in range(4):
        _click_box(hwnd, gw, _MENU_TOGGLE, "菜单开关", readback=True)
        time.sleep(0.9)
        _click_box(hwnd, gw, _TP_BTN, "快捷传送")
        time.sleep(1.5)
        if _dialog_open(gw):
            opened = True
            break
    if not opened:
        _log("快捷传送对话框打不开（4 轮）")
        return False
    _Z.post_click(hwnd, _TP_WAREHOUSE[0] + random.randint(-6, 6),
                  _TP_WAREHOUSE[1] + random.randint(-1, 3), gateway=gw)
    time.sleep(3.5)
    pos = _Z._lua_call(gw, r'''
local me = tp and tp.屏幕 and tp.屏幕.主角 and tp.屏幕.主角.xy
__out = tostring(tp and tp.地图 and tp.地图.地图名称) .. ','
     .. tostring(me and math.floor((me.x or 0) / 20)) .. ','
     .. tostring(me and math.floor((me.y or 0) / 20))''') or ""
    _log("落点: %s" % pos)
    # ★落地后关掉快捷传送对话框（对话框开着角色不能移动，会挡住后续点 NPC）
    _close_dialogs(hwnd, gw)
    return pos.startswith("长安城,35")


def _close_dialogs(hwnd, gw, tries=3):
    """关闭挡住世界点击的对话框（界面8：快捷传送/NPC 对话）。

    ★2026-09-12 用户实测：对话框开着时角色不能移动（世界点击被忽略）——
      传送落地后必须先把快捷传送对话框关掉，否则点 NPC 全部无效。
    ★2026-09-18 统一到 `ZGUI.close_quick_dialog`（点自带关闭按钮 → ESC 兜底，
      逻辑与本函数原来那份完全一致，只是提成了公共件）。
    """
    return _Z.close_quick_dialog(hwnd, gw, tries=tries)


def _call_warehouse_npc(hwnd, gw, rounds=3):
    """CALL 物品仓库管理员开面板。

    ★2026-09-12 用户定案：点击不准确 → 不成功就重新传送一次仓库洗牌再试
      （该 NPC 无 标识，不能走 send-data CALL；点击受队友遮挡影响）。
    点击位：落点[355,33] 时 NPC 恒在 (298,305)/(312,345) 两个实测位。
    对话弹出后点 用户标定 打开仓库 (117,322)-(169,332)。
    """
    for rnd in range(max(1, rounds)):
        if rnd > 0:
            _log("第 %d 轮未开面板 → 重新传送仓库洗牌" % rnd)
            if not _go_warehouse(hwnd, gw):
                continue
        # ★2026-09-15 重传洗牌轮：_go_warehouse 返回时可能已把菜单点关
        #   （最后一轮配对点击的收尾态），显式确认菜单已收起，防残留挡点击
        if _quick_menu_on(gw) is True:
            _click_box(hwnd, gw, _MENU_TOGGLE, "菜单开关", readback=False)
            time.sleep(0.6)
        _close_dialogs(hwnd, gw)
        try:
            _Z._bag_ensure_close(gw, hwnd)
        except Exception:
            pass
        # 点 NPC 两个实测位
        for (cx, cy) in ((298, 305), (312, 345)):
            _Z.post_click(hwnd, cx + random.randint(-3, 3),
                          cy + random.randint(-3, 3), gateway=gw)
            time.sleep(1.8)
            if _panel(hwnd, gw)["open"]:
                return True
            if _dialog_open(gw):
                break
        # 对话开了 → 点打开仓库（用户标定坐标）
        if _dialog_open(gw):
            _Z.post_click(hwnd, random.randint(120, 166),
                          random.randint(323, 331), gateway=gw)
            time.sleep(1.8)
            if _panel(hwnd, gw)["open"]:
                return True
    _log("打开仓库面板失败（%d 轮，含重传）" % rounds)
    return False


def zhuagui_store_all(pid, keep_names=_STORE_KEEP_NAMES, stack_min=_STORE_STACK_MIN,
                      hwnd=None, verbose=True):
    """单角色：背包物品存仓库（★2026-09-12 用户定案：边存边填页）。

    不预扫描全部分页（省 ~60s）——直接在当前分页开存；存不进去（该页满）
    就切下一页继续；26 页都满才放弃该件。
    规则：可叠物品（有 数量 字段）攒满 stack_min(99) 才存；保留第一排
    （格子id<=5）+ 名称含 天眼/合成旗/飞行旗。
    ★组队下无法使用仓库——调用方必须先解散队伍。
    返回 (成功标志, 存放件数, 说明)。
    """
    gw = "file://pzxy_p%d" % pid
    if hwnd is None:
        from tools.squad_auto_team import find_hwnd_by_pid
        hwnd = find_hwnd_by_pid(pid)
    if not hwnd:
        return False, 0, "找不到窗口"
    # ★2026-09-13 面板钉位：仓库面板/背包被拖拽会令分页/退出/出售固定坐标
    #   失准 → Lua 复位（仓库[14]→(200,395)、背包[3]→(0,0)）
    _Z._panel_pin_defaults(gw)
    time.sleep(0.4)
    # ★2026-09-12 用户要求"完美实现"：到仓库/开面板失败自动重试（2 次尝试）
    opened = False
    last_err = ""
    for attempt in range(2):
        if _go_warehouse(hwnd, gw) and _call_warehouse_npc(hwnd, gw):
            opened = True
            break
        last_err = "到仓库/开面板失败"
        _log("p%d 第 %d 次尝试未成功 → 5s 后重试" % (pid, attempt + 1))
        time.sleep(5.0)
    if not opened:
        return False, 0, last_err

    bag = _bag_items(hwnd, gw)
    todo = []
    for it in bag:
        nm, qty, gid = it["name"], it["qty"], it["id"]
        if not nm or not it["x"] or not it["y"]:
            continue
        if any(k in nm for k in keep_names):
            continue
        if gid is not None and gid <= _STORE_KEEP_SLOTS:      # 第一排保留
            continue
        if (qty.isdigit() and int(qty) < stack_min
                and not any(k in nm for k in _STORE_NO_STACK_MIN)):
            continue                                            # 可叠未攒满 → 留
        # ★2026-09-17 用户定案修复：上古锻造图策 只看等级不看种类，仅等级≥145 才存仓；
        #   <145 或等级读不到均不存（保守保留——不误存低等级，低等级由出售链路卖）。
        #   与 ZGUI._sellable_items 的「<145 出售 / ≥145 保留」两半规则互补。
        if '上古锻造图策' in nm:
            lv = it.get('lv')
            if lv is None or lv < 145:
                continue                                        # 不满足等级门槛 → 不存仓
        todo.append(it)
    if not todo:
        _log("p%d 无可存物品（保留规则过滤后）" % pid)
        _exit_panel(hwnd, gw)
        return True, 0, "无可存"

    # ★用户定案：不预扫描——直接在当前分页开存；存不进去（该页满）就切下一页
    #   继续；26 页都满才放弃该件。cur 从面板当前分页开始（延续上次进度）。
    # ★2026-09-16 用户定案（性能）：分页切换下沉到「存失败」分支——
    #   原实现每存一件都先 _switch_page 一次（每件白多一次点击
    #   +1.0~1.4s 回读等待），而同一页未满时完全不需要切。
    #   现改为：当前页已确认就位 → 直接右键存；成功则同页继续存下一件（零切页）；
    #   仅失败（页满）时才切下一页重试。
    st = _panel(hwnd, gw)
    cur = st.get("page") or 1
    cur_ready = False          # 当前 cur 页是否已确认就位（避免重复切页）
    stored = 0
    for it in todo:
        for _ in range(26):
            if not cur_ready and not _switch_page(hwnd, gw, cur):
                cur = cur % 26 + 1
                continue
            cur_ready = True
            before = _panel(hwnd, gw)["bag"]
            _Z.post_right_click(hwnd, it["x"], it["y"], gateway=gw)
            time.sleep(random.uniform(1.2, 1.6))
            after = _panel(hwnd, gw)["bag"]
            if after < before:                    # 存成功 → 同页继续放下一件
                stored += 1
                _log("p%d %s → 分页%d（余 %d 件）" % (pid, it["name"], cur, after))
                break
            _log("p%d 分页%d 存 %s 未生效（满页）→ 下一页"
                 % (pid, cur, it["name"]))
            cur = cur % 26 + 1
            cur_ready = False                 # 切页后需重新确认就位
        else:
            _log("p%d %s 26 个分页都满，放弃该件" % (pid, it["name"]))
    _exit_panel(hwnd, gw)
    return True, stored, "存入 %d 件" % stored


def zhuagui_bag_full_handle(pid, gw=None, hwnd=None,
                            extra_sell=_BAG_FULL_EXTRA_SELL,
                            extra_exclude=_BAG_FULL_EXTRA_EXCLUDE,
                            full_threshold=18, verbose=True):
    """背包满统一处理：先卖（腾空间+变现）后存（其余可存物入仓）。

    ★2026-09-17 用户定案：前往仓库存放道具前，必须先遍历背包、识别并出售所有
      可售垃圾，出售结束后再存仓。顺序约束与防丢失：
      1) 先卖：用 zhuagui_sell_junk 遍历背包、标记并出售所有可售物品（含 extra
         白名单与 <145 上古锻造图策）。出售优先于存放——既变现又腾出背包空间，
         避免「背包已满」状态下存仓交互异常、或把本该卖的垃圾存进仓库；
      2) 再存：出售结束后再用 zhuagui_store_all 存放其余可存物品（按仓库保留规则），
         此时背包已腾出空间、且垃圾已清，存仓不会因空间不足中断，也不会误存垃圾。
      ★组队下无法用仓库——调用方需先解散队伍（pp_gui 存仓流程已负责解散+重组）。
      ★满包触发：仅当背包占用≥full_threshold(默认18/20) 才执行，避免半满背包
         频繁跑存仓；由调用方（pp_gui「某角色背包满」判定）决定何时调用亦可。

    返回 (sell_count, store_ok, store_count, note)。
    """
    if gw is None:
        gw = "file://pzxy_p%d" % pid
    if hwnd is None:
        from tools.squad_auto_team import find_hwnd_by_pid
        hwnd = find_hwnd_by_pid(pid)
    if not hwnd:
        return 0, False, 0, "找不到窗口"

    n_used = _Z._bag_used_count(gw)
    if isinstance(n_used, int) and n_used >= 0 and n_used < full_threshold:
        _log("p%d 背包占用 %d 格（<阈值%d）→ 不触发存仓" % (pid, n_used, full_threshold))
        return 0, True, 0, "背包未满"

    # —— 1) 先卖（腾空间 + 变现）——
    _log("p%d 背包占用 %s 格 → 先出售可售垃圾" % (pid, n_used))
    sell = 0
    try:
        sell = _Z.zhuagui_sell_junk(gw, hwnd=hwnd, verbose=verbose,
                                    extra_sell=extra_sell,
                                    extra_exclude=extra_exclude) or 0
    except Exception as e:
        _log("p%d 出售异常（不阻断后续存仓）: %s" % (pid, e))
    _log("p%d 本次出售 %d 件" % (pid, sell))

    # —— 2) 再存（其余可存物入仓）——
    ok, n, msg = zhuagui_store_all(pid, hwnd=hwnd, verbose=verbose)
    return sell, ok, n, msg


def _exit_panel(hwnd, gw):
    _Z.post_click(hwnd, _WH_QUIT[0] + random.randint(-4, 4),
                  _WH_QUIT[1] + random.randint(-2, 2), gateway=gw)
    time.sleep(0.8)
    st = _panel(hwnd, gw)
    if st["open"]:
        _log("退出未生效，补 ESC")
        import ctypes
        u = ctypes.windll.user32
        u.PostMessageW(hwnd, 0x0100, 0x1B, 0)
        u.PostMessageW(hwnd, 0x0101, 0x1B, 0xC0000001)
        time.sleep(0.6)
