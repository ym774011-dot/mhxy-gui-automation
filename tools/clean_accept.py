# -*- coding: utf-8 -*-
"""严格接受新一轮：反复清残留 → CALL使者 → 按「跳转」匹配准备好了 → 点 → 复验"""
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
def rclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.4)
def lclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0204, 0x0001, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.4)
def dlg_vis():
    return lua("_G.__out=tostring(tp.窗口.对话栏.可视 or false)" if False else "local d=tp.窗口.对话栏 local x=0 if d and d.可视 then x=1 end; _G.__out=tostring(x)") == "1"

# 1) 反复关闭残留对话框，直到无可视
for _ in range(6):
    if dlg_vis():
        rclick(320, 150)
    else:
        break
    time.sleep(0.4)
print("清理后可视:", dlg_vis())

# 2) CALL 使者
print("CALL使者:", lua(r'''
local j=tp.场景.假人
local idx=nil
for i=1,#j do
  if type(j[i])=='table' and tostring(j[i].名称 or ''):find('门派闯关') then idx=i end
end
if not idx then _G.__out='NO'; return end
local o=j[idx]; local ok=pcall(function() return o['事件开始'](o) end)
_G.__out='IDX='..idx..' ok='..tostring(ok)'''))
time.sleep(1.2)
print("对话:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]=tostring(d.可视)..'|'..tostring(d.名称 or '')..'|'..tostring(d.文本内容 or '')
if d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local jj=o.选中判断
    out[#out+1]=i..':'..tostring(o.跳转 or o.跳转链接 or '')..'@'..tostring(jj and jj.x or '')..','..tostring(jj and jj.y or '')
  end
end
_G.__out=table.concat(out,'|')'''))

# 3) 读选项，点「准备好了」
opts = M._dialog_options(GW)
print("opts(link匹配):", [(o["index"], o["link"], o["cx"], o["cy"]) for o in opts])
target = None
for o in opts:
    if "准备好了" in (o["link"] or "") or "告诉我们第一关" in (o["link"] or ""):
        target = o
if not target:
    # 按跳转字段重新读
    v = lua(r'''
local d=tp.窗口.对话栏
local out={}
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local jj=o.选中判断
    out[#out+1]=tostring(i)..'|'..tostring(o.跳转 or o.跳转链接 or '')..'|'..tostring(jj and jj.x or '')..'|'..tostring(jj and jj.y or '')
  end
end
_G.__out=table.concat(out,'\n')''')
    for line in (v or "").splitlines():
        p = line.split("|")
        if len(p) >= 4 and "准备好了" in p[1]:
            target = {"index": p[0], "cx": p[2], "cy": p[3]}
if target:
    cx, cy = int(float(target["cx"])), int(float(target["cy"]))
    print(f"点击「准备好了」选项{target['index']} @ ({cx},{cy})")
    lclick(cx, cy)
else:
    print("未找到「准备好了」选项")
time.sleep(2.5)

# 4) 复验任务激活
def check107():
    return lua(r'''
local recs={}
if tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录 then
  for i,v in pairs(tp.窗口.任务追踪栏.数据记录) do
    if type(v)=='table' and tostring(v.类型 or v.任务类型 or '')=='107' then
      recs[#recs+1]='序列='..tostring(v.当前序列 or '')..'闯关n='..tostring(v.闯关序列 and #v.闯关序列 or '')
    end
  end
end
_G.__out=table.concat(recs,' | ') or 'NONE' ''')
print("107记录:", check107())
print("对话可视:", lua("local d=tp.窗口.对话栏; _G.__out=tostring(d and d.可视 or false)"))