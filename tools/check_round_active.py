# -*- coding: utf-8 -*-
"""等待几秒后直接查 类型=107 记录是否存在"""
import json, urllib.request, time, sys, os
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from library.map_packs import MPCG as M
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
def check():
    return lua(r'''
local recs={}
if tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录 then
  for i,v in pairs(tp.窗口.任务追踪栏.数据记录) do
    if type(v)=='table' then
      local t=v.类型 or v.任务类型 or ''
      if tostring(t)=='107' then
        recs[#recs+1]='序列='..tostring(v.当前序列 or '')..' 闯关='..tostring(v.闯关序列 and #v.闯关序列 or '')
      end
    end
  end
end
_G.__out=table.concat(recs,' | ') or 'NONE' ''')
for i in range(1, 5):
    v = check()
    if v and v != "NONE" and v:
        print(f"检测到107记录: {v}")
        break
    print(f"[{i}] 107记录: {v or 'NONE'}")
    time.sleep(2)
print("地图:", lua("_G.__out=tostring(tp.当前地图 or '')"))
print("任务识别:", json.dumps(M.MPCG_recognize(gateway=GW, verbose=False), ensure_ascii=False))