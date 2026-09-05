# -*- coding: utf-8 -*-
"""抓鬼单轮链路 实测跑批启动器（可观测性基础设施，2026-09-03 重建）。

定位
----
本文件**只做测量**，不修改任何业务判定逻辑。它循环调用
``tasks.library.ZGUI.zhuagui_do_round``，把每一轮的结果、耗时、失败环节、
以及整轮过程中的内存状态采样序列，逐轮实时落盘为 JSON Lines。

产出的数据用于证伪/证实两个待验证命题：
  #3 完成判定超时误判 —— 点「送你回地府」后任务栏刷新滞后，timeout=20s 不够
  #4 真战斗中「参战单位」是否非空 —— 决定战斗判据会不会漏判

设计取向：**每轮发生什么都能事后还原**，优先于跑得快。

硬约束（用户强调，违反会掉线/误操作）
-------------------------------------
* 只后台操作（PostMessage / WM_MOUSEMOVE 贝塞尔轨迹），不抢真实鼠标
  —— 本文件自身不发出任何点击，全部由 ZGUI 负责。
* 禁止「托管」功能 —— 本文件不触碰。
* 背包保持打开 —— 本文件不调用任何关包逻辑。
* 节奏 15~30s/轮 —— 见 ``--min-interval`` / ``--max-interval``。
* 采样器复用 ``ZGUI._lua_call``，因此自动继承其 ≥0.15s 随机抖动限速。

用法
----
::

    # 冒烟：只跑 1 轮，看链路通不通
    python run_unlimited_test.py --rounds 1

    # 无限跑，Ctrl+C 后完成当前轮再优雅退出
    python run_unlimited_test.py

    # A/B 对比：改 timeout / wait_dialog，用 tag 区分文件
    python run_unlimited_test.py --rounds 20 --timeout 35 --wait-dialog 2.0 --tag B
    python tools/zhuagui_stats.py test_data/zhuagui_*_A_*.jsonl test_data/zhuagui_*_B_*.jsonl

    # 不碰游戏，只验证启动器与内存探针本身可用（干跑）
    python run_unlimited_test.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

TEST_DATA_DIR = os.path.join(ROOT, "test_data")
SCHEMA_VERSION = 1

# 采样上限（防单轮异常超长导致 jsonl 单条过大）
MAX_SAMPLES_PER_ROUND = 400


# ============================================================
# 1. 内存探针（只读，pcall 包裹，字段缺失也不报错）
# ============================================================
# 说明：tp.战斗类 / 参战单位 / 敌方数量 / 背景显示 在本仓库历史代码中从未出现
# （全仓库 grep 无命中），因此这里一律用 pcall 探测并把「字段是否存在」本身
# 记录为观测结果 —— 这正是待办 #4 需要的证据。
_LUA_PROBE = r"""
local out = {}
local function add(k, v) out[#out+1] = k .. '=' .. tostring(v) end

local ok_b, b = pcall(function() return tp.战斗类 end)
add('战斗类存在', ok_b and (b ~= nil))
if type(b) == 'table' then
  local ok_cz, cz = pcall(function() return b.参战单位 end)
  add('参战单位类型', ok_cz and type(cz) or 'err')
  if type(cz) == 'table' then
    local n = 0
    for _ in pairs(cz) do n = n + 1 end
    add('参战单位pairs', n)
  end
  local ok_ds, ds = pcall(function() return b.敌方数量 end)
  add('敌方数量', ok_ds and tostring(ds) or 'err')
  local ok_bg, bg = pcall(function() return b.背景显示 end)
  add('背景显示', ok_bg and tostring(bg) or 'err')
end

local ok_ing, ing = pcall(function() return tp.战斗中 end)
add('战斗中', ok_ing and tostring(ing) or 'err')

local ok_m, m = pcall(function() return tp.地图 and tp.地图.地图名称 or '' end)
add('地图名称', ok_m and tostring(m) or 'err')

local cnt = ''
local ok_t, t = pcall(function() return tp.窗口 and tp.窗口.任务栏 and tp.窗口.任务栏.任务 end)
if ok_t and type(t) == 'table' then
  for i = 1, #t do
    local v = t[i]
    if type(v) == 'table' and tostring(v.名称 or '') == '抓鬼任务' then
      cnt = tostring(v.说明 or ''):match('第(%d+)次') or ''
      break
    end
  end
end
add('任务次数', cnt)

__out = table.concat(out, '|')
"""

# 探针返回的字段名（保持顺序即解析后的 key）
_PROBE_NUM_KEYS = ("参战单位pairs", "敌方数量")


def parse_probe(raw):
    """把探针返回串解析成 dict；解析失败/空返回返回 None。"""
    if not raw or "|" not in raw:
        return None
    d = {}
    for seg in raw.split("|"):
        if "=" not in seg:
            continue
        k, v = seg.split("=", 1)
        d[k] = _coerce(v)
    return d or None


def _coerce(v):
    if v == "true":
        return True
    if v == "false":
        return False
    if v == "nil" or v == "err":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


# ============================================================
# 2. 失败环节（fail_stage）推断
# ============================================================
# 环节取值（与文档 S0-observability.md 一致）：
#   窗口 / 回长安 / 接任务 / 瞬移 / 找鬼CALL / 点回地府 / 完成判定 / 网关 / 异常 / 未知
#
# 推断优先级：ZGUI 运行期 logger 输出（更具体） > do_round 返回 msg（兜底）。
# 注意：点「送你回地府」这一步（zhuagui_click_option）恒返回 True，失败不可观测，
#      其后果一律表现为「完成判定」超时 —— 文档已注明。
_STAGE_BY_LOG = (
    ("确保任务：回长安失败", "回长安"),
    ("确保任务：接任务失败", "接任务"),
    ("确保任务：使用天眼失败", "瞬移"),
    ("天眼符坐标读取失败", "瞬移"),
    ("背包无红色合成旗", "回长安"),
    ("找不到红色合成旗", "回长安"),
    ("钟馗对话未弹出", "接任务"),
    ("无法接任务", "接任务"),
    ("取消成功但重接失败", "接任务"),
    ("回长安未成功", "回长安"),
)

_STAGE_BY_MSG = (
    ("未找到游戏窗口", "窗口"),
    ("任务未就绪", "接任务"),
    ("无野鬼目标", "找鬼CALL"),
    ("超时未完成", "完成判定"),
)

_STAGE_BY_EXC = (
    ("ensure_gateway", "网关"),
)


def infer_stage(msg, log_lines, exc_text=""):
    """从日志/返回信息/异常文本推断失败环节。"""
    for key, stage in _STAGE_BY_LOG:
        if any(key in ln for ln in log_lines):
            return stage
    for key, stage in _STAGE_BY_MSG:
        if key in (msg or ""):
            return stage
    for key, stage in _STAGE_BY_EXC:
        if key in (exc_text or ""):
            return stage
    if msg and msg.startswith("抓鬼完成"):
        return "完成判定"
    if exc_text:
        return "异常"
    return "未知"


# ============================================================
# 3. result 分类（沿用项目历史口径，判据全部来自 do_round 返回值）
# ============================================================
#   ok       <- zhuagui_do_round 返回 (True,  "抓鬼完成*")
#   inbattle <- 返回 (False, "超时未完成")  ★历史命名；实际含义是
#              「完成判定超时」，并非「在战斗中」。改名会打断历史数据连续性，
#              故保留 inbattle 并在文档中明确其判据。
#   other    <- 返回 (False, 其它 msg)：窗口/任务未就绪/无野鬼目标
#   error    <- 调用抛异常
def classify(ok, msg):
    if ok:
        return "ok"
    if "超时未完成" in (msg or ""):
        return "inbattle"
    return "other"


# ============================================================
# 4. ZGUI 日志捕获（只读钩子：挂一个 logging.Handler，不改任何逻辑）
# ============================================================
class _LogCapture(logging.Handler):
    def __init__(self, sink, echo=False):
        super().__init__(level=logging.INFO)
        self._sink = sink
        self._echo = echo

    def emit(self, record):
        try:
            line = record.getMessage()
        except Exception:
            return
        self._sink.append("[%s] %s" % (record.levelname, line))
        if self._echo:
            sys.stdout.write("    | %-7s %s\n" % (record.levelname, line))
            sys.stdout.flush()


def _resolve_zgui_logger(zgui):
    """拿到 ZGUI 模块里真正用的 logging.Logger（utils.logger.Logger 有 _logger）。"""
    lg = getattr(zgui, "logger", None)
    inner = getattr(lg, "_logger", lg)
    return inner if isinstance(inner, logging.Logger) else None


# ============================================================
# 5. 内存采样器（后台线程，整轮连续采样，用于事后还原）
# ============================================================
class Sampler(threading.Thread):
    """每 interval 秒采一次内存快照，记录 (相对轮次开始的秒数, 快照)。

    复用 ZGUI._lua_call，自动继承其 ≥0.15s 随机抖动限速。
    """

    def __init__(self, zgui, gateway, interval, t0):
        super().__init__(daemon=True, name="zhuagui-sampler")
        self._zgui = zgui
        self._gw = gateway
        self._interval = interval
        self._t0 = t0
        self._stop = threading.Event()
        self.samples = []      # [(offset_s, snapshot_dict), ...]
        self.errors = 0

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                snap = parse_probe(self._zgui._lua_call(self._gw, _LUA_PROBE))
                if snap:
                    self.samples.append((round(time.time() - self._t0, 2), snap))
                else:
                    self.errors += 1
            except Exception:
                self.errors += 1
            # 抖动间隔，避免与轮询形成固定节拍
            self._stop.wait(self._interval * random.uniform(0.85, 1.25))


def _summarize_battle(samples):
    """从采样序列汇总战斗态事实（直击待办 #4）。"""
    in_battle = [s for _, s in samples if s.get("战斗中") is True]
    canzhan_nonempty = [s for s in in_battle
                        if (s.get("参战单位pairs") or 0) > 0]
    enemy_nonempty = [s for s in in_battle if _as_int(s.get("敌方数量"))]
    return {
        "observed": bool(in_battle),
        "samples": len(in_battle),
        "canzhan_nonempty_samples": len(canzhan_nonempty),
        "canzhan_max_pairs": max([_as_int(s.get("参战单位pairs")) for s in in_battle] or [0]),
        "enemy_max": max([_as_int(s.get("敌方数量")) for s in enemy_nonempty] or [0]),
        # 参战单位字段在本轮是否至少出现过一次非空（不限战斗中）
        "canzhan_ever_nonempty": any((s.get("参战单位pairs") or 0) > 0 for _, s in samples),
        "canzhan_pairs_any_max": max([_as_int(s.get("参战单位pairs")) for _, s in samples] or [0]),
    }


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _first_change_offset(samples, start_count):
    """采样序列中「任务次数」首次偏离 start_count 的时刻（相对轮次开始，秒）。

    这是 #3 的关键尺子：直接测出点「送你回地府」后任务栏刷新的真实延迟。
    """
    for off, s in samples:
        c = s.get("任务次数")
        if c is None:
            continue
        try:
            ci = int(c)
        except (TypeError, ValueError):
            continue
        if ci != start_count:
            return off
    return None


# ============================================================
# 6. 落盘
# ============================================================
class JsonlWriter:
    """逐轮 append + flush + fsync，进程崩溃也不丢已完成的轮次。"""

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._f = open(path, "a", encoding="utf-8")

    def write(self, rec):
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._f.flush()
        try:
            os.fsync(self._f.fileno())
        except OSError:
            pass

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass


# ============================================================
# 7. 优雅停止
# ============================================================
_STOP = threading.Event()


def _install_signal_handler():
    def _handler(signum, frame):
        if _STOP.is_set():
            sys.stdout.write("\n[stop] 再次 Ctrl+C，立即中止（当前轮可能成为脏数据）\n")
            sys.stdout.flush()
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            return
        _STOP.set()
        sys.stdout.write(
            "\n[stop] 收到 Ctrl+C —— 完成当前轮后优雅退出，不会中断到一半。\n"
            "       再按一次 Ctrl+C 可强制中止。\n")
        sys.stdout.flush()

    signal.signal(signal.SIGINT, _handler)


# ============================================================
# 8. 单轮执行
# ============================================================
def run_one_round(zgui, args, gateway, index):
    """执行一轮并产出完整记录 dict。异常不外抛（记成 error 轮）。"""
    t0 = time.time()
    log_lines = []
    handler = _LogCapture(log_lines, echo=args.verbose)
    logger = _resolve_zgui_logger(zgui)
    if logger is not None:
        logger.addHandler(handler)

    # ★2026-09-06 多开：每轮把目标窗口钉到本角色，防止 get_hwnd() 取到别的号
    try:
        _pw = zgui._find_role_window(args.role)
        if _pw:
            zgui.set_target_hwnd(_pw[1])
    except Exception:
        pass

    pre_task = {}
    try:
        pre_task = zgui.zhuagui_get_task(gateway) or {}
    except Exception:
        pass
    try:
        start_count = int((pre_task or {}).get("count") or 0)
    except (TypeError, ValueError):
        start_count = 0

    sampler = None
    if args.sample_interval > 0:
        sampler = Sampler(zgui, gateway, args.sample_interval, t0)
        sampler.start()

    ok, msg, exc_text = False, "", ""
    try:
        ok, msg = zgui.zhuagui_do_round(gateway=gateway,
                                        wait_dialog=args.wait_dialog,
                                        timeout=args.timeout,
                                        verbose=args.verbose)
    except Exception:
        exc_text = traceback.format_exc(limit=6)
        ok, msg = False, "异常: %s" % (sys.exc_info()[1],)
    finally:
        if sampler is not None:
            sampler.stop()
            sampler.join(timeout=args.sample_interval * 2 + 3)

    elapsed = round(time.time() - t0, 2)
    if logger is not None:
        logger.removeHandler(handler)

    # 轮次结束时的收尾快照（晚于最后一次采样，反映终态）
    post_snap = None
    try:
        post_snap = parse_probe(zgui._lua_call(gateway, _LUA_PROBE))
    except Exception:
        pass
    post_task = {}
    try:
        post_task = zgui.zhuagui_get_task(gateway) or {}
    except Exception:
        pass
    try:
        end_count = int((post_task or {}).get("count") or 0)
    except (TypeError, ValueError):
        end_count = -1

    result = "error" if exc_text else classify(ok, msg)
    # ★2026-09-05 提速观测：ZGUI 分段耗时（ensure_task_ready / enter_battle / wait_task_done）
    stages = dict(getattr(zgui, "_LAST_ROUND_STAGES", {}) or {})
    samples = [{"t": off, **snap} for off, snap in (sampler.samples if sampler else [])]
    if len(samples) > MAX_SAMPLES_PER_ROUND:
        samples = samples[:MAX_SAMPLES_PER_ROUND]

    rec = {
        "schema": SCHEMA_VERSION,
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "run_id": args.run_id,
        "tag": args.tag,
        "round_index": index,
        "role": args.role,
        "gateway": gateway,
        "result": result,
        "ok": bool(ok),
        "msg": msg,
        "elapsed_s": elapsed,
        "timeout": args.timeout,
        "wait_dialog": args.wait_dialog,
        "fail_stage": infer_stage(msg, log_lines, exc_text),
        "stages": stages,
        "task": {
            "name_before": (pre_task or {}).get("name", ""),
            "start_count": start_count,
            "end_count": end_count,
            "changed": end_count != start_count,
            # ★#3 的关键观测量：任务栏「第N次」首次变化的时刻（秒，相对轮次开始）
            "first_change_offset_s": _first_change_offset(sampler.samples if sampler else [],
                                                          start_count),
        },
        "mem_end": post_snap or {},
        "battle": _summarize_battle(sampler.samples if sampler else []),
        "samples": samples,
        "sample_errors": sampler.errors if sampler else 0,
        "log": log_lines,
        "error": exc_text or None,
    }
    return rec


# ============================================================
# 8.5 网关通道重置（轮次间隙兜底，2026-09-05）
# ============================================================
def _maybe_reset(gateway, index):
    """在轮次间隙重置网关注入通道，返回是否成功。

    ★背景：网关存在「候选表缓存 hasTp 导致永不重捕获」的卡死模式
     （症状：/api/lua 全部 10s 超时、queueLen 积压不降、captured=false、
      consumeStats 完全冻结）。lua_bridge.js 已加根治与软失效自愈，
     本函数只是**兜底保险**——在轮次间隙（安全点，此刻通道本就空闲）
     定期清一次，代价极低。

    重置四件套由网关侧保证：清队列 + 丢弃捕获 + 清候选表 + 重挂心跳。
    失败不影响主流程（记录后继续跑）。

    ★方案②（2026-09-05）：gateway 为 file:// 时跳过——文件通道无常驻 frida 桥，
    不存在注入通道积压问题，reset 无意义。
    """
    if str(gateway).lower().startswith("file"):
        return False
    try:
        req = urllib.request.Request(
            gateway.rstrip("/") + "/api/admin/reset",
            data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        res = d.get("result") or {}
        print("      [reset] 第%d轮后重置注入通道 | 丢弃积压=%s 原主state=%s"
              % (index, res.get("dropped"), res.get("wasMain")))
        # 重新捕获需要一点时间（挂心跳 hook → 候选过 tp 探针 → 捕获 → 拆心跳）。
        # 此处已在轮次间隙，多等 2s 让通道恢复到可注入状态再开下一轮。
        time.sleep(2.0)
        return True
    except Exception as e:
        print("      [reset] 第%d轮重置失败（不影响继续）: %s" % (index, e))
        return False


# ============================================================
# 9. 主流程
# ============================================================
def build_parser():
    p = argparse.ArgumentParser(
        description="抓鬼单轮链路实测跑批（可观测性基础设施，只测量不改逻辑）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--rounds", type=int, default=0,
                   help="跑几轮；0 = 无限（Ctrl+C 优雅停）")
    p.add_argument("--role", default="二号美人",
                   help="角色名（用于解析窗口/组号/网关端口）")
    p.add_argument("--gateway", default=None,
                   help="网关 URL；缺省按角色所在组的 gateway.port 解析；"
                        "传 file://pzxy 走方案②文件通道（零 frida，需先播种 worker）")
    p.add_argument("--timeout", type=float, default=20.0,
                   help="完成判定超时秒数（A/B 对比的主变量，#3 修复方向）")
    p.add_argument("--wait-dialog", type=float, default=1.2,
                   help="CALL 后等对话框出现的秒数（A/B 对比变量）")
    p.add_argument("--min-interval", type=float, default=15.0,
                   help="每轮最小周期（秒），含本轮耗时")
    p.add_argument("--max-interval", type=float, default=30.0,
                   help="每轮最大周期（秒），含本轮耗时")
    p.add_argument("--sample-interval", type=float, default=1.5,
                   help="内存采样间隔（秒）；0 = 关闭采样器")
    p.add_argument("--reset-every", type=int, default=10,
                   help="每 N 轮在轮次间隙重置一次网关注入通道（0=关闭）。"
                        "兜底防「候选表缓存 hasTp 导致永不重捕获」的卡死；"
                        "只在轮次间隙触发，不在战斗/对话中途清")
    p.add_argument("--tag", default="", help="运行标签，进入文件名便于 A/B 分组")
    p.add_argument("--out", default=None, help="输出 jsonl 路径（缺省自动生成）")
    p.add_argument("--verbose", action="store_true", help="实时回显 ZGUI 过程日志")
    p.add_argument("--quiet", action="store_true", help="只输出每轮一行摘要")
    p.add_argument("--rebind", action="store_true",
                   help="跑批前用 ensure_gateway 重新绑定网关（默认不开，避免干扰已运行的 GUI）")
    p.add_argument("--list-roles", action="store_true", help="列出已开游戏窗口与角色后退出")
    p.add_argument("--dry-run", action="store_true",
                   help="只取一次内存快照验证探针与网关，不跑轮次")
    return p


def resolve_gateway(zgui, args):
    """按角色解析网关 URL 与窗口信息。返回 (gateway_url, info_lines)。"""
    info = []
    gateway = args.gateway
    if gateway:
        info.append("网关(显式): %s" % gateway)
    else:
        try:
            from core.group_config import gateway_url
            groups = zgui._role_group_map()
            group = groups.get(args.role, 1)
            gateway = gateway_url(group)
            info.append("网关(角色 %s → 组%d): %s" % (args.role, group, gateway))
        except Exception as e:
            gateway = zgui.DEFAULT_GATEWAY
            info.append("网关(回退默认): %s (%s)" % (gateway, e))
    try:
        pw = zgui._find_role_window(args.role)
        if pw:
            pid, hwnd = pw
            info.append("窗口: 角色=%s pid=%d hwnd=0x%X" % (args.role, pid, hwnd))
            cur = zgui.get_hwnd()
            if cur and cur != hwnd:
                info.append("警告: ZGUI.get_hwnd()=0x%X 与角色窗口不一致（多开时请确认）" % cur)
        else:
            info.append("警告: 未找到角色 %s 的窗口（网关可能已绑到别的窗口）" % args.role)
    except Exception as e:
        info.append("窗口探测失败: %s" % e)
    return gateway, info


def main(argv=None):
    args = build_parser().parse_args(argv)
    random.seed()

    if args.list_roles:
        from tasks.library import ZGUI as _z
        try:
            from core.window_manager import window_manager
            for hwnd, title, pid, _v in (window_manager.list_game_windows() or []):
                print("pid=%-7d hwnd=0x%-8X 角色=%-12s 标题=%s"
                      % (pid, hwnd, _z._role_from_title(title) or "?", title))
        except Exception as e:
            print("窗口枚举失败:", e)
        return 0

    from tasks.library import ZGUI as zgui

    gateway, info_lines = resolve_gateway(zgui, args)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.run_id = run_id
    if args.out:
        out_path = args.out
    else:
        parts = ["zhuagui", run_id]
        if args.tag:
            parts.append(args.tag)
        parts.append("t%g_w%g" % (args.timeout, args.wait_dialog))
        out_path = os.path.join(TEST_DATA_DIR, "_".join(parts) + ".jsonl")

    print("=" * 68)
    print("抓鬼实测跑批 | run_id=%s tag=%s" % (run_id, args.tag or "-"))
    for ln in info_lines:
        print("  " + ln)
    print("  参数: rounds=%s timeout=%.1fs wait_dialog=%.2fs 节奏=%.0f~%.0fs 采样=%.1fs"
          % (args.rounds or "无限", args.timeout, args.wait_dialog,
             args.min_interval, args.max_interval, args.sample_interval))
    print("  日志: %s" % out_path)
    print("=" * 68)

    # 干跑：只验证探针与网关连通性，不发出任何点击
    if args.dry_run:
        snap = parse_probe(zgui._lua_call(gateway, _LUA_PROBE))
        print("[dry-run] 内存快照: %s" % json.dumps(snap, ensure_ascii=False))
        print("[dry-run] 任务: %s" % json.dumps(zgui.zhuagui_get_task(gateway),
                                                ensure_ascii=False))
        print("[dry-run] 完成（未跑轮次，未发出任何点击）")
        return 0 if snap else 2

    if args.rebind:
        try:
            from core.gateway_guard import ensure_gateway
            pw = zgui._find_role_window(args.role)
            ok_g, info_g = ensure_gateway(pid=pw[0] if pw else None, timeout=60.0)
            print("[rebind] %s %s" % (ok_g, info_g))
            if not ok_g:
                return 2
        except Exception as e:
            print("[rebind] 失败: %s" % e)
            return 2

    _install_signal_handler()
    writer = JsonlWriter(out_path)

    # 会话元信息（便于 A/B 回溯跑批条件）
    meta_path = out_path[:-len(".jsonl")] + ".meta.json"
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"run_id": run_id, "tag": args.tag, "role": args.role,
                       "gateway": gateway, "timeout": args.timeout,
                       "wait_dialog": args.wait_dialog,
                       "min_interval": args.min_interval,
                       "max_interval": args.max_interval,
                       "sample_interval": args.sample_interval,
                       "start": datetime.now().astimezone().isoformat(timespec="seconds"),
                       "info": info_lines}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print("[warn] meta 写入失败: %s" % e)

    counts = {"ok": 0, "inbattle": 0, "other": 0, "error": 0}
    index = 0
    exit_code = 0
    try:
        while True:
            index += 1
            if _STOP.is_set():
                print("[stop] 收到停止信号，第 %d 轮不再开始。" % index)
                break
            if args.rounds and index > args.rounds:
                break

            rec = run_one_round(zgui, args, gateway, index)
            writer.write(rec)
            counts[rec["result"]] = counts.get(rec["result"], 0) + 1
            done = sum(counts.values())
            rate = (counts["ok"] / done * 100.0) if done else 0.0

            if not args.quiet:
                print("[%03d] %-8s %6.1fs  %-6s 次数 %s→%s  变化@%s  战斗=%s/%s  参战max=%s  %s"
                      % (index, rec["result"], rec["elapsed_s"], rec["fail_stage"],
                         rec["task"]["start_count"], rec["task"]["end_count"],
                         rec["task"]["first_change_offset_s"],
                         rec["battle"]["samples"], len(rec["samples"]),
                         rec["battle"]["canzhan_pairs_any_max"],
                         rec["msg"][:40]))
            print("     累计 %d 轮: ok=%d inbattle=%d other=%d error=%d  OK率=%.1f%%"
                  % (done, counts["ok"], counts["inbattle"], counts["other"],
                     counts["error"], rate))
            sys.stdout.flush()

            # ★轮次间隙重置注入通道（安全点：本轮已结束、下一轮未开始）
            if args.reset_every and index % args.reset_every == 0 and not _STOP.is_set():
                _maybe_reset(gateway, index)

            # 节奏控制：目标周期=本轮耗时+停顿 落在 [min,max]，且至少停 1~2.5s
            if _STOP.is_set():
                break
            if args.rounds and index >= args.rounds:
                break
            target = random.uniform(args.min_interval, args.max_interval)
            pause = max(random.uniform(1.0, 2.5), target - rec["elapsed_s"])
            time.sleep(pause)
    except KeyboardInterrupt:  # 兜底（例如信号处理器已还原）
        print("\n[stop] 强制中止。")
        exit_code = 130
    finally:
        writer.close()

    print("=" * 68)
    print("结束 | 共 %d 轮 | ok=%d inbattle=%d other=%d error=%d | OK率=%.1f%%"
          % (sum(counts.values()), counts["ok"], counts["inbattle"],
             counts["other"], counts["error"],
             (counts["ok"] / sum(counts.values()) * 100.0) if sum(counts.values()) else 0.0))
    print("日志: %s" % out_path)
    print("统计: python tools/zhuagui_stats.py %s" % out_path)
    print("=" * 68)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
