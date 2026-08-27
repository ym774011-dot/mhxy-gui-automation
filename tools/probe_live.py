# -*- coding: utf-8 -*-
"""实时观察：CALL使者→点准备好了→3秒内连续采样对话栏/系统提示/任务追踪，捕获瞬时目标文本。"""
import json, sys, time, urllib.request
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from library.map_packs import MPCG as M

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

hwnd = M._bind_hwnd(GW, None)
print("地图:", M._cur_map_id(GW))
# 清理残留
for _ in range(3):
    if M._lua_expr(GW, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
        M._click(hwnd, 150, 320, rbutton=True); time.sleep(0.5)
    else:
        break
npc = M._lua_find_npc_substr(GW, "门派闯关")
print("使者:", npc)
if not npc.get("ok"):
    sys.exit()
M._lua_events_start(GW, npc["index"])
time.sleep(0.8)
opts = M._dialog_options(GW)
print("初始选项:", json.dumps(opts, ensure_ascii=False))
clicked = False
for o in opts:
    txt = (o["text"] or "") + "|" + (o["link"] or "")
    if M._ACCEPT_OPTION_KEYWORD in txt and o["cx"] and o["cy"]:
        print(f"点击准备好了 @{o['cx']},{o['cy']}")
        M._click(hwnd, int(float(o["cx"])), int(float(o["cy"])))
        clicked = True
        break
if not clicked:
    print("未找到准备好了选项"); sys.exit()
# 连续采样 3.5s
print("---- 连续采样 ----")
prev = None
for i in range(35):
    st = M._auto_state(GW)
    line = f"[{i*0.1:.1f}s] 可视={st.get('可视')} 名={st.get('名')!r} 文={st.get('文')!r}"
    if line != prev:
        print(line, flush=True)
        prev = line
    time.sleep(0.1)
print("---- 采样结束 ----")
# 最后再读一次追踪栏
print("last 追踪栏当前序列:", lua(r'''local t=tp.窗口.任务追踪栏.数据记录 local out='none' for k,v in pairs(t or {}) do if type(v)=='table' and tostring(v.类型 or '')=='107' then out=tostring(v.当前序列 or '') end end _G.__out=out'''))