# -*- coding: utf-8 -*-
"""team_monitor.py — 组队操作监视器。

用途：用户手动演示"组队/邀请/接受入队"时，全程记录 5 个实例的队伍状态变化
（面板7.队伍数据/本类开关、面板13/46/36/40/41 弹窗可视与文本），变更打时间戳
写入 test_data/team_monitor.log，关键变更自动截图 test_data/team_evt_*.png。
产出用于逆向组队交互链路，实现自动化组队。
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)
sys.path.insert(0, HERE)
import member_sell_loop as msl  # noqa: E402

LOG = os.path.join(ROOT, "test_data", "team_monitor.log")

SNAP_LUA = r"""
local parts = {}
local m = tp.地图
parts[#parts+1] = 'map=' .. tostring(m and m.地图名称 or '')
local jd = tp.主界面 and tp.主界面.界面数据
local p7 = type(jd) == 'table' and jd[7]
if type(p7) == 'table' then
  local td = p7.队伍数据
  if type(td) == 'table' then
    local acc = {}
    for k, v in pairs(td) do
      if type(v) == 'table' then
        acc[#acc+1] = tostring(k) .. ':{'
          .. tostring(v.名称 or v.名字 or '') .. '|'
          .. tostring(v.ID or v.id or '') .. '|'
          .. tostring(v.等级 or '') .. '|'
          .. tostring(v.职业 or '') .. '|'
          .. tostring(v.队长 or '') .. '|'
          .. tostring(v.x or '') .. ',' .. tostring(v.y or '') .. '}'
      else
        acc[#acc+1] = tostring(k) .. '=' .. tostring(v)
      end
    end
    parts[#parts+1] = '队伍数据={' .. table.concat(acc, ' ') .. '}'
  else
    parts[#parts+1] = '队伍数据=' .. type(td)
  end
  parts[#parts+1] = 'p7开关=' .. tostring(p7.本类开关)
  parts[#parts+1] = '阵型=' .. tostring(p7.当前阵法 or '')
  local sq = p7.申请列表
  if type(sq) == 'table' then
    parts[#parts+1] = '申请列表=' .. tostring(#sq)
  else
    parts[#parts+1] = '申请列表=' .. tostring(sq)
  end
else
  parts[#parts+1] = 'p7=nil'
end
for _, i in ipairs({13, 46, 36, 40, 41}) do
  local p = type(jd) == 'table' and jd[i]
  if type(p) == 'table' then
    parts[#parts+1] = '[' .. i .. ']可=' .. tostring(p.可视) ..
      ',状=' .. tostring(p.状态 or '') ..
      ',join=' .. tostring(p.介绍加入 or '') ..
      ',文=' .. tostring(p.文字 or '') .. tostring(p.标题文字 or '') ..
      tostring(p.介绍文本 or '')
  end
end
__out = table.concat(parts, ' ;; ')
"""


def log(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    pids = [int(a) for a in sys.argv[1:]] or [7732, 3916, 11568, 18908, 18736]
    workers = {}
    last = {}
    hwnds = {}
    log("=== 组队监视启动 pid=%s ===" % pids)
    deadline = time.time() + float(os.environ.get("TEAM_MONITOR_SEC", "2400"))
    while time.time() < deadline:
        for pid in pids:
            gw = "file://pzxy_p%d" % pid
            try:
                r = ZGUI._lua_call(gw, SNAP_LUA, timeout=4.0) or ""
            except Exception as e:
                r = "ERR:%s" % e
            prev = last.get(pid)
            if r != prev:
                log("p%d 变更: %s" % (pid, r.replace(" ;; ", " | ")[:800]))
                last[pid] = r
                # 关键变更截图：仅当该实例窗口可截
                try:
                    if pid not in hwnds or not hwnds[pid]:
                        hwnds[pid] = msl.find_hwnd_by_pid(pid)
                    if hwnds[pid]:
                        img, _, _ = ZGUI.grab_client(hwnds[pid])
                        fn = os.path.join(ROOT, "test_data", "team_evt_p%d_%s.png"
                                          % (pid, time.strftime("%H%M%S")))
                        img.save(fn)
                        log("p%d 截图: %s" % (pid, fn))
                except Exception:
                    pass
        time.sleep(1.2)
    log("=== 组队监视结束 ===")


if __name__ == "__main__":
    main()
