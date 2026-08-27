# -*- coding: utf-8 -*-
"""
WORLD_BOSS - 世界BOSS/活动怪自动监控与 farming 模块（Lua CALL + 地图包走路版）。

核心约束（2026-08-27 按爆率表与用户截图更新）：
  1. **按刷新时间表启动**：爆率表上BOSS有固定刷新时间（如二十八星宿每小时 0/30/51 分），
     模块支持等到指定时间再开始监控。
  2. **聊天公告识别**：从 tp.外部聊天框 / tp.窗口.聊天框 读取系统公告，解析 BOSS 名称 + 地图名。
     公告示例（图2）：
     "听闻凡间多有能人异士，玉皇大帝特派二十八星宿之一的娄金狗下凡至东海湾附近搜寻有仙缘之人..."
  3. **无坐标**：公告只给地图名，不给坐标。到图后扫描 tp.场景.场景人物 / tp.临时Npc 找 BOSS。
  4. **不瞬移到 BOSS 脸**：防举报。跨图到目标地图后：
     - 有地图包 → **真实走路**（Tab 大地图点击寻路）到 BOSS 附近；
     - 无地图包 / 走路失败（如花果山）→ 用户批准的兜底：**随机瞬移到 BOSS
       周边环带落点**（半径 3~8 格随机角度，绝不与 BOSS 坐标重叠、不贴脸）。
  4b. **距离门控（2026-08-27 实测）**：距 BOSS 超过 ``APPROACH_GRID_DISTANCE`` 格时
     直接 CALL 会弹“你距离这个NPC太远了”。故 CALL 前必须先量网格距离并走近。
  5. **CALL 进战斗**：贴近后调用 NPC 对象 ``事件开始`` → 读对话栏选项 → 用 BOSS 类别
     对应的红色战斗文案（如妖魔/鬼怪“让我来收拾你”，星宿“请星君赐教”）匹配 →
     CALL ``事件解析(跳转链接)`` 触发战斗。
  6. **组队/无等级要求**：由服务端校验，代码只负责找到并开战。

与旧版的差异：
  - 旧版：瞬移直达 BOSS 脸，战斗关键词用通用词。
  - 新版：走路贴近，战斗关键词用 BOSS 类别对应的红色战斗选项文案
    （妖魔“让我来收拾你”、灵猴“我来瞧瞧你的啥”、星宿“请星君赐教/那我就不客气了”等）。

调用：
  WORLD_BOSS_auto_farm()
  WORLD_BOSS_wait_and_farm(target_bosses=["娄金狗"], start_times=[(0,0),(30,0),(51,0)])
"""
import json
import re
import sys
import time
import random
import os
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any, Callable
from urllib.request import Request, urlopen

# 确保项目根目录在 sys.path，以便导入 library.map_packs.* 和 core.window_manager
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger("WORLD_BOSS")

try:
    from core.group_config import gateway_url
    DEFAULT_GATEWAY = gateway_url()
except Exception:
    DEFAULT_GATEWAY = "http://127.0.0.1:18082"
# 显式指定（环境变量优先级最高）。2026-08-27 用户指定：PID 15224 走组2网关 18083。
if os.environ.get("WORLD_BOSS_GATEWAY"):
    DEFAULT_GATEWAY = os.environ["WORLD_BOSS_GATEWAY"].rstrip("/")


# ============================================================
# 默认配置
# ============================================================

# 二十八星宿具体名称（公告中红色字部分）
_28_STAR_BOSSES = [
    "角木蛟", "亢金龙", "氐土貉", "房日兔", "心月狐", "尾火虎", "箕水豹",
    "斗木獬", "牛金牛", "女土蝠", "虚日鼠", "危月燕", "室火猪", "壁水貐",
    "奎木狼", "娄金狗", "胃土雉", "昴日鸡", "毕月乌", "觜火猴", "参水猿",
    "井木犴", "鬼金羊", "柳土獐", "星日马", "张月鹿", "翼火蛇", "轸水蚓",
]

# 十二生肖具体名称（公告红色字，2026-08-27 用户截图确认）：
#   “现有十二生肖中的{丑牛、寅虎、未羊}出现在了{江南野外}处捣乱，还请各位英雄侠士赶紧去降服它们。”
# 一条公告可含多个生肖名，地图只有一个。
_12_ZODIAC_BOSSES = [
    "子鼠", "丑牛", "寅虎", "卯兔", "辰龙", "巳蛇",
    "午马", "未羊", "申猴", "酉鸡", "戌狗", "亥猪",
]

# 目标 BOSS 名称列表。默认包含二十八星宿全部具体名 + 其他活动怪。
DEFAULT_TARGET_BOSSES = [
    "三界财神爷",    # 最高优先级（用户指定：三界财神爷＞知了王＞其他）
    "天降灵猴",      # 公告名
    "下凡的灵猴",    # 场景实体名（公告“天降灵猴”刷出的实体）
    "妖魔",
    "鬼怪",
    "妖魔统领",
    "知了王",
    "心魔",         # 公告：“师傅的心魔,跑到长安酒店一楼处祸害人间”（2026-08-27 实测）
    "下凡的星官",    # 公告：“特派星官下凡至宝象国赐福”（2026-08-27 实测）
    "星官",
] + list(_28_STAR_BOSSES) + list(_12_ZODIAC_BOSSES)

# 监控地图列表（顺序 = 无公告时的轮换顺序）。
# 有地图包的图走“真实走路”贴近；无地图包的图靠“BOSS周边随机落点瞬移”兜底。
DEFAULT_MONITORED_MAPS = [
    "东海湾",
    "江南野外",
    "建邺城",
    "长安",
    "长寿村",
    "长寿郊外",  # 妖魔刷新图；校准走路（data/map_calibration/长寿郊外.json）
    "大唐国境",  # 妖魔刷新图；校准走路（2026-08-27 用户校准）
    "花果山",   # 知了王/妖魔刷此图；校准走路（2026-08-27 用户校准）
    "傲来国",   # ALG 地图包（2026-08-27 注册）
    "宝象国",   # BXG 地图包（2026-08-27 注册；星官“赐福”刷新图）
    "大唐境外",  # 校准走路（2026-08-27 用户校准）
]

# BOSS → 可能刷新的地图（来源：2026-08-27 游戏公告原文截图）。
# 用途：1) 公告只报 BOSS 名不报地图时，按此表兜底选图；
#      2) 世界BOSS快报原文：“…妖魔…坐标 江南野外、东海湾、长寿郊外、大唐国境、花果山”。
BOSS_SPAWN_MAPS: Dict[str, List[str]] = {
    "妖魔": ["江南野外", "东海湾", "长寿郊外", "大唐国境", "花果山"],
    # 鬼怪与妖魔同期刷新（整点10分），大概率同表；待实测公告确认后修正
    "鬼怪": ["江南野外", "东海湾", "长寿郊外", "大唐国境", "花果山"],
}

# 地图名 → 地图包模块名（对应 library/map_packs/*.py）。
# 新增地图需先校准并补地图包，再在这里注册。
_MAP_MODULE_NAMES: Dict[str, str] = {
    "东海湾": "DHW",
    "江南野外": "JNYW",
    "建邺城": "JYC",
    "长安": "CAC",
    "长安城": "CAC",
    "长寿村": "CSC",
    "傲来国": "ALG",   # 2026-08-27 注册（内置校准 origin(293,199) scale(1.852,1.870)）
    "宝象国": "BXG",   # 2026-08-27 注册（星官“赐福”公告刷新图，实测见宝象国）
}

# 各地图默认降落坐标（地图网格坐标）。公告不带坐标时落地图入口/中心，再走路找怪。
DEFAULT_MAP_CENTER: Dict[str, Tuple[int, int]] = {
    "东海湾": (80, 80),
    "江南野外": (100, 90),
    "建邺城": (150, 100),
    "长安": (240, 101),
    "长安城": (240, 101),
    "长寿村": (80, 80),
    "长寿郊外": (60, 60),   # 粗略中心，待实测校准（妖魔刷新图）
    "大唐国境": (90, 90),   # 粗略中心，待实测校准（妖魔刷新图）
    "花果山": (80, 40),
    "宝象国": (117, 48),   # 2026-08-27 用户实测校准点（BXG origin(278,172) scale(2.786,2.792)）
    # 傲来国/大唐境外无默认落点：跨图时优先用 tp.场景.传送 的传送阵落点坐标
}

