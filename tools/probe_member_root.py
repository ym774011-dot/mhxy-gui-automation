# -*- coding: utf-8 -*-
"""探查会员卡根菜单：打开背包→右键会员卡，dump 菜单选项的跳转链接+选中判断坐标。"""
import json, sys, time, urllib.request
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from library.map_packs import MPCG as M

GW = "http://127.0.0.1:18083"
def lua(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

hwnd = M._bind_hwnd(GW, None)
print("地图:", M._cur_map_id(GW), "hwnd:", hwnd)
print("开背包:", M._open_bag(GW))
time.sleep(0.5)
print("卡坐标:", M._member_card_pos(GW))
c = M._member_card_pos(GW)
if c[0] is not None:
    M._click(hwnd, c[0], c[1], rbutton=True)
    time.sleep(1.0)
    print("---- 右键卡后 对话栏状态 ----")
    print(M._member_dialog_state(GW))
    print("---- 完整选项(跳转+选中判断) ----")
    print(lua(r'''
local d=tp.窗口.对话栏
local out={}
if d and d.选项 then
  for i=1,30 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local j=o.选中判断
    local cx,cy='',''
    if type(j)=='table' then
      local x=tonumber(j.x or 0);local x2=tonumber(j.x2 or 0)
      local y=tonumber(j.y or 0);local y2=tonumber(j.y2 or 0)
      if x2>x and y2>y then cx=tostring((x+x2)/2);cy=tostring((y+y2)/2) end
    end
    out[#out+1]=tostring(i)..':文字='..tostring(o.文字 or '')..' 跳转='..tostring(o.跳转链接 or '')..' 中心='..cx..','..cy
  end
end
_G.__out=table.concat(out,'\n')
'''))