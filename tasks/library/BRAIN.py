# -*- coding: utf-8 -*-
"""BRAIN —— WORLD_BOSS 自我进化记忆库（P0 骨架，2026-09-01）。

设计原则（全程不碰游戏引擎，0 崩溃风险）：
  - 纯数据层：只读写 data/brain_memory.json，不注入 Lua、不点鼠标；
  - 容错铁律：任何读写异常错误捕获并吞掉（记录 stderr），绝不向上抛出
    影响 farm 主流程——记忆库是"可选增强"，坏了就当没有；
  - 原子写：写盘先写 .tmp 再 os.replace，防崩溃留半截 JSON；
  - 置信度：每条经验带 fail/success 计数，达到阈值才"生效"（先观察后拉黑），
    抑制一次性误判；带 attrs 时间戳，超 TTL 的经验自动衰减/过期；
  - 四区隔离：memory = {"black":坑位黑名单, "hot":地图效率, "param":参数自适应,
    "session":会话断点}，互不干扰，各自独立读写。

用法（在 WORLD_BOSS.py 内）：
    import BRAIN  (或 from tasks.library import BRAIN)
    bm = BRAIN.BrainMemory()            # 自动加载 data/brain_memory.json
    bm.black_add(map, x, y, reason)     # 记录一次坑位 (P1)
    bm.black_blacklisted(map, x, y)     # 是否已达拉黑阈值 (P1)
    bm.hot_kill(map, cost_s)            # 记录一次击杀耗时 (P2)
    bm.hot_map_rank()                   # 每图平均耗时/击杀数效率榜 (P2)
    bm.param_update(key, value, metric) # 参数自适应观测 (P3)
    bm.session_set(...)/session_resume()# 断点恢复 (P4)
    bm.done()                           # 会话结束落盘
"""
import os
import json
import time as _time
import traceback

# 记忆库文件位置：与校准数据同目录（data/）
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_MEM_FILE = os.path.join(_DATA_DIR, "brain_memory.json")
# 经验 TTL（秒）：默认 7 天，超期自动老化（可被衰减/合并逻辑覆盖）
_DEFAULT_TTL = 7 * 24 * 3600
# 生效阈值（P1 坑位）：fail >= BLACK_FAIL_THRESHOLD 才正式拉黑
BLACK_FAIL_THRESHOLD = 3
# 成功抵消：成功 1 次抵消 fail_bad 次（防把"偶然失误"永久黑）
BLACK_SUCCESS_OFFSET = 2
# 每次衰减基数（P0 骨架保留接口，P1 起按场景真正使用）
_DECAY_ORDER = 2       # 每天衰减 n 次方级？否——用比例衰减，见 _decay
_DECAY_FACTOR = 0.5    # 超 TTL 后 fail 计数乘以该因子（趋近 0 自动失效）
_SAVE_BUFFER = 60      # 最多每 60s 落一次盘（高频击杀不写盘风暴）


