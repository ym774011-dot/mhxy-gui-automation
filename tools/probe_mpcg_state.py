# -*- coding: utf-8 -*-
"""探查门派闯关当前真实任务状态（网关 lua 直读）"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

code = r'''
local out={}
out[1]="地图="..tostring(tp.当前地图 or '')
out[2]="战斗="..tostring(tp.战斗中 and true or false)
local d=tp.窗口.对话栏
out[3]="对话可视="..tostring(d and d.可视 or false)
out[4]="对话名="..tostring(d and d.名称 or '')
out[5]="对话文="..tostring(d and d.文本内容 or '')
if tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录 then
  local recs=tp.窗口.任务追踪栏.数据记录
  out[6]="记录数="..tostring(#recs)
  for i,r in ipairs(recs) do
    if type(r)=='table' then
      out[#out+1]=i..":类型="..tostring(r.类型 or '').." 当前序列="..tostring(r.当前序列 or '').." 闯关序列="..tostring(r.闯关序列 or '')
    end
  end
else
  out[6]="任务追踪栏不可用"
end
_G.__out=table.concat(out,"\n")
'''
print(lua(code))