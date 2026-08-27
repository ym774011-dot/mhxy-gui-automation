# -*- coding: utf-8 -*-
"""读取当前对话内容与选项坐标"""
import json, urllib.request
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return "<ERR>: " + str(d.get("error"))
    v = d.get("result", {}).get("value")
    return v if v is not None else "(nil)"

print(lua(r'''
local d = tp.窗口.对话栏
local rows = {}
rows[1] = '名='..tostring(d.名称 or '')..' | 文='..tostring(d.文本内容 or '')
local o = d.选项
if type(o)=='table' then
  for i=1,20 do
    local it = o[i]
    if type(it)~='table' then break end
    local j = it.选中判断
    local cx,cy = '',''
    if type(j)=='table' then
      cx = tostring((tonumber(j.x or 0)+tonumber(j.x2 or 0))/2)
      cy = tostring((tonumber(j.y or 0)+tonumber(j.y2 or 0))/2)
    end
    rows[#rows+1] = '  opt'..i..'['..tostring(it.跳转链接 or it.基本内容 or '')..'] c=('..cx..','..cy..')'
  end
end
_G.__out = table.concat(rows,'\n')
'''))