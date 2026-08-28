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
  4b. **先 CALL 再走近（2026-08-28 用户定案）**：每个 BOSS 先原地 CALL ``事件开始``；
     只有 CALL 弹超距确认框 / 选项点了没进战斗 / 对象级失败时，才走近一次
     （走路优先，瞬移兜底）再 CALL。不做 CALL 前的距离预检走近。
  5. **CALL 进战斗**：调用 NPC 对象 ``事件开始`` → 读对话栏选项 → 用 BOSS 类别
     对应的红色战斗文案（如妖魔/鬼怪“让我来收拾你”，星宿“请星君赐教”）匹配 →
     CALL ``事件解析(跳转链接)`` 触发战斗；超距/未进战斗 → 走近一次重 CALL。
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
from collections import deque as _deque
from datetime import datetime as _datetime, timedelta as _timedelta
from typing import Optional, Tuple, List, Dict, Any, Callable  # noqa: 仅注解使用；模块尾部收编为下划线，避免进 GUI 函数列表
from urllib.request import Request as _Request, urlopen as _urlopen

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
    from core.group_config import gateway_url as _gateway_url
    DEFAULT_GATEWAY = _gateway_url()
except Exception:
    # 2026-08-28 补丁3：最后兜底，仅 group_config 导入失败（独立 CLI 运行）时生效。
    # 原 WORLD_BOSS_GATEWAY 环境变量 override 已删除（冗余配置通道，与组配置并存
    # 违反单一事实源）；实验指定网关请用函数 gateway= 参数。
    DEFAULT_GATEWAY = "http://127.0.0.1:18082"

# GUI 函数下拉框中文标注（core/task_library_manager._get_signature_str 约定：
# 命中 title 时显示 "中文标题  |  原签名"）。2026-08-28。
__function_meta__ = {
    "WORLD_BOSS_captcha_gate": {
        "title": "世界BOSS：防挂机验证码门（任务链首事件，有弹窗V7自动解）",
        "args": {
            "gateway": "网关地址，默认读组配置（http://127.0.0.1:18082）",
            "verbose": "是否打印细节",
        },
    },
    "WORLD_BOSS_auto_farm": {
        "title": "世界BOSS：自动监控 farming 主入口（公告+实扫+CALL战斗）",
        "args": {
            "monitored_maps": "监控地图列表，默认内置监控表",
            "target_bosses": "目标 BOSS 名单，默认内置白名单",
            "spawn_patterns": "公告刷新句式正则，默认内置",
            "battle_keywords": "对话栏战斗关键词，默认内置",
            "home_coord": "初始回点坐标 (gx, gy)，默认 (240, 101)",
            "max_runtime": "最长运行秒数，默认 1800",
            "chat_poll_interval": "聊天公告轮询间隔秒",
            "boss_scan_interval": "到图后 BOSS 实扫间隔秒",
            "clear_timeout": "清图判定秒数（无怪超此值即换图）",
            "battle_timeout": "单场战斗等待超时秒",
            "walk_background": "True=后台走路（PostMessage），False=前台",
            "verbose": "是否打印过程日志",
            "gateway": "网关地址，默认读组配置",
        },
    },
    "WORLD_BOSS_wait_and_farm": {
        "title": "世界BOSS：按刷新时间表等待，到点前自动启动 farming",
        "args": {
            "target_bosses": "目标 BOSS 名单（取最近的刷新时间点）",
            "schedule": "刷新时间表 {BOSS名: [分钟,...]}，默认内置",
            "pre_start_minutes": "提前多少分钟启动 farming，默认 2",
            "max_wait_minutes": "最大等待分钟数，超时直接返回",
            "gateway": "网关地址，默认读组配置",
            "verbose": "是否打印过程日志",
        },
    },
    "WORLD_BOSS_probe_chat": {
        "title": "世界BOSS：探测聊天框原始公告（验证字段名/格式）",
        "args": {
            "lines": "读取最近多少条，默认 120",
            "gateway": "网关地址，默认读组配置",
        },
    },
    "WORLD_BOSS_chat_maintenance": {
        "title": "世界BOSS：聊天通道例行维护（清理网关大缓存）",
        "args": {
            "gateway": "网关地址，默认读组配置",
            "verbose": "是否打印细节",
        },
    },
    "WORLD_BOSS_confirm_list": {
        "title": "世界BOSS：返回需用户确认的方向/决策清单",
    },
    "fetch_recv_announcements": {
        "title": "提取网关系统公告（proto38，xt系统+cw传说频道去重）",
        "args": {
            "gateway": "网关地址",
            "channel": "公告频道元组，默认 (\"xt\", \"cw\")",
        },
    },
    "probe_chat_raw": {
        "title": "读取最近系统公告文本列表（时间顺序，兼容旧接口）",
        "args": {
            "gateway": "网关地址",
            "lines": "最多返回最近多少条",
        },
    },
    "parse_spawn_notification": {
        "title": "解析单条公告为 BOSS 刷新通知 {boss,map,text}",
        "args": {
            "text": "公告原文",
            "target_bosses": "目标 BOSS 名单",
            "monitored_maps": "监控地图名单",
            "spawn_patterns": "可选刷新句式正则",
        },
    },
    "find_latest_spawn": {
        "title": "从公告缓存解析最近一条 BOSS 刷新通知",
        "args": {
            "gateway": "网关地址",
            "target_bosses": "目标 BOSS 名单",
            "monitored_maps": "监控地图名单",
            "spawn_patterns": "可选刷新句式正则",
            "lines": "回看最近多少条公告，默认 200",
        },
    },
    "scan_scene_bosses": {
        "title": "实扫当前场景 BOSS 实体（场景人物+临时Npc）",
        "args": {
            "gateway": "网关地址",
            "target_bosses": "目标 BOSS 名单",
            "exact_match": "需精确匹配的 BOSS 名元组，默认内置",
        },
    },
    "call_npc_event_start": {
        "title": "CALL 场景 BOSS 的『事件开始』进对话",
        "args": {
            "gateway": "网关地址",
            "uid": "实体数字键（按标识重找后兜底）",
            "bsid": "实体唯一标识（优先）",
        },
    },
    "get_dialog_options": {
        "title": "读取对话栏选项列表",
        "args": {"gateway": "网关地址"},
    },
    "call_dialog_battle": {
        "title": "对话栏匹配战斗关键词并 CALL 事件解析进战斗",
        "args": {
            "gateway": "网关地址",
            "keywords": "战斗关键词列表（黑名单『你认错人了』优先拦截）",
        },
    },
    "close_dialog": {
        "title": "右键关闭当前对话栏",
        "args": {"gateway": "网关地址"},
    },
}


def _gui_stop_requested() -> bool:
    """GUI 任务引擎的停止标志（'停止'按钮置位 core.task_engine.task_engine.should_stop）。

    farming 长循环每轮轮询它，保证 GUI 上点"停止"后几秒内安全退出，
    不必等 max_runtime 跑满。独立脚本/测试环境 import 失败 → 视为不停止。
    """
    try:
        from core.task_engine import task_engine as _eng
        return bool(getattr(_eng, "should_stop", None) and _eng.should_stop.is_set())
    except Exception:
        return False


