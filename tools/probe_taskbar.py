# -*- coding: utf-8 -*-
"""dump 任务追踪栏所有字段（找渲染文本=真实目标门派），以及窗口内可能的文本控件。"""
import json, sys, urllib.request
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")

GW = "http://127.0.0.1:18083"
def lua(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

print("== 任务追踪栏顶层字段 ==")
print(lua(r'''
local out={}
local tb=tp.窗口.任务追踪栏
if not tb then _G.__out='无任务追踪栏'; return end
for k,v in pairs(tb) do
  if type(v)=='function' then
    out[#out+1]=k..'=<func>'
  elseif type(v)=='table' then
    out[#out+1]=k..'=<table>'
  else
    out[#out+1]=k..'='..tostring(v)
  end
end
_G.__out=table.concat(out,'\n')
'''))

print("== 任务追踪栏.数据记录 每条原始(含文本/list) ==")
print(lua(r'''
local out={}
for k,v in pairs((tp.窗口.任务追踪栏.数据记录 or {})) do
  if type(v)=='table' then
    out[#out+1]='REC-'..tostring(k)..':'
    for fk,fv in pairs(v) do
      if type(fv)=='table' then
        local parts={}
        for i=1,math.min(#fv,6) do parts[#parts+1]=tostring(fv[i]) end
        out[#out+1]= '  '..fk..'=table['..table.concat(parts,',')..']'
      else
        out[#out+1]= '  '..fk..'='..tostring(fv)
      end
    end
  end
end
if #out==0 then out[1]='(无记录)' end
_G.__out=table.concat(out,'\n')
'''))

print("== 全局场景/任务相关文本 (搜索门派名关键词) ==")
print(lua(r'''
local out={}
local names={'魔王寨','阴曹地府','盘丝洞','无底洞','五庄观','龙宫','普陀山','凌波城','天宫','化生寺','女儿村','方寸山','神木林','狮驼岭','大唐官府','门派闯关'}
-- 从任务追踪栏 instanced 表找文本
for _,nm in ipairs(names) do
  local found=false
  local function scan(v)
    if found then return end
    if type(v)=='table' then
      for kk,vv in pairs(v) do
        if found then return end
        if type(vv)=='table' then scan(vv)
        elseif type(vv)=='string' and string.find(vv,nm) then
          out[#out+1]=nm..' << '..tostring(kk)..'='..vv; found=true
        elseif type(vv)=='number' and vv==nm then
          -- no
        end
      end
    end
  end
  scan(tp.窗口.任务追踪栏)
end
if #out==0 then out[1]='(任务追踪栏内未找到门派关键词)' end
_G.__out=table.concat(out,'\n')
'''))