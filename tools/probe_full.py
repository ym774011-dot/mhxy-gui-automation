# -*- coding: utf-8 -*-
"""全面探查：类型107记录全部字段 + 使者完整对话树（是否含查看当前目标菜单）。"""
import json, sys, time, urllib.request
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from library.map_packs import MPCG as M

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

# 1) 类型107记录全部字段
print("==== 类型107 记录全字段dump ====")
print(lua(r'''
local out={}
local t=tp.窗口.任务追踪栏.数据记录
for k,v in pairs(t or {}) do
  if type(v)=='table' and tostring(v.类型 or '')=='107' then
    for fk,fv in pairs(v) do
      if type(fv)=='table' then
        local s={}
        for i=1,#fv do s[#s+1]=tostring(fv[i]) end
        out[#out+1]=fk..'=table['..table.concat(s,',')..']'
      elseif type(fv)=='boolean' then
        out[#out+1]=fk..'='..tostring(fv)
      else
        out[#out+1]=fk..'='..tostring(fv)
      end
    end
  end
end
_G.__out=table.concat(out,'\n')
'''))

# 2) 场景假人里是否有使者本体（含更多属性/菜单）
print("==== 场景中大门派闯关相邻假人 ====")
print(lua(r'''
local out={}
local j=tp.场景.假人
if type(j)=='table' then
  for i=1,#j do
    if type(j[i])=='table' and (tostring(j[i].名称 or '')):find('门派闯关') then
      out[#out+1]=i..':'..tostring(j[i].名称 or '')
      for fk,fv in pairs(j[i]) do
        if type(fv)~='table' and type(fv)~='function' and not string.find(tostring(fk),'^%u') == false then
          out[#out+1]= '   '..fk..'='..tostring(fv)
        end
      end
    end
  end
end
_G.__out=table.concat(out,'\n')
'''))