def _sleep_stoppable(seconds: float) -> bool:
    """可被 GUI 停止打断的 sleep：0.5s 粒度分段。

    :return: True = 正常睡完；False = 中途收到停止信号（提前返回）。
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _gui_stop_requested():
            return False
        time.sleep(min(0.5, max(0.05, deadline - time.time())))
    return not _gui_stop_requested()


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
    "妖魔头领",     # 2026-08-27 公告实际用词：“妖魔头领气得正在傲来国寻衅闹事”
    "知了王",
    # “师傅的心魔”已按用户要求移除（2026-08-27 23:28 目前打不过，以后能打过再加回）
    # “星官/下凡的星官”已移除（2026-08-27 23:39 实测：赐福 NPC，对话选项=
    #  “请星官赐福/你认错人了”，根本无战斗选项，留着只会导致无限走近+CALL 空转）
    "地煞星",       # 2026-08-27 传说频道(cw)实锤：随机词缀名（“初出茅庐地煞星”等），按类别子串匹配
    "天罡星",
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
    "北俱芦洲", # 2026-08-27 链路实测：'花果山传送北俱芦洲' 全局直达；校准走路（2026-08-27 用户校准 像素(627,304)@191,63）
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
    "1514": "花果山",   # 2026-08-27 实测：'北俱芦洲传送花果山' 全局直达
    "1174": "北俱芦洲", # 2026-08-27 实测
    "1091": "长寿郊外", # 2026-08-27 实测：'长寿村传送长寿郊外' 直达
    "1070": "长寿村",   # 2026-08-27 实测：'长寿郊外传送长寿村' 直达
    "1092": "傲来国",   # 2026-08-28 实测：'花果山传送傲来国' 全局直达
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
    # ★ 2026-08-27 实测新增（花果山链路打通，全部单 token 全局直达）：
    "花果山":   ["北俱芦洲传送花果山"],
    "北俱芦洲": ["花果山传送北俱芦洲"],
    "长寿郊外": ["长寿村传送长寿郊外"],
    "长寿村":   ["长寿郊外传送长寿村"],
    # ★ 2026-08-28 实测：东海湾传送表无傲来国、长安表也无，唯一入口在花果山
    #   （"花果山传送傲来国"）。按 BFS 全局查表铁律，任意位置可直达。
    "傲来国":   ["花果山传送傲来国"],
    "方寸山":   ["长寿郊外传送长寿村", "长寿村传送方寸山"],
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
# 泛化传说公告锚点（2026-08-27 实测，频道标签="cw" 不是 "xt"）：
#   “神秘的初出茅庐地煞星带着天界的宝物降临在了柳林坡、东海湾、江南野外一带，
#    只有智勇双全的强者才有机缘获得宝物，少侠敢来挑战么！”
# BOSS 名词缀随机生成无法穷举 → 锚定句子结构提取，类别取已知后缀（子串匹配实体名）。
_GENERIC_SPAWN_RE = re.compile(r"([^\s，,。]{2,24}?)带着天界的宝物降临在了([^\s，,。]+)")
_GENERIC_BOSS_CLASSES = ("地煞星", "天罡星", "星宿", "生肖")

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
    "妖魔头领":    ["让我来收拾你", "收拾你"],  # 2026-08-27 公告实际用词是"妖魔头领"（非"统领"）
    "天降灵猴":    ["我来瞧瞧你的啥", "瞧瞧你的啥"],
    "下凡的灵猴":  ["我来瞧瞧你的啥", "瞧瞧你的啥"],
    "知了王":      ["知了还这么嚣张？讨打！", "讨打", "嚣张"],
    "心魔":        ["消灭他们", "消灭", "前去消灭"],
    "二十八星宿":  ["请星君赐", "那我就不客气了", "不客气"],  # "请星君赐"前缀兼
                     # 容"请星君赐教"（教）与"请星君赐消"（消，2026-08-27 星官截图）
    "十二生肖":    ["那我就不客气了", "不客气"],  # 2026-08-27 实测寅虎对话：红色选项“那我就不客气了”，
                                                  # 第二行“你继续观赏景色吧”=取消
    # 2026-08-28 三界财神爷截图：红色选项“我要试试”（领取/开战），“我就试试”变体兜底。
    # “查看”类说明性选项不在本表 → 永不误点，更不会被当成最高优先级动作。
    "三界财神爷":  ["我要试试", "我就试试"],
}
# 二十八星宿每个具体名共享同一套关键词
for _s in _28_STAR_BOSSES:
    BOSS_BATTLE_KEYWORDS.setdefault(_s, BOSS_BATTLE_KEYWORDS["二十八星宿"])
# 十二生肖每个具体名共享同一套关键词
for _s in _12_ZODIAC_BOSSES:
    BOSS_BATTLE_KEYWORDS.setdefault(_s, BOSS_BATTLE_KEYWORDS["十二生肖"])

# 通用战斗关键词兜底（当BOSS具体名没匹配到时）。
# 注意：“是的我要去/我还要逛逛”是超距确认框不是战斗选项，绝不放进关键词
# （点了会被服务器静默拒绝且对话原样留着），由 _dialog_is_too_far 专门识别。
DEFAULT_BATTLE_KEYWORDS = [
    "挑战", "战斗", "击杀", "抓捕", "制服", "对付", "消灭", "进入战斗", "讨伐",
    "降服",  # 十二生肖公告用词：“赶紧去降服它们”（2026-08-27 截图）
]

# 超距确认框标志：CALL 后弹出的对话含这些字样 = 距离太远，需要走近后重试。
_FAR_DIALOG_MARKERS = ("是的我要去", "我还要逛逛", "太远")

# 对话选项黑名单：含这些措辞的选项绝不点（星官实测“你认错人了”=拒绝赐福）。
_BATTLE_DENY_OPTIONS = (
    "你认错人了",
    "告辞",
    "再见",
    "离开",
)

# CALL 优先定案（用户 2026-08-27 20:52 明确）：每只 BOSS 先原地 CALL；
# 只有弹“太远”确认框/无战斗选项时才走近（走路优先）一次，再 CALL 重试。
# 绝不“打过一只就先走一段”，也绝不失败后随机散开环带——都太费时间。
QUICK_CALL_MAX_TRIES = 3
# 2026-08-28 C11：4→6 格。实测 CALL 命中最远 19.2 格（超距确认框阈值远比
# 想象宽），4 格让边走边CALL多跑冤枉路；6 格在"少走路"与"防太远弹窗"间取衡。
APPROACH_GRID_DISTANCE = 6.0
WALK_ARRIVAL_TIMEOUT = 30.0  # 走路贴近后等"离BOSS进范围"的上限（旧 90s 太长，怪在眼前干等）
WALK_ARRIVAL_BOX = 20        # 2026-08-28 用户定案：落点 ±20 格内就算"走路到位"，
                             # 不再强制走到 4 格内才认（CALL 不中由后续补瞬移拉近）
WALK_START_TIMEOUT = 6.0     # 走路点击后角色坐标必须在这窗口内动起来；
                             # 不动 = 点击没生效（像素映射偏差/被 UI 吃掉），立即转瞬移
WALK_STALL_TIMEOUT = 6.0     # 走路中途连续无位移上限（卡住/被打断 → 放弃走路转瞬移）
# ★ 2026-08-28 用户定案"边走边CALL"：打开地图点击目标坐标后，立即关闭地图并
#   马上 CALL 目标，每 WALK_CALL_INTERVAL 秒 CALL 一次，绝无"到达后傻等固定延迟"。
#   超时上限 = 距离 / 预计走路速度 + 余量（≈走到落点的时刻）；走完仍未中 →
#   落点再补一次 CALL 兜底。接近目标即可 CALL 成功，无需精确站上坐标点。
WALK_CALL_INTERVAL = 0.5     # 边走边CALL 节拍（秒）
WALK_SPEED_GRID_SEC = 4.0    # 预计走路速度（格/秒），用于估算走路超时上限
WALK_TIME_MARGIN = 5.0       # 走路时间估算余量（秒），覆盖起步/寻路绕行开销
# 无地图包瞬移兜底落点：BOSS 周边随机环带半径范围（格）。绝不落在 BOSS 坐标上。
TELEPORT_OFFSET_RANGE = (3.0, 8.0)
# 第一次落点仍超距时，第二次补传用更近的半径。
TELEPORT_RETRY_RANGE = (2.0, 4.0)

# 必须名称完全相等才匹配的 BOSS（避免“妖魔”误中普通 NPC）。
# 注意：扫描时“天降灵猴”的公告名可能对应场景实体“下凡的灵猴”，需同时注册。
EXACT_MATCH_BOSSES = ("知了王", "妖魔统领", "天降灵猴", "下凡的灵猴", "三界财神爷")

# 击杀优先级（2026-08-28 用户修订）：数字越小越优先。
# 根因修复：旧表只有财神爷/知了王，星宿/灵猴/生肖全落默认 2 与妖魔鬼怪同级，
# 妖魔鬼怪数量多+距离近永远赢 → "偏向打妖魔鬼怪"。现在稀有怪全部压过普通怪。
# 2026-08-28 二修（用户实测"没看到打妖魔头领，基本都是妖魔鬼怪"）：
#   场景杂鱼实体名是完整词"妖魔鬼怪"，旧表只登记了"妖魔/鬼怪"两词，
#   导致"妖魔鬼怪"落默认 2、反而压过头领的 3 → 优先级倒挂。
#   现：头领/统领=2（杂鱼之上），"妖魔鬼怪"显式登记=3（垫底）。
#   0 三界财神爷（用户指定最高）
#   1 限时稀有：知了王 / 灵猴 / 二十八星宿 / 天罡地煞 / 十二生肖
#   2 妖魔头领 / 妖魔统领（公告点名的大怪）
#   3 妖魔鬼怪 / 妖魔 / 鬼怪（每小时 :10 常刷、数量多，垫底——打不完不用抢）
# 2026-08-28 五定案（用户 20:55）：妖魔鬼怪/妖魔/鬼怪=最低优先级重新生效——
#   本表恢复参与普通模式排序：稀有(1) > 头领/统领(2) > 妖族杂鱼(3)垫底；
#   且妖族公告不再触发跨图（LOW_PRIORITY_BOSSES），只在场景内顺手清。
# 2026-08-28 六定案（用户 21:02）：未登记(默认 2) 从 _boss_priority 移除——
#   未登记实体一律视为非目标（不排序/不攻击），白名单+本表双重门控，
#   防止未知 NPC/杂鱼被走近+CALL 空转。词缀类（"初出茅庐地煞星"）按类别子串归级。
BOSS_PRIORITY = {
    "三界财神爷": 0,
    "知了王": 1,
    "天降灵猴": 1,
    "下凡的灵猴": 1,
    "地煞星": 1,
    "天罡星": 1,
    "妖魔头领": 2,
    "妖魔统领": 2,
    "妖魔鬼怪": 3,
    "妖魔": 3,
    "鬼怪": 3,
}
for _n in _28_STAR_BOSSES:
    BOSS_PRIORITY[_n] = 1
for _n in _12_ZODIAC_BOSSES:
    BOSS_PRIORITY[_n] = 1

# 2026-08-28 五定案：这批公告词/实体名视为"杂鱼"——公告不触发跨图，
# 场景内排序永远垫底（其他 BOSS 打完才轮到它们）。
LOW_PRIORITY_BOSSES = {"妖魔鬼怪", "妖魔", "鬼怪"}

# 2026-08-28 用户定案：三界财神爷"最最最优先"抢占模式。
# 公告出现（未进战斗/刚离战）→ 立即瞬移财神爷图，期间绝不 CALL 其他怪；
# 财神爷没了/被人锁定 → 解除抢占回落普通模式。普通模式除财神爷外无优先级。
CAISHEN_BOSS = "三界财神爷"
# 2026-08-28 用户四定案：财神爷图扫不到财神 → 立即回落（本图 CALL 其他 BOSS，
# 没有其他再换图），绝不多轮干等。2 次×0.5s 间隔只容忍场景加载瞬间。
CAISHEN_SCAN_MISS_LIMIT = 2
CAISHEN_SCAN_MISS_GAP = 0.5


def _boss_priority(name: str):
    """BOSS 击杀优先级；未登记返回 None（=非目标，不参与排序/攻击）。

    词缀类（六定案）：场景实体名带随机词缀（如"初出茅庐地煞星"），
    按类别子串归到该类别的优先级，否则词缀名会被误判为未登记非目标。
    """
    n = str(name or "").strip()
    if n in BOSS_PRIORITY:
        return BOSS_PRIORITY[n]
    for cls in ("地煞星", "天罡星"):
        if cls in n:
            return BOSS_PRIORITY[cls]
    return None

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
    "WORLD_BOSS_chat_maintenance": {
        "title": "清理网关 recv/send/hex 大缓存（10分钟一次防膨胀，噪声消息已在解析层过滤）",
        "params": {"gateway": "网关地址", "verbose": "是否打印日志"},
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
    """POST JSON 到 gateway，返回解析后的 JSON。

    2026-08-27：网关不在线（WinError 10061 连接拒绝）时不再直接炸任务——
    先走 _heal_gateway()（gateway_guard.ensure_gateway 按 window_manager.pid
    重拉并 attach），成功后重试一次；仍失败才抛出。
    """
    body = json.dumps(data).encode("utf-8") if data is not None else None

    def _once():
        req = _Request(
            gateway.rstrip("/") + path,
            data=body,
            headers={"Content-Type": "application/json"} if body else {},
        )
        with _urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    try:
        return _once()
    except Exception as e:
        refused = isinstance(getattr(e, "reason", None), ConnectionRefusedError)
        if not (refused or "10061" in str(e)):
            raise
        if not _heal_gateway():
            # 2026-08-27：冷启动 attach 可达 170~200s，ensure_gateway 的
            # 轮询窗口偶发卡边缘误报 timeout——网关其实马上就绪。
            # heal "失败"后缓冲 20s 直接重试 HTTP 一次，不放弃。
            time.sleep(20.0)
            return _once()
        return _once()


def _heal_gateway() -> bool:
    """frida script 销毁（游戏重开导致 PID 失联）时自愈网关。

    通过 gateway_guard.ensure_gateway() 杀旧网关并按 window_manager.pid
    重新拉起。独立运行/导入失败时静默放弃。

    2026-08-27：冷启动 attach 实测 170~200s（ensure_gateway timeout=300s），
    期间任务引擎日志完全静默，看起来像"卡死"（用户 22:26 报告，实际 5m23s
    后自愈成功）。这里补上开始/结束日志，让自愈过程可见。
    """
    try:
        from core import gateway_guard
        _t0 = time.time()
        logger.info("网关自愈开始（冷启动 attach 可达 170~200s，非卡死，请耐心等待）...")
        ok, _info = gateway_guard.ensure_gateway(verbose=False)
        logger.info(f"网关自愈{'成功' if ok else '失败'} 耗时 {time.time() - _t0:.0f}s info={_info}")
        return bool(ok)
    except Exception as e:
        logger.warning(f"网关自愈异常: {e}")
        return False


def _is_bridge_dead(err: str) -> bool:
    """判断网关错误是否为 frida 会话已失效。"""
    e = str(err)
    return ("script has been destroyed" in e
            or "目标进程" in e and "不存在" in e
            or "Failed to attach" in e
            or "process not found" in e.lower())


def _lua(gateway: str, code: str, result_var: str = "__out") -> str:
    """经 /api/lua 执行 Lua 语句块，返回 result_var 值字符串。

    frida 会话死亡（游戏重开换 PID）时自动自愈网关并重试一次。
    """
    r = _http_json(gateway, "/api/lua", {"code": code, "result_var": result_var})
    if not r.get("ok"):
        err = str(r.get("error", r))
        if _is_bridge_dead(err) and _heal_gateway():
            r = _http_json(gateway, "/api/lua",
                           {"code": code, "result_var": result_var})
            if not r.get("ok"):
                raise RuntimeError(f"Lua 执行失败: {r.get('error', r)}")
        else:
            raise RuntimeError(f"Lua 执行失败: {r.get('error', r)}")
    return (r.get("result") or {}).get("value") or ""


def _lua_expr(gateway: str, expr: str) -> str:
    """经 /api/lua/expr 执行单个表达式，会话死亡时自动自愈重试一次。"""
    r = _http_json(gateway, "/api/lua/expr", {"expr": expr})
    if not r.get("ok"):
        err = str(r.get("error", r))
        if _is_bridge_dead(err) and _heal_gateway():
            r = _http_json(gateway, "/api/lua/expr", {"expr": expr})
            if not r.get("ok"):
                raise RuntimeError(f"expr 失败: {r.get('error', r)}")
        else:
            raise RuntimeError(f"expr 失败: {r.get('error', r)}")
    return (r.get("result") or {}).get("value") or ""


# ============================================================
# 坐标体系守门（2026-08-28 用户实测：东海湾被瞬到 4710,7235 出界）
# ============================================================
# 根因：传送表 t[i].坐标 / 部分实体 x/y 存的是**内部像素坐标（网格×20）**，
# 直接当网格发给网关会被再 ×20（或直接写入位置），角色落到地图边界外，
# HUD 显示 4710,7235 这类"分辨率级"数值。
# 铁律：**任何瞬移坐标必须过 _norm_grid_xy 守门，像素/网格自动判定 + 边界钳制。**

# 梦幻单张地图网格上限经验值（最大图 ~300×240 格）。超过 → 判为像素坐标。
GRID_SANITY_MAX = 400

_MAP_BOUNDS_CACHE: Dict[str, Tuple[int, int]] = {}


def _load_map_bounds(map_name: str) -> Optional[Tuple[int, int]]:
    """读 data/map_ui_blocks.json 的 max_game_coord（用户实测边界），返回 (max_x,max_y)。"""
    if map_name in _MAP_BOUNDS_CACHE:
        return _MAP_BOUNDS_CACHE[map_name]
    bounds = None
    try:
        p = os.path.join(_PROJECT_ROOT, "data", "map_ui_blocks.json")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        mx = data.get(map_name, {}).get("max_game_coord")
        if mx and len(mx) >= 2:
            bounds = (int(mx[0]), int(mx[1]))
    except Exception:
        bounds = None
    _MAP_BOUNDS_CACHE[map_name] = bounds
    return bounds


def _norm_grid_xy(x, y, map_name: str = None):
    """把可疑坐标规约成合法网格坐标，返回 (x, y, note)。

    规则：
      1. x/y 任一 > GRID_SANITY_MAX → 判为内部像素坐标，÷20 转网格；
      2. 已知地图边界（map_ui_blocks.max_game_coord，用户实测）→ 钳制入界；
      3. 未知地图至少保证 ≥0 且 ≤GRID_SANITY_MAX。
    """
    x, y = float(x), float(y)
    note = ""
    if abs(x) > GRID_SANITY_MAX or abs(y) > GRID_SANITY_MAX:
        x, y = x / 20.0, y / 20.0
        note = "像素→网格÷20"
    if map_name:
        b = _load_map_bounds(map_name)
        if b:
            cx = int(min(max(round(x), 0), b[0]))
            cy = int(min(max(round(y), 0), b[1]))
            if (cx, cy) != (int(round(x)), int(round(y))):
                note = (note + "+边界钳制").lstrip("+") if note else "边界钳制"
            x, y = cx, cy
        else:
            x = int(min(max(round(x), 0), GRID_SANITY_MAX))
            y = int(min(max(round(y), 0), GRID_SANITY_MAX))
    else:
        x = int(min(max(round(x), 0), GRID_SANITY_MAX))
        y = int(min(max(round(y), 0), GRID_SANITY_MAX))
    return x, y, note


def _gw_teleport(gateway: str, x: int, y: int, map_name: str = None) -> dict:
    """瞬移到地图网格坐标 (x,y)。网关内部 ×20 发内部坐标 + 1002 同步。
    2026-08-28：入口强制过 _norm_grid_xy 守门（像素自动÷20 + 边界钳制）。
    """
    nx, ny, note = _norm_grid_xy(x, y, map_name)
    if note:
        logger.warning(f"瞬移坐标守门: ({x},{y}) → ({nx},{ny}) [{note}]")
    return _http_json(
        gateway, "/api/act/teleport",
        {"x": int(nx), "y": int(ny), "sync": True, "jump": True}, timeout=15.0,
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
        # 2026-08-28 量纲修复：tp.场景.传送.坐标 恒为内部像素（×20 网格，
        # 全量实测均为 20 倍数，如 傲来国传送女儿村 (120,220)→网格(6,11)），
        # 读取时即转网格；>GRID_SANITY_MAX 才转的守门会漏掉 (120,220) 这类小值。
        return desc_part, int(float(x) / 20), int(float(y) / 20)
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
        # 2026-08-28 量纲修复：与 _find_hop_teleport 同源，传送表坐标恒为内部像素，÷20 转网格
        return desc_part, int(float(x) / 20), int(float(y) / 20)
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
        # 2026-08-28 守门：传送表坐标可能是内部像素值（如 4710,7235），过守门再发
        tx, ty, note = _norm_grid_xy(tx, ty, target_map)
        if note:
            logger.warning(f"cross_map 坐标守门: desc={desc} 原始=({d_x},{d_y}) "
                           f"→ ({tx},{ty}) [{note}]")
        return _http_json(gateway, "/api/act/cross_map",
                          {"desc": desc, "x": int(tx), "y": int(ty),
                           "wait_ms": 3500, "sync": True}, timeout=25.0)
    # 实测链路兜底（2026-08-27）：desc 全局查表 → 链式拼接从任意位置直达。
    # 2026-08-28 B6 修复：旧实现每步发完请求不查结果，链中一步被吞整链错位
    # （后续 hop 都基于错误起点）。现在每步查 HTTP ok，失败静默重发一次。
    chain = _HOP_CHAINS.get(target_map)
    if chain:
        for desc in chain:
            for _attempt in (1, 2):
                r = _http_json(gateway, "/api/act/cross_map",
                               {"desc": desc, "x": 100, "y": 100,
                                "wait_ms": 3000, "sync": True}, timeout=25.0)
                if isinstance(r, dict) and r.get("ok"):
                    break
                logger.warning(f"hop 链步骤失败({'重试' if _attempt == 1 else '放弃'}): "
                               f"desc={desc} resp={r}")
                time.sleep(1.0)
            time.sleep(1.2)  # 2026-08-28 提速轮：1.8→1.2（网关 sync+wait_ms 已等主程）
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
    # ★ 大地图有效点击范围钳制（2026-08-28）：WORLD_BOSS 直连走路绕过了
    #   task_library_manager 的避让钩子，这里显式走 map_coord_ui_avoid，
    #   否则 map_ui_blocks.json 的 max_game_coord 对 BOSS farming 不生效。
    try:
        from core.map_ui_block import map_coord_ui_avoid
        _gx, _gy, _ui = map_coord_ui_avoid(map_name, int(gx), int(gy))
        if (_gx, _gy) != (int(gx), int(gy)):
            if verbose:
                print(f"  [UI避让] {map_name} ({gx},{gy}) → ({_gx:.0f},{_gy:.0f})（{_ui}）")
            gx, gy = int(_gx), int(_gy)
    except Exception:
        pass  # 避让失败不阻断走路
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

# 聊天噪声过滤（用户 2026-08-27 定案）：系统频道里这些内容不看——
# 活跃度奖励提示、鲜衣怒马会员卡广告等，纯浪费解析时间。
_CHAT_NOISE_MARKERS = ("活跃度奖励", "活跃度", "鲜衣怒马", "会员卡", "会员")


def _is_chat_noise(text: str) -> bool:
    return any(m in (text or "") for m in _CHAT_NOISE_MARKERS)

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


# 2026-08-28 B9：recvall 全量 dump 的 TTL 缓存——内层每杀一只前的财神爷公告
# 检查曾每次都拉全量缓存（2000 包解析），3s TTL 内复用结果，量级下降。
# 副作用仅是公告最长滞后 3s 被感知，对 20~30 分钟粒度的刷新周期无影响。
_ANN_CACHE: Dict[str, Any] = {"t": 0.0, "items": []}
_ANN_CACHE_TTL = 3.0


def fetch_recv_announcements(gateway: str, channel=("xt", "cw")) -> List[Dict[str, Any]]:
    """从网关 /api/net/recvall 缓存提取系统公告（proto38），按缓存顺序去重。

    channel 默认收 "xt"(系统) + "cw"(传说) 两种频道 —— 2026-08-27 实测
    世界BOSS（地煞星/天罡星）公告走的是 cw 频道，只收 xt 会整条漏掉。

    返回 [{channel, text}]，text 已剥离颜色码。缓存 2000 条约覆盖几十分钟，
    足够覆盖 20~30 分钟粒度的刷新周期。
    """
    # 注意：第3个位置参数是 data，timeout 必须用关键字传参
    #（曾因 timeout=30.0 被当成 body POST 导致网关 404）
    now = time.time()
    if now - _ANN_CACHE["t"] < _ANN_CACHE_TTL:
        return _ANN_CACHE["items"]
    r = _http_json(gateway, "/api/net/recvall", None, timeout=30.0)
    # 网关异常时 result 为 null（如 frida 脚本销毁），安全降级为空列表
    if not isinstance(r, dict):
        return []
    pkts = r.get("result")
    if not isinstance(pkts, list) and isinstance(pkts, dict):
        pkts = pkts.get("packets") or pkts.get("value")
    if not isinstance(pkts, list):
        return []
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
            if channel and ch not in channel:
                continue
            txt = _strip_colors(m.group(2))
            if not txt:
                continue
            if _is_chat_noise(txt):
                continue
            key = txt[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append({"channel": ch, "raw": m.group(0), "text": txt})
    _ANN_CACHE["t"] = now
    _ANN_CACHE["items"] = out
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
    # 0) 泛化锚点（2026-08-27 传说频道实锤格式，BOSS 名随机词缀）：
    #    “神秘的初出茅庐地煞星带着天界的宝物降临在了柳林坡、东海湾、江南野外一带…”
    #    提取已知类别后缀（地煞星/天罡星…）作为目标名；多张地图整句保留，
    #    下方地图名检测会在整句里逐个命中监控图。
    m_gen = _GENERIC_SPAWN_RE.search(t)
    boss_names = set()
    if m_gen:
        for cls in _GENERIC_BOSS_CLASSES:
            if cls in m_gen.group(1):
                boss_names.add(cls)
                break
    # 1) 展开公告中的 BOSS 关键词为实体名集合
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

def _boss_key(b: dict) -> tuple:
    """excluded 黑名单键（2026-08-28 A2 修复）。

    旧键 (name,gx,gy)：同一坐标重生的新怪会被上一只尸体的黑名单永久误排除；
    同名双实体同格也互相误伤。改用 bsid（全场唯一、跨槽位重排稳定，2026-08-27
    实测）；个别实体无 bsid 时才回退位置键（保守兼容）。"""
    bsid = b.get("bsid") or ""
    return ("bsid", bsid) if bsid else ("pos", b["name"], b["gx"], b["gy"])


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
      -- 2026-08-28 量纲修复：格子x/格子y 本身是网格；兜底字段 u.x/u.y 是内部像素(×20)，在源头÷20
      local gx = tonumber(u.格子x) or ((tonumber(u.x) or -20) / 20)
      local gy = tonumber(u.格子y) or ((tonumber(u.y) or -20) / 20)
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
                    # 2026-08-28 A4 修复：格子x/格子y 可能是浮点（如 "10.5"），
                    # 旧 int("10.5") 直接 ValueError → 实体被静默丢掉
                    bgx, bgy = int(float(gx)), int(float(gy))
                    # 2026-08-28 守门：实体兜底字段 u.x/u.y 可能是内部像素坐标，
                    # >GRID_SANITY_MAX 判为像素 → ÷20 转网格，否则环带瞬移会出界
                    if abs(bgx) > GRID_SANITY_MAX or abs(bgy) > GRID_SANITY_MAX:
                        bgx, bgy = round(bgx / 20.0), round(bgy / 20.0)
                        logger.warning(f"BOSS 坐标守门: {name} 原始=({gx},{gy}) → ({bgx},{bgy}) [像素→网格÷20]")
                    cands.append({
                        "id": uid, "name": name,
                        "gx": bgx, "gy": bgy, "model": model,
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
    # 2026-08-28 实测：下凡的灵猴弹的战斗选项是"让我来收拾你"（与妖魔/鬼怪同款），
    # 并非截图里的"我来瞧瞧你的啥"——类别映射对不上实际文案变体会导致整只跳过。
    # 兜底：把所有类别的关键词并集排在专用词之后（这些文案都是战斗选项专属，
    # 只点已扫描 BOSS 实体，误点风险为零）。
    for _all in BOSS_BATTLE_KEYWORDS.values():
        kws.extend(_all)
    # 去重并保持顺序
    seen = set()
    unique = []
    for k in kws:
        if k not in seen and len(k) > 0:
            seen.add(k)
            unique.append(k)
    return unique + [k for k in fallback if k not in seen]


def _wait_battle_start(gateway: str, timeout: float = 3.0, poll: float = 0.25) -> bool:
    """点了战斗选项后，等待 tp.战斗中 变 true（真进战斗的权威验证）。

    pcall(事件解析) 返回 ok 不代表进战斗（2026-08-27 实测假击杀 14 连：
    pcall ok=true 但战斗根本没触发）。必须以 tp.战斗中 为准。
    2026-08-28：15s→4s、poll 1.0→0.4；再压 4s→3s、0.4→0.25（提速轮）。
    真触发时战斗态 1~2s 内就会出现；没触发就是超距，早失败早走近重试。
    误判成超距的代价只是一次廉价走近重试，且下一轮 _in_battle 守门能兜住
    战斗态迟到的情况。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _in_battle(gateway):
            return True
        time.sleep(poll)
    return False


