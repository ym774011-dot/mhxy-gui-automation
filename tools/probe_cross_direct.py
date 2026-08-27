# -*- coding: utf-8 -*-
"""探查 取传送点 函数 + 地图名/ID映射 + 实测合成desc跨图直达门派"""
import json, urllib.request, time, re

GW = "http://127.0.0.1:18083"
SECTS = ["大唐官府", "方寸山", "女儿村", "神木林", "化生寺", "盘丝洞",
         "阴曹地府", "无底洞", "魔王寨", "狮驼岭", "天宫", "普陀山",
         "凌波城", "五庄观", "龙宫"]


def jget(gw, path, data=None, timeout=15):
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


def expr(e):
    try:
        d = jget(GW, "/api/lua/expr", {"expr": e})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"


print("=== 1) 取传送点 函数签名/用法 ===")
print("取传送点=type:", expr("tostring(type(_G['取传送点'] or 'nil'))"))
code = r'''
local f = _G['取传送点']
local out = {}
if type(f) == "function" then
  -- 尝试无参调用
  local ok, r = pcall(f)
  out[#out+1] = "pcall()=" .. tostring(ok) .. " r=" .. tostring(r)
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 2) 搜地图名→ID 全局映射（含门派名）===")
code = r'''
local out = {}
local seen = {}
for k, v in pairs(_G) do
  if type(v) == "table" then
    for k2, v2 in pairs(v) do
      local s = tostring(type(v2)=='string' and v2 or k2)
      if string.find(s, "大唐官府") or string.find(s, "龙宫") or string.find(s, "天宫") then
        out[#out+1] = tostring(k) .. "[" .. tostring(k2) .. "]=" .. s
        if #out >= 40 then break end
      end
    end
  end
  if #out >= 40 then break end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 3) 实测合成 desc 跨图直达门派（当前长安）===")
cur = expr("tostring(tp.当前地图 or '')")
print("出发地图id =", cur)
# 只测几个，避免乱跳。用一个可回退的方案：每跳之前先记录，成功后跳回长安
home_desc = "长安传送金銮殿"   # 是 长安传送 表里可靠的一条，但会跳到金銮殿
# 更安全：跳回用 江南野外的传送表。先用长安内的传送回长安
def map_id():
    return expr("tostring(tp.当前地图 or '')")

for s in ["大唐官府"]:  # 先只测一个
    desc = "长安传送" + s
    print(f"\n--- 合成desc[{desc}] ---")
    try:
        d = jget(GW, "/api/act/cross_map", {"desc": desc, "x": 6160, "y": 80, "wait_ms": 2500, "sync": True})
        print("ok=", d.get("ok"), "resp=", str(d.get("result"))[:120])
    except Exception as e:
        print("cross err", e)
    time.sleep(2)
    print("跳后地图id =", map_id())