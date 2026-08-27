# -*- coding: utf-8 -*-
"""探查接触按钮结构（可能含关闭/X按钮），随后尝试右键关闭"""
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
local c = d and d.接触按钮
local out = {}
out[1] = "接触按钮type=" .. type(c)
if type(c) == "table" then
  local rows = {}
  for i = 1, 20 do
    local b = c[i]
    if type(b) ~= "table" then break end
    local j = b.选中判断
    local pos = ""
    if type(j) == "table" then
      pos = tostring(j.x) .. "," .. tostring(j.y) .. "," .. tostring(j.x2) .. "," .. tostring(j.y2)
    end
    rows[#rows + 1] = (tostring(b.文字 or b.名称 or b.Id or b.id or '') ) .. "@" .. pos
  end
  out[2] = "按钮数=" .. #rows
  out[3] = table.concat(rows, " | ")
else
  out[2] = tostring(c)
end
_G.__out = table.concat(out, "\n")'''))