# -*- coding: utf-8 -*-
"""读取当前对话栏的选项列表（文字/跳转/坐标）"""
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
        if d.get("ok") is False:
            return f"<LUA_ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

print(lua(r'''
local d = tp.窗口.对话栏
local out = {}
out[1] = "名称=" .. tostring(d and d.名称)
out[2] = "文本内容=" .. tostring(d and d.文本内容 or "")
local opt = d and d.选项
out[#out+1] = "选项 类型=" .. type(opt)
if type(opt)=="table" then
  local n=0
  for i=1,40 do
    local o = opt[i]
    if type(o)~="table" then break end
    n=n+1
    out[#out+1] = "["..i.."] 文字="..tostring(o.文字 or "") .. " 跳转="..tostring(o.跳转 or o.链接 or o.执行 or o.事件 or "")
  end
  out[#out+1] = "_count="..n
end
out[#out+1] = "--- 全部字段 ---"
if type(opt)=="table" then
  for k,v in pairs(opt) do
    if type(v)=="table" then
      local sub={}
      for k2,v2 in pairs(v) do
        if type(v2)=="table" then sub[#sub+1]=tostring(k2).."{}"
        else sub[#sub+1]=tostring(k2).."="..tostring(v2) end
      end
      out[#out+1]=tostring(k).."={"..table.concat(sub,", ").."}"
    else
      out[#out+1]=tostring(k).."="..tostring(v)
    end
  end
end
_G.__out=table.concat(out,"\n")'''))