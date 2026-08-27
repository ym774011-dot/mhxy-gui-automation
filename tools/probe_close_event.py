# -*- coding: utf-8 -*-
"""尝试用 Lua 调用对话栏关闭事件，并验证对话框是否关闭"""
import json, urllib.request, time
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
def close_vis():
    v = lua("_G.__out = tostring(tp.窗口.对话栏.可视 or false)")
    return (v or "").strip()
print("关闭前可视=", close_vis())
# 尝试调用 关闭事件
code = r'''
local d = tp.窗口.对话栏
local f = d.关闭事件
local ok, err = false, nil
if f then ok, err = pcall(function() return f(d) end) end
_G.__out = tostring(ok) .. (err and (":" .. tostring(err)) or "")
'''
print("调用关闭事件结果=", lua(code))
time.sleep(0.8)
print("关闭后可视=", close_vis())