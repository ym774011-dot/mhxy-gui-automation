# -*- coding: utf-8 -*-
"""T3 背包判据一次性验证脚本（只读，零点击）。

用途
----
验证 ``tasks/library/ZGUI.py::_bag_visible`` 的新判据
（``tp.主界面.界面数据[3].本类开关 == true``）是否与背包真实开合状态一致。

只做**只读**操作：全部经由 ``ZGUI._lua_call`` 读内存字段，
不发送任何点击 / PostMessage / 抓鬼循环。符合用户硬约束。

用法（在仓库根目录执行）
------------------------
::

    # 1) 开态验证：背包**打开**时跑，应输出 PASS（开关=true 且 _bag_visible=True）
    python tools/_verify_bag_judge.py --expect open

    # 2) 关态验证（需用户手动配合！）：
    #    用户自己点游戏界面把背包关掉（脚本绝不代点），
    #    然后跑同一条命令，应输出 PASS（开关=false 且 _bag_visible=False）
    python tools/_verify_bag_judge.py --expect close

    # 不带 --expect 则只打印探测数据，不做 PASS/FAIL 判定（纯诊断模式）

硬约束
------
* 只读 Lua（``_lua_call`` 读字段），禁止任何点击/发包/PostMessage。
* 不启动抓鬼循环。
* 关态验证由用户手动关包配合，脚本自身不产生任何关闭动作。
"""

import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tasks.library.ZGUI import _bag_visible, _lua_call, DEFAULT_GATEWAY  # noqa: E402

# 各面板开关总览 + 面板3 详情，两条只读 Lua 拿齐诊断信息
LUA_ALL_PANELS = r"""
local j = tp.主界面 and tp.主界面.界面数据
if type(j) ~= 'table' then __out = 'NO_TABLE' return end
local parts = {}
for idx, pd in pairs(j) do
  if type(pd) == 'table' then
    parts[#parts + 1] = tostring(idx) .. '=' .. tostring(pd.本类开关)
  end
end
__out = table.concat(parts, ' ')
"""

LUA_PANEL3_DETAIL = r"""
local j = tp.主界面 and tp.主界面.界面数据
local pd = j and j[3]
if type(pd) ~= 'table' then __out = 'NO_PANEL3' return end
local n = 0
local itd = pd.物品数据
if type(itd) == 'table' then for _ in pairs(itd) do n = n + 1 end end
__out = '开关=' .. tostring(pd.本类开关)
      .. ' 状态=' .. tostring(pd.状态)
      .. ' 类型=' .. tostring(pd.类型)
      .. ' 物品数=' .. tostring(n)
"""


def gateway_alive(timeout: float = 3.0):
    """探测网关 /api/status（只读无副作用）。返回 (bool, 说明)。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(DEFAULT_GATEWAY + "/api/status", timeout=timeout) as r:
            return True, f"HTTP {r.status} {r.read(200).decode('utf-8', 'replace')}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description="T3 背包判据只读验证")
    ap.add_argument("--expect", choices=["open", "close"], default=None,
                    help="期望状态：open=背包打开时应为 true；close=背包关闭时应为 false")
    args = ap.parse_args()

    print("=" * 62)
    print("T3 背包判据验证（只读，不点击任何东西）")
    print("=" * 62)

    ok, msg = gateway_alive()
    print(f"[1] 网关探测 {DEFAULT_GATEWAY}/api/status : {'在线' if ok else '异常'}")
    print(f"    {msg}")
    if not ok:
        print("\n!! 网关不可用，无法读内存。请先确认：")
        print("    1) mhxy-mcp-gateway 已启动且 attach 到游戏 PID")
        print("    2) 游戏客户端已登录进场景")
        print("    之后重新执行本脚本。")
        return 2

    allp = _lua_call(DEFAULT_GATEWAY, LUA_ALL_PANELS) or "(nil)"
    print(f"\n[2] 全面板 本类开关 总览（只读）:\n    {allp}")

    detail = _lua_call(DEFAULT_GATEWAY, LUA_PANEL3_DETAIL) or "(nil)"
    print(f"[3] 面板3 详情（只读）:\n    {detail}")

    vis = _bag_visible(DEFAULT_GATEWAY)
    print(f"[4] ZGUI._bag_visible() 判定 = {vis}")

    if args.expect is None:
        print("\n（未指定 --expect，仅输出探测数据，不做判定）")
        print("    开态验证：背包打开时跑  python tools/_verify_bag_judge.py --expect open")
        print("    关态验证：用户手动关包后跑 python tools/_verify_bag_judge.py --expect close")
        return 0

    expected = (args.expect == "open")
    passed = (vis == expected)
    print("\n" + "-" * 62)
    if passed:
        print(f"PASS  期望 {'打开(true)' if expected else '关闭(false)'}，判定一致")
    else:
        print(f"FAIL  期望 {'打开(true)' if expected else '关闭(false)'}，"
              f"实际判定 {vis} —— 判据与真实状态不符，需回查")
    print("-" * 62)
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断")
        sys.exit(130)
    except Exception as e:  # 兜底：保证脚本自身异常不误伤游戏
        print(f"脚本异常（未对游戏产生任何影响）: {type(e).__name__}: {e}")
        sys.exit(1)
