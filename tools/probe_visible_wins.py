# -*- coding: utf-8 -*-
"""枚举当前所有"可视"窗口，定位会员卡界面并抓取传送选项"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=25):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

print("=== 可视窗口 + 文本内容 + 选项数 ===")
code = r'''
local w = tp.窗口
local out = {}
if type(w) ~= "table" then out[1]="NOTABLE" end
for name, win in pairs(w) do
  local vis = (type(win)=="table") and (win.可视 or win.显示1 or win.显示 or win.isShow or false)
  if vis then
    out[#out+1] = "★" .. tostring(name) ..
      " | 文本=" .. tostring(win.文本内容 or "") ..
      " | opts=" .. tostring(count(win.选项 or {})) ..
      " | 名称=" .. tostring(win.名称 or "")
  end
end
_G.__out = table.concat(out, "\n")'''
# 用内联计数函数
code = r'''
local w = tp.窗口
local function cnt(t) local n=0 for _ in pairs(t) do n=n+1 end return n end
local out = {}
if type(w) ~= "table" then out[1]="NOTABLE" end
for name, win in pairs(w) do
  if type(win)=="table" and (win.可视 or win.显示1) then
    local nn = (type(win.选项)=="table") and cnt(win.选项) or 0
    out[#out+1] = "★" .. tostring(name) .. " | 文本=" .. tostring(win.文本内容 or "") .. " | opts=" .. tostring(nn) .. " | 名称=" .. tostring(win.名称 or "")
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))