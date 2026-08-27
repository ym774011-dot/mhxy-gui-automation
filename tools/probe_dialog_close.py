# -*- coding: utf-8 -*-
"""探查对话框结构：位置/尺寸/关闭按钮，用于右键关闭"""
import json, urllib.request
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
print(lua(r'''
local d = tp.窗口.对话栏
local out = {}
if type(d) ~= "table" then out[1] = "对话栏=nil" else
  out[1] = "可视=" .. tostring(d.可视)
  out[2] = "x=" .. tostring(d.x or d.x1 or '') .. " y=" .. tostring(d.y or '')
  out[3] = "x2=" .. tostring(d.x2 or '') .. " y2=" .. tostring(d.y2 or '')
  out[4] = "宽=" .. tostring(d.宽 or '') .. " 高=" .. tostring(d.高 or '')
  out[5] = "名称=" .. tostring(d.名称 or '')
end
-- 所有按钮/选项（含关闭）
local btns = {}
for i = 1, 30 do
  local o = d and d.按钮 and d.按钮[i]
  if type(o) ~= "table" then break end
  btns[#btns + 1] = tostring(o.文字 or o.名称 or o.跳转 or '') .. "@" .. tostring(o.选中判断 and (type(o.选中判断)=='table' and ((o.选中判断.x or 0)+ (o.选中判断.x2 or 0))/2 .. "," .. ((o.选中判断.y or 0)+(o.选中判断.y2 or 0))/2 or '') or '')
end
-- 含顶级键（探查可能存在的字段名）
local keys = {}
if type(d) == "table" then
  for k, _ in pairs(d) do
    if type(k) == "string" then keys[#keys + 1] = k end
  end
end
out[6] = "按钮列表=" .. table.concat(btns, " | ")
out[7] = "对话栏字段=" .. table.concat(keys, ",")
_G.__out = table.concat(out, "\n")'''))