# 地图ID → 地图名（tp.当前地图 返回的是数字ID）。
# 2026-08-27 全图 BFS 实测（两次链式 hop 扫过 46 图）：
#   1501 内部 desc 叫“建邺城”，但客户端显示名是“宝象国”（星官截图核实）。
MAP_ID_TO_NAME: Dict[str, str] = {
    "1001": "长安",
    "1002": "化生寺",
    "1004": "大雁塔一层",
    "1005": "大雁塔二层",
    "1006": "大雁塔三层",
    "1007": "大雁塔四层",
    "1008": "大雁塔五层",
    "1028": "长安酒店一楼",
    "1029": "长安酒店二楼",
    "1193": "江南野外",
    "1198": "大唐官府",
    "1054": "程咬金府",
    "1110": "大唐国境",
    "1173": "大唐境外",
    "1122": "阴曹地府",
    "1127": "地狱迷宫一层",
    "1123": "森罗殿",
    "1125": "轮回司",
    "1512": "魔王寨",
    "1146": "五庄观",
    "1131": "狮驼岭",
    "1513": "盘丝岭",
    "1208": "朱紫国",
    "1210": "麒麟山",
    "1235": "丝绸之路",
    "1203": "小西天",
    "1218": "墨家村",
    "1501": "建邺城",   # 显示名=宝象国
    "1505": "建邺杂货铺",
    "1506": "东海湾",
    "1507": "东海海底",
    "1508": "沉船",
    "1509": "沉船内室",
    "1514": "花果山",   # 2026-08-27 早前实测（知了王公告+现场核实）；今日 BFS 未见入口，链路待补
}
_MAP_NAME_TO_ID: Dict[str, str] = {v: k for k, v in MAP_ID_TO_NAME.items()}

# ★ 2026-08-27 BFS 铁律：服务器对 cross_map 的 desc 做【全局查表】，不校验当前图、
#   不校验坐标（x,y 随便填都能切图）。因此每条“起点传送/进终点”边都是全局传送符，
#   链式拼接可从任意位置直达目标图。
# 注意：1501 内部叫“建邺城”，显示名是“宝象国”——公告若报“宝象国”，hop 链用建邺城。
_HOP_CHAINS: Dict[str, List[str]] = {
    "长安":     ["江南野外传送长安"],
    "江南野外": ["长安传送江南野外"],
    "建邺城":   ["长安传送江南野外", "江南野外传送建邺城"],
    "宝象国":   ["长安传送江南野外", "江南野外传送建邺城"],
    "东海湾":   ["长安传送江南野外", "江南野外传送建邺城", "建邺城进东海湾新"],
    "东海海底": ["长安传送江南野外", "江南野外传送建邺城", "建邺城进东海湾新",
                 "东海湾进东海海底"],
    "大唐国境": ["长安传送大唐国境"],
    "大唐境外": ["长安传送大唐国境", "大唐国境传送大唐境外"],
    "朱紫国":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送朱紫国"],
    "麒麟山":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送朱紫国",
                 "朱紫国传送麒麟山"],
    "丝绸之路": ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送朱紫国",
                 "朱紫国传送丝绸之路"],
    "盘丝岭":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送盘丝岭"],
    "狮驼岭":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送狮驼岭"],
    "魔王寨":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送魔王寨"],
    "五庄观":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送五庄观"],
    "阴曹地府": ["长安传送大唐国境", "大唐国境传送阴曹地府"],
    "小西天":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送小西天"],
    "墨家村":   ["长安传送大唐国境", "大唐国境传送大唐境外", "大唐境外传送墨家村"],
}

# 刷新时间表（BOSS名或BOSS类别 -> 每小时内分钟列表）。
# 用于 WORLD_BOSS_wait_and_farm 等到指定时间。
# 空列表表示“不固定时间，全天靠公告”。
DEFAULT_BOSS_SCHEDULE: Dict[str, List[int]] = {
    "天降灵猴": [0, 20, 40],
    "妖魔鬼怪": [10],
    "妖魔": [10],
    "鬼怪": [10],
    "妖魔统领": [],
    "二十八星宿": [0, 30, 51],
    "十二生肖": [],   # 刷新时间未知，纯公告驱动（2026-08-27 截图）
    "知了王": [30],
    "天罡星": [50],
    "地煞星": [25],
}
# 二十八星宿每个具体名共享时间表
for _s in _28_STAR_BOSSES:
    DEFAULT_BOSS_SCHEDULE[_s] = [0, 30, 51]

# 聊天公告解析正则。覆盖：
#   1) "二十八星宿之一的娄金狗下凡至东海湾附近..."
#   2) "天降灵猴出现在东海湾(45,67)"
#   3) "妖魔统领在江南野外刷新"
#   4) "东海湾出现了天降灵猴"
#   5) "现有十二生肖中的{丑牛、寅虎、未羊}出现在了{江南野外}处捣乱"（多BOSS单图，
#      解析器按名称命中，无需专用正则；单BOSS命名中 pattern3 已覆盖）
DEFAULT_SPAWN_PATTERNS = [
    # 图2 二十八星宿格式：...之一的{boss}下凡至{map}附近...
    r"(?:之一)?的\s*{boss}\s*下凡至\s*{map}",
    r"{boss}.*?(?:出现在了?|出现于|在|降临|刷新于|现身|下凡至|跑到)\s*{map}.*?[\(（](\d+)[,，](\d+)[\)）]",
    r"{boss}.*?(?:出现在了?|出现于|在|降临|刷新于|现身|下凡至|跑到)\s*{map}",
    r"{map}.*?(?:出现了|刷新了|降临了|现身了|下凡了).*?{boss}.*?[\(（](\d+)[,，](\d+)[\)）]",
    r"{map}.*?(?:出现了|刷新了|降临了|现身了|下凡了).*?{boss}",
]

# BOSS 类别 → 实际对话选项里“进战斗”的红色文案（来自 2026-08-27 截图）。
# 每个 BOSS 触发战斗的选项固定为第一行红色字；第二行“我只是路过”等是取消。
BOSS_BATTLE_KEYWORDS: Dict[str, List[str]] = {
    "妖魔":        ["让我来收拾你"],
    "鬼怪":        ["让我来收拾你"],
    "妖魔统领":    ["让我来收拾你", "收拾你"],
    "天降灵猴":    ["我来瞧瞧你的啥", "瞧瞧你的啥"],
    "下凡的灵猴":  ["我来瞧瞧你的啥", "瞧瞧你的啥"],
    "知了王":      ["知了还这么嚣张？讨打！", "讨打", "嚣张"],
    "心魔":        ["消灭他们", "消灭", "前去消灭"],
    "二十八星宿":  ["请星君赐", "那我就不客气了", "不客气"],  # "请星君赐"前缀兼
                     # 容"请星君赐教"（教）与"请星君赐消"（消，2026-08-27 星官截图）
    "十二生肖":    ["那我就不客气了", "不客气"],  # 2026-08-27 实测寅虎对话：红色选项“那我就不客气了”，
                                                  # 第二行“你继续观赏景色吧”=取消
}
# 二十八星宿每个具体名共享同一套关键词
for _s in _28_STAR_BOSSES:
    BOSS_BATTLE_KEYWORDS.setdefault(_s, BOSS_BATTLE_KEYWORDS["二十八星宿"])
# 十二生肖每个具体名共享同一套关键词
for _s in _12_ZODIAC_BOSSES:
    BOSS_BATTLE_KEYWORDS.setdefault(_s, BOSS_BATTLE_KEYWORDS["十二生肖"])

# 通用战斗关键词兜底（当BOSS具体名没匹配到时）。
DEFAULT_BATTLE_KEYWORDS = [
    "挑战", "战斗", "击杀", "抓捕", "制服", "对付", "消灭", "进入战斗", "讨伐",
    "降服",  # 十二生肖公告用词：“赶紧去降服它们”（2026-08-27 截图）
]

# 对话选项黑名单：含这些措辞的选项绝不点（星官实测“你认错人了”=拒绝赐福）。
_BATTLE_DENY_OPTIONS = (
    "你认错人了",
    "告辞",
    "再见",
    "离开",
)

# 距离门控：角色与 BOSS 网格距离 ≤ 此值才允许 CALL 事件开始。
# 实测超距时游戏弹“你距离这个NPC太远了”，CALL 无效（2026-08-27 用户确认）。
# 用户定案流程：原地 CALL → 弹“太远”→ 走到 BOSS 周边“随机10~50格”→ 再 CALL；
# 成功继续，失败再走。上限 QUICK_CALL_MAX_TRIES 次后跳过该只。
QUICK_CALL_RING_RANGE = (10.0, 50.0)
QUICK_CALL_MAX_TRIES = 4
APPROACH_GRID_DISTANCE = 4.0
# 无地图包瞬移兜底落点：BOSS 周边随机环带半径范围（格）。绝不落在 BOSS 坐标上。
TELEPORT_OFFSET_RANGE = (3.0, 8.0)
# 第一次落点仍超距时，第二次补传用更近的半径。
TELEPORT_RETRY_RANGE = (2.0, 4.0)

