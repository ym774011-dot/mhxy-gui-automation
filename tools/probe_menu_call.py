# -*- coding: utf-8 -*-
"""打开会员卡菜单后，探查 对话栏 及其选项是否有可 CALL 的函数字段"""
import json, urllib.request, time, os, sys, ctypes
GW = "http://127.0.0.1:18083"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from core.window_manager import window_manager
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")

pid = (json.loads(urllib.request.urlopen(GW + "/api/status", timeout=10)
                  .read().decode("utf-8", "replace")).get("result") or {}).get("pid")
window_manager.bind(pid=int(pid))
hwnd = getattr(window_manager, "hwnd", None)
u = ctypes.windll.user32
def rclick(cx, cy):
    lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp)

# 会员卡坐标（上次探测 352,194）
rclick(352, 194)
time.sleep(1.3)
print(lua(r'''
local out = {}
local d = tp.窗口.对话栏
out[1] = "可视=" .. tostring(d and d.可视) .. " 名称=" .. tostring(d and d.名称 or '')
-- 对话栏函数字段
local df = {}
local ds = {}
if type(d) == "table" then
  for k, v in pairs(d) do
    if type(k) == "string" then
      if type(v) == "function" then df[#df+1] = k
      elseif type(v) ~= "table" then ds[#ds+1] = k
      end
    end
  end
end
out[2] = "[对话栏] 函数=" .. table.concat(df, ", ")
out[3] = "[对话栏] 字段=" .. table.concat(ds, ", ")
-- 选项结构：文字/跳转链接 + 是否有函数字段
local rows = {}
if d and d.选项 then
  for i = 1, 20 do
    local o = d.选项[i]
    if type(o) ~= "table" then break end
    local of = {}
    for k, v in pairs(o) do
      if type(k) == "string" and type(v) == "function" then of[#of+1] = k end
    end
    rows[#rows+1] = "选项" .. i .. "=" .. tostring(o.文字 or o.跳转链接 or '') .. " 函数[" .. table.concat(of, ",") .. "]"
  end
end
out[4] = table.concat(rows, " | ")
_G.__out = table.concat(out, "\n")'''))