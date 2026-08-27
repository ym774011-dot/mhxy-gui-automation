# -*- coding: utf-8 -*-
"""用 Lua 直接 CALL 道具行囊:打开() 打开背包"""
import json, urllib.request, time
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("打开前 可视:", lua(r'_G.__out=tostring(tp.窗口 道具行囊 и tp.窗口.道具行囊.可视)'))
print("打开前 可视(正确写法):", lua(r'_G.__out=tostring(tp.窗口 and tp.窗口.道具行囊 and tp.窗口.道具行囊.可视)'))
print("尝试 :打开() :")
print(lua(r'''
local b=tp.窗口 and tp.窗口.道具行囊
local ok,err = pcall(function() return b["打开"](b) end)
_G.__out="打开调用 ok="..tostring(ok).." r/err="..tostring(err)'''))
time.sleep(0.8)
print("打开后 可视:", lua(r'_G.__out=tostring(tp.窗口 and tp.窗口.道具行囊 and tp.窗口.道具行囊.可视)'))
print("物品数量/找卡:", lua(r'''
local b=tp.窗口 and tp.窗口.道具行囊
local out={}
local card=false
local function scan(t)
  if type(t)=="table" then
    if type(t.名称)=="string" and tostring(t.名称)=="鲜衣怒马会员卡" then card=true end
    for _,v in pairs(t) do if not card and type(v)=="table" then scan(v) end end
  end
end
scan(b)
out[1]="会员卡="..tostring(card)
_G.__out=table.concat(out,"\n")'''))