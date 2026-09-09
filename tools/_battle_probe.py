# -*- coding: utf-8 -*-
"""T4 战斗探针（只读，零点击）—— 真战斗进行中才有意义。

定位
----
抓鬼链路的"是否真在战斗"判据长期依赖 `tp.战斗中`，但：
  (a) 该字段在本服（卡通版胖子西游）被用户明令禁用作成功判据；
  (b) `tp.战斗类.参战单位 / 敌方数量 / 背景显示` 以及 `tp.战斗中 / 地图名称`
      这"四+一"个字段在**全仓库业务代码零命中**，本服是否真实存在未证实。

本脚本**不修改任何业务判定**，只在真战斗进行中（或任意时刻）反复发只读 Lua
探测，把每个字段的"存在性 / 类型 / 值 / 异常"逐行落盘 jsonl，作为 T4 真机
采样证据。待 T4 拿到真实数据后，T6 的判据接入方案再定稿。

硬约束（违反会掉线/误操作）
--------------------------
* 只读：`pcall` 包裹每个字段，字段缺失也只是记录，绝不写、绝不发包、绝不点击。
* 零点击 / 零 PostMessage / 零抓鬼循环。本脚本自身不发出任何写操作。
* RPC 间隔严格 >= 0.15s（继承 ZGUI 的 `_LUA_MIN_GAP`）并带随机抖动，
  避免固定节奏被识别为脚本。

用法
----
::

    # 无限采样（建议进真战斗后尽快启动，Ctrl+C 优雅退出）
    python tools/_battle_probe.py --port 18082 --interval 2.0

    # 只采 60 秒
    python tools/_battle_probe.py --duration 60 --out test_data/battle_probe.jsonl

    # 指定网关端口与输出路径
    python tools/_battle_probe.py --port 18082 --out test_data/bp_1.jsonl
"""

import argparse
import json
import os
import random
import sys
import threading
import time
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_VERSION = 1

# 与 ZGUI._LUA_MIN_GAP / _LUA_GAP_JITTER 对齐，统一限速语义
_LUA_MIN_GAP = 0.15
_LUA_GAP_JITTER = 1.7
_LUA_LAST = [0.0]
_LUA_LOCK = threading.Lock()

# 探测字段清单（"四+一"）：战斗类 子字段 + 战斗中 + 地图名称
# 每个字段用 pcall 探测；存在性本身就是数据（本服未必有）。
LUA_PROBE = r"""
local out = {}
local function rec(k, ok, v)
  if not ok then
    out[#out + 1] = k .. '~~err~~' .. 'pcall_error'
    return
  end
  if v == nil then
    out[#out + 1] = k .. '~~none~~' .. ''
    return
  end
  out[#out + 1] = k .. '~~' .. type(v) .. '~~' .. tostring(v)
end

-- 顶层字段存在性
local ok_bt, bt = pcall(function() return tp.战斗类 end)
rec('战斗类', ok_bt, bt)
if ok_bt and type(bt) == 'table' then
  local ok_cz, cz = pcall(function() return bt.参战单位 end)
  rec('参战单位', ok_cz, cz)
  if ok_cz and type(cz) == 'table' then
    local n = 0
    for _ in pairs(cz) do n = n + 1 end
    out[#out + 1] = '参战单位数~~number~~' .. tostring(n)
    -- 只读：记录前 20 个单位的名称/称谓/标识（无发包）
    local u = {}
    for i = 1, math.min(20, n) do
      local it = cz[i]
      if type(it) == 'table' then
        u[#u + 1] = tostring(i) .. ':' .. tostring(it.名称 or '') .. '/' .. tostring(it.称谓 or '') .. '/id=' .. tostring(it.标识 or '')
      end
    end
    out[#out + 1] = '参战单位明细~~string~~' .. table.concat(u, ';')
  end
  local ok_ds, ds = pcall(function() return bt.敌方数量 end)
  rec('敌方数量', ok_ds, ds)
  local ok_bg, bg = pcall(function() return bt.背景显示 end)
  rec('背景显示', ok_bg, bg)
end

local ok_ing, ing = pcall(function() return tp.战斗中 end)
rec('战斗中', ok_ing, ing)

local ok_m, m = pcall(function() return tp.地图 and tp.地图.地图名称 or nil end)
rec('地图名称', ok_m, m)

__out = table.concat(out, '||')
"""


