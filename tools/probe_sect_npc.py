# -*- coding: utf-8 -*-
"""dump 门派传送人(初始tp.场景.假人 与 当前场景) 的门派传送列表"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=25):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"

# 1) dump 门派传送人(假人12) 完整结构
print("=== 每日活动.初始tp.场景.假人[12] 门派传送人 ===")
code = r'''
local d = tp.窗口.每日活动.初始tp.场景.假人
local out = {}
if type(d) ~= "table" then out[1]="NOTABLE" end
-- 枚举所有假人键, 先找名称=门派传送人/圣山传送人/门派闯关使者 的索引
for k, v in pairs(d) do
  if type(v) == "table" then
    local nm = tostring(v.名称 or "")
    if string.find(nm, "门派传送人") or string.find(nm, "圣山传送人") or string.find(nm, "门派闯关") then
      out[#out+1] = "== 假人 " .. tostring(k) .. " 名称=" .. nm .. " =="
      for fk, fv in pairs(v) do
        local tv = type(fv)
        if tv == "table" then
          local sub = {}
          for s2, v2 in pairs(fv) do
            if type(v2) == "table" then sub[#sub+1] = tostring(s2).."{...}"
            else sub[#sub+1] = tostring(s2).."="..tostring(v2) end
          end
          out[#out+1] = "  " .. tostring(fk) .. " = {" .. table.concat(sub, ", ") .. "}"
        elseif tv == "function" then
          out[#out+1] = "  " .. tostring(fk) .. " = function"
        else
          out[#out+1] = "  " .. tostring(fk) .. " = " .. tostring(fv) .. " (" .. tv .. ")"
        end
      end
      out[#out+1] = ""
    end
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))