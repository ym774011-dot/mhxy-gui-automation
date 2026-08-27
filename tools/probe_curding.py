# -*- coding: utf-8 -*-
"""即时读取当前对话栏（会员卡可能仍开） + 每日活动初始化按钮"""
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
        if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

print("=== 当前 对话栏 状态 ===")
code = r'''
local d = tp.窗口.对话栏
local out = {}
out[#out+1] = "可视=" .. tostring(d and d.可视) .. " 名称=" .. tostring(d and d.名称)
out[#out+1] = "文本内容=" .. tostring(d and d.文本内容 or "")
local opt = d and d.选项
local n = 0
if type(opt)=="table" then for _ in pairs(opt) do n=n+1 end end
out[#out+1] = "选项数=" .. tostring(n)
for i=1,math.min(n,30) do
  local o = opt[i]
  if type(o)=="table" then
    out[#out+1] = "  ["..i.."] 文字="..tostring(o.文字 or o.基本内容 or "").." 跳转="..tostring(o.跳转 or o.跳转链接 or "")
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))

print("\n=== 每日活动.初始tp.窗口.道具行囊 顶层 ===")
code = r'''
local d = tp.窗口.每日活动.初始tp.窗口.道具行囊
local out = {}
if type(d)~="table" then out[1]="NOTABLE" else
  for k,v in pairs(d) do out[#out+1]=tostring(k).." : "..type(v) end
end
table.sort(out)
_G.__out=table.concat(out,"\n")'''
print(lua(code))