# -*- coding: utf-8 -*-
"""探查当前状态：袋/对话栏/卡item位置(右键卡重开菜单用)"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def show(tag, code):
    d = lua(code)
    v = d.get("result", {}).get("value")
    print(f"=== {tag} ===")
    print(v if v is not None else ("<ERR: %s>" % d.get("error")))

# 当前地图 + 坐标 + 对话栏状态
show("地图/坐标/对话栏", r'''
local out = {}
out[#out+1] = "当前地图=" .. tostring(tp.当前地图 or "")
out[#out+1] = "坐标=" .. tostring(tp.角色坐标.x) .. "," .. tostring(tp.角色坐标.y)
local d = tp.窗口.对话栏
out[#out+1] = "对话栏可视=" .. tostring(d and d.可视 or false) .. " 名称=" .. tostring(d and d.名称 or "")
local opt = d and d.选项
local n = 0
if type(opt) == "table" then for _ in pairs(opt) do n = n + 1 end end
out[#out+1] = "对话栏选项数=" .. tostring(n)
local bag = tp.窗口.道具行囊
out[#out+1] = "袋可视=" .. tostring(bag and bag.可视 or false)
_G.__out = table.concat(out, "\n")''')

# 卡item 在袋里的位置信息 (物品表 i=1)
show("袋物品[1](卡) 位置字段", r'''
local bag = tp.窗口.道具行囊
local items = bag and bag.物品
local out = {}
if type(items) ~= "table" then out[1] = "NOTABLE" else
  local seen = 0
  for k, it in pairs(items) do
    if type(it) == "table" then
      local nm = tostring(it.名称 or it.名字 or "")
      if nm == "鲜衣怒马会员卡" or seen == 0 then
        seen = seen + 1
        out[#out+1] = "-- key=" .. tostring(k) .. " 名称=" .. nm
        for fk, fv in pairs(it) do
          if not (type(fv) == "table" or type(fv) == "function") then
            out[#out+1] = "   " .. tostring(fk) .. "=" .. tostring(fv)
          end
        end
        if seen > 3 then break end
      end
    end
  end
end
_G.__out = table.concat(out, "\n")''')