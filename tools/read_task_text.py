# -*- coding: utf-8 -*-
"""读取 任务栏 / 任务追踪栏 显示的当前目标文本（游戏权威显示）"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("=== 任务栏(主任务窗口) dump ===")
print(lua(r'''
local tb=tp.窗口.任务栏
local out={}
if type(tb)=="table" then
  for k,v in pairs(tb) do
    local tv=type(v)
    if tv~="table" then out[#out+1]=tostring(k).."="..tostring(v)
    else
      -- 递归找含"前往/护法/门派"的字符串文本
      local function findstr(t,tbl_path,depth)
        if depth>5 then return end
        for k2,v2 in pairs(t) do
          if type(v2)=="string" and (string.find(v2,"前往") or string.find(v2,"护法") or string.find(v2,"门派") or string.find(v2,"考验")) then
            out[#out+1]=tbl_path.."."..tostring(k2).." = "..v2
          elseif type(v2)=="table" then findstr(v2,tbl_path.."."..tostring(k2),depth+1) end
        end
      end
      findstr(v,tostring(k),0)
    end
  end
else out[1]="无任务栏" end
_G.__out=table.concat(out,"\n")'''))

print("\n=== 任务追踪栏 显示文本 ===")
print(lua(r'''
local zz=tp.窗口.任务追踪栏
local out={}
if type(zz)=="table" then
  -- 常见字段：文本, 标题, 任务列表, 文本行
  out[#out+1]="可视="..tostring(zz.可视)
  for k,v in pairs(zz) do
    if type(v)=="string" and v~="" then out[#out+1]=tostring(k).."="..v end
  end
  -- 递归所有字符串
  local seen={}
  local function findstr(t,path,depth)
    if depth>6 or seen[t] then return end
    seen[t]=true
    for k2,v2 in pairs(t) do
      if type(v2)=="string" and v2~="" and (string.find(v2,"前往") or string.find(v2,"护法") or string.find(v2,"魔王") or string.find(v2,"大唐") or string.find(v2,"挑战") or string.find(v2,"闯关") or string.find(v2,"考验") or string.find(v2,"当前")) then
        out[#out+1]=path.."."..tostring(k2).." = "..v2
      elseif type(v2)=="table" then findstr(v2,path.."."..tostring(k2),depth+1) end
    end
  end
  findstr(zz,"追踪",0)
else out[1]="无追踪栏" end
_G.__out=table.concat(out,"\n")'''))