def _wait_dialog_ready(gateway: str, timeout: float = 1.5, poll: float = 0.2):
    """CALL 后轮询等对话栏弹出（替代固定 sleep 1.5s），返回选项列表。"""
    t0 = time.time()
    opts = []
    while time.time() - t0 < timeout:
        try:
            opts = get_dialog_options(gateway)
        except Exception:
            opts = []
        if opts:
            return opts
        time.sleep(poll)
    return opts


def _wait_battle_end(gateway: str, timeout: float = 180.0, poll: float = 0.5) -> bool:
    """轮询 tp.战斗中；先等到 true（战斗开始），再等回 false（结束）。

    2026-08-28 提速轮：poll 2.0→0.5——战斗结束瞬间最多 0.5s 就察觉，
    旧版每只怪白等平均 1s。"""
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


# 2026-08-28 实测修复：1501 内部 desc=建邺城，客户端显示名=宝象国 —— 两个名字指同一张图。
# _ensure_on_map 严格 == 比较导致「hop 链已到图、落图复核却判失败进 10 分钟冷却」。
_MAP_ALIAS_CANON = {"宝象国": "建邺城"}


def _map_same(a: str, b: str) -> bool:
    """地图名等价比较（宝象国/建邺城互为别名）。"""
    if a == b:
        return True
    return _MAP_ALIAS_CANON.get(a, a) == _MAP_ALIAS_CANON.get(b, b)


