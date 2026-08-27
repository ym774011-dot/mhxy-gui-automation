# -*- coding: utf-8 -*-
"""MPCG 门派闯关 - Lua 层数据源探查工具（2026-08-25 refactor-mpcg-lua）。

用途: 在游戏已附加网关的前提下，转储门派闯关相关的 Lua 字段，
确认「目标门派地图名」与「完成次数」所在的数据源路径（Task 1）。

用法:
  python tools/probe_mpcg.py                # 组1 网关 18082
  python tools/probe_mpcg.py --port 18083   # 指定网关端口（多组）
  python tools/probe_mpcg.py --all          # 全部 18082..18080+N 端口逐一尝试

说明:
  - 纯只读探查（/api/lua），不会改动游戏状态。
  - 需要玩家「已接门派闯关任务 + 任务追踪栏有激活门派目标」才有完整数据。
  - 输出 key=value 转储 + 任务追踪栏结构遍历。
"""
import json
import sys
import argparse
import urllib.request


def _lua(gateway: str, code: str, timeout: float = 5.0):
    try:
        req = urllib.request.Request(
            gateway + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
        if not d.get("ok"):
            return {"ok": False, "error": d.get("error", "")}
        return {"ok": True, "value": d.get("result", {}).get("value", "")}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}


# 转储: 任务追踪栏数据记录 + 介绍文本 + 计数 + 小地图/当前地图 + 队伍任务标识
_DUMP = r'''
local out = {}
-- 1) 任务追踪栏数据记录（结构化：名称/地图名称/地图编号/x/y/类型/模型/江湖次数...）
local recs = {}
if type(tp.窗口.任务追踪栏.数据记录) == "table" then
  local n = 0
  for k, v in pairs(tp.窗口.任务追踪栏.数据记录) do
    n = n + 1
    if n <= 8 and type(v) == "table" then
      local r = tostring(k) .. "={"
      for fk, fv in pairs(v) do r = r .. tostring(fk) .. "=" .. tostring(fv) .. "," end
      recs[#recs + 1] = r .. "}"
    end
  end
end
out.rec_count = table.concat(recs, " || ")
-- 2) 介绍文本（行数 + 文字行）
out.intro_lines = tostring(tp.窗口.任务追踪栏.介绍文本.行数量 or 0)
local txt = {}
if type(tp.窗口.任务追踪栏.介绍文本.文字) == "table" then
  local nn = 0
  for k, v in pairs(tp.窗口.任务追踪栏.介绍文本.文字) do
    nn = nn + 1
    if nn <= 40 and type(v) == "string" then txt[#txt + 1] = v end
  end
end
out.intro_text = table.concat(txt, "|")
-- 3) 任务计数
out.count_main = tostring(tp.队伍[1].主线 or 0)
out.count_jh   = tostring(tp.队伍[1].江湖次数 or 0)
out.count_sm   = tostring(tp.队伍[1].师门次数 or 0)
-- 4) 当前地图 + 小地图名
out.cur_map = tostring(tp.当前地图 or "")
out.map_name = tostring(tp.窗口.小地图.地图名称 or "")
-- 5) 任务标识数组（玩家id_类型_时间戳，含类型线索）
local tl = {}
if type(tp.队伍[1].任务) == "table" then
  for i = 1, 5 do if tp.队伍[1].任务[i] then tl[#tl + 1] = tostring(tp.队伍[1].任务[i]) end end
end
out.task_ids = table.concat(tl, ",")
-- 输出
_G.__out = ""
for k, v in pairs(out) do _G.__out = _G.__out .. k .. "=" .. v .. "\n" end
'''


def probe(gateway: str):
    print("=" * 60)
    print(f"[probe] gateway={gateway}")
    r = _lua(gateway, _DUMP)
    if not r.get("ok"):
        print(f"  !! 网关执行失败: {r.get('error')}")
        return
    for line in (r.get("value") or "").splitlines():
        print("  " + line)


def probe_globals_filter(gateway: str, flt: str = "门派"):
    """探索 _G 全局表含关键字的字段名（/api/globals?filter=）。"""
    try:
        req = urllib.request.Request(gateway + f"/api/globals?filter={flt}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  [globals filter={flt}] {resp.read().decode('utf-8', 'replace')}")
    except Exception as e:
        print(f"  [globals] err {e}")


def main():
    ap = argparse.ArgumentParser(description="MPCG 门派闯关 Lua 数据源探查")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="尝试多组端口")
    args = ap.parse_args()

    ports = []
    if args.port:
        ports.append(args.port)
    elif args.all:
        ports = list(range(18082, 18090))
    else:
        ports.append(18082)

    gateways = [f"http://127.0.0.1:{p}" for p in ports]
    for gw in gateways:
        probe(gw)
    # 附加: 全局表关键字探查（命名线索, 只对第一个可达网关做）
    probe_globals_filter(gateways[0], "门派")
    probe_globals_filter(gateways[0], "闯关")


if __name__ == "__main__":
    main()