class BrainMemory:
    """WORLD_BOSS 经验记忆库（进程内单例使用）。

    线程安全说明：farm 是单线程逐杀，无需加锁；若有并发写请自行外置锁。
    """

    def __init__(self, mem_file: str = None, verbose: bool = False):
        self._file = mem_file or _MEM_FILE
        self._verbose = verbose
        self._mem = self._load()
        # 分区块引用（保证黑名单等各键存在）
        for _k in ("black", "hot", "param", "session"):
            self._mem.setdefault(_k, {})
        self._dirty = False
        self._last_save = 0.0
        self._log("[BRAIN] 记忆库已加载", self._file)

    # ------------------------------------------------------------------
    # 基础：加载 / 保存 / 原子写
    # ------------------------------------------------------------------
    def _log(self, *a):
        if self._verbose:
            try:
                print(*a, flush=True)
            except Exception:
                pass

    def _load(self) -> dict:
        try:
            if os.path.exists(self._file):
                with open(self._file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass   # 坏文件静默回退空 dict（记忆库是可选增强，绝不影响 farm）
        return {}

    def _maybe_save(self, force: bool = False) -> None:
        """节流落盘：距上次保存 < _SAVE_BUFFER 秒且非 force 则跳过。"""
        if not self._dirty:
            return
        now = _time.time()
        if not force and now - self._last_save < _SAVE_BUFFER:
            return
        try:
            os.makedirs(os.path.dirname(self._file), exist_ok=True)
            tmp = self._file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._mem, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._file)   # 原子替换，防半截 JSON
            self._dirty = False
            self._last_save = now
        except Exception:
            traceback.print_exc()

    def done(self, force: bool = True) -> None:
        """会话结束/主动落盘。"""
        self._maybe_save(force=force)

    def dump(self) -> dict:
        """调试快照（不落盘，返回内存副本）。"""
        return json.loads(json.dumps(self._mem))

    # ------------------------------------------------------------------
    # 置信度衰减（P0 骨架统一入口）
    # ------------------------------------------------------------------
    @staticmethod
    def _decay(entry: dict, now: float = None) -> None:
        """按时间衰减一条经验：超 TTL 后 fail/success 按比例缩水。

        entry: {"fail": n, "success": m, "ts": 最后更新时间}
        衰减规则（防“旧经验永久生效”）：
          - 距最后更新 > TTL → fail *= 0.5（连续衰减，直至 < 生效阈值自动失效）
          - success 满则整条清除（撞大运算不算经验，留着也没用）
        """
        if not isinstance(entry, dict):
            return
        now = now or _time.time()
        last = entry.get("ts") or 0
        age = now - last
        if age > _DEFAULT_TTL:
            entry["fail"] = int(entry.get("fail", 0) * _DECAY_FACTOR)
            if entry.get("fail", 0) <= 0:
                entry.pop("fail", None)
            # 时间戳刷新，下一轮继续按比例衰减（避免一次全清）
            entry["ts"] = now
        # success 爆表 = 该位置后来一直成功 → 取消黑名单资格
        if entry.get("success", 0) >= 10:
            entry.pop("fail", None)
            entry.pop("success", None)
            entry["cleared"] = True

    # ------------------------------------------------------------------
    # P1 坑位黑名单：black[map][f"{x},{y}"] = {"fail","success","ts","reason"}
    # ------------------------------------------------------------------
    def black_add(self, map_name: str, x, y, reason: str = "", now: float = None) -> None:
        """记录一次“该位置坑”（CALL 失败/被锁/弹窗）。未达阈值只是观察，不拉黑。"""
        try:
            now = now or _time.time()
            key = f"{int(x)},{int(y)}"
            m = self._mem["black"].setdefault(str(map_name), {})
            e = m.get(key)
            if not isinstance(e, dict):
                e = m.setdefault(key, {})
            self._decay(e, now)
            e["fail"] = int(e.get("fail", 0)) + 1
            e["ts"] = now
            if reason:
                e["reason"] = str(reason)[:120]
            if e.get("success") and not e.get("cleared"):
                # 之前成功过、后面又失败：成功抵消
                e["success"] = max(0, int(e.get("success", 0)) - BLACK_SUCCESS_OFFSET)
            self._dirty = True
            self._maybe_save()
        except Exception:
            traceback.print_exc()

    def black_success(self, map_name: str, x, y, now: float = None) -> None:
        """该位置成功击杀 → 提升 success，抵消历史失败。"""
        try:
            now = now or _time.time()
            key = f"{int(x)},{int(y)}"
            m = self._mem["black"].get(str(map_name))
            if not isinstance(m, dict):
                return
            e = m.get(key)
            if not isinstance(e, dict):
                return
            self._decay(e, now)
            e["success"] = int(e.get("success", 0)) + 1
            # 成功同时扣减失败次数（对称于 black_add 的 success 抵消）
            if e.get("fail", 0) > 0:
                e["fail"] = max(0, int(e["fail"]) - BLACK_SUCCESS_OFFSET)
            e["ts"] = now
            # 成功显著覆盖失败 → 撤黑
            if e.get("fail", 0) <= 0:
                e.pop("fail", None)
                e.pop("success", None)
                e["cleared"] = True
            self._dirty = True
            self._maybe_save()
        except Exception:
            traceback.print_exc()

    def black_blacklisted(self, map_name: str, x, y) -> bool:
        """该位置是否已达拉黑阈值（fail >= BLACK_FAIL_THRESHOLD 且未被 success 抵消）。"""
        try:
            m = self._mem["black"].get(str(map_name))
            key = f"{int(x)},{int(y)}"
            e = (m or {}).get(key)
            if not isinstance(e, dict) or e.get("cleared"):
                return False
            self._decay(e)   # 读时顺手衰减（超 TTL 自动缩水到阈值下）
            return int(e.get("fail", 0)) >= BLACK_FAIL_THRESHOLD
        except Exception:
            return False

    def black_list(self) -> dict:
        """调试/展示：全部黑名单条目。"""
        try:
            return json.loads(json.dumps(self._mem.get("black", {})))
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # P2 热点图/效率榜：hot[map] = {"kills","cost_sum","cross_cnt","ts"}
    # ------------------------------------------------------------------
    def hot_kill(self, map_name: str, cost_s: float, cross: bool = False, now: float = None) -> None:
        """记录该地图一次击杀（cost_s = 战间间隔秒；cross=是否跨图而来）。"""
        try:
            now = now or _time.time()
            h = self._mem["hot"].get(str(map_name))
            if not isinstance(h, dict):
                h = self._mem["hot"].setdefault(str(map_name), {})
            h["kills"] = int(h.get("kills", 0)) + 1
            h["cost_sum"] = float(h.get("cost_sum", 0.0)) + float(cost_s or 0.0)
            if cross:
                h["cross_cnt"] = int(h.get("cross_cnt", 0)) + 1
            h["ts"] = now
            self._dirty = True
            self._maybe_save()
        except Exception:
            traceback.print_exc()

    def hot_record_cross(self, map_name: str, now: float = None) -> None:
        """从异地跨图落地（无击杀也算，用于跨图链路成功率统计）。"""
        try:
            h = self._mem["hot"].setdefault(str(map_name), {})
            h["cross_cnt"] = int(h.get("cross_cnt", 0)) + 1
            h["ts"] = now or _time.time()
            self._dirty = True
            self._maybe_save()
        except Exception:
            traceback.print_exc()

    def hot_map_rank(self, min_kills: int = 3) -> list:
        """效率榜：按“平均战间耗时”升序排（最快 → 最慢）。

        :param min_kills: 统计样本下限，样本不足的图不进榜（防小样本误导）
        :return: [{"map","kills","avg_cost","cross_ct"}, ...]
        """
        try:
            out = []
            for m, h in self._mem.get("hot", {}).items():
                if not isinstance(h, dict):
                    continue
                k = int(h.get("kills", 0))
                if k < min_kills:
                    continue
                out.append({
                    "map": str(m),
                    "kills": k,
                    "avg_cost": round(float(h.get("cost_sum", 0.0)) / k, 2),
                    "cross_ct": int(h.get("cross_cnt", 0)),
                })
            out.sort(key=lambda r: r["avg_cost"])
            return out
        except Exception:
            return []

    def hot_weighted_pick(self, candidates: list, pool_avg: float = 12.0) -> str:
        """P2 效率加权选图（2026-09-01）。

        :param candidates: 候选地图名列表（调用方已排除当前图/近期图）
        :param pool_avg: 无历史数据图的默认平均耗时（秒）——比已统计图“差一点”，
                         让有记录的效率洼地图优先，无数据图次之（探索与利用兼顾）
        :return: 选中地图名（保证返回 candidates 内某一张）
        加权规则：avg_cost 越小分越高 → weight = 1/(avg_cost - 3)，avg_cost 取
        hot 里该图历史均值，没有则用 pool_avg。用随机加权避免“永远选同一个图”。
        """
        import random as _random
        if not candidates:
            return ""
        ws, names = [], []
        for m in candidates:
            avg = pool_avg
            try:
                h = self._mem.get("hot", {}).get(str(m))
                if isinstance(h, dict) and int(h.get("kills", 0)) > 0:
                    avg = float(h.get("cost_sum", 0.0)) / int(h["kills"])
            except Exception:
                avg = pool_avg
            # avg_cost 越小权重越高；3s 下限防除零
            w = 1.0 / max(0.5, avg - 2.0)
            ws.append(w)
            names.append(str(m))
        try:
            return _random.choices(names, weights=ws, k=1)[0]
        except Exception:
            return names[_random.randrange(len(names))]

    # ------------------------------------------------------------------
    # P3 参数自适应：param[key] = {"n","sum","best_metric","ts"}
    # ------------------------------------------------------------------
    def param_observe(self, key: str, value: float, metric: float = None, now: float = None) -> None:
        """观测一次参数表现：value=取值；metric=绩效指标（越小越好，如战间耗时）。"""
        try:
            now = now or _time.time()
            p = self._mem["param"].setdefault(str(key), {})
            p["n"] = int(p.get("n", 0)) + 1
            p["sum"] = float(p.get("sum", 0.0)) + float(value)
            # 记录“跑出最好绩效时的取值”以作候选
            if metric is not None:
                best = p.get("best_metric")
                if best is None or metric < best:
                    p["best_metric"] = float(metric)
                    p["best_value"] = float(value)
            p["ts"] = now
            self._dirty = True
            self._maybe_save()
        except Exception:
            traceback.print_exc()

    def param_current(self, key: str) -> tuple:
        """返回 (均值, 样本数) —— farm 用作当前推荐值。"""
        try:
            p = self._mem["param"].get(str(key))
            if not isinstance(p, dict) or int(p.get("n", 0)) <= 0:
                return None, 0
            n = int(p["n"])
            return float(p.get("sum", 0.0)) / n, n
        except Exception:
            return None, 0

    def param_best(self, key: str):
        """返回历史最优取值（metric 最小时对应的 value）。"""
        try:
            p = self._mem["param"].get(str(key))
            if not isinstance(p, dict) or p.get("best_value") is None:
                return None
            return float(p["best_value"])
        except Exception:
            return None

    def param_suggest(self, key: str, default: float, min_val: float = None,
                      max_val: float = None) -> float:
        """P3 软适应建议值（2026-09-01）。

        :param key: 参数名
        :param default: 无数据时的兜底（= 硬编码默认）
        :param min_val/max_val: 允许范围钳制（防学歪——绝不把战线推到危险区）
        :return: 有足够样本时返回"历史最优绩效对应取值"（并在范围内）；
                 否则返回默认。仅供 farm 软读取，不自动改全局硬编码。
        """
        val = self.param_best(key)
        if val is None:
            return default
        if min_val is not None:
            val = max(min_val, val)
        if max_val is not None:
            val = min(max_val, val)
        return val

    # ------------------------------------------------------------------
    # P4 会话断点：session = {"cur_map","cur_x","cur_y","kills",
    #                          "started_at","last_ts","reason"}
    # ------------------------------------------------------------------
    def session_begin(self, cur_map: str = None, x=None, y=None, kills: int = 0, reason: str = "start") -> None:
        """开启/续写会话现场（每次关键节点写入）。"""
        try:
            now = _time.time()
            s = self._mem["session"]
            s["cur_map"] = str(cur_map) if cur_map is not None else s.get("cur_map")
            if x is not None:
                s["cur_x"] = int(x)
            if y is not None:
                s["cur_y"] = int(y)
            s["kills"] = int(kills if kills else s.get("kills", 0))
            s.setdefault("started_at", now)
            s["last_ts"] = now
            s["reason"] = str(reason)
            self._dirty = True
            self._maybe_save()
        except Exception:
            traceback.print_exc()

    def session_resume(self) -> dict:
        """启动时读取上次断点现场（返回副本；无则空 dict）。"""
        try:
            s = self._mem.get("session")
            return json.loads(json.dumps(s)) if isinstance(s, dict) else {}
        except Exception:
            return {}

    def session_reset(self) -> None:
        """正常结束时清空断点（避免下次误以为要续跑）。"""
        try:
            self._mem["session"].clear()
            self._dirty = True
            self._maybe_save()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 状态：重启自吸收 / 统计
    # ------------------------------------------------------------------
    def stats(self) -> dict:
        """一句话汇报：各类记忆条目数（供 GUI/日志）。"""
        try:
            return {
                "black_maps": len(self._mem.get("black", {})),
                "black_entries": sum(len(v) for v in self._mem.get("black", {}).values()
                                     if isinstance(v, dict)),
                "hot_maps": len(self._mem.get("hot", {})),
                "param_keys": len(self._mem.get("param", {})),
                "session": bool(self._mem.get("session")),
                "file": self._file,
            }
        except Exception:
            return {}


# 模块级便捷单例（farm 内直接 BRAIN.bm 使用）
bm = BrainMemory(verbose=False)