def _ensure_on_map(gateway: str, target_map: str, x: int = None, y: int = None) -> bool:
    """确保角色在 target_map；不在则跨图，在则落地图中心/指定坐标。返回是否到位。

    2026-08-28 修复：cross_map 返回 ok ≠ 真到了（hop 链分支发完请求就 ok:True），
    曾出现"人在长寿郊外、日志标花果山、拿花果山校准数据点错屏幕"。
    现在跨图后实读地图名复核，不匹配重试一次，仍不匹配返回 False。"""
    cur = _cur_map_name(gateway)
    if _map_same(cur, target_map):
        cx, cy = (x, y) if (x is not None and y is not None) else DEFAULT_MAP_CENTER.get(target_map, (80, 80))
        _gw_teleport(gateway, cx, cy, map_name=target_map)
        return True
    for _ in range(2):   # ok≠到达：实读复核，最多重试一次
        try:
            _gw_cross_map(gateway, target_map, x, y)
        except Exception as e:
            logger.warning(f"_ensure_on_map 跨图失败: {e}")
        # 2026-08-28 提速轮：固定 sleep 1.5 → 0.3s 步进轮询，地图名一刷新就返回
        for _p in range(5):
            time.sleep(0.3)
            if _map_same(_cur_map_name(gateway), target_map):
                return True
    return False


# ============================================================
# 主循环
# ============================================================

# ============================================================
# 距离门控：走近 BOSS（走路优先，随机落点瞬移兜底）
# ============================================================

import math as _math


def _role_grid(gateway: str):
    """读角色网格坐标（内部坐标 ÷20）。失败返回 None。

    2026-08-28 提速轮：原两次独立 _lua_expr（2 个 HTTP 请求）合并为 1 次。"""
    try:
        v = _lua_expr(gateway, 'tostring(tp.角色坐标.x)..","..tostring(tp.角色坐标.y)')
        xs, ys = v.split(",", 1)
        return float(xs) / 20.0, float(ys) / 20.0
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


def _bigmap_visible(gateway: str) -> Optional[bool]:
    """读大地图可视状态 tp.窗口.小地图.可视。

    ★ 2026-08-28 走路未启动根因修复的关键：
      - 大地图开着时再按 TAB 是**关闭**（toggle），点击会落在游戏场地上无效；
      - `_click_background` 末尾的**右键会把开着的地图关掉**（实测 可视 true→false），
        随后 _close_big_map 再 TAB 就把图**重新打开** → 开关状态永久错位，
        之后每次走路 TAB 都先关图 → 点击无效 → "走路未启动" → 全部退化瞬移。
      因此开/关图前必须先读状态，只在需要时才按 TAB。
    :return: True/False = 读到状态；None = 网关查询失败（调用方按旧逻辑兜底）。
    """
    try:
        v = _lua(gateway, "_G.__out = tostring(tp.窗口.小地图 and tp.窗口.小地图.可视)")
        if v == "true":
            return True
        if v == "false":
            return False
    except Exception:
        pass
    return None


def _press_tab_if(hwnd: int, want_visible: bool, gateway: str,
                  verbose: bool = False) -> bool:
    """状态感知 TAB：仅当大地图可视状态 ≠ want_visible 时才按键，并轮询确认翻转。

    ★ 2026-08-28 二轮修复：按完必须**确认状态真的翻转**（轮询读 可视，最多 ~1.2s）。
      实测两次 TAB 间隔 <0.3s 时游戏可能吞掉一次 toggle（预同步 TAB + 地图包 TAB
      竞态 → 状态与预期相反 → 点击落场地无效 → "走路未启动"）。
    :return: True = 实际按了 TAB（且确认翻转）；False = 状态已满足未按键。
    """
    from library.map_packs.DHW import _press_tab
    vis = _bigmap_visible(gateway)
    if vis is None:
        # 查询失败：按旧逻辑盲按（保持兼容），调用方无法保证状态
        _press_tab(hwnd, background=True)
        return True
    if vis != want_visible:
        # 2026-08-28 B7 修复：首次 TAB 后未确认翻转 → 不再只告警，复核后补按一次。
        # 竞态来源：走路点击末尾的右键关图在途（游戏侧延迟处理），我们读到
        # vis=True 按 TAB，右键先落把图关掉、TAB 再把图打开 → 状态与预期相反。
        # 补按时以实时读到的状态为基准再 toggle 一次，多数情况一轮自愈。
        for _attempt in (1, 2):
            _press_tab(hwnd, background=True)
            # 轮询确认翻转（_press_tab 自带 0.3s settle，这里再给最多 ~1s 余量）
            t0 = time.time()
            while time.time() - t0 < 1.0:
                now = _bigmap_visible(gateway)
                if now == want_visible:
                    if verbose:
                        act = "打开" if want_visible else "关闭"
                        extra = "" if _attempt == 1 else "（补按后成功）"
                        print(f"  ✓ 大地图{act}（可视={vis} → TAB，已确认）{extra}", flush=True)
                    return True
                time.sleep(0.15)
            if _attempt == 1:
                if verbose:
                    print("  ! TAB 后状态未确认翻转（可能被右键关图竞态吞键），补按一次", flush=True)
        if verbose:
            print(f"  ! 大地图 TAB 两次仍未翻转（期望可视={want_visible}）"
                  f"——下轮预同步会再纠正", flush=True)
        return True
    if verbose:
        print(f"  · 大地图已处于目标状态（可视={vis}），跳过 TAB", flush=True)
    return False


