# -*- coding: utf-8 -*-
"""点使者「准备好了」→ 确认新一轮激活（类型=107 出现）"""
import json, urllib.request, time, sys, os, ctypes
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from library.map_packs import MPCG as M
from core.window_manager import window_manager
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
pid = (json.loads(urllib.request.urlopen(GW + "/api/status", timeout=10)
                  .read().decode("utf-8", "replace")).get("result") or {}).get("pid")
window_manager.bind(pid=int(pid))
hwnd = getattr(window_manager, "hwnd", None)
u = ctypes.windll.user32
opts = M._dialog_options(GW)
print("选项:", [(o["index"], o["text"], o["cx"], o["cy"]) for o in opts])
target = None
for o in opts:
    if "准备好了" in o["text"] or "告诉我们第一关" in o["text"]:
        target = o
if not target and opts:
    target = next((o for o in opts if o["index"] == "1"), opts[0])
if target:
    cx, cy = int(float(target["cx"])), int(float(target["cy"]))
    lp = (cy << 16) | (cx & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0001, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp)
    print("已点选项:", target["index"], target["text"], "@", cx, cy)
time.sleep(2)
print("任务识别:", json.dumps(M.MPCG_recognize(gateway=GW, verbose=False), ensure_ascii=False))
print("对话栏:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d and d.可视).." 名="..tostring(d and d.名称 or '').." 文="..tostring(d and d.文本内容 or '')
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    out[#out+1]=i..':'..tostring(o.文字 or o.跳转链接 or '')
  end
end
_G.__out=table.concat(out,' | ')'''))