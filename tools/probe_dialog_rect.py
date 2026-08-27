# -*- coding: utf-8 -*-
"""获取 对话栏 尺寸/位置，找关闭用坐标，并测右键关闭"""
import json, urllib.request, ctypes, sys, os, time
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("对话栏 结构:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d.可视).." 坐标="..tostring(d.x)..","..tostring(d.y).." 宽="..tostring(d.宽 or '').." 高="..tostring(d.高 or '')
out[2]="x="..tostring(d.x2 or d.x1 or ''), 
_G.__out=table.concat(out,"\n")'''))
# 尝试读对话框的选中判断/关闭坐标，或 x1/x2/y1/y2
print("对话栏 rect 字段:", lua(r'''
local d=tp.窗口.对话栏
local out={}
for k,v in pairs(d) do
  if type(v)~="table" then out[#out+1]=tostring(k).."="..tostring(v) end
end
_G.__out=table.concat(out," | ")'''))