def _close_big_map(verbose: bool = False, gateway: str = None) -> None:
    """立即关闭大地图（Tab 键，后台，状态感知）。

    2026-08-28 用户定案：打开地图点击目标坐标后，立即关闭地图并马上 CALL
    （边走边CALL），绝不开着大地图干等。失败只提示不阻断（不影响后续 CALL）。
    窗口解析与走路通道一致：_get_bound_pid() → locate_game_window。
    2026-08-28 状态感知：gateway 可用时先读 可视，已关闭就不按 TAB——
    盲按 TAB 会把刚被右键关掉的地图重新打开（走路失败根因，见 _bigmap_visible）。
    """
    try:
        from library.map_packs.DHW import _press_tab
        from library.common.win_utils import locate_game_window
        pid = _get_bound_pid()
        hwnd = 0
        if pid > 0:
            hwnd, _title = locate_game_window(pid, verbose=False)
        if hwnd:
            if gateway:
                _press_tab_if(hwnd, False, gateway, verbose)
            else:
                _press_tab(hwnd, background=True)
                if verbose:
                    print("  ✓ 大地图已关闭（点完坐标立即关图）", flush=True)
        elif verbose:
            print("  ! 无法定位游戏窗口，跳过关图（不阻断流程）", flush=True)
    except Exception as e:
        if verbose:
            print(f"  ! 关闭大地图失败（不阻断流程）: {e}", flush=True)


def _walk_and_call(gateway: str, boss_gx: int, boss_gy: int,
                   dist0: float, verbose: bool, call_fn) -> str:
    """边走边CALL 主循环（2026-08-28 用户定案）。

    走路点击已发出、大地图已关闭后进入本循环：
      - 每 WALK_CALL_INTERVAL 秒 CALL 一次（接近目标即可命中，无需精确站上坐标）；
      - 超时上限 = 距离 / 预计走路速度 + 余量（≈走到落点的时刻）；
      - CALL 成功立即返回，绝无"到达后傻等固定延迟"；
      - 走完/超时后补一次 CALL 兜底（用户定案）；
      - 卡住检测：连续 WALK_STALL_TIMEOUT 无位移 → 先试补 CALL，再交瞬移兜底。
    :param call_fn: 单次 CALL 尝试，返回 "battle"/"gone"/"far"/"fail"
    :return: "walked_call_ok" CALL已触发战斗 / "gone" 目标消失 / "walked" 走完未中
    """
    timeout = max(3.0, dist0 / WALK_SPEED_GRID_SEC + WALK_TIME_MARGIN)
    t0 = time.time()
    last_rg, last_move_t = _role_grid(gateway), time.time()
    next_call = 0.0
    stalled = False
    while time.time() - t0 < timeout:
        rg = _role_grid(gateway)
        if rg is not None:
            if last_rg is None or _grid_dist(rg, last_rg[0], last_rg[1]) > 0.3:
                last_rg, last_move_t = rg, time.time()
            elif time.time() - last_move_t > WALK_STALL_TIMEOUT:
                if verbose:
                    print(f"  ! 走路卡住（{WALK_STALL_TIMEOUT:.0f}s 无位移，"
                          f"停在 ({rg[0]:.0f},{rg[1]:.0f})），边走边CALL收尾", flush=True)
                stalled = True
                break
        # ★ 边走边CALL：0.5s 节拍，命中战斗立即返回
        if time.time() >= next_call:
            next_call = time.time() + WALK_CALL_INTERVAL
            r = call_fn()
            if r == "battle":
                d = _grid_dist(rg, boss_gx, boss_gy) if rg else -1.0
                if verbose:
                    print(f"  ✓ 边走边CALL命中（{time.time()-t0:.1f}s，距BOSS {d:.1f} 格）",
                          flush=True)
                return "walked_call_ok"
            if r == "gone":
                return "gone"
        time.sleep(0.1)
    # 走完/超时（≈已到落点）或卡住 → 补一次 CALL 兜底（用户定案）
    if verbose:
        print(f"  → 走路阶段结束（{time.time()-t0:.0f}s，"
              f"{'中途卡住' if stalled else '到达估算上限'}），补 CALL 兜底", flush=True)
    r = call_fn()
    if r == "battle":
        return "walked_call_ok"
    if r == "gone":
        return "gone"
    return "walked"


def _approach_boss(gateway: str, cur_map: str, boss_gx: int, boss_gy: int,
                   walk_background: bool, verbose: bool,
                   call_fn=None) -> str:
    """把角色带到能 CALL 的距离内（2026-08-28 边走边CALL 定案版）。

    流程：地图包/校准真实走路 → 点击目标坐标后 **立即关大地图** → 马上开 CALL
    （边走边CALL，每 0.5s 一次，超时上限=距离估算的走路时间，走完补 CALL 兜底）
    → 仍不中再走瞬移环带兜底。全程无"到达后傻等固定延迟"。
    :param call_fn: 单次 CALL 尝试（返回 "battle"/"gone"/"far"/"fail"），见 _farm_one_boss
    :return: "close" 已在阈值内 / "walked_call_ok" 途中/兜底CALL已命中 /
             "walked" 走完仍未中 / "gone" 目标消失 / "teleported" 瞬移兜底 /
             "far" 全部手段失败
    """
    rg = _role_grid(gateway)
    if rg is not None and _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE:
        return "close"

    # 1) 有地图包或校准数据 → 真实走路（拟人优先，防举报）
    if _get_map_walker(cur_map) or _load_calibration(cur_map):
        # lazy-bind：未绑定 PID 时现场绑定（farm 主流程已绑，独立调用/重连后兜底），
        # 否则走路必然报"未绑定 PID"退化成瞬移（2026-08-28 实测暴露）。
        if _get_bound_pid() <= 0:
            _ensure_walker_bound(gateway, verbose=verbose)
        jx = max(0, int(boss_gx) + random.randint(-2, 2))
        jy = max(0, int(boss_gy) + random.randint(-2, 2))
        dist0 = _grid_dist(rg, boss_gx, boss_gy) if rg else 30.0
        est = max(3.0, dist0 / WALK_SPEED_GRID_SEC + WALK_TIME_MARGIN)
        if verbose:
            print(f"  → 走路贴近 {cur_map} ({jx},{jy})（距BOSS≈{dist0:.0f}格，"
                  f"边走边CALL上限 {est:.0f}s）", flush=True)
        # ★ 状态感知预同步（2026-08-28 走路未启动根因修复）：
        #   地图包/校准走路第一步都是"TAB 开图"，若大地图当前已开着，
        #   这个 TAB 会把它关掉 → 点击落场地无效 → 走路必败。
        #   所以走路前先检查：图开着就先 TAB 关掉，让后续 TAB 稳定开图。
        try:
            from library.common.win_utils import locate_game_window as _lgw
            _pid = _get_bound_pid()
            _hwnd = 0
            if _pid > 0:
                _hwnd, _ = _lgw(_pid, verbose=False)
            if _hwnd:
                _press_tab_if(_hwnd, False, gateway, verbose)
        except Exception:
            pass  # 预同步失败不阻断走路
        walk_res = _walk_to(cur_map, jx, jy, background=walk_background, verbose=verbose)
        if walk_res.get("ok"):
            # ★ 用户定案：点完目标坐标立即关大地图，马上 CALL
            _close_big_map(verbose, gateway=gateway)
            # 移动启动门控：点击没生效（角色完全没动）→ 直接转瞬移兜底
            t0s = time.time()
            base = _role_grid(gateway)
            moving = False
            while time.time() - t0s < WALK_START_TIMEOUT:
                rg = _role_grid(gateway)
                if rg and base and _grid_dist(rg, base[0], base[1]) > 0.5:
                    moving = True
                    break
                if rg and base is None:
                    base = rg
                # 2026-08-28 提速：启动探测期不空等——每拍顺手 CALL 一次
                # （点击可能没生效，但 CALL 零成本；中途命中战斗直接省掉瞬移兜底）
                if call_fn is not None:
                    r = call_fn()
                    if r == "battle":
                        return "walked_call_ok"
                    if r == "gone":
                        return "gone"
                time.sleep(0.5)
            if not moving:
                if verbose:
                    print(f"  ! 走路未启动（{WALK_START_TIMEOUT:.0f}s 内角色坐标无变化，"
                          f"点击没生效），转瞬移兜底", flush=True)
            elif call_fn is not None:
                # ★ 边走边CALL：每 0.5s CALL 一次，走完补 CALL 兜底
                r = _walk_and_call(gateway, boss_gx, boss_gy, dist0, verbose, call_fn)
                if r in ("walked_call_ok", "gone"):
                    return r
                # 走完仍未中 → 落点可能仍超距，走下面瞬移环带拉近兜底
            else:
                # 兼容旧调用（无 call_fn）：按落点 ±WALK_ARRIVAL_BOX 轮询到位
                t0w = time.time()
                last_rg, last_move_t = rg, time.time()
                while time.time() - t0w < WALK_ARRIVAL_TIMEOUT:
                    rg = _role_grid(gateway)
                    if rg is not None:
                        if _grid_dist(rg, last_rg[0], last_rg[1]) > 0.3:
                            last_rg, last_move_t = rg, time.time()
                        elif time.time() - last_move_t > WALK_STALL_TIMEOUT:
                            break
                        if _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE:
                            return "walked"
                        if (abs(rg[0] - jx) <= WALK_ARRIVAL_BOX
                                and abs(rg[1] - jy) <= WALK_ARRIVAL_BOX):
                            return "walked"
                    time.sleep(0.4)
        elif verbose:
            print(f"  ! 走路未到位（{walk_res.get('message')}），转瞬移兜底", flush=True)

    # 2) 走路不可用/未启动/走完仍超距 → 随机环带落点瞬移兜底（不重叠BOSS）
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
            _gw_teleport(gateway, tx, ty, map_name=cur_map)
        except Exception as e:
            logger.warning(f"瞬移失败: {e}")
            continue
        time.sleep(0.5)  # jump 落地快（提速轮：1.0→0.5）
        rg = _role_grid(gateway)
        if rg is None or _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE + 1:
            return "teleported"
    return "far"


