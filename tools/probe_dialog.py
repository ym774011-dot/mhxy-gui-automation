# -*- coding: utf-8 -*-
"""dump 当前对话栏全部字段（名称/文本/选项文字与选中判断）"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

# 解析闯关序列 table
code = r'''
local recs=tp.窗口.任务追踪栏.数据记录
local out={"闯关序列解析:"}
for i,r in ipairs(recs) do
  if type(r)=='table' and r.类型==107 then
    local q=r.闯关序列
    if type(q)=='table' then
      local parts={}
      for idx=1,#q do parts[#parts+1]=tostring(q[idx]) end
      out[#out+1]="闯关序列="..table.concat(parts,",")
    else
      out[#out+1]="闯关序列(非表)="..tostring(q)
    end
  end
end
_G.__out=table.concat(out,"\n")
'''
print(lua(code))
print("---- 对话栏 dump ----")
code2 = r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d and d.可视 or false)
out[2]="名="..tostring(d and d.名称 or '')
out[3]="文本="..tostring(d and d.文本内容 or '')
if d and d.选项 then
  out[#out+1]="选项数="..tostring(#d.选项)
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local sel=""
    if o.选中判断 then
      local a=o.选中判断
      sel=" [sel="..tostring(a.x or '')..","..tostring(a.y or '')..","..tostring(a.x2 or '')..","..tostring(a.y2 or '').."]"
    end
    out[#out+1]=i..":"..tostring(o.文字 or '').." | "..tostring(o.跳转链接 or '')..sel
  end
end
_G.__out=table.concat(out,"\n")
'''
print(lua(code2))