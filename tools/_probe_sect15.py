# -*- coding: utf-8 -*-
"""只读探测：门派闯关真实门派数量与序表（不点击、不改状态）。

用途：dump 本服门派闯关 15 个门派的完整名单与字段地图，为重写 CLI 脚本（SECT15.py）提供事实依据。★2026-09-06 用户确认共 15 个门派。
只用 /api/lua 读内存，不发出任何点击、不修改任何游戏状态。

调用方式与 tasks/library/ZGUI.py 的 _lua_call 保持一致：
  body = {"code": code, "result_var": "__out"}  utf-8
  返回取 d["result"]["value"]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

GW = "http://127.0.0.1:18082"


def lua(code, timeout=15, raw=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    body = json.dumps({"code": code, "result_var": "__out"}).encode("utf-8")
    req = urllib.request.Request(GW + "/api/lua", data=body,
                                 headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if raw:
        return d
    if d.get("ok"):
        return d.get("result", {}).get("value")
    return "[ERR] " + str(d.get("error", ""))[:300]


# 0) 先探 tp 顶层与 tp.窗口 的子键，定位真实字段树
P0 = r'''
local function keys(t, limit)
  local ks = {}
  local n = 0
  for k, _ in pairs(t) do n = n + 1; if n <= (limit or 60) then ks[#ks+1] = tostring(k) end end
  table.sort(ks)
  return table.concat(ks, ',') .. ' (total=' .. n .. ')'
end
local out = {}
out[#out+1] = 'tp: ' .. (type(tp)=='table' and keys(tp, 80) or tostring(tp))
if type(tp)=='table' and type(tp.窗口)=='table' then
  out[#out+1] = 'tp.窗口: ' .. keys(tp.窗口, 80)
end
__out = table.concat(out, '\n')
'''

# 1) 类型107 门派闯关记录
P1 = r'''
local out={}
local W = tp and tp.窗口
if not (W and type(W.任务追踪栏)=='table') then __out='NO_任务追踪栏'; return end
local t = W.任务追踪栏.数据记录
if type(t)~='table' then __out='NO_RECS'; return end
local hits=0
for k,v in pairs(t) do
  if type(v)=='table' and tostring(v.类型 or '')=='107' then
    hits=hits+1
    local n=0
    local items={}
    if type(v.闯关序列)=='table' then
      for kk,vv in pairs(v.闯关序列) do n=n+1; items[#items+1]=tostring(vv) end
    end
    table.sort(items)
    out[#out+1]=string.format('seq_n=%d current=%s seq=[%s]', n, tostring(v.当前序列), table.concat(items,','))
    local ks={}
    for kk,_ in pairs(v) do ks[#ks+1]=tostring(kk) end
    table.sort(ks)
    out[#out+1]='fields='..table.concat(ks,',')
  end
end
out[#out+1]='hits='..hits
__out=table.concat(out,'\n')
'''

# 2) 任务追踪栏介绍文本（真实目标门派 + 完成次数）
P2 = r'''
local W = tp and tp.窗口
local tb = W and W.任务追踪栏 and W.任务追踪栏.介绍文本
if not (tb and tb.显示表) then __out='(无介绍文本)'; return end
local parts={}
for _,line in ipairs(tb.显示表) do
  if type(line)=='table' then
    for _,seg in ipairs(line) do
      if type(seg)=='table' and seg.内容 then parts[#parts+1]=seg.内容 end
    end
  end
end
__out=table.concat(parts,'')
'''

# 3) 当前地图 + 角色名
P3 = r'''
local m = tp and tp.地图
__out = 'map='..tostring(m and m.地图名称)..' cur='..tostring(tp and tp.当前地图)
  ..' role='..tostring(tp and tp.角色 and tp.角色.名称)
'''

# 4) 当前场景 NPC 名（找「XX护法」样式）
P4 = r'''
local names={}
local t = tp and tp.场景 and tp.场景.场景人物
if type(t)=='table' then
  local n=0
  for k,v in pairs(t) do
    n=n+1
    if n<=60 and type(v)=='table' then
      local nm = tostring(v.名称 or v.名字 or '')
      if nm ~= '' then names[#names+1]=nm end
    end
  end
end
__out=table.concat(names,' / ')
'''

# 5) 抓鬼任务栏（对照：现在在抓鬼，验通道是否通）
P5 = r'''
local W = tp and tp.窗口
local tb = W and W.任务栏 and W.任务栏.任务
if type(tb) ~= 'table' then __out='(无任务栏)'; return end
local out={}
for i=1,#tb do
  local v=tb[i]
  if type(v)=='table' then
    out[#out+1]=tostring(v.名称)..' :: '..tostring(v.说明)
  end
end
__out=table.concat(out,'\n')
'''

PROBES = (
    ("0. tp / tp.窗口 字段树", P0),
    ("1. 类型107门派闯关记录", P1),
    ("2. 任务追踪栏介绍文本", P2),
    ("3. 当前地图/角色", P3),
    ("4. 当前场景NPC(前60)", P4),
    ("5. 抓鬼任务栏(通道验证)", P5),
)


def main():
    print("=" * 72)
    print("门派闯关 只读探测 | 网关 %s" % GW)
    print("=" * 72)
    for name, code in PROBES:
        print("\n=== %s ===" % name)
        try:
            v = lua(code)
            v = "" if v is None else str(v).strip()
            print(v[:1600] if v else "(空)")
        except Exception as e:
            print("[ERR] %s: %s" % (type(e).__name__, e))
        time.sleep(0.35)
    print("\n" + "=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