def _dialog_is_too_far(gateway: str) -> bool:
    """当前对话栏是否为超距确认框（['是的我要去','我还要逛逛'] 或含"太远"）。"""
    try:
        texts = " ".join(o["text"] + o["label"] for o in get_dialog_options(gateway))
        return any(m in texts for m in _FAR_DIALOG_MARKERS)
    except Exception:
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
    """对单个 BOSS 实体 —— 原地 CALL + 边走边CALL（2026-08-28 用户四定案）。

    流程（全程无"到达后傻等固定延迟"）：
      1) 原地立即 CALL 一次（怪在面前/近距离 → 直接命中开打，最快路径）；
      2) 超距/未中 → 走路贴近：点击地图目标坐标后 **立即关大图**，马上开 CALL，
         每 WALK_CALL_INTERVAL(0.5s) CALL 一次，超时上限=距离/预计走路速度+余量，
         走完仍未中 → 落点补一次 CALL 兜底；接近即可命中，无需精确站上坐标；
      3) 走路不可用/未启动/走完仍超距 → 瞬移环带拉近（approach 内部）→ 落地补 CALL。
    CALL 成功立即进战斗，整个移动链（走路→瞬移）都在 _approach_boss 内一次完成。
    """
    moves = 0

    def _call_once() -> str:
        """单次完整 CALL 尝试。返回 "battle"/"gone"/"far"/"fail"。"""
        # 上次 CALL 可能已触发战斗但窗口没探到（tp.战斗中 有延迟），先查战斗态
        if _in_battle(gateway):
            return "battle"
        ok, msg = call_npc_event_start(gateway, boss.get("id"), boss.get("bsid"))
        if not ok:
            if "消失" in msg or "NOTFOUND" in msg:
                return "gone"
            return "far"  # 对象级失败（NOFN 等）：大概率距离远，边走边CALL会自然重试
        _wait_dialog_ready(gateway)
        bok, bmsg = call_dialog_battle(gateway, battle_keywords)
        if bok:
            # pcall ok ≠ 进战斗：必须等 tp.战斗中 变 true 才算真触发
            # （2026-08-27 实测：远处 pcall 全部 ok=true 但战斗没发生 → 假击杀 14 连；
            #   2026-08-28 实测：窗口 2.0s 偏短（tp.战斗中 有延迟）→ 恢复 3.0s）
            if _wait_battle_start(gateway, timeout=3.0):
                return "battle"
            close_dialog(gateway)
            if verbose:
                print(f"  [CALL] 选项已点但 3s 内未进战斗（{bmsg}），下一节拍继续 CALL",
                      flush=True)
            return "far"
        far = _dialog_is_too_far(gateway)
        close_dialog(gateway)
        if verbose and far:
            print("  [CALL] 超距确认框（边走边CALL中，靠近后自动命中）", flush=True)
        return "far" if far else "fail"

    # 1) 原地立即 CALL（怪就在面前 → 直接命中，不移动）
    r = _call_once()
    if r == "battle":
        ended = _wait_battle_end(gateway, timeout=battle_timeout)
        close_dialog(gateway)
        return {"ok": True, "battle_ended": ended, "msg": "call_ok",
                "attempts": 1, "approached": False}
    if r == "gone":
        return {"ok": False, "reason": "gone", "msg": "目标已消失"}
    if verbose:
        print("  [CALL] 原地未命中 → 转走路贴近 + 边走边CALL", flush=True)

    # 2) 走路贴近 + 边走边CALL（点图即关图开CALL；内置走完补 CALL 兜底）
    mode = _approach_boss(gateway, cur_map, boss["gx"], boss["gy"],
                          walk_background, verbose, call_fn=_call_once)
    moves += 1
    if mode == "walked_call_ok":
        ended = _wait_battle_end(gateway, timeout=battle_timeout)
        close_dialog(gateway)
        return {"ok": True, "battle_ended": ended, "msg": "walk_call_ok",
                "attempts": 2, "approached": True}
    if mode == "gone":
        return {"ok": False, "reason": "gone", "msg": "目标已消失（走近途中）"}
    if mode == "far":
        return {"ok": False, "reason": "unreachable", "msg": "走近失败仍超距"}

    # 3) 到位/瞬移落地后仍未中 → 最后补一次 CALL 兜底
    r = _call_once()
    if r == "battle":
        ended = _wait_battle_end(gateway, timeout=battle_timeout)
        close_dialog(gateway)
        return {"ok": True, "battle_ended": ended, "msg": "final_call_ok",
                "attempts": 3, "approached": moves > 0}
    if r == "gone":
        return {"ok": False, "reason": "gone", "msg": "目标已消失"}
    return {"ok": False, "reason": "no_battle_option",
            "msg": "原地CALL+边走边CALL+落地补CALL后仍未命中（可能已被他人锁定）"}


def _pick_random_map(cur_map: Optional[str], monitored_maps: List[str],
                     recent: tuple = ()) -> str:
    """从监控地图里挑一张（排除当前图 + 近期去过的图）。

    2026-08-28 用户定案：实扫权威——瞬移到图后 Lua 扫白名单怪，没有就换图。
    配套改进：换图时优先排除 recent（最近去过的图，函数内 deque 维护），
    避免在刚清过的图之间来回打转；排除后为空才放宽。
    """
    pool = [m for m in monitored_maps if m != cur_map and m not in recent]
    if not pool:
        pool = [m for m in monitored_maps if m != cur_map] or list(monitored_maps)
    return random.choice(pool)


