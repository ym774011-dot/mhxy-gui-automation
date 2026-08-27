# -*- coding: utf-8 -*-
"""在游戏 UI 树中找 背包/行囊 按钮坐标"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

# 先打开背包，让按钮被读到（背包开着时按钮更准）——不，枚举 UI 组件
print("=== 枚举 tp.窗口 顶层控件名 ===")
print(lua(r'''
local w=tp.窗口
local out={}
if type(w)=="table" then
  for k,v in pairs(w) do
    if type(v)=="table" then
      local n=0; for _ in pairs(v) do n=n+1 end
      out[#out+1]=tostring(k).."=table(n="..n..")"
    else
      out[#out+1]=tostring(k).."="..tostring(v)
    end
  end
end
_G.__out=table.concat(out,"\n")'''))

print("\n=== 递归找名称含 背包/行囊/包裹 的控件及其位置 ===")
print(lua(r'''
local out={}
local seen={}
local function dump(node, path, depth)
  if depth>6 or type(node)~="table" or seen[node] then return end
  seen[node]=true
  local nm = tostring(node.名称 or node.name or "")
  local found=false
  if nm~="" and (string.find(nm,"背包") or string.find(nm,"行囊") or string.find(nm,"包裹") or string.find(nm,"物品")) then
    local x=node.x or node.左 or (node.位置 and node.位置.x) or node.fx
    local y=node.y or node.上 or (node.位置 and node.位置.y) or node.fy
    out[#out+1]=path.." 名称="..nm.." x="..tostring(x).." y="..tostring(y).." 宽="..tostring(node.宽 or node.w or "").." 高="..tostring(node.高 or node.h or "")
    found=true
  end
  for k,v in pairs(node) do
    if type(v)=="table" and not seen[v] then
      dump(v, path.."."..tostring(k), depth+1)
    end
  end
end
dump(tp.窗口,"窗口",0)
out[#out+1]="_done"
_G.__out=table.concat(out,"\n")'''))