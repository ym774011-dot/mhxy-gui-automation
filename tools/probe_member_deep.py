# -*- coding: utf-8 -*-
"""深入探查：定位『鲜衣怒马会员卡』及门派传送锚点 / GIF码"""
import json, urllib.request

GW = "http://127.0.0.1:18083"


def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"


def expr(e):
    try:
        d = jget(GW, "/api/lua/expr", {"expr": e})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"


def jget(gw, path, data=None, timeout=15):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


print("=== 1) 列出道具列表全部物品（名称/数量/是否会员相关）===")
code = r'''
local out = {}
local t = tp.道具列表
if type(t) ~= "table" then out[1]="NOTABLE" else
  local n = 0
  for id, it in pairs(t) do
    n = n + 1
    local nm = tostring(type(it)=="table" and (it.名称 or it.名字 or it.name or "") or t)
    out[#out+1] = tostring(id) .. "|" .. nm
  end
  out[#out+1] = "_count=" .. n
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 2) 通配搜含『会员』/『门派』/『传送』的窗口字段 ===")
for kw in ["会员", "门派传送", "传送"]:
    kwl = kw
    code = (
        r"local out = {} "
        r"local seen = {} "
        r"local function scan(t, path) "
        r"  if type(t) ~= 'table' then return end "
        r"  for k, v in pairs(t) do "
        r"    local ks = tostring(k) "
        r"    if string.find(ks, KW) then "
        r"      if not seen[ks] then seen[ks] = true; if #out < 80 then "
        r"        local nm = (type(v)=='table') and tostring(v.名称 or '') or '' "
        r"        out[#out+1] = path .. '.' .. ks .. ' : ' .. type(v) .. ' | 名称=' .. nm end end "
        r"    end "
        r"  end "
        r"end "
        r"scan(tp, 'tp') "
        r"scan(tp.窗口 or {}, 'tp.窗口') "
        r"scan(tp.场景 or {}, 'tp.场景') "
        r"_G.__out = table.concat(out, '\n')"
    ).replace("KW", "'" + kwl + "'")
    print(f"--- 关键词[{kw}] ---")
    print(lua(code))