def _ensure_walker_bound(gateway: str, verbose: bool = True) -> Optional[int]:
    """farming 启动前自动绑定 window_manager（2026-08-27 23:39 新增）。

    绑不上 → 走路全部失败 → 每只 BOSS 退化成瞬移环带（违反防举报原则）。
    来源优先级：网关 /api/status 的 result.pid（与 Lua 通道同进程，最权威）
    → settings.json 的 window.pid 兜底。
    :return: 绑定的 pid；None = 绑定失败（调用方自行决定是否继续）。
    """
    pid = None
    try:
        with _urlopen(_Request(gateway.rstrip("/") + "/api/status"), timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        pid = ((data.get("result") or {}).get("pid")) or data.get("pid")
    except Exception:
        pass
    if not pid:
        try:
            cfg_path = os.path.join(_PROJECT_ROOT, "config", "settings.json")
            with open(cfg_path, encoding="utf-8") as f:
                pid = (json.load(f).get("window") or {}).get("pid")
        except Exception:
            pass
    if pid:
        try:
            from core.window_manager import window_manager
            window_manager.bind(pid=int(pid))
            if verbose:
                print(f"[bind] window_manager 已绑定 pid={pid}（走路通道可用）", flush=True)
            return int(pid)
        except Exception as e:
            if verbose:
                print(f"[bind] 绑定 pid={pid} 失败: {e}", flush=True)
    if verbose:
        print("[bind] 未能绑定 PID，走路将退化为瞬移兜底（违反防举报原则，请检查网关）",
              flush=True)
    return None


def WORLD_BOSS_captcha_gate(gateway: str = None, verbose: bool = True) -> dict:
    """防挂机验证码门：GUI 任务链首事件。

    有弹窗 → V7 直解自动点掉；无弹窗 → 直接放行。
    :param verbose: 是否打印细节。
    :return: {"ok": True, "captcha_resolved": bool}
    """
    gateway = gateway or DEFAULT_GATEWAY
    resolved = _captcha_solve(gateway, verbose=verbose)
    return {"ok": True, "captcha_resolved": bool(resolved)}


def WORLD_BOSS_auto_farm(
    monitored_maps: List[str] = None,
    target_bosses: List[str] = None,
    spawn_patterns: List[str] = None,
    battle_keywords: List[str] = None,
    home_coord: Tuple[int, int] = (240, 101),
    max_runtime: int = 1800,
    chat_poll_interval: float = 1.5,
    boss_scan_interval: float = 1.0,
    clear_timeout: float = 10.0,
    battle_timeout: float = 180.0,
    walk_background: bool = True,
    verbose: bool = True,
    gateway: str = DEFAULT_GATEWAY,
) -> dict:
    """世界BOSS自动监控 farming 主入口。

    优先级（2026-08-28 五定案）：
      0) 三界财神爷抢占：公告出现（未进战斗/刚离战）→ 立即瞬移财神爷图，
         期间绝不 CALL 其他怪；财神爷没了/被锁定 → 回落普通模式；
      1) 聊天公告（入口信号） > 到图 Lua 实扫白名单怪（权威）；
      2) 普通模式按 BOSS_PRIORITY 排序：稀有(1) > 头领/统领(2) >
         妖魔鬼怪/妖魔/鬼怪(3)垫底；同优先级距离近先打。
         妖族杂鱼公告不触发跨图（LOW_PRIORITY_BOSSES 过滤），
         只在场景轮换时顺手清——其他 BOSS 打完才轮到它们；
         未登记实体（优先级 None）=非目标，不排序不攻击（六定案）；
      3) 换图优先排除近期去过的 3 张图，避免在清过的图之间打转。
    """
    monitored_maps = monitored_maps or list(DEFAULT_MONITORED_MAPS)
    target_bosses = target_bosses or list(DEFAULT_TARGET_BOSSES)
    spawn_patterns = spawn_patterns or list(DEFAULT_SPAWN_PATTERNS)
    battle_keywords = battle_keywords or list(DEFAULT_BATTLE_KEYWORDS)
    # 2026-08-28 B8 修复：监控表去重——同图双名（如 建邺城/宝象国 同为 1501）
    # 只保留首个，否则轮换会在两名之间空转切图（_map_same 归一后再判重）。
    _deduped: List[str] = []
    for _m in monitored_maps:
        if not any(_map_same(_m, _k) for _k in _deduped):
            _deduped.append(_m)
    monitored_maps = _deduped

    # 0) 启动自绑：走路通道必须先于任何 BOSS 交互就绪
    _ensure_walker_bound(gateway, verbose)

    t0 = time.time()
    cur_map = None           # 当前正在 farming 的地图
    no_boss_since = None     # 最近一次在 cur_map 扫到 BOSS 的时刻
    farmed_total = 0
    excluded = set()         # 函数级黑名单：确认无战斗选项/已消失的实体跨轮排除
                             # （2026-08-27 23:39 修复：原来每轮重置导致对 10 只
                             #   赐福星官无限走近+CALL 空转刷瞬移）
    last_cache_clear = time.time()   # 聊天/网络缓存 10 分钟一清（用户定案）
    last_ann_text = None    # 已执行过的公告原文（过期公告拉扯修复 2026-08-28）
    ann_cleared = False     # 该公告对应的图是否已被判清图
    unreachable = {}        # 跨图失败的图 -> 冷却截止时间戳（2026-08-28）
    recent_maps = _deque(maxlen=3)  # 近期去过的图（换图避让，2026-08-28 实扫定案配套）
    # 2026-08-28 三界财神爷抢占模式状态
    caishen_pinned = None       # {"map","text"}：抢占激活中（期间只打财神爷）
    caishen_seen_texts = set()  # 已消费的财神爷公告原文（防同一条反复抢占）
    caishen_scan_miss = 0       # 财神爷图连续无实体复扫计数
    print("=== WORLD_BOSS_auto_farm 开始 ===", flush=True)
    print(f"  监控地图={monitored_maps}", flush=True)
    print(f"  目标BOSS={target_bosses[:10]}{'...' if len(target_bosses)>10 else ''}", flush=True)

    stopped = False
    while time.time() - t0 < max_runtime:
        # -1) GUI 停止按钮：任何时刻置位都立即退出（可随时停止要求）
        if _gui_stop_requested():
            stopped = True
            break

        # 0) 验证码避让：弹窗时先 V7 直解（Lua 读答案+按钮坐标自动点掉），解不掉才暂停等待
        if not _captcha_solve(gateway, verbose):
            if verbose:
                print(f"[{int(time.time()-t0)}s] 验证码窗口弹出且未解除，暂停等待...", flush=True)
            if not _sleep_stoppable(5):
                stopped = True
                break
            continue

        # 0.4) 战斗态守门 + 财神爷在场直接领取（2026-08-28 用户四定案，最高优先）：
        #      三界财神爷已出现在当前场景（就在面前）→ 最优先动作是直接 CALL 领取，
        #      绝不跨图、绝不先去"查看公告"/响应其他公告——"查看"只是信息动作，
        #      永远低于"目标在场直接领取"。
        # 2026-08-28 A3 修复：战斗超时退出后角色可能仍在战斗中，主循环此前无守门，
        # 会在战斗态跨图/瞬移（瞬移包被服务器丢弃还浪费轮次）。战斗中等待自然结束。
        # 2026-08-28 B5 修复：每轮只做一次全量场景扫描，0.4 与 step2 共享结果
        # （旧逻辑 0.4 扫一次 + step2 再扫一次，双倍 Lua dump 开销）。
        in_battle = _in_battle(gateway)
        scanned = None  # 本轮场景扫描结果（0.4/step2 共享；跨图后置 None 强制重扫）
        if in_battle:
            if verbose:
                print(f"[{int(time.time()-t0)}s] 战斗中（超时未决/战斗收尾），原地等待...", flush=True)
            if not _sleep_stoppable(2.0):
                stopped = True
                break
            continue
        scanned = scan_scene_bosses(gateway, target_bosses)
        cs_here = [x for x in scanned
                   if x["name"] == CAISHEN_BOSS and _boss_key(x) not in excluded]
        if cs_here:
            b = cs_here[0]
            if verbose:
                print(f"[{int(time.time()-t0)}s] ⚡ 财神爷就在面前（{cur_map or '?'} "
                      f"{b['gx']},{b['gy']}）→ 直接领取，不切图", flush=True)
            kw = _boss_battle_keywords(b["name"], list(battle_keywords))
            real_map = _cur_map_name(gateway) or cur_map or ""
            res = _farm_one_boss(gateway, b, kw, battle_timeout,
                                 walk_background, verbose, real_map)
            if res.get("ok") and res.get("battle_ended"):
                farmed_total += 1
                print(f"  ✓ 击杀 三界财神爷（累计 {farmed_total}）", flush=True)
            else:
                reason = res.get("reason") or "failed"
                print(f"  ✗ 三界财神爷 跳过: {reason} {res.get('msg')}", flush=True)
                excluded.add(_boss_key(b))
            continue

        # 0.5) 三界财神爷抢占模式（2026-08-28 用户定案：最最最优先）。
        #      未进战斗时财神爷公告出现 → 立即瞬移财神爷图，期间绝不 CALL 其他怪；
        #      财神爷没了/被人锁定 → 解除抢占回落普通模式（该图其他怪照常打）。
        #      2026-08-28 四定案：公告随时查看；财神爷图没财神 → 本图 CALL 其他
        #      BOSS，没有其他再换图（复扫上限已收紧为 2×0.5s）。
        # 0.5 抢占检查复用 0.4 的 in_battle（战斗中已在上面 continue，此处必为 False）
        if caishen_pinned is None and not in_battle:
            cs_ann = find_latest_spawn(gateway, [CAISHEN_BOSS],
                                       monitored_maps, spawn_patterns)
            if cs_ann and cs_ann.get("text") not in caishen_seen_texts:
                caishen_seen_texts.add(cs_ann.get("text"))
                caishen_pinned = {"map": cs_ann["map"], "text": cs_ann.get("text")}
                caishen_scan_miss = 0
                if verbose:
                    print(f"[{int(time.time()-t0)}s] ⚡ 财神爷公告抢占 → {cs_ann['map']}",
                          flush=True)
        if caishen_pinned:
            cs_map = caishen_pinned["map"]
            if cs_map in unreachable and time.time() < unreachable[cs_map]:
                if verbose:
                    print(f"  ⚡ 财神爷图 {cs_map} 跨图冷却中 → 判放弃，回落普通模式", flush=True)
                caishen_pinned = None
                continue
            # 跨图（jump 链，0.3s 级）；失败入冷却并放弃抢占
            if not _ensure_on_map(gateway, cs_map, None, None):
                unreachable[cs_map] = time.time() + 600
                if verbose:
                    print(f"  ⚡ 跨图到财神爷图 {cs_map} 失败 → 放弃抢占", flush=True)
                caishen_pinned = None
                continue
            cur_map = cs_map
            cs_list = scan_scene_bosses(gateway, [CAISHEN_BOSS])
            if cs_list:
                caishen_scan_miss = 0
                b = cs_list[0]
                kw = _boss_battle_keywords(b["name"], list(battle_keywords))
                res = _farm_one_boss(gateway, b, kw, battle_timeout,
                                     walk_background, verbose, cur_map)
                if res.get("ok") and res.get("battle_ended"):
                    farmed_total += 1
                    print(f"  ✓ 击杀 三界财神爷 @ {cur_map}（累计 {farmed_total}）", flush=True)
                else:
                    # gone = 没了；no_battle_option = 被人锁定/占领 → 都解除抢占
                    print(f"  ✗ 三界财神爷 跳过: {res.get('reason')} {res.get('msg')}", flush=True)
                caishen_pinned = None  # 打完/没打成 → 回落普通模式
            else:
                # 公告先到怪未刷 / 已被击杀消失：复扫几轮再判，绝不顺手打其他怪
                caishen_scan_miss += 1
                if caishen_scan_miss >= CAISHEN_SCAN_MISS_LIMIT:
                    if verbose:
                        print(f"  ⚡ 财神爷图 {caishen_scan_miss} 扫无财神实体 → "
                              f"本图 CALL 其他 BOSS，没有再换图（回落普通模式）", flush=True)
                    caishen_pinned = None
                else:
                    if not _sleep_stoppable(CAISHEN_SCAN_MISS_GAP):
                        stopped = True
                        break
            continue  # 抢占期间不走普通公告/换图逻辑

        # 1) 聊天公告 → 目标地图
        # 2026-08-28 修复"过期公告拉扯"：recv 缓存里的老公告没有时间戳，
        # find_latest_spawn 永远返回它 → 跨图去打→12s 清图→又被拉回，无限打转。
        # 记忆机制：同一条公告对应的图已被判清图（ann_cleared=True）后，
        # 这条公告作废，直到缓存里出现新文本才重新生效。
        spawn = find_latest_spawn(gateway, target_bosses, monitored_maps, spawn_patterns)
        if spawn and spawn.get("text") == last_ann_text and ann_cleared:
            spawn = None  # 过期公告：对应图已清过，不再拉回
        elif spawn:
            if spawn.get("text") != last_ann_text:
                last_ann_text = spawn.get("text")
                ann_cleared = False
        # 2026-08-28 五定案：妖魔鬼怪/妖魔/鬼怪=最低优先级——公告不再为它们跨图。
        # 其他 BOSS 的公告照常响应；杂鱼只在场景轮换时顺手清（全场只剩杂鱼照打）。
        if spawn and spawn.get("boss") in LOW_PRIORITY_BOSSES:
            spawn = None
        if spawn:
            if cur_map != spawn["map"]:
                if verbose:
                    extra = f"（公告图: {'、'.join(spawn.get('maps', []))}）" if len(spawn.get("maps", [])) > 1 else ""
                    print(f"[{int(time.time()-t0)}s] 公告: {spawn['boss']} @ {spawn['map']}{extra}", flush=True)
            # 2026-08-28 修复：跨图失败（无 hop 链/传送失败）时不能装作已到位，
            # 否则 cur_map 标签说谎、场景还是旧图、清图判定全乱。
            # 失败的图记入 unreachable（10 分钟冷却），本轮当无公告处理。
            if spawn["map"] in unreachable and time.time() < unreachable[spawn["map"]]:
                if verbose:
                    print(f"[{int(time.time()-t0)}s] 公告图 {spawn['map']} 跨图失败冷却中，跳过",
                          flush=True)
                spawn = None
            else:
                if not _ensure_on_map(gateway, spawn["map"], None, None):
                    unreachable[spawn["map"]] = time.time() + 600
                    if verbose:
                        print(f"[{int(time.time()-t0)}s] 跨图到 {spawn['map']} 失败，"
                              f"10分钟内不再尝试该图", flush=True)
                    spawn = None
                else:
                    cur_map = spawn["map"]
                    recent_maps.append(cur_map)
                    no_boss_since = None
                    scanned = None  # 跨图后 0.4 的扫描属旧图，作废（B5 共享扫描配套）
        elif cur_map is None:
            # 暂无公告：随机切一张监控地图扫描（保持在线待命）
            cur_map = _pick_random_map(None, monitored_maps, tuple(recent_maps))
            no_boss_since = None
            # 2026-08-28：初始切图也要核实——失败则以真实地图名为准（防标签说谎）
            if not _ensure_on_map(gateway, cur_map, None, None):
                unreachable[cur_map] = time.time() + 600
                cur_map = _cur_map_name(gateway) or cur_map
            recent_maps.append(cur_map)
            scanned = None  # 同上：跨图后旧扫描作废

        # 1.5) 每 10 分钟清理一次网关 recv 缓存（防膨胀拖慢 dumpRecvAll，
        #      用户 2026-08-27 定案）；失败静默跳过，不影响主流程。
        #      （2026-08-27 修复：原"暂无公告，随机扫描"日志错放在此分支，
        #        有公告时也会打印误导排查，已删除）
        if time.time() - last_cache_clear >= WORLD_BOSS_CACHE_CLEAR_INTERVAL:
            last_cache_clear = time.time()
            WORLD_BOSS_chat_maintenance(gateway, verbose=verbose)

        # 2) 扫描当前地图 BOSS
        # 2026-08-28 修复：外层判定必须剔除 excluded（尸体/被锁实体），
        # 否则"34个BOSS全是尸体"的图永远不清图、不轮换，干转死循环。
        # 2026-08-28 B5：复用 0.4 的本轮扫描（未跨图时），不再重复全量 dump。
        if scanned is None:
            scanned = scan_scene_bosses(gateway, target_bosses)
        # 2026-08-28 六定案：未登记实体（_boss_priority=None）=非目标，
        # 直接剔除——不排序/不攻击，也不再阻塞清图判定/轮换。
        bosses = [x for x in scanned
                  if _boss_key(x) not in excluded
                  and _boss_priority(x["name"]) is not None]
        if bosses:
            no_boss_since = None
            if verbose:
                print(f"[{int(time.time()-t0)}s] {cur_map} 发现 {len(bosses)} 个BOSS: "
                      + ", ".join(f"{b['name']}@{b['gx']},{b['gy']}" for b in bosses), flush=True)
            # 每击杀一只后重扫：战斗后场景人物槽位/实例会重排（SYBUZ2 同款坑），
            # 静态列表的 id/bsid 会错位导致 CALL 错实体（2026-08-27 实测）。
            # excluded 为函数级黑名单，跨轮生效：无战斗选项/已消失的实体不再重试。
            real_map_cache = [None]  # 提速轮：本轮 farm 内地图不变，实读地图名只查一次
            while time.time() - t0 < max_runtime:
                if _gui_stop_requested():
                    stopped = True
                    break
                if not _captcha_solve(gateway, verbose):
                    break
                # 0.5) 财神爷抢占检查（2026-08-28 用户定案）：每打一只前都查，
                #      未进战斗时公告出现 → 立刻放弃本图杂鱼，交外层瞬移去财神爷图
                cs_ann = find_latest_spawn(gateway, [CAISHEN_BOSS],
                                           monitored_maps, spawn_patterns)
                if cs_ann and cs_ann.get("text") not in caishen_seen_texts:
                    caishen_seen_texts.add(cs_ann.get("text"))
                    caishen_pinned = {"map": cs_ann["map"], "text": cs_ann.get("text")}
                    caishen_scan_miss = 0
                    if verbose:
                        print(f"  ⚡ 财神爷公告抢占: {cs_ann['map']} → 放弃当前杂鱼", flush=True)
                    break
                live = [x for x in scan_scene_bosses(gateway, target_bosses)
                        if _boss_key(x) not in excluded
                        and _boss_priority(x["name"]) is not None]
                if not live:
                    break
                try:
                    rg0 = _role_grid(gateway)
                    gx0, gy0 = (rg0[0], rg0[1]) if rg0 else (0.0, 0.0)
                except Exception:
                    gx0, gy0 = 0.0, 0.0
                # 2026-08-28 五定案：普通模式恢复优先级排序——财神爷独立抢占外，
                # BOSS_PRIORITY 小者先打：稀有(1) > 头领/统领/未登记(2) >
                # 妖魔鬼怪/妖魔/鬼怪(3)垫底；同优先级距离近先打。
                # 同坐标白名单怪全类型都可攻击（不限一种）。
                cs_live = [x for x in live if x["name"] == CAISHEN_BOSS]
                if cs_live:
                    b = cs_live[0]
                    if verbose:
                        print("  ⚡ 财神爷在场 → 直接领取（优先于优先级/距离排序）", flush=True)
                else:
                    b = min(live, key=lambda x: (_boss_priority(x["name"]),
                                                 (x["gx"] - gx0) ** 2 + (x["gy"] - gy0) ** 2))
                this_keywords = _boss_battle_keywords(b["name"], list(battle_keywords))
                # 2026-08-28：走路/校准一律用实读地图名——cur_map 标签万一错了
                # （跨图未到达），拿错图的校准数据点屏幕会全错（长寿郊外点花果山像素事故）
                # 2026-08-28 提速轮：内层循环内地图不会变，每只怪读一次 → 进图读一次缓存
                if not real_map_cache[0]:
                    real_map_cache[0] = _cur_map_name(gateway) or cur_map
                real_map = real_map_cache[0]
                res = _farm_one_boss(gateway, b, this_keywords, battle_timeout,
                                     walk_background, verbose, real_map)
                if res.get("ok") and res.get("battle_ended"):
                    farmed_total += 1
                    print(f"  ✓ 击杀 {b['name']} @ {cur_map}（累计 {farmed_total}）", flush=True)
                else:
                    # battle_ended=False = 根本没进战斗（假触发），同样按失败处理
                    reason = res.get("reason") or ("no_battle_start" if res.get("ok") else "failed")
                    print(f"  ✗ {b['name']} 跳过: {reason} {res.get('msg')}", flush=True)
                    excluded.add(_boss_key(b))
                if not _sleep_stoppable(0.3):  # 2026-08-28 提速轮：1.0→0.3，连续击杀不间断
                    stopped = True
                    break
        else:
            # 3) 当前地图无 BOSS —— 2026-08-28 用户定案：**到图实扫白名单怪为准**，
            #    没有 → 立即换下一张图，不再干等满 clear_timeout。
            #    公告只是入口信号；图上有没有怪以 Lua 扫场景人物/临时Npc 为权威。
            if no_boss_since is None:
                no_boss_since = time.time()
                # 场景加载 0.8s 后复扫一次：命中 → 回主循环直接进 farm 分支
                # （2026-08-28 提速轮：1.5→0.8，实扫立判，没怪立刻走）
                if not _sleep_stoppable(0.8):
                    stopped = True
                    break
                re = [x for x in scan_scene_bosses(gateway, target_bosses)
                      if _boss_key(x) not in excluded]
                if re:
                    continue
                # 复扫仍空 → 立即轮换（公告记忆同步作废，防老公告拉回）
                ann_cleared = True
                nxt = _pick_random_map(cur_map, monitored_maps, tuple(recent_maps))
                if verbose:
                    print(f"[{int(time.time()-t0)}s] {cur_map} 实扫无白名单怪，立即换图 → {nxt}",
                          flush=True)
                no_boss_since = None
                if _ensure_on_map(gateway, nxt, None, None):
                    cur_map = nxt
                    recent_maps.append(nxt)
                else:
                    # 2026-08-28：跨图没真到 → 该图冷却，cur_map 落回真实地图名
                    unreachable[nxt] = time.time() + 600
                    cur_map = _cur_map_name(gateway) or cur_map
                    if verbose:
                        print(f"  ! 跨图到 {nxt} 未到达（实读={cur_map}），10分钟冷却", flush=True)
            elif time.time() - no_boss_since >= clear_timeout:
                # 兜底：复扫曾有怪但全被锁/清掉后持续无 BOSS，走老路径轮换
                ann_cleared = True
                nxt = _pick_random_map(cur_map, monitored_maps, tuple(recent_maps))
                if verbose:
                    print(f"[{int(time.time()-t0)}s] {cur_map} 已清图（{clear_timeout}s无BOSS），"
                          f"轮换 → {nxt}", flush=True)
                no_boss_since = None
                if _ensure_on_map(gateway, nxt, None, None):
                    cur_map = nxt
                    recent_maps.append(nxt)
                else:
                    unreachable[nxt] = time.time() + 600
                    cur_map = _cur_map_name(gateway) or cur_map
                    if verbose:
                        print(f"  ! 跨图到 {nxt} 未到达（实读={cur_map}），10分钟冷却", flush=True)
            if not _sleep_stoppable(boss_scan_interval):
                stopped = True
                break
            continue

        if not _sleep_stoppable(boss_scan_interval):
            stopped = True
            break

    result = {"ok": True, "farmed_total": farmed_total, "elapsed": int(time.time() - t0)}
    if stopped:
        result["stopped"] = True
    print(f"=== WORLD_BOSS_auto_farm 结束：累计击杀 {farmed_total}，耗时 {int(time.time()-t0)}s"
          f"{'（GUI 停止）' if stopped else ''} ===", flush=True)
    return result


def _next_schedule_time(minutes_list: List[int], pre_minutes: int = 0) -> Optional[_datetime]:
    """返回下一个符合分钟列表的时间点（可提前 pre_minutes）。

    2026-08-28 A1 修复：
      - 旧实现 now.replace(hour=(now.hour+1)%24) 不带日期进位，23 点后算出的
        "明天 00:xx" 实际落在今天 00:xx（已过去）→ 全部候选被过滤 → 返回 None。
      - 旧实现 max(0, m-pre_minutes) 把提前量钳死在本小时内，整点刷新
        （m=0, pre=2）的提前启动时刻应为昨天 23:58，被钳成 00:00 失效。
    新实现：minutes 是"每小时内的分钟"表（如 [0,10] = 每小时的 :00 和 :10），
    以小时为步长平铺未来 3 天共 72 个整点候选，提前量用减法（自动跨午夜借位）。"""
    if not minutes_list:
        return None
    now = _datetime.now()
    base = now.replace(second=0, microsecond=0)
    candidates = []
    for h in range(0, 3 * 24):   # 未来 3 天 × 每小时
        hb = (base + _timedelta(hours=h)).replace(minute=0)
        for m in minutes_list:
            dt = hb.replace(minute=m)                     # 真实刷新时刻
            candidates.append(dt - _timedelta(minutes=pre_minutes))  # 启动时刻
    valid = [d for d in candidates if d > now]
    return min(valid) if valid else None


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
    nearest: Optional[_datetime] = None
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

    now = _datetime.now()
    wait_sec = max(0, int((nearest - now).total_seconds()))
    if wait_sec > max_wait_minutes * 60:
        return {"ok": False, "message": f"下一个刷新点 {nearest_boss} @ {nearest} 超过最大等待 {max_wait_minutes} 分钟"}

    if verbose:
        print(f"[WORLD_BOSS] 等待到 {nearest}（{nearest_boss} 刷新前{pre_start_minutes}分钟），还需 {wait_sec}s", flush=True)
    # 2026-08-28 B10 修复：裸 time.sleep(wait_sec) 不可中断，GUI 点停止要干等
    # 到点；改为 0.5s 步进 + 停止检查，随时可取消。
    waited = 0.0
    while waited < wait_sec:
        if _gui_stop_requested() or not _sleep_stoppable(min(0.5, wait_sec - waited)):
            print("[WORLD_BOSS] 等待期间被 GUI 停止，未启动 farming", flush=True)
            return {"ok": False, "stopped": True,
                    "message": f"等待 {nearest_boss} 刷新期间被 GUI 停止"}
        waited += 0.5

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


# 缓存清理周期：10 分钟（用户 2026-08-27 定案，防 recv 缓存膨胀拖慢嗅探）
WORLD_BOSS_CACHE_CLEAR_INTERVAL = 600.0


def WORLD_BOSS_chat_maintenance(gateway: str = DEFAULT_GATEWAY, verbose: bool = True) -> dict:
    """聊天通道例行维护：
      1) 调 gateway /api/net/clear 清空 JS 侧 recvAll/sendAll/hexAll 大缓存
         （keyPackets/关键协议保留，验证码溯源不受影响）；
      2) 返回清理结果。需要 net_sniff.js 含 clearCaches 导出——
         网关重启重新注入后才生效；老脚本会返回 ok=False，调用方安全降级。
    """
    try:
        r = _http_json(gateway, "/api/net/clear", None, timeout=15.0)
        if verbose:
            cleared = (r.get("result") or {}).get("cleared")
            print(f"[WORLD_BOSS] 聊天缓存清理: ok={r.get('ok')}"
                  + (f", 共{cleared}条" if cleared is not None else f", {r.get('error','')}"),
                  flush=True)
        return r
    except Exception as e:
        if verbose:
            print(f"[WORLD_BOSS] 聊天缓存清理失败(忽略): {e}", flush=True)
        return {"ok": False, "error": str(e)}


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
         "default": "APPROACH_GRID_DISTANCE=6 格（2026-08-28 C11：4→6，实测 CALL 19.2 格可命中）：≤6 直接 CALL，>6 先走近（走路优先）。",
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


# ---- GUI 函数列表去噪（2026-08-28）----
# typing 泛型仅用于注解（def 时已求值完毕），此处收编为下划线别名，
# 避免它们以“可调用对象”身份混进 GUI 函数下拉框。若在函数体运行期引用
# 这六个名字会 NameError——运行期请使用 _List 等下划线别名。
_List, _Dict, _Optional, _Tuple, _Any, _Callable = List, Dict, Optional, Tuple, Any, Callable
del List, Dict, Optional, Tuple, Any, Callable
