# -*- coding: utf-8 -*-
import json, sys, time, urllib.request
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from library.map_packs import MPCG as M
GW = "http://127.0.0.1:18083"
def lua(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

print("== 开袋前 道具行囊 dump ==")
print(lua(r'''
local b=tp.窗口.道具行囊
local out={}
if not b then _G.__out='无道具行囊窗口'; return end
out[#out+1]='可视='..tostring(b.可视)
out[#out+1]='类型='..tostring(getmetatable and getmetatable(b) and getmetatable(b).__name or '?')
-- 枚举键名
local keys={}
for k in pairs(b) do keys[#keys+1]=tostring(k) end
out[#out+1]='键='..table.concat(keys,',')
if type(b.物品)=='table' then
  local names={}
  for kk,it in pairs(b.物品) do
    if type(it)=='table' then names[#names+1]=tostring(it.名称 or it.id or it)_name or ('?'..tostring(kk)) end
  end
  out[#out+1]='物品数='..string.len(table.concat(names,' '))..' 名称采样='..table.concat(names,'|')
end
_G.__out=table.concat(out,'\n')
'''))
print("== 尝试打开 ==")
print("_open_bag:", M._open_bag(GW))
print("== 打开后 可视 ==", M._lua_expr(GW, "tostring(tp.窗口.道具行囊.可视 or false)"))
print("== 打开后 卡坐标 ==", M._member_card_pos(GW))