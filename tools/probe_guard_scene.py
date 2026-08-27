# -*- coding: utf-8 -*-
"""探查当前场景里的护法 + 地图名 + 对话栏详情"""
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
local out = {}
out[1] = "当前地图=" .. tostring(tp.当前地图)
out[2] = "当前地图名=" .. tostring(tp.当前地图名字 or tp.场景名 or "")
out[3] = "战斗中=" .. tostring(tp.战斗中)
-- 场景里的护法
local guards = {}
local j = tp.场景.假人
if type(j) == "table" then
  for i = 1, #j do
    if type(j[i]) == "table" then
      local nm = tostring(j[i].名称 or "")
      if string.find(nm, "护法") then
        guards[#guards + 1] = nm .. "@" .. tostring(j[i].坐标 and (j[i].坐标.x .. "," .. j[i].坐标.y) or "?")
      end
    end
  end
end
out[4] = "护法列表=" .. table.concat(guards, " | ")
-- 对话详情
local d = tp.窗口.对话栏
out[5] = "对话名称=" .. tostring(d and d.名称) .. " 可视=" .. tostring(d and d.可视)
out[6] = "对话文本=" .. tostring(d and d.文本内容 or "")
_G.__out = table.concat(out, "\n")'''))