def _lua_call(port, code, timeout=8.0):
    """只读 Lua RPC（与 ZGUI._lua_call 等价的独立实现，带限速）。返回原始串或 None。"""
    gw = "http://127.0.0.1:%d/api/lua" % int(port)
    try:
        wait = _LUA_LAST[0] + _LUA_MIN_GAP * random.uniform(1.0, _LUA_GAP_JITTER) - time.time()
        if wait > 0:
            time.sleep(wait)
    except Exception:
        pass
    with _LUA_LOCK:
        _LUA_LAST[0] = time.time()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            body = json.dumps({"code": code, "result_var": "__out"}).encode("utf-8")
            req = urllib.request.Request(
                gw, data=body, headers={"Content-Type": "application/json"})
            with opener.open(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if d.get("ok"):
                return d.get("result", {}).get("value")
            return None
        except Exception:
            return None


def parse_raw(raw):
    """把探针返回串解析为 {字段: {exists, type, value, err}}。"""
    res = {}
    if not raw or "||" not in raw:
        return res, None
    for seg in raw.split("||"):
        if "~~" not in seg:
            continue
        k, t, v = seg.split("~~", 2)
        if t == "err":
            res[k] = {"exists": False, "type": "err", "value": None, "err": v or "pcall失败"}
        elif t == "none":
            res[k] = {"exists": False, "type": "nil", "value": None, "err": None}
        else:
            res[k] = {"exists": True, "type": t, "value": v, "err": None}
    units = None
    if "参战单位明细" in res and res["参战单位明细"]["exists"]:
        units = res["参战单位明细"]["value"]
    return res, units


def sample_once(port):
    ts = datetime.now().isoformat(timespec="seconds")
    raw = _lua_call(port, LUA_PROBE)
    fields, units = parse_raw(raw)
    rec = {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "port": int(port),
        "fields": fields,
        "units": units,
        "raw": raw,
        "error": None if raw else "no_response_or_not_ok",
    }
    return rec


def main():
    ap = argparse.ArgumentParser(description="T4 战斗探针（只读，零点击）")
    ap.add_argument("--port", type=int, default=18082, help="mhxy-mcp-gateway 端口（默认18082）")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="采样间隔秒（严格>=0.15，自动加抖动；默认2.0）")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="采样总时长秒（0=无限，Ctrl+C 退出）")
    ap.add_argument("--out", type=str, default=None,
                    help="输出 jsonl 路径（默认 test_data/battle_probe_YYYYMMDD_HHMMSS.jsonl）")
    args = ap.parse_args()

    interval = max(_LUA_MIN_GAP, float(args.interval))
    out_path = args.out or os.path.join(
        ROOT, "test_data",
        "battle_probe_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print("=" * 64)
    print("T4 战斗探针（只读 / 零点击）—— 真战斗进行中才有意义")
    print("=" * 64)
    print(f"网关端口 : {args.port}")
    print(f"采样间隔 : {interval:.2f}s（含抖动，>= {_LUA_MIN_GAP}）")
    print(f"总时长   : {'无限' if args.duration <= 0 else args.duration} ")
    print(f"输出     : {out_path}")
    print("-" * 64)

    t0 = time.time()
    n = 0
    f = open(out_path, "a", encoding="utf-8")
    try:
        while True:
            if args.duration > 0 and (time.time() - t0) >= args.duration:
                break
            rec = sample_once(args.port)
            n += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            # 控制台摘要：只列存在性，便于现场观察
            live = {k: ("Y/" + v.get("type", "?")) if v.get("exists") else "N"
                    for k, v in rec["fields"].items()}
            print(f"[{n:04d}] {rec['ts']}  err={rec['error']}  {live}")
            gap = interval + random.uniform(0, min(0.5, interval * 0.3))
            time.sleep(gap)
    except KeyboardInterrupt:
        print("\nCtrl+C，优雅退出（已落盘样本不丢失）")
    finally:
        f.close()
    print(f"完成：共 {n} 个样本 → {out_path}")


if __name__ == "__main__":
    main()
