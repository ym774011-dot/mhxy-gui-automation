# -*- coding: utf-8 -*-
"""重新触发并立即抓取 对话栏 文本行 + 选项 + 跳转desc"""
import json, urllib.request, time

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
        v = d.get("result", {}).get("value")
        if d.get("ok") is False:
            return f"<LUA_ERR:{d.get('error')}>"
        return v
    except Exception as e:
        return f"<EXC {e}>"

# 1) 重新触发 门派闯关使者
code = r'''
local t = nil
for id, u in pairs(tp.场景.场景人物 or {}) do
  if type(u)=="table" and tostring(u.名称 or "")=="门派闯关使者" then t=u break end
end
local ok, r = pcall(function() if t and t["事件开始"] then return t["事件开始"](t) end end)
_G.__out = tostring(ok) .. " r=" .. tostring(r)'''
print("触发:", lua(code))
time.sleep(0.6)

# 2) 抓对话栏
print("\n=== 对话栏 状态 + 文本行 ===")
code = r'''
local d = tp.窗口.对话栏
local out = {}
out[#out+1] = "可视=" .. tostring(d and d.可视) .. " 名称=" .. tostring(d and d.名称)
out[#out+1] = "文本内容=" .. tostring(d and d.文本内容 or "")
out[#out+1] = "行数量=" .. tostring(d and d.丰富文本 and d.丰富文本.行数量 or "?")
-- 显示表文本行
if d and d.丰富文本 and d.丰富文本.显示表 then
  for k, v in pairs(d.丰富文本.显示表) do
    if type(v)=="table" then
      out[#out+1] = "  行["..tostring(k).."] 内容="..tostring(v.内容 or "")
    end
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))

print("\n=== 对话栏.选项 数量与文字 ===")
code = r'''
local opt = tp.窗口.对话栏.选项
local out = {}
if type(opt) ~= "table" then out[1]="NOTABLE:"..type(opt) else
  local n = 0
  for i = 1, 30 do
    local o = opt[i]
    if type(o) ~= "table" then break end
    n = n + 1
    out[#out+1] = "["..i.."] 文字="..tostring(o.文字 or "").." 名称="..tostring(o.名称 or "").." 跳转="..tostring(o.跳转 or o.链接 or o.执行 or "")
  end
  out[#out+1] = "_count="..n
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))