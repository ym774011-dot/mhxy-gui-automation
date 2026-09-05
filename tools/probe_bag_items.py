# -*- coding: utf-8 -*-
"""probe_bag_items.py — 只读探测：背包面板3 结构 + 物品全字段 dump

目的（自动出售垃圾装备前置调研，2026-09-06）：
  1) 物品数据里找"装备"判据字段（类型/类别/等级...）——防误卖天眼符/合成旗
  2) 面板3 的字段树里找"出售"控件（有坐标就能拖拽出售）
  3) 顺手确认背包里当前有什么（验证抓鬼垃圾装备长什么样）

只读，不点击不修改。走方案②文件通道（游戏内 worker）。
用法：
  E:/py/python.exe tools/probe_bag_items.py            # 全部 dump
  E:/py/python.exe tools/probe_bag_items.py --panel    # 只 dump 面板3 结构
"""
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

from library.pzxy_ipc import PzxyWorker  # noqa: E402

LUA_PANEL = r"""
local j = tp.主界面 and tp.主界面.界面数据
if type(j) ~= 'table' then __out = 'NOBAG' return end
local p3 = j[3]
if type(p3) ~= 'table' then __out = 'NOBAG' return end
local pf = {}
for k, v in pairs(p3) do
  if type(v) ~= 'table' then
    pf[#pf+1] = tostring(k)..'='..tostring(v)
  else
    local sub = {}
    for k2, v2 in pairs(v) do
      if type(v2) ~= 'table' then sub[#sub+1] = tostring(k2)..'='..tostring(v2) end
    end
    pf[#pf+1] = tostring(k)..':{'..table.concat(sub, ',')..'}'
  end
end
__out = 'PANEL3 '..table.concat(pf, ' ;; ')
"""

LUA_ITEMS = r"""
local j = tp.主界面 and tp.主界面.界面数据
local pd = type(j) == 'table' and type(j[3]) == 'table' and j[3].物品数据
if type(pd) ~= 'table' then __out = 'NOBAG' return end
-- 深度拼接：介绍/说明类字段（富文本表）把所有叶子字符串连起来
local function deep_concat(v, depth)
  if depth > 4 then return '' end
  local tv = type(v)
  if tv == 'string' then return v end
  if tv ~= 'table' then return tostring(v) end
  local acc = {}
  for _, v2 in pairs(v) do
    acc[#acc+1] = deep_concat(v2, depth + 1)
  end
  return table.concat(acc, '')
end
local parts = {}
local n = 0
for i = 1, 200 do
  local it = pd[i]
  if type(it) == 'table' then
    n = n + 1
    local fs = {}
    for k, v in pairs(it) do
      local ks = tostring(k)
      if ks == '介绍' or ks == '说明' or ks == '文本' or ks == '描述' then
        fs[#fs+1] = ks..'=<TXT>'..deep_concat(v, 0)..'</TXT>'
      elseif type(v) ~= 'table' then
        fs[#fs+1] = ks..'='..tostring(v)
      else
        local sub = {}
        for k2, v2 in pairs(v) do
          if type(v2) ~= 'table' then sub[#sub+1] = tostring(k2)..'='..tostring(v2) end
        end
        fs[#fs+1] = ks..':{'..table.concat(sub, ',')..'}'
      end
    end
    parts[#parts+1] = '['..i..']'..table.concat(fs, ';;')
  end
end
__out = 'ITEMS n='..n..' ;; '..table.concat(parts, ' ;; ')
"""


LUA_FINDSELL = r"""
-- 深度搜索文字为"出售"的控件（tp.窗口 + 面板3 各下钻 3 层），命中则取所在表的 x/y
local out = {}
local function scan(root, tag)
  if type(root) ~= 'table' then return end
  for k, v in pairs(root) do
    if type(v) == 'table' then
      for k2, v2 in pairs(v) do
        local s2 = tostring(v2)
        if s2 == '出售' then
          out[#out+1] = tag..'.'..tostring(k)..'.'..tostring(k2)..'=出售 x='..tostring(v.x or '')..' y='..tostring(v.y or '')
        elseif type(v2) == 'table' then
          for k3, v3 in pairs(v2) do
            local s3 = tostring(v3)
            if s3 == '出售' then
              out[#out+1] = tag..'.'..tostring(k)..'.'..tostring(k2)..'.'..tostring(k3)..'=出售 x='..tostring(v2.x or '')..' y='..tostring(v2.y or '')
            elseif type(v3) == 'table' then
              for k4, v4 in pairs(v3) do
                if tostring(v4) == '出售' then
                  out[#out+1] = tag..'.'..tostring(k)..'.'..tostring(k2)..'.'..tostring(k3)..'.'..tostring(k4)..'=出售 x='..tostring(v3.x or '')..' y='..tostring(v3.y or '')
                end
              end
            end
          end
        end
      end
    end
  end
end
scan(tp.窗口, '窗口')
local j = tp.主界面 and tp.主界面.界面数据
if type(j) == 'table' then scan(j[3], '面板3') end
if #out == 0 then __out = 'NOTFOUND' return end
__out = table.concat(out, ' ;; ')
"""


def find_sell():
    """深挖"出售"控件坐标。"""
    w = PzxyWorker()
    if not w.is_alive():
        print("[X] worker 不在线")
        return 1
    ok, val = w.cmd(LUA_FINDSELL, timeout=5.0)
    print(("出售控件搜索: " + (val if ok else "FAIL %s" % val)))
    return 0


def main():
    only_panel = "--panel" in sys.argv
    w = PzxyWorker()
    if not w.is_alive():
        print("[X] worker 心跳不在（游戏没开/未播种）。先用桌面 bat 启动一次跑批，或手动播种。")
        return 1
    frame = w.heartbeat()
    print("[ok] worker 存活 frame=%s" % (frame[0],))

    out = {}
    print("\n==== 面板3（行囊）字段树 ====")
    ok, val = w.cmd(LUA_PANEL, timeout=5.0)
    print(val if ok else "FAIL: %s" % val)
    out["panel3"] = val if ok else None

    if not only_panel:
        print("\n==== 物品数据全字段 ====")
        ok2, val2 = w.cmd(LUA_ITEMS, timeout=5.0)
        print((val2 or "")[:6000] if ok2 else "FAIL: %s" % val2)
        out["items_raw"] = val2 if ok2 else None

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(HERE, "bag_dump_%s.json" % ts)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n[落盘] %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
