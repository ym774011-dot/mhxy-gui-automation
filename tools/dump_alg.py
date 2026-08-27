# -*- coding: utf-8 -*-
"""傲来国 → 花果山：dump传送路线 + 场景人物（找花果山入口NPC）。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua, http_json, cur_map

# 传送路线
code1 = r'''
local out = {}
local ok, err = pcall(function()
  local r = tp.场景.传送路线
  if r then
    for k,v in pairs(r) do
      local sv
      if type(v) == "table" then
        local parts = {}
        for kk,vv in pairs(v) do parts[#parts+1] = tostring(kk).."="..tostring(vv) end
        sv = "{"..table.concat(parts,",").."}"
      else
        sv = tostring(v)
      end
      out[#out+1] = tostring(k).." -> "..sv
    end
  else
    out[#out+1] = "no_routes"
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, "\n")
'''
print('路线:', lua(code1))

# 场景人物（找船夫/入口）
code2 = r'''
local out = {}
local t = tp.场景.场景人物
if t then for k,v in pairs(t) do
  local n = tostring(v.名称 or "?")
  if not n:find("灵猴") and not n:find("妖魔") then
    local id = tostring(v.编号 or v.ID or "?")
    local x = v.坐标 and string.format("%.0f", v.坐标.x) or "?"
    local y = v.坐标 and string.format("%.0f", v.坐标.y) or "?"
    out[#out+1] = n.."#"..id.."@"..x..","..y
  end
end end
_G.__out = table.concat(out, " ;; ")
'''
print('人物:', lua(code2))
