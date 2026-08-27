# -*- coding: utf-8 -*-
"""调试 _peek_mission_target：分步 dump 使者对话，定位解析失败环节。"""
import json, sys, time
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from library.map_packs import MPCG as M

GW = "http://127.0.0.1:18083"

def lua(code):
    d = json.loads(urllib_request(json.dumps({"code": code})))
    from library.map_packs.MPCG import _lua_read
    raise NotImplementedError

import urllib.request
def lua_call(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

print("地图:", M._cur_map_id(GW))
hwnd = M._bind_hwnd(GW, None)
print("hwnd:", hwnd)

# 清理残留
for _ in range(3):
    vis = M._lua_expr(GW, "tostring(tp.窗口.对话栏.可视 or false)")
    print("清理前可视:", vis)
    if vis == "true":
        M._click(hwnd, 150, 320, rbutton=True); time.sleep(0.5)
    else:
        break

# 定位使者
npc = M._lua_find_npc_substr(GW, "门派闯关")
print("使者:", npc)
if npc.get("ok"):
    print("事件开始返回值:", M._lua_events_start(GW, npc["index"]))
    time.sleep(1.0)
    print("事件开始后 对话可视:", M._lua_expr(GW, "tostring(tp.窗口.对话栏.可视 or false)"))
    print("事件开始后 对话名:", repr(M._lua_expr(GW, "tostring(tp.窗口.对话栏.名称 or '')")))
    print("事件开始后 对话文:", repr(M._lua_expr(GW, "tostring(tp.窗口.对话栏.文本内容 or '')")))
    opts = M._dialog_options(GW)
    print("选项:", json.dumps(opts, ensure_ascii=False))
    # 尝试点击准备好了
    clicked = False
    for o in opts:
        txt = (o["text"] or "") + "|" + (o["link"] or "")
        if M._ACCEPT_OPTION_KEYWORD in txt and o["cx"] and o["cy"]:
            print(f"点击准备好了 @{o['cx']},{o['cy']}")
            M._click(hwnd, int(float(o["cx"])), int(float(o["cy"])))
            clicked = True
            break
    time.sleep(1.0)
    print("点击后 对话可视:", M._lua_expr(GW, "tostring(tp.窗口.对话栏.可视 or false)"))
    print("点击后 对话名:", repr(M._lua_expr(GW, "tostring(tp.窗口.对话栏.名称 or '')")))
    print("点击后 对话文:", repr(M._lua_expr(GW, "tostring(tp.窗口.对话栏.文本内容 or '')")))
    print("点击后 选项:", json.dumps(M._dialog_options(GW), ensure_ascii=False))
    print("next_sect(点击后文本):", M._next_sect(M._lua_expr(GW, "tostring(tp.窗口.对话栏.文本内容 or '')")))