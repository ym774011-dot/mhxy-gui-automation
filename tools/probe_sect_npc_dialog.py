# -*- coding: utf-8 -*-
"""触发 门派传送人/圣山传送人 事件，抓传送选项"""
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
        if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

def trigger(npc_name):
    code = r'''
local t=nil
for id,u in pairs(tp.场景.场景人物 or {}) do
  if type(u)=="table" and tostring(u.名称 or "")=="NPCN" then t=u break end
end
local ok,r=pcall(function() if t and t["事件开始"] then return t["事件开始"](t) end end)
_G.__out = tostring(ok).." r="..tostring(r)'''.replace("NPCN", npc_name)
    print("触发", npc_name, ":", lua(code))
    time.sleep(0.7)

def dump_dialog(tag):
    code = r'''
local d = tp.窗口.对话栏
local out = {}
out[#out+1] = "名称="..tostring(d and d.名称)
out[#out+1] = "文本内容="..tostring(d and d.文本内容 or "")
local opt = d and d.选项
if type(opt) ~= "table" then out[#out+1]="_opts: NOTABLE" else
  out[#out+1]="_opts:"
  local n=0
  for i=1,20 do
    local o=opt[i]
    if type(o)~="table" then break end
    n=n+1
    local bits={}
    for k,v in pairs(o) do
      if type(v)=="table" then bits[#bits+1]=tostring(k).."{...}"
      else bits[#bits+1]=tostring(k).."="..tostring(v) end
    end
    out[#out+1]=tostring(i)..": {"..table.concat(bits,"; ").."}"
  end
  out[#out+1]="_opt_count="..n
end
_G.__out = table.concat(out,"\n")'''
    print(f"--- {tag} ---")
    print(lua(code))

trigger("圣山传送人")
dump_dialog("圣山传送人")
trigger("门派传送人")
dump_dialog("门派传送人")