# 必须名称完全相等才匹配的 BOSS（避免“妖魔”误中普通 NPC）。
# 注意：扫描时“天降灵猴”的公告名可能对应场景实体“下凡的灵猴”，需同时注册。
EXACT_MATCH_BOSSES = ("知了王", "妖魔统领", "天降灵猴", "下凡的灵猴", "三界财神爷")

# 击杀优先级（用户指定 2026-08-27）：数字越小越优先。
# 三界财神爷 > 知了王 > 其他（其他默认=2）。同优先级按距离近的先打。
BOSS_PRIORITY = {
    "三界财神爷": 0,
    "知了王": 1,
}
_BOSS_PRIORITY_DEFAULT = 2


def _boss_priority(name: str) -> int:
    """BOSS 击杀优先级，未登记的一律 2。"""
    return BOSS_PRIORITY.get(str(name or "").strip(), _BOSS_PRIORITY_DEFAULT)

# 模块元数据（任务库注册用）
MODULE_NAME = "WORLD_BOSS"
FUNCTIONS = {
    "WORLD_BOSS_auto_farm": {
        "title": "世界BOSS自动监控 farming（聊天公告→跨图→走路找怪→CALL战斗）",
        "params": {
            "monitored_maps": "监控地图列表（默认5张有地图包的野外图）",
            "target_bosses": "目标BOSS名称列表（默认含二十八星宿全部具体名）",
            "spawn_patterns": "聊天公告匹配正则（默认自动构造）",
            "battle_keywords": "对话选项战斗关键词兜底列表",
            "home_coord": "无目标时待机坐标，默认长安(240,101)",
            "max_runtime": "最大运行秒数（默认1800=30分钟）",
            "chat_poll_interval": "聊天轮询间隔秒（默认1.5）",
            "boss_scan_interval": "地图BOSS扫描间隔秒（默认2.0）",
            "clear_timeout": "单图无BOSS后等待多久判定清图（默认30）",
            "battle_timeout": "单场战斗最大等待秒（默认180）",
            "walk_background": "地图包走路是否后台点击（默认True）",
            "verbose": "是否打印详细日志",
        },
    },
    "WORLD_BOSS_wait_and_farm": {
        "title": "按刷新时间表等待，到点后启动 WORLD_BOSS_auto_farm",
        "params": {
            "target_bosses": "目标BOSS",
            "schedule": "刷新时间表 {boss:[分钟列表]}；默认用 DEFAULT_BOSS_SCHEDULE",
            "pre_start_minutes": "提前多少分钟开始监控（默认2）",
            "max_wait_minutes": "最多等待多少分钟（默认60）",
            "farm_kwargs": "透传给 WORLD_BOSS_auto_farm 的参数",
        },
    },
    "WORLD_BOSS_probe_chat": {
        "title": "探测聊天框最近含BOSS/地图的公告（调试用，验证聊天字段）",
        "params": {"lines": "读取最近多少条", "gateway": "网关地址"},
    },
    "WORLD_BOSS_confirm_list": {
        "title": "返回需要用户确认的方向/决策清单",
        "params": {},
    },
}


# ============================================================
# 底层网关通信
# ============================================================

