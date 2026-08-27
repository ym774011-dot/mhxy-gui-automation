# -*- coding: utf-8 -*-
"""探查 物品使用路由：找打开会员传送窗口的入口 + 物品click/使用 函数"""
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


print("=== 1) tp._物品.super 的全部方法 ===")
code = r'''
local m = tp._物品
local out = {}
local function dump(t, prefix)
  if type(t) ~= "table" then return end
  for k, v in pairs(t) do
    if type(v) == "function" then
      out[#out+1] = prefix .. tostring(k) .. "() = " .. tostring(v)
    else
      out[#out+1] = prefix .. tostring(k) .. " = " .. type(v)
    end
  end
end
if type(m) == "table" then
  dump(m, "")
  dump(m.super, "super.")
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 2) 全局限函数名含 使用/道具/点击/会员/门派 ===")
code = r'''
local out = {}
for k, v in pairs(_G) do
  local ks = tostring(k)
  if (string.find(ks, "使用") or string.find(ks, "道具") or string.find(ks, "会员") or
      string.find(ks, "门派") or string.find(ks, "传送") or string.find(ks, "物品")) then
    if type(v) == "function" or type(v) == "table" then
      out[#out+1] = ks .. " : " .. type(v)
    end
    if #out >= 80 then break end
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 3) GET /api/globals 全部全局名（找使用入口）===")
try:
    d = jget(GW, "/api/globals", {"filter": "使用|道具|会员|门派|物品"})
    gl = d.get("result", {})
    if isinstance(gl, dict):
        g = gl.get("globals") or gl.get("names") or gl
        if isinstance(g, list):
            print("\n".join(str(x) for x in g[:60]))
        else:
            print(json.dumps(gl, ensure_ascii=False)[:2000])
    else:
        print(json.dumps(d, ensure_ascii=False)[:2000])
except Exception as e:
    print("globals err:", e)