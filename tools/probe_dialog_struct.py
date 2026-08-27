# -*- coding: utf-8 -*-
"""dump tp.窗口.对话栏 完整结构 — 会员传送界面数据源"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def isstring(v):
    return v == "string"

def dump_obj(path, depth=0, maxdepth=4, prefix=""):
    """递归 dump 一个 Lua 对象结构"""
    tmp = (
        "local function ind(d) return string.rep(\"  \", d) end\n"
        "local out = {}\n"
        "local function walk(p, d)\n"
        "  if d > _MAXD then return end\n"
        "  local t = p\n"
        "  if type(t) ~= \"table\" then\n"
        "    out[#out+1] = ind(d) .. \" : \" .. tostring(t) .. \" (\" .. type(t) .. \")\"\n"
        "    return\n"
        "  end\n"
        "  out[#out+1] = ind(d) .. \"  {table, len=\" .. tostring(#t) .. \"}\"\n"
        "  for i = 1, math.min(30, #t) do walk(t[i], d+1) end\n"
        "  for k, v in pairs(t) do\n"
        "    if not (type(k) == \"number\" and k >= 1 and k <= math.min(30, #t)) then\n"
        "      out[#out+1] = ind(d) .. \"  [\" .. tostring(k) .. \"]\"\n"
        "      walk(v, d+1)\n"
        "    end\n"
        "  end\n"
        "end\n"
        "walk(_PATH, 0)\n"
        "_G.__out = table.concat(out, \"\\n\")\n"
    )
    lua_body = ("local _MAXD = %d\n" % maxdepth) + \
               ("local _PATH = %s\n" % path) + tmp
    code = lua_body
    d = lua(code)
    return d.get("result", {}).get("value") or d.get("error")

# 只 dump 对话栏
print("=== 对话栏(会员传送) 结构 ===")
print(dump_obj("tp.窗口.对话栏", maxdepth=3))