# -*- coding: utf-8 -*-
"""重新CALL使者，完整 dump 对话文本与选项各字段（文字/跳转/内容/事件）"""
import json, urllib.request, time, sys, os, ctypes
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
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
# 确保在长安193,125
lua("_G.__out=''")
# CALL 使者
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
print(lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d and d.可视).." 名="..tostring(d and d.名称 or '').." 文="..tostring(d and d.文本内容 or '')
out[2]="标题="..tostring(d and d.标题 or '').." 提示="..tostring(d and d.提示 or '')
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local parts={}
    parts[1]="文字="..tostring(o.文字 or '')
    parts[2]="跳转="..tostring(o.跳转 or o.跳转链接 or '')
    parts[3]="类型="..tostring(o.类型 or o.kind or '')
    local jj=o.选中判断
    parts[4]="判断="..tostring(type(jj)=='table' and (tostring(jj.x or '')..','..tostring(jj.y or '')) or '')
    out[#out+1]=i..':['..table.concat(parts,';')..']'
  end
end
_G.__out=table.concat(out,'\n')'''))