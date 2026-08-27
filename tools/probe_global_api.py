# -*- coding: utf-8 -*-
"""最后确认：搜索 G 层 / tp 顶层 的可CALL传送/使用函数"""
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
# tp 顶层键
code.append("local out = {}")
code.append("local tpk = {}")
code.append("for k, v in pairs(tp) do if type(k) == 'string' then tpk[#tpk+1] = k .. ':' .. type(v) end end")
code.append("table.sort(tpk)")
code.append("out[1] = '[tp顶层] ' .. table.concat(tpk, ' ')")
# G 层中与 传送/跳转/使用/物品/会员/快捷键 相关函数
code.append("local gfun = {}")
code.append("for k, v in pairs(_G or {}) do")
code.append("  if type(v) == 'function' and type(k) == 'string' then")
code.append("    if string.find(k, '传送') or string.find(k, '跳转') or string.find(k, '移动') or string.find(k, '使用') or string.find(k, '物品') or string.find(k, '会员') or string.find(k, '道具') then")
code.append("      gfun[#gfun+1] = k")
code.append("    end")
code.append("  end")
code.append("end")
code.append("out[2] = '[G层函数] ' .. table.concat(gfun, ' ')")
code.append("_G.__out = table.concat(out, '\\n')")
print(lua("\n".join(code)))