def _http_json(gateway: str, path: str, data: dict = None, timeout: float = 10.0) -> dict:
    """POST JSON 到 gateway，返回解析后的 JSON。"""
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = Request(
        gateway.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _lua(gateway: str, code: str, result_var: str = "__out") -> str:
    """经 /api/lua 执行 Lua 语句块，返回 result_var 值字符串。"""
    r = _http_json(gateway, "/api/lua", {"code": code, "result_var": result_var})
    if not r.get("ok"):
        raise RuntimeError(f"Lua 执行失败: {r.get('error', r)}")
    return (r.get("result") or {}).get("value") or ""


def _lua_expr(gateway: str, expr: str) -> str:
    """经 /api/lua/expr 执行单个表达式。"""
    r = _http_json(gateway, "/api/lua/expr", {"expr": expr})
    if not r.get("ok"):
        raise RuntimeError(f"expr 失败: {r.get('error', r)}")
    return (r.get("result") or {}).get("value") or ""


def _gw_teleport(gateway: str, x: int, y: int) -> dict:
    """瞬移到地图网格坐标 (x,y)。网关内部 ×20 发内部坐标 + 1002 同步。"""
    return _http_json(
        gateway, "/api/act/teleport",
        {"x": int(x), "y": int(y), "sync": True, "jump": True}, timeout=15.0,
    )


def _find_hop_teleport(gateway: str, target_name: str):
    """读当前图 tp.场景.传送 找能到 target_name 的传送条目，返回 (desc,x,y) 或 None。"""
    code = (
        'local out = "" '
        'local t = tp.场景.传送 '
        'if t then for i = 1, #t do '
        '  local s = tostring(t[i].切换 or "") '
        '  if string.find(s, "%s") then '
        '    if t[i].坐标 then '
        '      out = s .. "|" .. tostring(t[i].坐标.x) .. "," .. tostring(t[i].坐标.y) '
        '    end '
        '    break '
        '  end '
        'end end '
        '_G.__out = out'
    ) % str(target_name).strip()
    try:
        d = _http_json(gateway, "/api/lua", {"code": code})
        v = d.get("result", {}).get("value")
    except Exception:
        return None
    if v and "|" in v and "," in v:
        desc_part, xy = v.split("|", 1)
        x, y = xy.split(",")
        return desc_part, int(float(x)), int(float(y))
    return None


def _find_exact_hop(gateway: str, dest_name: str, sep: str = "传送",
                    prefix_match: bool = False):
    """读当前图 tp.场景.传送，找 **终点等于**(或前缀匹配) dest_name 的传送条目。

    切换 desc 有两种格式：
      - '起点传送终点'（如 '长安传送东海湾'）
      - '起点进终点'  （如 '建邺城进东海湾旧'，宝象国/建邺城实测表）
    按 sep 切分后比对终点；prefix_match=True 时终点以 dest_name 开头即命中
    （用于 '东海湾旧/东海湾新' 这类后缀变体）。返回 (desc, x, y) 或 None。
    """
    dest = str(dest_name).strip()
    if prefix_match:
        cmp_lua = f'string.sub(d, 1, #{dest}) == "{dest}"'
    else:
        cmp_lua = f'd == "{dest}"'
    code = (
        'local out = "" '
        'local t = tp.场景.传送 '
        'if t then for i = 1, #t do '
        '  local s = tostring(t[i].切换 or "") '
        '  local _, d = s:match("^(.*)" .. SEP_TOKEN .. "(.*)$") '
        '  if d ~= nil and CMP_EXPR then '
        '    if t[i].坐标 then '
        '      out = s .. "|" .. tostring(t[i].坐标.x) .. "," .. tostring(t[i].坐标.y) '
        '    end '
        '    break '
        '  end '
        'end end '
        '_G.__out = out'
    ).replace("SEP_TOKEN", f'"{str(sep).strip()}"').replace("CMP_EXPR", cmp_lua)
    try:
        d = _http_json(gateway, "/api/lua", {"code": code})
        v = d.get("result", {}).get("value")
    except Exception:
        return None
    if v and "|" in v and "," in v:
        desc_part, xy = v.split("|", 1)
        x, y = xy.split(",")
        return desc_part, int(float(x)), int(float(y))
    return None


def _gw_cross_map(gateway: str, target_map: str, x: int = None, y: int = None) -> dict:
    """跨图传送到目标地图（2026-08-27 BFS 实测终版）：

    优先级：
      1. 当前图传送表直达（三级匹配：精确终点 / '进'前缀 / substring）；
      2. ★ 实测链路 _HOP_CHAINS：服务器对 desc 全局查表、不校验当前图和坐标，
         链式拼接从任意位置直达目标；
      3. 旧两段式（回长安枢纽再查表）——链路表未覆盖时的兜底。
    """
    hop = (_find_exact_hop(gateway, target_map)
           or _find_exact_hop(gateway, target_map, sep="进", prefix_match=True)
           or _find_hop_teleport(gateway, target_map))
    if hop:
        desc, d_x, d_y = hop
        tx, ty = (x, y) if (x is not None and y is not None) else (d_x, d_y)
        return _http_json(gateway, "/api/act/cross_map",
                          {"desc": desc, "x": int(tx), "y": int(ty),
                           "wait_ms": 3500, "sync": True}, timeout=25.0)
    # 实测链路兜底（2026-08-27）：desc 全局查表 → 链式拼接从任意位置直达。
    chain = _HOP_CHAINS.get(target_map)
    if chain:
        for desc in chain:
            _http_json(gateway, "/api/act/cross_map",
                       {"desc": desc, "x": 100, "y": 100,
                        "wait_ms": 3000, "sync": True}, timeout=25.0)
            time.sleep(1.8)
        return {"ok": True, "error": None, "via": "hop_chain"}
    # 两段式：回长安枢纽
    hub_hop = (_find_exact_hop(gateway, "长安")
               or _find_exact_hop(gateway, "长安", sep="进", prefix_match=True))
    if hub_hop:
        h_desc, h_x, h_y = hub_hop
        _http_json(gateway, "/api/act/cross_map",
                   {"desc": h_desc, "x": int(h_x), "y": int(h_y),
                    "wait_ms": 3500, "sync": True}, timeout=25.0)
        time.sleep(1.5)   # 等切图稳定，长安传送表才可读
        hop2 = _find_exact_hop(gateway, target_map)
        if hop2:
            desc2, x2, y2 = hop2
            return _http_json(gateway, "/api/act/cross_map",
                              {"desc": desc2, "x": int(x2), "y": int(y2),
                               "wait_ms": 3500, "sync": True}, timeout=25.0)
        return {"ok": False,
                "error": f"长安传送表无到 '{target_map}' 的路线（需手工确认该图开放传送）"}
    return {"ok": False,
            "error": "当前图传送表无到目标/长安的路线"}


def _cur_map_name(gateway: str) -> str:
    """读取当前地图名（优先 当前地图名，回退 当前地图）。"""
    try:
        v = _lua_expr(gateway, "tostring(tp.当前地图名 or tp.当前地图 or '')").strip()
        # tp.当前地图 返回数字ID（如 1514），映射回中文名；未知ID原样返回
        return MAP_ID_TO_NAME.get(v, v)
    except Exception:
        return ""


def _in_battle(gateway: str) -> bool:
    try:
        return _lua_expr(gateway, "tostring(tp.战斗中 or false)") == "true"
    except Exception:
        return False


def _captcha_active(gateway: str) -> bool:
    """验证码/防脚本窗口是否弹出。"""
    try:
        code = r'''
local w = tp.窗口.防脚本
local a = (w and w.可视 and w.可视 ~= false and w.可视 ~= 0) or false
_G.__out = tostring(a)
'''
        return _lua(gateway, code) == "true"
    except Exception:
        return False


def _captcha_solve(gateway: str, verbose: bool = False) -> bool:
    """验证码弹窗时用 V7 直解自动点掉（Lua 读答案+按钮坐标 → 后台点击）。

    返回 True = 无弹窗或已解除；False = 弹窗中且未解掉（上层应暂停等待）。
    与 task_engine 同款模式：solve_v7 自足判断，不依赖 monitor 状态文件。
    """
    if not _captcha_active(gateway):
        return True
    try:
        from core.captcha_v7 import solve_v7
        from core.window_manager import window_manager
        hwnd = int(getattr(window_manager, "hwnd", 0) or 0)
        ok, detail = solve_v7(hwnd, gateway=gateway)
        if ok:
            if verbose:
                print(f"  验证码 V7 直解成功 答案={detail.get('answer')}", flush=True)
            return True
        if detail.get("reason") != "no_captcha" and verbose:
            print(f"  验证码 V7 未解成功({detail.get('reason')})，等待人工/monitor...", flush=True)
        return False
    except Exception as e:
        if verbose:
            print(f"  验证码直解异常: {e}", flush=True)
        return False


# ============================================================
# PID / 后台模式 / 地图包走路
# ============================================================

def _get_bound_pid() -> int:
    """取 GUI 绑定的游戏 PID。"""
    try:
        from core.window_manager import window_manager
        return int(getattr(window_manager, "pid", 0) or 0)
    except Exception:
        return 0


def _is_background_mode() -> bool:
    """读配置判断地图包是否应走后台点击。"""
    try:
        from config.config import config
        return config.get("window.input_mode", "") == "background"
    except Exception:
        return True


def _get_map_walker(map_name: str) -> Optional[Callable]:
    """根据中文地图名返回对应地图包主函数（如 JNYW/DHW）。失败返回 None。"""
    mod_name = _MAP_MODULE_NAMES.get(map_name) or _MAP_MODULE_NAMES.get(map_name.replace("城", ""))
    if not mod_name:
        return None
    try:
        mod = __import__(f"library.map_packs.{mod_name}", fromlist=[mod_name])
        return getattr(mod, mod_name, None)
    except Exception:
        return None


def _load_calibration(map_name: str) -> Optional[dict]:
    """读取校准工具落盘的地图数据 data/map_calibration/<地图名>.json。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "data", "map_calibration", f"{map_name}.json")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        ox, oy = d["origin_pixel"]
        sx, sy = d["scale"]
        if not sx or not sy:
            return None
        return {"origin": (float(ox), float(oy)), "scale": (float(sx), float(sy))}
    except Exception:
        return None


def _calibrated_walk(map_name: str, gx: int, gy: int, pid: int,
                     background: bool = True, verbose: bool = False) -> dict:
    """无专用地图包时的通用走路：校准数据 Tab 开大图 → 后台点目标像素。

    数据来自校准工具 `save <地图名>` 落盘的 JSON。不瞬移，与地图包同款点击链路。
    """
    calib = _load_calibration(map_name)
    if calib is None:
        return {"ok": False,
                "message": f"地图 '{map_name}' 无地图包且无校准数据"
                           f"（用校准工具 save {map_name} 生成）"}
    try:
        from library.common.win_utils import (locate_game_window,
                                              client_to_screen)
        from library.map_packs.DHW import (_click_background, _press_tab,
                                           _click_foreground)
    except Exception as e:
        return {"ok": False, "message": f"导入点击助手失败: {e}"}
    hwnd, _title = locate_game_window(pid, verbose=verbose)
    if not hwnd:
        return {"ok": False, "message": f"未找到游戏窗口 (PID={pid})"}
    ox, oy = calib["origin"]
    sx, sy = calib["scale"]
    px, py = ox + gx * sx, oy + gy * sy
    _press_tab(hwnd, background=background)   # 打开大地图
    if background:
        _click_background(hwnd, px, py)
    else:
        sxp, syp = client_to_screen(hwnd, px, py)
        _click_foreground(hwnd, px, py)
        if verbose:
            print(f"  前台点击 屏幕({sxp},{syp})")
    msg = f"✓ 校准走路 ({gx},{gy}) → 像素({px:.1f},{py:.1f})"
    if verbose:
        print(f"  {msg}")
    return {"ok": True, "message": msg, "target_pixel": (px, py)}


def _walk_to(map_name: str, gx: int, gy: int, pid: int = None,
             background: bool = True, verbose: bool = False) -> dict:
    """使用地图包走路/寻路到 (gx,gy)。不瞬移。

    无专用地图包时，回退到校准数据通用走路（data/map_calibration/<地图名>.json）。
    返回地图包的结果 dict，额外字段 ok/message。
    """
    walker = _get_map_walker(map_name)
    pid = pid or _get_bound_pid()
    if pid <= 0:
        return {"ok": False, "message": "未绑定游戏 PID，无法走路"}
    if walker is None:
        return _calibrated_walk(map_name, int(gx), int(gy), pid,
                                background=background, verbose=verbose)
    try:
        res = walker((int(gx), int(gy)), pid=pid, click=True,
                     background=background, verbose=verbose)
        if isinstance(res, dict):
            return res
        return {"ok": bool(res), "message": str(res)}
    except Exception as e:
        return {"ok": False, "message": f"地图包走路异常: {e}"}


# ============================================================
# 聊天公告读取与解析（gateway /api/net/recvall 嗅探版）
# ============================================================
#
# 2026-08-27 实测定论：游戏内 tp.外部聊天框/消息框 只是绘制控件，无消息数组；
# 真正可靠的公告源是 **网关 recv 缓存** —— 服务器公告以 proto38 下发：
#   do local ret={序号=38,内容={频道="xt",内容="#R/一群妖魔鬼怪冲破了仙界封印，
#   来到了#G/江南野外、东海湾、长寿郊外、大唐国境、花果山#R/作恶..."}} return ret end
# 实测公告样本（频道 xt = 系统）：
#   一群妖魔鬼怪冲破了仙界封印，来到了A、B、C作恶...      → 妖魔+鬼怪 × 多图
#   雷霆一劈，天空中飞来许多灵猴，他们出现在了大唐国境处捣乱 → 下凡的灵猴
#   据说有新型冠状病毒出现在花果山到处感染人类...
#   三界财神爷出现在花果山赐福...
#   仙帝下凡，魔尊转世，人皇出世...在北俱芦洲和各位少侠交手
#   师傅的心魔,跑到长安酒店一楼处祸害人间...

# 公告颜色码（#R/#G/#Y/#W/#S(频道名)/#数字）剥离用
_COLOR_CODE_RE = re.compile(r"#(?:[RGYWBS]/?|[0-9]{1,3}|\([^\)]*\))")

# BOSS 别名：公告关键词 → 场景实体名列表
_BOSS_ALIASES: Dict[str, List[str]] = {
    "妖魔鬼怪": ["妖魔", "鬼怪"],
    "灵猴": ["下凡的灵猴", "天降灵猴"],
    # “特派星官下凡至宝象国赐福”（2026-08-27 实测公告）；实体名二选一待扫场景确认
    "星官": ["下凡的星官", "星官"],
}

# 地图名别名（公告名 → 监控表名）
_MAP_ALIASES: Dict[str, str] = {
    "长安酒店一楼": "长安",
    "长安城": "长安",
}


def _strip_colors(text: str) -> str:
    """剥掉 #R/#G/#Y/#W/#S(...) 等 GM 颜色码，返回纯文本。"""
    return _COLOR_CODE_RE.sub("", text or "")


def fetch_recv_announcements(gateway: str, channel: str = "xt") -> List[Dict[str, Any]]:
    """从网关 /api/net/recvall 缓存提取系统公告（proto38），按缓存顺序去重。

    返回 [{channel, text}]，text 已剥离颜色码。缓存 2000 条约覆盖几十分钟，
    足够覆盖 20~30 分钟粒度的刷新周期。
    """
    r = _http_json(gateway, "/api/net/recvall", timeout=30.0)
    pkts = r.get("result", r)
    if not isinstance(pkts, list):
        pkts = pkts.get("packets") or pkts.get("value") or []
    seen = set()
    out: List[Dict[str, Any]] = []
    for p in pkts:
        hx = (p.get("hex") or "").replace(" ", "")
        if len(hx) <= 24:
            continue
        try:
            raw = bytes.fromhex(hx)
            body = raw[12:].decode("gbk", errors="replace")
        except Exception:
            continue
        for seg in body.split(":7"):
            # 结尾是 '}}'（内层内容表 + 外层 ret 表），必须允许连续右括号
            m = re.search(
                r'序号=38,内容=\{(?:频道="([^"]*)",)?内容="(.*?)"\}+\s*return ret end',
                seg, re.S,
            )
            if not m:
                continue
            ch = m.group(1) or ""
            if channel and ch != channel:
                continue
            txt = _strip_colors(m.group(2))
            if not txt:
                continue
            key = txt[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append({"channel": ch, "raw": m.group(0), "text": txt})
    return out


def probe_chat_raw(gateway: str, lines: int = 200) -> List[str]:
    """读取最近系统公告文本列表（时间顺序）。兼容旧接口，底层走 recvall 嗅探。"""
    anns = fetch_recv_announcements(gateway)
    msgs = [a["text"] for a in anns]
    return msgs[-int(lines):] if lines else msgs


def parse_spawn_notification(
    text: str,
    target_bosses: List[str],
    monitored_maps: List[str],
    spawn_patterns: List[str] = None,
) -> Optional[Dict[str, Any]]:
    """从单条公告文本解析 BOSS 刷新通知。返回 {boss,map,text} 或 None。

    解析策略（实测评级）：
      1. 别名展开：公告词（妖魔鬼怪/灵猴）→ 实体 BOSS 名；
      2. 地图定位：取文本中出现的监控地图名（多图公告 → 取第一张有地图包的图，
         上层轮换扫描时会把其余图也扫一遍）。
    """
    t = text or ""
    # 1) 展开公告中的 BOSS 关键词为实体名集合
    boss_names = set()
    for kw, aliases in _BOSS_ALIASES.items():
        if kw in t:
            boss_names.update(aliases)
    # 直接提到的目标 BOSS 名（星宿具体名等）
    for b in target_bosses:
        if b and b in t:
            boss_names.add(b)
    if not boss_names:
        return None
    # 过滤到目标集
    tgt = set(target_bosses)
    boss_names = {b for b in boss_names if b in tgt}
    if not boss_names:
        return None
    # 2) 提取地图名（含别名归一）
    maps_found = []
    normalized = t
    for alias, std in _MAP_ALIASES.items():
        if alias in normalized and std not in maps_found:
            normalized += "。" + std  # 归一化追加，让下方检测命中标准名
    for mp in monitored_maps:
        if mp in normalized and mp not in maps_found:
            maps_found.append(mp)
    # 有地图包的图一律可定位（即使不在监控轮换表里，也能跨图去打）
    for extra in _MAP_MODULE_NAMES:
        if extra in normalized and extra not in maps_found:
            maps_found.append(extra)
    if not maps_found:
        # 公告只报 BOSS 名不报地图 → 按 BOSS_SPAWN_MAPS 兜底选图
        # （2026-08-27 公告截图：妖魔刷“江南野外、东海湾、长寿郊外、大唐国境、花果山”）
        fallback: List[str] = []
        for b in sorted(boss_names):
            for mp in BOSS_SPAWN_MAPS.get(b, []):
                if mp not in fallback:
                    fallback.append(mp)
        if not fallback:
            return None
        return {"boss": sorted(boss_names)[0], "map": fallback[0],
                "maps": fallback, "text": t, "map_source": "spawn_table"}
    boss = sorted(boss_names)[0]
    return {"boss": boss, "map": maps_found[0], "maps": maps_found,
            "text": t, "map_source": "notice"}


def find_latest_spawn(
    gateway: str,
    target_bosses: List[str],
    monitored_maps: List[str],
    spawn_patterns: List[str] = None,
    lines: int = 200,
) -> Optional[Dict[str, Any]]:
    """读网关嗅探公告，返回最近一条有效 BOSS 刷新通知。"""
    msgs = probe_chat_raw(gateway, lines)
    for text in reversed(msgs):
        parsed = parse_spawn_notification(text, target_bosses, monitored_maps, spawn_patterns)
        if parsed:
            return parsed
    return None


# ============================================================
# 场景 BOSS 扫描与 CALL 战斗
# ============================================================

def scan_scene_bosses(
    gateway: str,
    target_bosses: List[str],
    exact_match: Tuple[str, ...] = EXACT_MATCH_BOSSES,
) -> List[Dict[str, Any]]:
    """扫描 tp.场景.场景人物 + tp.临时Npc，返回匹配目标 BOSS 的候选列表。"""
    code = r'''
local out = {}
local function scan(tbl, src)
  if type(tbl) ~= "table" then return end
  for id, u in pairs(tbl) do
    if type(u) == "table" then
      local name = tostring(u.名称 or u.名字 or "")
      local model = tostring(u.模型 or u.模型名 or "")
      local gx = tonumber(u.格子x or u.x or -1) or -1
      local gy = tonumber(u.格子y or u.y or -1) or -1
      local bsid = tostring(u.标识 or "")   -- 全场唯一且跨槽位重排稳定，实测 2026-08-27
      if #name > 0 then
        out[#out+1] = string.format("%s|%s|%s|%s|%s|%s|%s", tostring(id), name, gx, gy, model, src, bsid)
      end
    end
  end
end
scan(tp.场景.场景人物, "npc")
scan(tp.临时Npc, "tmp")
_G.__out = table.concat(out, ";")
'''
    raw = _lua(gateway, code)
    cands = []
    for entry in (raw or "").split(";"):
        parts = entry.split("|")
        if len(parts) < 6:
            continue
        uid, name, gx, gy, model, src = parts[:6]
        bsid = parts[6] if len(parts) > 6 else ""
        for boss in target_bosses:
            matched = (name == boss) if boss in exact_match else ((boss in name) or (name == boss))
            if matched:
                try:
                    cands.append({
                        "id": uid, "name": name,
                        "gx": int(gx), "gy": int(gy), "model": model,
                        "src": src, "boss_pattern": boss,
                        "bsid": bsid,
                    })
                except ValueError:
                    pass
                break
    return cands


def call_npc_event_start(gateway: str, uid: str = None, bsid: str = None) -> Tuple[bool, str]:
    """CALL 场景 BOSS 的 事件开始。

    优先按 ``标识``（全场唯一、跨槽位重排稳定，2026-08-27 实测编号/数组索引都会
    被槽位池复用）重找对象；找不到再退回 uid 数字键。"""
    bsid_lit = (bsid or "").replace('"', "")
    code = f'''
local u = nil
if "{bsid_lit}" ~= "" then
  local pools = {{tp.场景.场景人物, tp.临时Npc}}
  for _, t in ipairs(pools) do
    if type(t) == "table" then
      for _, e in pairs(t) do
        if type(e) == "table" and tostring(e.标识 or "") == "{bsid_lit}" then
          u = e; break
        end
      end
      if u then break end
    end
  end
end
if not u and "{uid or ""}" ~= "" then
  local n = tonumber("{uid}")
  local t = tp.场景.场景人物 or {{}}
  if n then u = t[n] end
  if not u then u = t["{uid}"] or (tp.临时Npc or {{}})["{uid}"] end
end
if not u then _G.__out = "NOTFOUND"; return end
local mt = getmetatable(u)
local ev = (mt and mt.__index and mt.__index.事件开始) or u["事件开始"]
if type(ev) ~= "function" then _G.__out = "NOFN"; return end
local ok, ret = pcall(function() return ev(u) end)
_G.__out = tostring(ok) .. "|" .. tostring(ret or "")
'''
    raw = _lua(gateway, code)
    if raw == "NOTFOUND":
        return False, "目标已消失"
    parts = raw.split("|", 1)
    return parts[0] == "true", (parts[1] if len(parts) > 1 else "")


def get_dialog_options(gateway: str) -> List[Dict[str, str]]:
    """读取对话栏选项。"""
    code = r'''
local out = {}
local opts = (tp.窗口.对话栏 or {}).选项
if opts then
  for i = 1, 20 do
    local o = opts[i]
    if type(o) ~= "table" then break end
    out[#out+1] = string.format("%s|%s|%s",
      tostring(o.基本内容 or ""),
      tostring(o.跳转链接 or ""),
      tostring(o.文字 or o.标签 or ""))
  end
end
_G.__out = table.concat(out, "\n")
'''
    raw = _lua(gateway, code)
    opts = []
    for line in (raw or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) >= 2:
            opts.append({"text": parts[0], "link": parts[1],
                         "label": parts[2] if len(parts) > 2 else ""})
    return opts


def call_dialog_battle(gateway: str, keywords: List[str]) -> Tuple[bool, str]:
    """在对话栏选项中匹配战斗关键词并 CALL 事件解析(跳转链接)。

    黑名单优先：含“你认错人了”等拒绝措辞的选项绝不点
    （2026-08-27 星官实测：选错=拒绝赐福，白跑一趟）。"""
    opts = get_dialog_options(gateway)
    if not opts:
        return False, "对话栏无选项"
    for o in opts:
        text = f"{o['text']}|{o['label']}|{o['link']}"
        if any(deny in text for deny in _BATTLE_DENY_OPTIONS):
            continue
        for kw in keywords:
            if kw in text:
                code = f'''
local link = "{o['link']}"
local ok, ret = pcall(function() return tp.窗口.对话栏:事件解析(link) end)
_G.__out = tostring(ok) .. "|" .. tostring(ret or "")
'''
                raw = _lua(gateway, code)
                parts = raw.split("|", 1)
                return parts[0] == "true", f"选项[{o['text']}] 关键词[{kw}] ok={parts[0]}"
    return False, f"无匹配关键词，选项={[o['text'] for o in opts]}"


def close_dialog(gateway: str) -> None:
    """右键关闭当前对话栏。"""
    try:
        _lua(gateway, r'''
if tp.窗口.对话栏 and tp.窗口.对话栏.可视 then
  pcall(function() tp.窗口.对话栏:关闭() end)
end
''')
    except Exception:
        pass


def _boss_battle_keywords(boss_name: str, fallback: List[str]) -> List[str]:
    """根据 BOSS 实体名返回专用战斗关键词列表，再拼通用兜底。"""
    # 天降灵猴的公告名与场景实体名差异
    aliases = {
        "天降灵猴": ["天降灵猴", "下凡的灵猴"],
        "下凡的灵猴": ["下凡的灵猴", "天降灵猴"],
    }
    names = aliases.get(boss_name, [boss_name])
    kws: List[str] = []
    for n in names:
        kws.extend(BOSS_BATTLE_KEYWORDS.get(n, []))
    # 去重并保持顺序
    seen = set()
    unique = []
    for k in kws:
        if k not in seen and len(k) > 0:
            seen.add(k)
            unique.append(k)
    return unique + [k for k in fallback if k not in seen]


def _wait_battle_end(gateway: str, timeout: float = 180.0, poll: float = 2.0) -> bool:
    """轮询 tp.战斗中；先等到 true（战斗开始），再等回 false（结束）。"""
    t0 = time.time()
    started = False
    while time.time() - t0 < timeout:
        b = _in_battle(gateway)
        if b:
            started = True
        elif started:
            return True
        time.sleep(poll)
    return started


def _ensure_on_map(gateway: str, target_map: str, x: int = None, y: int = None) -> bool:
    """确保角色在 target_map；不在则跨图，在则落地图中心/指定坐标。返回是否到位。"""
    cur = _cur_map_name(gateway)
    if cur == target_map:
        cx, cy = (x, y) if (x is not None and y is not None) else DEFAULT_MAP_CENTER.get(target_map, (80, 80))
        _gw_teleport(gateway, cx, cy)
        return True
    try:
        r = _gw_cross_map(gateway, target_map, x, y)
        time.sleep(1.0)
        return bool(r.get("ok"))
    except Exception as e:
        logger.warning(f"_ensure_on_map 跨图失败: {e}")
        return False


# ============================================================
# 主循环
# ============================================================

# ============================================================
# 距离门控：走近 BOSS（走路优先，随机落点瞬移兜底）
# ============================================================

import math as _math


def _role_grid(gateway: str):
    """读角色网格坐标（内部坐标 ÷20）。失败返回 None。"""
    try:
        px = float(_lua_expr(gateway, "tp.角色坐标.x"))
        py = float(_lua_expr(gateway, "tp.角色坐标.y"))
        return px / 20.0, py / 20.0
    except Exception:
        return None


def _grid_dist(rg, gx: float, gy: float) -> float:
    if rg is None:
        return 999.0
    return _math.hypot(rg[0] - gx, rg[1] - gy)


def _wait_arrival_grid(gateway: str, tx: float, ty: float,
                       timeout: float = 90.0, poll: float = 1.2,
                       tol: float = APPROACH_GRID_DISTANCE) -> bool:
    """轮询角色网格坐标，等待走到 (tx,ty) 附近（距离≤tol）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        rg = _role_grid(gateway)
        if rg and _grid_dist(rg, tx, ty) <= tol:
            return True
        time.sleep(poll)
    return False


def _approach_boss(gateway: str, cur_map: str, boss_gx: int, boss_gy: int,
                   walk_background: bool, verbose: bool) -> str:
    """把角色带到能 CALL 的距离内。返回模式:
      "close"      已在阈值内，无需移动
      "walked"     地图包真实走路到位
      "teleported" 无地图包/走不到 → 随机环带落点瞬移兜底（不重叠BOSS）
      "far"        全部手段失败，仍超距（调用方应跳过该BOSS）
    """
    rg = _role_grid(gateway)
    if rg is not None and _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE:
        return "close"

    # 1) 有地图包或校准数据 → 真实走路（拟人优先，防举报）
    if _get_map_walker(cur_map) or _load_calibration(cur_map):
        jx = max(0, int(boss_gx) + random.randint(-2, 2))
        jy = max(0, int(boss_gy) + random.randint(-2, 2))
        if verbose:
            print(f"  → 走路贴近 {cur_map} ({jx},{jy})", flush=True)
        walk_res = _walk_to(cur_map, jx, jy, background=walk_background, verbose=verbose)
        if walk_res.get("ok") and _wait_arrival_grid(gateway, jx, jy):
            return "walked"
        if verbose:
            print(f"  ! 走路未到位（{walk_res.get('message')}），转瞬移兜底", flush=True)

    # 2) 无地图包/走不到 → 随机环带落点瞬移（用户批准的兜底）
    for rng in (TELEPORT_OFFSET_RANGE, TELEPORT_RETRY_RANGE):
        ang = random.uniform(0.0, _math.tau)
        d = random.uniform(*rng)
        # 保证 ≥3 格起步：cos/sin 可能同时接近 0 造成落点贴脸，重抽一次
        if _math.hypot(_math.cos(ang), _math.sin(ang)) * d < 2.0:
            ang += 0.7
        tx = max(0, int(round(boss_gx + _math.cos(ang) * d)))
        ty = max(0, int(round(boss_gy + _math.sin(ang) * d)))
        if verbose:
            print(f"  → 瞬移到 BOSS 周边随机落点 ({tx},{ty})（距BOSS≈{d:.1f}格）", flush=True)
        try:
            _gw_teleport(gateway, tx, ty)
        except Exception as e:
            logger.warning(f"瞬移失败: {e}")
            continue
        time.sleep(1.0)
        rg = _role_grid(gateway)
        if rg is None or _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE + 1:
            return "teleported"
    return "far"


def _move_to_ring(gateway: str, cur_map: str, boss_gx: float, boss_gy: float,
                  walk_background: bool, verbose: bool,
                  ring_range=QUICK_CALL_RING_RANGE) -> bool:
    """移动到 BOSS 周边“随机环带”落点（默认10~50格，用户定案 2026-08-27）。

    有地图包 → 真实走路；无地图包/走路失败 → 随机环带点瞬移兜底。
    返回是否成功靠近目标环带点。
    """
    ang = random.uniform(0.0, _math.tau)
    d = random.uniform(*ring_range)
    tx = max(0, int(round(boss_gx + _math.cos(ang) * d)))
    ty = max(0, int(round(boss_gy + _math.sin(ang) * d)))

    if _get_map_walker(cur_map) or _load_calibration(cur_map):
        if verbose:
            print(f"  → 太远提示：走到 {cur_map} 周边环带 ({tx},{ty})（距BOSS≈{d:.0f}格）", flush=True)
        walk_res = _walk_to(cur_map, tx, ty, background=walk_background, verbose=verbose)
        if walk_res.get("ok") and _wait_arrival_grid(gateway, tx, ty):
            return True
        if verbose:
            print(f"  ! 走路未到位（{walk_res.get('message')}），转瞬移兜底", flush=True)

    try:
        if verbose:
            print(f"  → 瞬移到环带落点 ({tx},{ty})（距BOSS≈{d:.0f}格）", flush=True)
        _gw_teleport(gateway, tx, ty)
        time.sleep(1.0)
        rg = _role_grid(gateway)
        return rg is not None and _grid_dist(rg, tx, ty) <= 4
    except Exception as e:
        logger.warning(f"环带瞬移失败: {e}")
        return False


def _farm_one_boss(
    gateway: str,
    boss: dict,
    battle_keywords: List[str],
    battle_timeout: float,
    walk_background: bool,
    verbose: bool,
    cur_map: str,
) -> dict:
    """对单个 BOSS 实体。

    用户定案流程（2026-08-27）：原地 CALL → 若弹“距离太远”（表现为对话无战斗
    选项）→ 移动到 BOSS 周边随机 10~50 格 → 再 CALL；成功继续，失败再走。
    循环 QUICK_CALL_MAX_TRIES 次仍不中才跳过该只。"""
    for attempt in range(1, QUICK_CALL_MAX_TRIES + 1):
        ok, msg = call_npc_event_start(gateway, boss.get("id"), boss.get("bsid"))
        if not ok:
            if "消失" in msg or "NOTFOUND" in msg:
                return {"ok": False, "reason": "gone", "msg": msg}
            # CALL 直接失败（对象找不到/无函数）→ 移动后重试
        else:
            time.sleep(1.5)
            bok, bmsg = call_dialog_battle(gateway, battle_keywords)
            if bok:
                ended = _wait_battle_end(gateway, timeout=battle_timeout)
                close_dialog(gateway)
                return {"ok": True, "battle_ended": ended, "msg": bmsg,
                        "approach": f"CALL×{attempt}"}
            # 开了对话但无战斗选项 ≈ 弹“你距离这个NPC太远了”→ 走环带重试
            close_dialog(gateway)
            if verbose:
                print(f"  [尝试{attempt}] 太远提示（{bmsg}），移动到随机环带再CALL", flush=True)

        if attempt == QUICK_CALL_MAX_TRIES:
            break
        time.sleep(random.uniform(0.5, 1.2))
        if not _move_to_ring(gateway, cur_map, boss["gx"], boss["gy"],
                             walk_background, verbose):
            break

    return {"ok": False, "reason": "no_battle_option",
            "msg": f"{QUICK_CALL_MAX_TRIES}次环带CALL均未命中战斗选项"}


def _pick_random_map(cur_map: Optional[str], monitored_maps: List[str]) -> str:
    """从监控地图里随机挑一张（排除当前地图）。全部排除时兜底当前图以外任意一张。"""
    pool = [m for m in monitored_maps if m != cur_map] or list(monitored_maps)
    return random.choice(pool)


def WORLD_BOSS_auto_farm(
    monitored_maps: List[str] = None,
    target_bosses: List[str] = None,
    spawn_patterns: List[str] = None,
    battle_keywords: List[str] = None,
    home_coord: Tuple[int, int] = (240, 101),
    max_runtime: int = 1800,
    chat_poll_interval: float = 1.5,
    boss_scan_interval: float = 2.0,
    clear_timeout: float = 10.0,
    battle_timeout: float = 180.0,
    walk_background: bool = True,
    verbose: bool = True,
    gateway: str = DEFAULT_GATEWAY,
) -> dict:
    """世界BOSS自动监控 farming 主入口。

    优先级：聊天公告 > 随机轮换地图。
      1) 每轮循环先查聊天窗口公告（约 boss_scan_interval 一次），有公告立刻去公告图；
      2) 无公告时：当前图 Lua 扫描无目标 → clear_timeout 内仍无 → 随机换一张
         非当前图的监控地图继续 Lua 扫描（等 clear_timeout 的间隙同样在轮询公告）。
    """
    monitored_maps = monitored_maps or list(DEFAULT_MONITORED_MAPS)
    target_bosses = target_bosses or list(DEFAULT_TARGET_BOSSES)
    spawn_patterns = spawn_patterns or list(DEFAULT_SPAWN_PATTERNS)
    battle_keywords = battle_keywords or list(DEFAULT_BATTLE_KEYWORDS)

    t0 = time.time()
    cur_map = None           # 当前正在 farming 的地图
    no_boss_since = None     # 最近一次在 cur_map 扫到 BOSS 的时刻
    farmed_total = 0
    print("=== WORLD_BOSS_auto_farm 开始 ===", flush=True)
    print(f"  监控地图={monitored_maps}", flush=True)
    print(f"  目标BOSS={target_bosses[:10]}{'...' if len(target_bosses)>10 else ''}", flush=True)

    while time.time() - t0 < max_runtime:
        # 0) 验证码避让：弹窗时先 V7 直解（Lua 读答案+按钮坐标自动点掉），解不掉才暂停等待
        if not _captcha_solve(gateway, verbose):
            if verbose:
                print(f"[{int(time.time()-t0)}s] 验证码窗口弹出且未解除，暂停等待...", flush=True)
            time.sleep(5)
            continue

        # 1) 聊天公告 → 目标地图
        spawn = find_latest_spawn(gateway, target_bosses, monitored_maps, spawn_patterns)
        if spawn:
            if cur_map != spawn["map"]:
                if verbose:
                    extra = f"（公告图: {'、'.join(spawn.get('maps', []))}）" if len(spawn.get("maps", [])) > 1 else ""
                    print(f"[{int(time.time()-t0)}s] 公告: {spawn['boss']} @ {spawn['map']}{extra}", flush=True)
                cur_map = spawn["map"]
                no_boss_since = None
            _ensure_on_map(gateway, spawn["map"], None, None)
        elif cur_map is None:
            # 暂无公告：随机切一张监控地图扫描（保持在线待命）
            cur_map = _pick_random_map(None, monitored_maps)
            no_boss_since = None
            if verbose:
                print(f"[{int(time.time()-t0)}s] 暂无公告，随机扫描 {cur_map}", flush=True)
            _ensure_on_map(gateway, cur_map, None, None)

        # 2) 扫描当前地图 BOSS
        bosses = scan_scene_bosses(gateway, target_bosses)
        if bosses:
            no_boss_since = None
            if verbose:
                print(f"[{int(time.time()-t0)}s] {cur_map} 发现 {len(bosses)} 个BOSS: "
                      + ", ".join(f"{b['name']}@{b['gx']},{b['gy']}" for b in bosses), flush=True)
            # 每击杀一只后重扫：战斗后场景人物槽位/实例会重排（SYBUZ2 同款坑），
            # 静态列表的 id/bsid 会错位导致 CALL 错实体（2026-08-27 实测）。
            excluded = set()  # 本轮已失败的 (name,gx,gy)，防止对同一尸体反复尝试
            while time.time() - t0 < max_runtime:
                if not _captcha_solve(gateway, verbose):
                    break
                live = [x for x in scan_scene_bosses(gateway, target_bosses)
                        if (x["name"], x["gx"], x["gy"]) not in excluded]
                if not live:
                    break
                try:
                    px = float(_lua_expr(gateway, "tp.角色坐标.x"))
                    py = float(_lua_expr(gateway, "tp.角色坐标.y"))
                    gx0, gy0 = px / 20.0, py / 20.0
                except Exception:
                    gx0, gy0 = 0.0, 0.0
                # 优先级（三界财神爷>知了王>其他）为主键，同优先级按距离近先打
                b = min(live, key=lambda x: (_boss_priority(x["name"]),
                                             (x["gx"] - gx0) ** 2 + (x["gy"] - gy0) ** 2))
                this_keywords = _boss_battle_keywords(b["name"], list(battle_keywords))
                res = _farm_one_boss(gateway, b, this_keywords, battle_timeout,
                                     walk_background, verbose, cur_map)
                if res.get("ok"):
                    farmed_total += 1
                    print(f"  ✓ 击杀 {b['name']} @ {cur_map}（累计 {farmed_total}）", flush=True)
                else:
                    print(f"  ✗ {b['name']} 跳过: {res.get('reason')} {res.get('msg')}", flush=True)
                    excluded.add((b["name"], b["gx"], b["gy"]))
                time.sleep(1.0)
        else:
            # 3) 当前地图无 BOSS
            if no_boss_since is None:
                no_boss_since = time.time()
            elif time.time() - no_boss_since >= clear_timeout:
                # 清图：随机换一张非当前地图（聊天公告优先级更高，下一轮循环即会被打断）
                nxt = _pick_random_map(cur_map, monitored_maps)
                if verbose:
                    print(f"[{int(time.time()-t0)}s] {cur_map} 已清图（{clear_timeout}s无BOSS），"
                          f"随机轮换 → {nxt}", flush=True)
                cur_map = nxt
                no_boss_since = None
                _ensure_on_map(gateway, cur_map, None, None)
            time.sleep(boss_scan_interval)
            continue

        time.sleep(boss_scan_interval)

    print(f"=== WORLD_BOSS_auto_farm 结束：累计击杀 {farmed_total}，耗时 {int(time.time()-t0)}s ===", flush=True)
    return {"ok": True, "farmed_total": farmed_total, "elapsed": int(time.time() - t0)}


def _next_schedule_time(minutes_list: List[int], pre_minutes: int = 0) -> Optional[datetime]:
    """返回今天内下一个符合分钟列表的时间点（可提前 pre_minutes）。"""
    if not minutes_list:
        return None
    now = datetime.now()
    # 当前小时内的候选
    candidates = []
    for m in minutes_list:
        dt = now.replace(minute=m, second=0, microsecond=0)
        dt_pre = dt.replace(minute=max(0, m - pre_minutes))
        if dt_pre <= now:
            candidates.append(dt)
        else:
            candidates.append(dt_pre)
    # 下个小时起的候选
    future = []
    for m in minutes_list:
        nxt = now.replace(minute=m, second=0, microsecond=0)
        if nxt < now:
            nxt = nxt.replace(hour=(now.hour + 1) % 24)
        nxt_pre = nxt.replace(minute=max(0, m - pre_minutes))
        future.append(nxt_pre)
    all_valid = [d for d in candidates + future if d > now]
    return min(all_valid) if all_valid else None


def WORLD_BOSS_wait_and_farm(
    target_bosses: List[str] = None,
    schedule: Dict[str, List[int]] = None,
    pre_start_minutes: int = 2,
    max_wait_minutes: int = 60,
    gateway: str = DEFAULT_GATEWAY,
    verbose: bool = True,
    **farm_kwargs,
) -> dict:
    """按刷新时间表等待，到最近一个刷新点前 pre_start_minutes 分钟启动 farming。

    若 target_bosses 含多个，取所有 BOSS 中最近的刷新时间点。
    """
    target_bosses = target_bosses or list(DEFAULT_TARGET_BOSSES)
    schedule = schedule or dict(DEFAULT_BOSS_SCHEDULE)

    # 计算下一个最近刷新点
    nearest: Optional[datetime] = None
    nearest_boss = ""
    for boss in target_bosses:
        minutes = schedule.get(boss, [])
        if not minutes:
            continue
        dt = _next_schedule_time(minutes, pre_start_minutes)
        if dt and (nearest is None or dt < nearest):
            nearest = dt
            nearest_boss = boss

    if nearest is None:
        return {"ok": False, "message": "未找到有效的刷新时间表，无法定时启动"}

    now = datetime.now()
    wait_sec = max(0, int((nearest - now).total_seconds()))
    if wait_sec > max_wait_minutes * 60:
        return {"ok": False, "message": f"下一个刷新点 {nearest_boss} @ {nearest} 超过最大等待 {max_wait_minutes} 分钟"}

    if verbose:
        print(f"[WORLD_BOSS] 等待到 {nearest}（{nearest_boss} 刷新前{pre_start_minutes}分钟），还需 {wait_sec}s", flush=True)
    time.sleep(wait_sec)

    # 启动主 farm
    result = WORLD_BOSS_auto_farm(
        target_bosses=target_bosses,
        gateway=gateway,
        verbose=verbose,
        **farm_kwargs,
    )
    result["scheduled_at"] = nearest.isoformat()
    result["scheduled_boss"] = nearest_boss
    return result


# ============================================================
# 调试 / 确认清单
# ============================================================

def WORLD_BOSS_probe_chat(lines: int = 120, gateway: str = DEFAULT_GATEWAY) -> dict:
    """探测聊天框原始内容（验证聊天字段名 + 公告格式）。"""
    msgs = probe_chat_raw(gateway, lines)
    hits = []
    for ln in msgs:
        if any(b in ln for b in DEFAULT_TARGET_BOSSES) or any(m in ln for m in DEFAULT_MONITORED_MAPS):
            hits.append(ln)
    return {"total_lines": len(msgs), "boss_or_map_lines": hits, "recent": msgs[-20:]}


def WORLD_BOSS_confirm_list() -> List[dict]:
    """返回需要用户确认的方向/决策清单。"""
    return [
        {"topic": "公告嗅探通道",
         "question": "（已实测解决）公告改走 gateway /api/net/recvall 嗅探 proto38 频道=xt。",
         "default": "fetch_recv_announcements() 已在 2026-08-27 实测抓到妖魔/灵猴/财神爷/心魔等真实公告。",
         "risk": "若换角色/端口，注意 gateway 地址参数"},
        {"topic": "公告文本格式",
         "question": "（已实测）妖魔鬼怪为多图公告（A、B、C、D、E）；灵猴单图；星宿具体公告尚未捕获样本。",
         "default": "解析按『BOSS关键词 + 文本中出现的监控地图名』匹配，不依赖固定句式；新格式只需扩 _BOSS_ALIASES/_MAP_ALIASES。",
         "risk": "星宿公告格式未验证→首轮星宿刷新时跑 probe_chat 核对"},
        {"topic": "BOSS 实体归属",
         "question": "刷新出的BOSS是 tp.场景.场景人物 还是 tp.临时Npc？",
         "default": "代码同时扫 场景人物 与 临时Npc。",
         "risk": "只扫错表→看不到BOSS"},
        {"topic": "战斗触发关键词",
         "question": "点BOSS后对话选项里，第一行红色字是否就是进战斗选项？",
         "default": "已按截图配置：妖魔/鬼怪→让我来收拾你；天降灵猴/下凡的灵猴→我来瞧瞧你的啥；知了王→知了还这么嚣张？讨打！；二十八星宿→请星君赐教/那我就不客气了。",
         "risk": "关键词错→CALL事件解析点错选项→不进战斗/选到路过"},
        {"topic": "走路地图包",
         "question": "目标地图是否都有对应地图包（JNYW/JYC/DHW/CAC/CSC）？",
         "default": "有地图包→真实走路；无地图包（花果山）→ BOSS 周边随机环带落点瞬移兜底（3~8格，不重叠），2026-08-27 用户批准。",
         "risk": "落点随机在障碍物旁可能卡走不到→CALL仍太远则跳过该只，下轮重试"},
        {"topic": "距离门控",
         "question": "超距 CALL 会弹“你距离这个NPC太远了”，阈值是多少格？",
         "default": "APPROACH_GRID_DISTANCE=4 格：≤4 直接 CALL，>4 先走近（走路优先）。",
         "risk": "阈值过小多一次逼近动作；过大仍弹太远提示"},
        {"topic": "清图判定",
         "question": "怎样算'这张图刷的BOSS打完了'？是无BOSS持续N秒，还是有'XX已消失'公告？",
         "default": "clear_timeout=30s 连续无BOSS即轮换；可调。",
         "risk": "阈值小→频繁空转切图；大→漏掉新刷"},
    ]


if __name__ == "__main__":
    import sys
    gw = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GATEWAY
    res = WORLD_BOSS_probe_chat(gateway=gw)
    print(json.dumps(res, ensure_ascii=False, indent=2))
