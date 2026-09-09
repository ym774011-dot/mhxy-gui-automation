# -*- coding: utf-8 -*-
"""一次性诊断：用 pcall 包住，dump tp / 主界面 / 界面数据 真实结构。用完即删。"""
import sys
sys.path.insert(0, ".")
from tasks.library.ZGUI import _lua_call

G = "http://127.0.0.1:18082"

LUA = r"""
local out = {}
local function step(s) out[#out+1] = s end
local function keys(t, limit)
  limit = limit or 300
  local a = {}
  local n = 0
  for k, v in pairs(t) do
    n = n + 1
    a[#a+1] = tostring(k) .. ':' .. type(v)
  end
  local s = table.concat(a, ',')
  if #s > limit then s = s:sub(1, limit) .. '…(' .. n .. '项)' end
  return s
end
local ok, emsg = pcall(function()
  step('tp=' .. type(tp))
  if type(tp) ~= 'table' then return end
  step('tpkeys=' .. keys(tp))
  local m = tp.主界面
  step('主界面=' .. type(m))
  if type(m) ~= 'table' then return end
  step('主界面keys=' .. keys(m))
  local j = m.界面数据
  step('界面数据=' .. type(j))
  if type(j) ~= 'table' then return end
  local parts = {}
  for idx, pd in pairs(j) do
    if type(pd) == 'table' then
      parts[#parts+1] = tostring(idx) .. '=' .. tostring(pd.本类开关)
    end
  end
  step('panels(本类开关)=' .. table.concat(parts, ' '))
end)
if not ok then step('ERROR: ' .. tostring(emsg)) end
__out = table.concat(out, '\n')
"""

print(">>> 诊断 tp 结构（pcall 包裹）:")
print(_lua_call(G, LUA) or "(nil)")
print()
print(">>> 探测其他可能的背包路径:")
ALT = r"""
local out = {}
local cands = {'行囊','背包','bag','package','item','物品','行囊界面','背包界面'}
for _, c in ipairs(cands) do
  local v = tp[c]
  out[#out+1] = c .. '=' .. type(v)
end
-- 也看 tp.主界面 下有没有类似名字
if type(tp.主界面) == 'table' then
  for k, v in pairs(tp.主界面) do
    local s = tostring(k)
    if s:find('包') or s:find('行囊') or s:find('物品') or s:find('界面') then
      out[#out+1] = '主界面.' .. s .. '=' .. type(v)
    end
  end
end
__out = table.concat(out, '\n')
"""
print(_lua_call(G, ALT) or "(nil)")
