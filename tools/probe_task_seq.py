# -*- coding: utf-8 -*-
"""直接读取任务追踪栏 类型=107 记录的 当前序列+闯关序列+全部字段"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("=== 类型=107 记录全字段 ===")
print(lua(r'''
local recs = tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录
local out = {}
if type(recs)~="table" then out[1]="无数据记录"; _G.__out=table.concat(out,"\n"); return end
local found=0
-- 遍历记录
local function walk(vt, path)
  if type(vt)~="table" then return end
  for k,v in pairs(vt) do
    if type(v)=="table" then
      local t = v.类型 or v.type
      if tostring(t)=="107" then
        found=found+1
        out[#out+1]="### 记录#"..found.." path="..path.."["..tostring(k).."]"
        -- 收集该记录下非表字段
        for k2,v2 in pairs(v) do
          if type(v2)~="table" then
            out[#out+1]="   "..tostring(k2).." = "..tostring(v2)
          else
            -- 闯关序列/当前序列 可能是表或数字
            local ks = tostring(k2)
            if string.find(ks,"序列") or string.find(ks,"闯关") or string.find(ks,"当前") then
              local sub={}
              local n=0
              for i=1,20 do
                local t=v2[i]
                if t==nil then break end
                n=n+1; sub[#sub+1]=tostring(t)
              end
              out[#out+1]="   "..ks.." = {"..table.concat(sub,",").."} (n="..n..")"
            end
          end
        end
      end
      walk(v, path.."["..tostring(k).."]")
    end
  end
end
walk(recs, "记录")
out[#out+1]="_found107="..found
_G.__out=table.concat(out,"\n")'''))