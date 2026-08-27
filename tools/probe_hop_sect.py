# -*- coding: utf-8 -*-
"""探查 tp.场景.传送 是否有直达门派图（用跨图 CALL 替代会员卡菜单）"""
import json, urllib.request
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")

code = []
code.append("local t = tp.场景.传送")
code.append("_G.__out = '当前地图=' .. tostring(tp.当前地图)")
code.append("if type(t) ~= 'table' then _G.__out = _G.__out .. '\\n无传送表' return end")
code.append("local sects = {'大唐官府','方寸山','化生寺','凌波城','龙宫','魔王寨','女儿村','普陀山','盘丝洞','神木林','狮驼岭','天宫','无底洞','五庄观','阴曹地府'}")
code.append("local hit = {}")
code.append("local n = 0")
code.append("for i = 1, #t do")
code.append("  local s = tostring(t[i].切换 or '')")
code.append("  if string.len(s) > 0 then")
code.append("    n = n + 1")
code.append("    for _, sn in ipairs(sects) do")
code.append("      if string.find(s, sn) then hit[#hit+1] = tostring(i) .. ':' .. s end")
code.append("    end")
code.append("  end")
code.append("end")
code.append("_G.__out = _G.__out .. '\\n传送条数=' .. tostring(#t) .. ' 非空=' .. tostring(n) .. ' 门派命中=' .. tostring(#hit) .. ' => [' .. table.concat(hit, ' | ') .. ']'")
print(lua("\n".join(code)))