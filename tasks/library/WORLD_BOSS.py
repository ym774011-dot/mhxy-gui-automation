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

# 2026-08-29 分离网关：聊天公告独立网关（WORLD_BOSS_CHAT_GATEWAY）。
# 建议配合主网关 MHXY_GW_MIN=1（纯 Lua 桥）+ 聊天网关 MHXY_GW_CHAT=1（仅嗅探）
# 分进程隔离"网络数据嗅探"与"游戏内部 Lua 桥"，降低注入互为干扰导致崩溃的风险。
# 未设置时公告走与主流程同一个 gateway（旧行为）。
_CHAT_GW = os.environ.get("WORLD_BOSS_CHAT_GATEWAY") or ""

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
    "新型冠状病毒",  # 2026-08-29 用户确认：与"下凡的灵猴"同为 P3 白名单，路过就近顺手打
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
# 注意：本表 = 会出现世界 BOSS 的图；城镇枢纽（长安/长安城）不在此列，
#   它们只作跨图传送中转（见 MAP_ROUTES / _find_exact_hop），永不刷 BOSS。
DEFAULT_MONITORED_MAPS = [
    "东海湾",
    "江南野外",
    "建邺城",
    "长寿村",
    "长寿郊外",  # 妖魔刷新图；校准走路（data/map_calibration/长寿郊外.json）
    "大唐国境",  # 妖魔刷新图；校准走路（2026-08-27 用户校准）
    "花果山",   # 知了王/妖魔刷此图；校准走路（2026-08-27 用户校准）
    "北俱芦洲", # 2026-08-27 链路实测：'花果山传送北俱芦洲' 全局直达；校准走路（2026-08-27 用户校准 像素(627,304)@191,63）
    "傲来国",   # ALG 地图包（2026-08-27 注册）
    "宝象国",   # BXG 地图包（2026-08-27 注册；星官“赐福”刷新图）
    "大唐境外",  # 校准走路（2026-08-27 用户校准）
]

# 城镇枢纽图：永不刷世界 BOSS（用户 2026-08-29 定案：长安城不出怪物 BOSS）。
# 这些图仅作为跨图传送中转（MAP_ROUTES / _find_exact_hop 仍保留其路线），
# 不参与 farming 轮换、也不作为公告跨图目标——否则脚本会跑到城里空转找怪。
# 用 _map_same 归一，避免“长安 / 长安城”双名漏判。
NO_BOSS_CITY_MAPS = ("长安", "长安城")

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
    "1226": "宝象国",   # 2026-08-30 实测：宝象国真实地图 ID=1226（"碗子山传送宝象国"落点）
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
# ★ 2026-08-30 宝象国链路打通（用户指路 + 实图 dump 验证）：宝象国不能从大唐境外
#   直接传送，需经「大唐境外→(驿站对话)→碗子山(1228)→宝象国(1226)」：
#   - 大唐境外→碗子山无 desc，靠点驿站老板"送我过去"（_STATION_DLG_ 占位，实现在
#     _station_dialog_cross，实测成功）；碗子山传送表实测含「碗子山传送宝象国@60,3664」。
#   - 朱紫国从大唐境外直达「大唐境外传送朱紫国@120,1080」。
#   （旧链路「长安→江南野外→建邺城」部分时刻失败，现统一走西域链路更稳。）
_HOP_CHAINS: Dict[str, List[str]] = {
    "长安":     ["江南野外传送长安"],
    "江南野外": ["长安传送江南野外"],
    "建邺城":   ["长安传送大唐国境", "大唐国境传送大唐境外",
                 "_STATION_DLG_", "碗子山传送宝象国"],
    "宝象国":   ["长安传送大唐国境", "大唐国境传送大唐境外",
                 "_STATION_DLG_", "碗子山传送宝象国"],
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
    "妖魔头领":    ["让我来收拾你", "收拾你",
                     "休得在此放肆", "放肆"],  # 2026-08-27 公告实际用词是"妖魔头领"（非"统领"）
                                                    # 2026-08-29 截图：冥府头领红色选项"休得在此放肆"开战
    "天降灵猴":    ["我来瞧瞧你的啥", "瞧瞧你的啥"],
    "下凡的灵猴":  ["我来瞧瞧你的啥", "瞧瞧你的啥"],
    "新型冠状病毒": ["酒精消毒", "戴上口罩", "消灭它们", "消灭", "消杀", "收拾你"],
    # 2026-08-30 实测实锤：CALL 后对话选项 = 「酒精消毒」「戴上口罩」（链接同文案），
    # 旧词条(消灭/消杀/收拾)与宽松兜底(杀/灭/打/战…)全不匹配 → 无法开战（用户反馈）。
    # 实测量到的选项已放入第一位，另保留旧词条防变体。
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
    "休得在此放肆",  # 2026-08-29 截图：头领类 BOSS（冥府头领）红色开战选项
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
# ★ 2026-08-30 用户定案：这些图禁用走路通道，接近 BOSS 全用瞬移——图太大，
#   跨图走路动辄几十秒纯浪费（大唐境外实测）。命中列表直接跳过 _approach_boss 的
#   走路分支，落到随机环带瞬移兜底（3~8 格随机落点，落地稳定窗已处理）。
_TELEPORT_ONLY_MAPS = ("大唐境外",)
# ★ 2026-08-30 用户定案（速度优先）：目标距离超过此格数 → 直接瞬移环带贴近。
# ★ 2026-09-01 用户再定案（拟人/防瞬移）：**>80 格才瞬移**。8→20→8 的反复
#   源于"走路 TAB 开关大地图卡顿"与"瞬移密度高触发崩溃"两难；本次定案 80：
#   - ≤15 格：原地 CALL（CALL_SKIP_DIST=15，实测 CALL 上限 19.2 格）
#   - 15~80 格：真实走路 + 边走边 CALL（拟人优先，防举报；4 格/s 速度：
#     15 格≈4s、80 格≈20s+余量，边走边CALL 接近目标即命中，不需走满）
#   - >80 格：才瞬移（远距离瞬移价值充分，且大幅降低瞬移触发引擎崩溃概率）
TELEPORT_FAST_DIST = 80.0
# 2026-08-30 用户定案：走路通道"提前 CALL"——走路落点不再直接点怪坐标±2，
# 而是落在怪周边 10±5 格的随机提前就位点；角色进入提前点就边走边 CALL
# （call 有效距离实测 ≥19 格，10 格范围内必然可命中），无需走到怪脸上；
# 提前点 CALL 未中 → 二次精确走到怪坐标旁再 CALL，最后才瞬移兜底。
WALK_APPROACH_LEAD = 10.0          # 提前就位点距离基准（格）
WALK_APPROACH_LEAD_JITTER = 5.0    # 提前就位点随机容错（±5 格）
WALK_APPROACH_LEAD_MIN = WALK_APPROACH_LEAD - WALK_APPROACH_LEAD_JITTER  # 5
WALK_APPROACH_LEAD_MAX = WALK_APPROACH_LEAD + WALK_APPROACH_LEAD_JITTER  # 15
# 2026-08-30 用户定案：平级内由近到远取最近目标（异名交叉攻击已移除，防地图东跑西跑）
# （CROSS_NAME_NEAR_DIST 已随 2026-08-30 平级选择简化删除）
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
WALK_CALL_INTERVAL = 1.5     # 边走边CALL 节拍（秒）（2026-08-29 用户定案：0.5→1.5，降低走路期高频CALL对寻路的干扰/对对话框刷新的冲击）
WALK_SPEED_GRID_SEC = 4.0    # 预计走路速度（格/秒），用于估算走路超时上限
WALK_TIME_MARGIN = 5.0       # 走路时间估算余量（秒），覆盖起步/寻路绕行开销
# 无地图包瞬移兜底落点：BOSS 周边随机环带半径范围（格）。绝不落在 BOSS 坐标上。
# 2026-08-30 用户提速：3-8格→2-4格——落点更贴近 BOSS，落地当场 CALL 即可命中
#（实测 CALL 命中可达 19 格，2~4 格自然命中），不再"落点过远→二次补传"白等。
TELEPORT_OFFSET_RANGE = (2.0, 4.0)
# 第一次落点仍超距时，第二次补传用更近的半径。
TELEPORT_RETRY_RANGE = (1.0, 2.5)
# ★2026-08-30 用户：远距离不原地CALL（避免超距弹窗/幽灵对话空转），
#   先移动（走路/瞬移）到有效距离再 CALL。CALL 可直接命中实测上限 ~19 格，
#   但自动战斗的"超距确认框"在 6 格外就可能弹出。
# ★2026-08-31 00:25 用户再定案：8→15——CALL 实测上限 19.2 格，15 格内直接
#   原地 CALL（留 4 格余量）。即使弹出超距确认框也只是多 1 次 Lua（_dialog_is_too_far
#   识别后自动走近），省下 1 次瞬移（~3s + 引擎装载风险）——减操作密度防崩。
CALL_SKIP_DIST = 15.0
# ★2026-08-30 瞬移连发冷却（用户实锤高危点："走路没到位在目标范围瞬移2次"）：
#   两次瞬移最小间隔，防连发 Lua/同步包冲击。
TELEPORT_GAP = 3.0

# 必须名称完全相等才匹配的 BOSS（避免“妖魔”误中普通 NPC）。
# 注意：扫描时“天降灵猴”的公告名可能对应场景实体“下凡的灵猴”，需同时注册。
# 注意：妖魔统领已从本表移除（2026-08-29）——它与妖魔头领是同一只 BOSS，
# 只是名字后缀不同（头领/统领），改由下方 SUFFIX_MATCH_BOSSES 统一按后缀识别，
# 避免"避世统领"这类前缀变体因为不在精确表里被漏掉。
EXACT_MATCH_BOSSES = ("知了王", "天降灵猴", "下凡的灵猴", "三界财神爷")

# 2026-08-29 新增：后缀匹配表——BOSS 全名前缀不固定、只有后缀固定。
#   妖魔头领 / 妖魔统领 是同一只 BOSS，只是后缀不同；且实测实体名前缀
#   每次刷新都变（避世头领、净神头领、XX 统领…），只有后缀恒定。
#   若按完整名进白名单，不同前缀的实体会被整体漏掉。
#   匹配方式统一为 name.endswith(后缀)，同时作用于场景扫描 / 公告文本 / 优先级。
SUFFIX_MATCH_BOSSES: Tuple[str, ...] = ("头领", "统领")
# 后缀 → 代表类别（用于取战斗关键词与优先级档位）。
#   两个后缀指向同一只 BOSS，统一归类到"妖魔头领"：
#   "避世头领""净神统领"都能拿到"让我来收拾你"，且同处 PRI_TOULING 档。
BOSS_SUFFIX_CATEGORY: Dict[str, str] = {
    "头领": "妖魔头领",
    "统领": "妖魔头领",
}

# 2026-08-29 新增：二十八星君 / 二十八星宿 公告专用锚点。
#   句式："玉皇大帝特派二十八星君之一的娄金狗到东海湾附近……"
#   兼容"二十八星宿"写法，以及"下凡至 / 降临 / 出现 / 到"等多种动词。
#   星君名用惰性匹配（靠动词分词），地点段放宽到 20 字后在 Python 侧
#   按已知地图名取最长命中（再长的修饰语如"附近一带"都会被自然剔除）。
_STAR_LORD_SPAWN_RE = re.compile(
    r"二十八星(?:君|宿)\s*(?:之)?\s*(?:一)?\s*(?:的)?\s*"
    r"([^\s，,。、]{2,10}?)"
    r"\s*(?:下凡至|下凡到|降临至|降临于|降临|出现在了|出现在|出现于|出现|到达|到|至|去往|前往|赶往)"
    r"\s*([^\s，,。、]{2,20})"
)
# 公告文本里按后缀切 token：取后缀前 1~2 字作前缀（头领 / 统领 各生成一条）。
#   限制 2 字的原因：放宽到 3+ 字会把"听说避世头领"的"听说"一起吞进来。
_SUFFIX_TOKEN_RES = {
    suf: re.compile(r"([^\s，,。、]{1,2}" + re.escape(suf) + r")")
    for suf in SUFFIX_MATCH_BOSSES
}

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
# 2026-08-30 用户新定案（速度/交叉战斗优化）：平级内交叉战斗，同档按距离由近到远
PRI_CAISHEN = 0      # 三界财神爷：最高，唯一触发抢占模式
PRI_TOULING = 1      # 妖魔头领（前缀不定，后缀匹配）= 妖魔统领 = 知了王 —— 用户新定 P1
PRI_ZHILIAO = 1      # 知了王 —— 与 *头领 / *统领 并列 P1
PRI_STARLORD = 2     # 二十八星宿：**不看公告**，地图识别到就打，与众怪平级 P2
PRI_WHITELIST = 2    # 其余白名单：灵猴 / 十二生肖 / 天罡星 / 地煞星 → 平级 P2
PRI_TRASH = 2        # 妖族杂鱼：妖魔鬼怪 / 妖魔 / 鬼怪 → 平级 P2（同层统一按距离取最近）

BOSS_PRIORITY = {
    "三界财神爷": PRI_CAISHEN,
    "知了王": PRI_ZHILIAO,
    "妖魔头领": PRI_TOULING,
    "妖魔统领": PRI_TOULING,
}
# 二十八星君 / 二十八星宿 28 个具体名（娄金狗等）：财神爷之后、头领/知了王之前
for _n in _28_STAR_BOSSES:
    BOSS_PRIORITY[_n] = PRI_STARLORD
# 其余白名单：灵猴 / 新型冠状病毒 / 十二生肖 / 天罡地煞
for _n in ("天降灵猴", "下凡的灵猴", "新型冠状病毒", "天罡星", "地煞星"):
    BOSS_PRIORITY[_n] = PRI_WHITELIST
for _n in _12_ZODIAC_BOSSES:
    BOSS_PRIORITY[_n] = PRI_WHITELIST
# 妖族杂鱼：每小时 :10 常刷、数量多，垫底——打不完不用抢
for _n in ("妖魔鬼怪", "妖魔", "鬼怪"):
    BOSS_PRIORITY[_n] = PRI_TRASH

# 顶级目标阈值：优先级 <= 此值属"顶级目标"——三界财神爷出现即进入抢占模式，
# 期间只打顶级目标。2026-08-30 用户新定案：顶级 = 财神爷(P0) + 头领/统领/知了王(P1)；
# 二十八星宿**不再是顶级**（不看公告、不触发抢占/跨图，地图扫到按普通 P2 打）。
TOP_TIER_PRIORITY = PRI_TOULING
TOP_TIER_BOSS_NAMES = tuple(sorted(n for n, p in BOSS_PRIORITY.items()
                                   if p <= TOP_TIER_PRIORITY))

# 2026-08-28 五定案：这批公告词/实体名视为"杂鱼"——公告不触发跨图，
# 场景内排序永远垫底（其他 BOSS 打完才轮到它们）。
LOW_PRIORITY_BOSSES = {"妖魔鬼怪", "妖魔", "鬼怪"}
# ★ 2026-08-30 用户定案：二十八星宿"不看公告"——星宿公告不触发跨图，
#   地图场景识别到就按普通 P2 打（开着公告跨图会在各星宿公告图之间被拉扯）。
NO_CROSS_BOSSES = frozenset(LOW_PRIORITY_BOSSES) | frozenset(_28_STAR_BOSSES)

# 2026-08-30 用户新定案重写：顶级目标抢占模式。
#   优先级链：三界财神爷(P0) ＞ 头领 = 统领 = 知了王(P1) ＞ 其余全部（含星宿）P2。
#   触发：本图实扫到财神爷，或聊天公告出现财神爷 → 抢占并（必要时）瞬移到该图；
#   抢占期间只打顶级目标（P0~P1）；全无 → 解除抢占，回落普通模式。
#   二十八星宿不参与抢占、不看公告，场景扫到按 P2 打。
CAISHEN_BOSS = "三界财神爷"
# 解除抢占的宽容度：顶级目标连扫这么多次仍为空才回落（2 次×0.5s 只容忍场景加载瞬间），
# 绝不多轮干等——旧版"财神爷一没就立刻回落"会漏掉同图的知了王/妖魔头领。
CAISHEN_SCAN_MISS_LIMIT = 2
CAISHEN_SCAN_MISS_GAP = 0.5


# 2026-08-29 目标名单运行期登记：供 _boss_priority 对"名单内但未映射档位"的名字兜底为白名单档
_RUN_TARGET_BOSSES = frozenset()
# ★ 2026-08-30 顶级公告优先跨图：主循环设置"顶部目标（财神/星宿/头领）公告指向他图"
#   → 本图杂鱼的第一个 CALL 立即中止、先跨图（_farm_one_boss 启动时检查）。
_TOP_PIN_MAP: Optional[str] = None
# ★ 2026-08-30 流畅度指标：上一场战斗结束时间戳（验证"战斗结束→下次开战"间隔，
#   目标在附近时应 ~1s；若明显偏大说明流程里有等待点需要排查）。
_PREV_BATTLE_END: Optional[float] = None
_BATTLE_START_TS: float = 0.0
_BATTLE_END_TS: float = 0.0
# 2026-08-30 分子级诊断：farm_one_boss 入口 / 开战瞬间打点
_FARM_START_TS: float = 0.0
# ★2026-08-30 提速：战斗结束结算动画窗口内，立刻发起的攻击会被引擎打回（nodlg/
#   反复重试白耗 ~8s）。统一在每场战斗结束后固定等 _POST_BATTLE_SETTLE 秒（动画
#   收尾），让下一次攻击第一发即命中——把"8s 失败重试"换成"1.6s 一次等齐"。
_POST_BATTLE_SETTLE = 1.6
_POST_BATTLE_TS: float = 0.0


def _battle_gap_metric(ended: bool) -> Optional[float]:
    """战斗结束 → 计算"上次战斗结束→本场开战"间隔（秒）流畅度指标，并滚动状态。

    :param ended: 本场战斗是否正常结束（_wait_battle_end）
    :return: 间隔秒；首场或未正常结束返回 None
    """
    global _PREV_BATTLE_END, _BATTLE_START_TS, _BATTLE_END_TS, _POST_BATTLE_TS
    if not ended:
        return None
    _BATTLE_END_TS = __tm.time()
    _POST_BATTLE_TS = _BATTLE_END_TS   # 2026-08-30 结算动画窗口锚点
    gap = (_BATTLE_START_TS - _PREV_BATTLE_END) if _PREV_BATTLE_END else None
    if gap is not None and gap < 0:
        gap = None
    _PREV_BATTLE_END = _BATTLE_END_TS
    return gap


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
    # 后缀匹配（2026-08-29）："避世头领""净神头领"… 前缀每次刷新都变，
    # 只有后缀恒定 → 归到该后缀代表类别的优先级（*_头领 = 妖魔头领档）。
    for suf in SUFFIX_MATCH_BOSSES:
        if n.endswith(suf):
            return BOSS_PRIORITY[BOSS_SUFFIX_CATEGORY.get(suf, suf)]
    # 2026-08-29 追加：本次运行目标名单内的未登记名 → 默认白名单档，避免被 _live_bosses 剔除非目标漏打
    if n in _RUN_TARGET_BOSSES:
        return PRI_WHITELIST
    return None


def _is_top_tier(name: str) -> bool:
    """是否"顶级目标"：P0 三界财神爷 / P1 头领 = 统领 = 知了王（2026-08-30 用户新定）。

    顶级目标触发抢占模式——只要任一在场（或财神爷公告出现），就只打这一类；
    二十八星宿不属于顶级：不看公告、不触发抢占，场景识别到按普通 P2 打。
    """
    p = _boss_priority(name)
    return p is not None and p <= TOP_TIER_PRIORITY


def _dist2(x: Dict[str, Any], gx0: float, gy0: float) -> float:
    """目标到角色 (gx0, gy0) 的距离平方。"""
    return (x["gx"] - gx0) ** 2 + (x["gy"] - gy0) ** 2


def _pick_target(live: List[Dict[str, Any]], gx0: float = 0.0, gy0: float = 0.0,
                 only_top: bool = False, last_name: str = None):
    """从候选里按 (优先级, 距离平方) 选目标。

    :param only_top: True = 只在顶级目标(P0~P2)中选；顶级目标全无返回 None，
        调用方据此判断"该解除抢占回落普通模式了"。
    :param last_name: 兼容保留（2026-08-30 起不再用于"异名跳远"：
        用户定案"优先级不动，平级内由近到远取最近目标"，避免地图东跑西跑）。
    """
    pool = [x for x in live if _is_top_tier(x["name"])] if only_top else list(live)
    if not pool:
        return None
    # 求本池最低优先级档（最优先的档）
    minp = min(_boss_priority(x["name"]) for x in pool)
    tier = [x for x in pool if _boss_priority(x["name"]) == minp]
    if len(tier) <= 1:
        return tier[0] if tier else None
    # 2026-08-30 用户定案：平级内严格按"距角色坐标由近到远"取最近目标——
    # 上一只名字不同（异名交叉攻击）时不再切换到稍远的异名怪，避免地图东跑西跑。
    # 距离即选目标：同档多目标直接取 _dist2（角色坐标 gx0,gy0）最小者。
    return min(tier, key=lambda q: _dist2(q, gx0, gy0))


def _live_bosses(scanned: List[Dict[str, Any]], excluded: set) -> List[Dict[str, Any]]:
    """扫描结果 → 可攻击目标：剔 excluded（尸体/被锁实体）+ 未登记非目标。

    excluded 为函数级黑名单（跨轮生效）：无战斗选项/已消失的实体不再重试
    （2026-08-27 23:39 修复：原来每轮重置导致对 10 只赐福星官无限走近+CALL 空转）。
    未登记实体（_boss_priority 返回 None）= 非目标（2026-08-28 六定案），
    不排序/不攻击，也不阻塞清图判定与换图轮换。
    """
    return [x for x in scanned
            if _boss_key(x) not in excluded
            and _boss_priority(x["name"]) is not None]

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

# 2026-08-28 23:16-23:35 实锤（automation.log）：游戏重启后 frida attach 被拒
# （VirtualAllocEx 0x5），网关反复"spawn 即退"，18082 持续拒绝连接；
# _http_json 原逻辑"heal 失败→20s→再试一次→仍失败就 raise"把整个 farm 事件
# 炸掉（23:27:43 / 23:30:59 / 23:34:16 三连 10061，GUI on_error=skip）。
# farm 对网关失联的正确姿态：挂起等待自愈（周期 ensure_gateway + 原请求探测），
# 恢复后无缝续跑；仅挂起超时或用户点停止才抛出。
GATEWAY_DOWN_MAX_WAIT_S = 1800.0   # 失联最长挂起 30 分钟，超时才放弃
GATEWAY_DOWN_POLL_S = 10.0         # 挂起期间探测周期（自愈为其 3 倍周期一次）


def _dismiss_engine_error_dialog() -> bool:
    """点掉 Galaxy2D 引擎致命错误弹窗（2026-08-29 00:25 实锤新增）。

    边走边CALL 对已失效实体反复调 事件开始/事件解析 时，引擎可能抛
    **原生致命错误**（模态 MessageBox："致命的错误 / this arg is not a
    userdata!"）。该弹窗卡住游戏主线程 → 网关 Lua 全部读超时。
    Lua 层 pcall 拦不住原生弹窗，唯一解法是后台 PostMessage 点"确定"，
    引擎随即恢复。弹窗属游戏进程（GetWindowThreadProcessId 校验），
    兜底场景（PID 未绑定）只点标题精确匹配的第一个。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hits = []   # (hwnd, pid)

        def _enum_cb(hwnd, lparam):
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value
            if ("致命的错误" in t) or ("not a userdata" in t):
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                hits.append((hwnd, int(pid.value)))
            return True

        CMPFUNC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(CMPFUNC(_enum_cb), 0)
        if not hits:
            return False
        game_pid = _get_bound_pid()
        target = None
        for hwnd, pid in hits:
            if game_pid and pid == game_pid:
                target = hwnd
                break
        if target is None:
            target = hits[0][0]
        # 先试 WM_COMMAND(IDOK=1)（后台无焦点可收）；实测部分 MessageBox 不认，
        # 再对 Button 子窗口发 BM_CLICK，直到 IsWindow 确认弹窗销毁
        user32.PostMessageW(target, 0x0111, 1, 0)
        gone = False
        for _ in range(10):
            if not user32.IsWindow(target):
                gone = True
                break
            btn = user32.FindWindowExW(target, 0, "Button", None)
            if btn:
                user32.PostMessageW(btn, 0x00F5, 0, 0)   # BM_CLICK
            time.sleep(0.2)
        if gone:
            logger.warning("已自动点掉引擎致命错误弹窗（this arg is not a userdata!），等待引擎恢复")
        else:
            logger.warning("引擎致命错误弹窗点击后未关闭，下个超时周期重试")
        return gone
    except Exception as e:
        logger.warning(f"点掉引擎错误弹窗失败: {e}")
        return False


def _http_json(gateway: str, path: str, data: dict = None, timeout: float = 10.0) -> dict:
    """POST JSON 到 gateway，返回解析后的 JSON。

    2026-08-27：网关不在线（WinError 10061 连接拒绝）时不再直接炸任务——
    先走 _heal_gateway()（gateway_guard.ensure_gateway 按 window_manager.pid
    重拉并 attach）后重试。
    2026-08-28（10061 三连炸修复）：heal 失败不再"20s 缓冲后试一次就放弃"，
    改为挂起等待自愈：原请求本身即探测，恢复后无缝续跑；仅挂起超过
    GATEWAY_DOWN_MAX_WAIT_S 或用户点停止才抛出（上层按原样报错）。
    2026-08-29（读超时三连炸修复）：读超时（TimeoutError "timed out"）与
    10061 同等待遇——此前只有 10061 走挂起重试，读超时直接 raise 把整个
    farm 事件炸掉（00:25:24 实锤：引擎被致命错误弹窗卡死 → 全部请求
    超时 → scan_scene_bosses 一发超时整场 farm 结束）。超时路径额外
    自动点掉引擎致命弹窗（_dismiss_engine_error_dialog）从根上解锁。
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

    import urllib.error as _urllib_err

    down_since = None
    last_heal = 0.0
    last_dismiss = 0.0
    while True:
        try:
            r = _once()
            if down_since is not None:
                logger.info(f"网关已恢复（失联/卡死 {time.time() - down_since:.0f}s），任务继续")
            return r
        except _urllib_err.HTTPError as e:
            # 2026-08-29 诊断：打印网关 4xx/5xx 的状态码与响应体（含具体 error）
            try:
                _b = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                _b = ""
            logger.warning(f"_http_json 网关返回 HTTP {e.code} {path}: {_b}")
            raise
        except Exception as e:
            reason = getattr(e, "reason", None)
            refused = isinstance(reason, ConnectionRefusedError) or "10061" in str(e)
            timed_out = (isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)
                         or "timed out" in str(e).lower())
            if not (refused or timed_out):
                raise   # 非失联/超时错误照旧上抛，GUI 能看到真实错误
            now = time.time()
            if down_since is None:
                down_since = now
                if timed_out:
                    logger.warning(f"网关读超时（引擎可能被致命错误弹窗卡死，将自动点掉），"
                                   f"挂起等待恢复（最长 {int(GATEWAY_DOWN_MAX_WAIT_S / 60)} 分钟）: {e}")
                else:
                    logger.warning(f"网关失联(10061)，挂起等待自愈"
                                   f"（最长 {int(GATEWAY_DOWN_MAX_WAIT_S / 60)} 分钟）: {e}")
            elif now - down_since > GATEWAY_DOWN_MAX_WAIT_S:
                raise   # 挂起超时，放弃（保留最后一次异常）
            if _gui_stop_requested():
                raise   # 用户停止：交还上层，任务引擎正在收尾
            if timed_out:
                # 弹窗可能反复弹：每 2s 探一次，点掉后给引擎 1s 恢复时间再重发请求
                if now - last_dismiss >= 2.0:
                    last_dismiss = now
                    if _dismiss_engine_error_dialog():
                        time.sleep(1.0)
                time.sleep(1.0)
            else:
                if now - last_heal >= GATEWAY_DOWN_POLL_S * 3:
                    last_heal = now
                    _heal_gateway()   # 能拉起就拉起；拉不起下个自愈周期再试
                time.sleep(GATEWAY_DOWN_POLL_S)


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
        logger.info("网关自愈开始（attach 实测 ~1.2s；若等满超时窗多为探测失明，"
                    "结束日志会带真实原因）...")
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


def _maybe_prepend_gc(code: str) -> str:
    """节流式 GC 前置（2026-08-29 23:40 根因修复配套）。

    lua51 内存不足直杀 exit 的缓解：不每趟都 GC（有开销/可能干扰扫描时序），
    而是按周期（默认每 30 秒 / 每 200 次调用）在最外层 Lua 代码块前附带
    ``collectgarbage("collect", 0)`` 一次增量回收。已带 GC 的代码不重复加。
    """
    global _last_gc_ts, _lua_call_count
    _lua_call_count += 1
    _now = _lua_call_count
    import time as _t
    _elapsed = _t.time() - _last_gc_ts
    if "collectgarbage" in code or "需要GC加在开头" in code:
        return code
    if _elapsed >= 20.0 and _now % 1 == 0:
        _last_gc_ts = _t.time()
        return "-- 节流GC\ncollectgarbage(\"collect\", 0)\n" + code
    return code


_lua_call_count = 0
import time as __tm
_last_gc_ts = __tm.time()

# ★2026-08-30 全局 Lua 节流器（方案A：9:07-9:30 attach 静置 23 分钟零崩溃 vs farm
#  持续注入 1-8 分钟随机崩 → 触发源=持续 Lua 脚本活动；用户提示"走路通道一直 CALL"
#  是最高频点之一）。WORLDBOSS_LUA_SLOW.flag 存在时，所有经 _lua/_lua_expr 的注入
#  强制最小间隔（默认 1.0s），把走路CALL/扫描/公告的高频注入统一压平。
_LUA_MIN_GAP = 0.0
_lua_last_ts = 0.0


def _lua_throttle():
    """全局节流：距上次注入不足 _LUA_MIN_GAP 则 sleep 补齐。"""
    global _lua_last_ts
    if _LUA_MIN_GAP > 0:
        _wait = _LUA_MIN_GAP - (__tm.time() - _lua_last_ts)
        if _wait > 0:
            __tm.sleep(_wait)
        _lua_last_ts = __tm.time()


def _lua(gateway: str, code: str, result_var: str = "__out") -> str:
    """经 /api/lua 执行 Lua 语句块，返回 result_var 值字符串。

    frida 会话死亡（游戏重开换 PID）时自动自愈网关并重试一次。

    2026-08-29 23:40 根因修复：lua51 内部 "not enough memory" 会直接 exit(1)
    杀进程（Ghidra 逆向 FUN_1001f880 实锤）。主因是高频注入 Lua + 跨图装载把
    game state 内存堆高。这里按节流周期在每个 Lua 代码块前附带一次增量 GC，
    从源头缓解内存累积。
    """
    code = _maybe_prepend_gc(code)
    _lua_throttle()
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
    _lua_throttle()
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
      1. 已知地图边界（map_ui_blocks.max_game_coord，用户实测）→ 以该图边界×15
         判像素（内部像素=网格×20，边界×15 能把真实像素值（如 12040）与合法
         网格（如大唐国境 349/大唐境外 533，仅略超测量边界）清晰分开——老全局
         GRID_SANITY_MAX=400 或"边界本身"都会把贴近边界/略超边的合法格坐标
         误判成像素 ×÷20 → 怪物定位全错、反复落错点空转刷时间）；
      2. 超过网格上限×15 → 判为内部像素坐标，÷20 转网格；
      3. 钳制入界（≤0 或 ≥地图边界）。
    """
    x, y = float(x), float(y)
    note = ""
    b = _load_map_bounds(map_name) if map_name else None
    lim = (max(b) * 15.0) if b else GRID_SANITY_MAX
    if abs(x) > lim or abs(y) > lim:
        x, y = x / 20.0, y / 20.0
        note = "像素→网格÷20"
    if map_name:
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


# 驿站对话跨图：无 desc 的入口（如大唐境外→碗子山）。在开阔图找"驿站老板"
#（对话含"送我过去"的传送驿站），CALL 事件开始 → PostMessage 点选项中心 → 切图。
# ★ 2026-08-30 实测定论：
#   - 大唐境外有两个"驿站老板"：@205,93（野怪，对话"让我来收拾你/我只是路过"）、
#     @13,95（真传送驿站，对话"送我过去/我还要逛逛"）——必须选后者。
#   - 选项"送我过去"选中判断矩形 (sx=219, sy=354, w=56, h=14) = 客户区绝对坐标，
#     中心 (247,361)。PostMessage 点击该点即触发传送（实测成功 1228 碗子山）。
#   - 需 hwnd 做后台 PostMessage（与 _fast_foot_click 同款）。
_STATION_DIALOG_TEXT = "送我过去"   # 传送驿站的首选项文本（区分野怪驿站）

# ★ 2026-08-30 驿站定位（用户定案：大唐境外全瞬移、不走路——图太大走路太慢）：
#   驿站对话跨图前提是角色贴近驿站（实测 CALL 距驿站 ≤~4 格才开对话栏，远了
#   事件开始 无反应）。hop 链中间步骤角色只落在地图入口，离驿站几十~上百格 →
#   自动链路必失败（14:14 记录）。修法：直接瞬移到驿站旁可走格 (12,95)——实测
#   落点精确到 1 格内（大唐境外站 @13,95，另一"驿站老板"@205,93 贴近后同样是
#   [送我过去|我还要逛逛]）。注意跨图刚完成立刻瞬移会被 snap 到远处，须等落地稳定。
_STATION_POINTS: Dict[str, Tuple[int, int]] = {
    "大唐境外": (12, 95),
    # ★2026-09-01 建邺城→江南野外：建邺守卫（称谓"传送江南野外"）网格坐标 (9,141)
    #   （用户 00:40 提供；柔和 CALL 后点"传送江南野外"实测 1501→1193 成功）
    "建邺城": (9, 141),
}


def _close_dialog(gateway: str) -> None:
    """关闭当前打开的对话栏（驿站/商店等窗口通用）。"""
    try:
        code = r'''
local d = tp.窗口.对话栏
if d then
  local cm = d.关闭 or d.关 or (getmetatable(d) and getmetatable(d).__index and getmetatable(d).__index.关闭)
  if cm then pcall(cm, d) end
end
_G.__out = (d ~= nil) and "closed" or "none"
'''
        _lua(gateway, code)
    except Exception:
        pass


def _station_dialog_cross(gateway: str, verbose: bool = True,
                          opt_text: str = None) -> bool:
    """点击当前图「传送 NPC」的传送选项实现跨图（无 desc 时用）。

    通用化（2026-09-01 实测）：
      - 驿站老板（大唐境外）→ 选项「送我过去」（opt_text=None 默认）
      - 建邺守卫（建邺城）→ 选项「传送江南野外」（opt_text="传送江南野外"）
      候选实体 = 名称含「驿站老板/守卫」且其 称谓/对话 含目标子串的 NPC。

    ★2026-09-01 「柔和 CALL」定案（用户指出"CALL 太快会崩"）：
      引擎装载对话脚本需要时间，CALL 后立即读选项/点击会撞未就绪状态 → 触发
      「this arg is not a userdata!」致命弹窗 → 游戏崩溃退选服界面（00:29 实锤
      PID 17784→23220）。柔和节奏 = CALL 后等 2s 装载 + 点击间隔 0.3~0.4s +
      MOUSEMOVE 前置，实测建邺守卫 CALL+点传送 全链路无崩溃、成功切图到江南野外。

    :param opt_text: 要点击的传送选项文本；None=默认「送我过去」（驿站）
    :return: True 切图成功（地图 ID 与发起时不同） / False 失败
    """
    target_opt = opt_text or _STATION_DIALOG_TEXT   # 默认驿站"送我过去"
    from library.common.win_utils import locate_game_window as _lgw
    try:
        import ctypes as _ct
    except Exception:
        return False
    pid = _get_bound_pid()
    hwnd = 0
    if pid > 0:
        _h = _lgw(pid, verbose=False)
        hwnd = _h[0] if isinstance(_h, tuple) else _h
    if not hwnd:
        if verbose:
            print("  ! 传送NPC跨图：未定位游戏窗口", flush=True)
        return False
    # ★ 2026-08-30 用户定案：大唐境外全用瞬移（图太大，走路太慢）。定位驿站同样
    #   直接瞬移到驿站旁可走格——实测 (12,95) 瞬移落点精确到 1 格内（落地稳定后
    #   CALL 必开"送我过去"）。瞬移落地后短等稳定窗，坐标还在跳动期 CALL 会扑空。
    cur_map = _cur_map_name(gateway)
    st = _STATION_POINTS.get(cur_map)
    if st:
        rg = _role_grid(gateway)
        near = (rg is not None and abs(rg[0] - st[0]) < 5.0
                and abs(rg[1] - st[1]) < 5.0)
        if not near:
            if verbose:
                print(f"  → 传送NPC跨图：瞬移到驿站旁 {cur_map}({st[0]},{st[1]})"
                      f"（当前 {rg}）", flush=True)
            for _tp in range(2):   # 落地抖动重试一次
                _gw_teleport(gateway, st[0], st[1], map_name=cur_map)
                time.sleep(1.2)
                rg = _role_grid(gateway)
                if (rg is not None and abs(rg[0] - st[0]) < 5.0
                        and abs(rg[1] - st[1]) < 5.0):
                    break
            if verbose:
                print(f"  → 传送NPC跨图：落地 {rg}", flush=True)
    # 1)~5) 找含目标选项的传送 NPC CALL → 点选项 → 等切图。
    # ★ 2026-08-30 实测修订：大唐境外两个"驿站老板"@13,95 与 @205,93 贴近后
    #   都会开 [送我过去|我还要逛逛]（此前误判 @205,93 为野怪）。逐个 CALL 后检查
    #   对话栏是否出现目标选项，不出现就右键关掉继续试下一个——绝不只凭 ok 就
    #   break（CALL 成功 ≠ 开了目标对话）。
    # ★ 2026-09-01 柔和定案：CALL 后必须短等装载（见 docstring），读选项也要
    #   逐次间隔拉长，避免高密 Lua 往返触发引擎战斗脚本装载崩溃。
    code = r'''
local out = ""
local target = "TARGET_OPT"
for _, pool in ipairs({tp.场景.场景人物, tp.临时Npc}) do
  if type(pool) == "table" then
    for k, e in pairs(pool) do
      if type(e) == "table" then
        local nm = tostring(e.名称 or e.名字 or "")
        local sub = tostring(e.称谓 or e.子类 or "")
        -- 驿站老板 OR 传送守卫（称谓含目标图/传送字样的 NPC 都可能是入口）
        if nm:find("驿站") or nm:find("守卫") or sub:find("传送") then
          local mt = getmetatable(e)
          local ev = (mt and mt.__index and mt.__index.事件开始) or e["事件开始"]
          if type(ev) == "function" then
            local ok, er = pcall(function() return ev(e) end)
            if ok then out = tostring(k) break end
          end
        end
      end
    end
  end
  if out ~= "" then break end
end
_G.__out = out
'''
    code = code.replace("TARGET_OPT", target_opt)
    for _att in range(2):
        if _att > 0:
            _close_dialog(gateway)   # 清理上一个 attempt 残留的对话栏
            time.sleep(0.6)
        uid = _lua(gateway, code)
        if not uid:
            if verbose:
                print(f"  ! 传送NPC跨图：找不到含'{target_opt}'的传送NPC", flush=True)
            continue
        # ★2026-09-01 柔和定案：CALL NPC 后必须等 2s 让引擎装载对话脚本
        #   （0s 就操作会撞未就绪 → this arg is not a userdata → 崩游戏退选服）
        time.sleep(2.0)
        # 2) 柔和等对话栏装载完成（再兜底轮询）
        dlg_ok = False
        for _ in range(12):
            time.sleep(0.5)
            d = _read_dialog_bar(gateway)
            if any(target_opt in x for x in d):
                dlg_ok = True
                break
        if not dlg_ok:
            if verbose:
                print(f"  ! 传送NPC跨图：CALL 后无选项（uid={uid}），尝试直接点击", flush=True)
        # 3) 读目标选项选中判断矩形（客户区绝对坐标）
        sel = _read_dialog_sel_rect(gateway, target_opt)
        if not sel:
            if verbose:
                print(f"  ! 传送NPC跨图：读不到'{target_opt}'矩形", flush=True)
            continue
        cx, cy = (sel[0] + sel[2]) // 2, (sel[1] + sel[3]) // 2
        if verbose:
            print(f"  → 传送NPC跨图：点'{target_opt}' 客户区({cx},{cy})", flush=True)
        # 4) 柔和 PostMessage 点击（MOUSEMOVE → 0.35s → down → 0.35s → up）
        user32 = _ct.windll.user32
        lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
        time.sleep(0.8)
        user32.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.35)
        user32.PostMessageW(hwnd, 0x0201, 1, lp); time.sleep(0.35)
        user32.PostMessageW(hwnd, 0x0202, 0, lp)
        # 5) 等地图变化（发起时的地图 ID）
        cur0 = _cur_map_id(gateway)
        for _ in range(20):
            time.sleep(1.0)
            now = _cur_map_id(gateway)
            if now is not None and now != cur0:
                if verbose:
                    print(f"  ✓ 传送NPC跨图成功：地图 {cur0} → {now}", flush=True)
                return True
        if verbose:
            print(f"  ! 传送NPC跨图：点后 20s 地图未变（{cur0}→{_cur_map_id(gateway)}），重试",
                  flush=True)
    return False


def _read_dialog_bar(gateway: str) -> List[str]:
    """读对话栏选项文本列表。"""
    code = r'''
local out = {}
local d = tp.窗口.对话栏
if d and d.选项 then
  for i = 1, 16 do
    local e = d.选项[i]
    if type(e) == "table" then
      out[#out+1] = tostring(e.基本内容 or e.跳转链接 or "")
    end
  end
end
_G.__out = table.concat(out, ";")
'''
    raw = _lua(gateway, code)
    return [x for x in (raw or "").split(";") if x]


def _read_dialog_sel_rect(gateway: str, opt_text: str) -> Optional[tuple]:
    """读对话栏指定选项的选中判断矩形 (x, y, x2, y2)（客户区绝对坐标）。"""
    code = r'''
local out = ""
local d = tp.窗口.对话栏
if d and d.选项 then
  for i = 1, 16 do
    local e = d.选项[i]
    if type(e) == "table" then
      local t = tostring(e.基本内容 or e.跳转链接 or "")
      if t == OPT_TEXT then
        local s = e.选中判断
        if s then
          out = tostring(s.x) .. "," .. tostring(s.y) .. "," ..
                tostring(s.x2) .. "," .. tostring(s.y2)
        end
        break
      end
    end
  end
end
_G.__out = out
'''.replace("OPT_TEXT", '"%s"' % opt_text)
    raw = _lua(gateway, code)
    if not raw:
        return None
    try:
        xs = [int(float(v)) for v in raw.split(",")]
        return tuple(xs) if len(xs) == 4 else None
    except Exception:
        return None


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


# ============================================================
# 飞行符跨图（2026-09-01 用户定案：减少瞬移动作）
# ============================================================
# 原理：目标图在飞行符可传列表（长安/建邺城/傲来国/长寿村/西梁女国/宝象国/
# 朱紫国，校准文件 data/fly_map_calib.json）→ 行囊右键飞行符道具 → 弹出传送
# 地图界面 → 左键点目标图按钮（校准坐标）→ 等地图切换 → 瞬移落点。
# 相对 hop 链：单次界面点击直达目标图，代替多段瞬移 hop（跨图密集瞬移是
# 引擎战斗脚本装载崩溃的触发器之一）。
#
# 关键实测（2026-09-01 00:0x）：
#   - 行囊物品表在"刚打开瞬间"可能未加载（读到 nil）→ 先关包再开包强制刷新；
#   - Lua 资源组按钮坐标与实际渲染有偏差（长安差 ~58px）→ 点击用校准坐标；
#   - 右键=打开飞行符道具；左键=传送界面里直接传送（无确认按钮）。

# 飞行符可传地图 → 校准文件键名（长安=长安城, 建邺=建邺城, 西梁女国=西凉女国）
_FLY_MAP_KEYS: Dict[str, str] = {
    "长安": "长安",
    "建邺城": "建邺",
    "傲来国": "傲来国",
    "长寿村": "长寿村",
    "西梁女国": "西梁女国",
    "宝象国": "宝象国",
    "朱紫国": "朱紫国",
}
_FLY_CALIB_FILE = os.path.join(_PROJECT_ROOT, "data", "fly_map_calib.json")

# ★2026-09-01 飞行符二级中转：目标图不在飞行符直达 7 键，但可 飞行符→中转图 →
#   守卫/驿站对话传送 到达。值 = (中转图, 对话框选项文本, 守卫网格坐标 or None)
#   实测链路（00:40~00:44）：
#     - 江南野外：飞行符→建邺城→建邺守卫"传送江南野外"(9,141) 1501→1193 ✓ 无崩溃
#   用户提供的中转辐射关系（2026-09-01 00:45，守卫入口待逐图实测后补坐标）：
#     - 长寿村 → 方寸山、长寿郊外 → 大唐境外
#     - 朱紫国 → 大唐境外 → 大唐国境 ←→ 长安城
#     - 傲来国 → 花果山 → 北俱芦洲
#   opt 为 None 时用 _station_dialog_cross 默认「送我过去」（驿站入口）
_FLY_TRANSIT: Dict[str, Tuple[str, str, Optional[Tuple[int, int]]]] = {
    "江南野外": ("建邺城", "传送江南野外", (9, 141)),
    # 以下为规划项（守卫坐标/选项待实测后激活；None 守卫 = 由 hop 链兜底）
    "方寸山":   ("长寿村", None, None),
    "长寿郊外": ("长寿村", None, None),
    "大唐境外": ("朱紫国", None, None),
    "大唐国境": ("朱紫国", None, None),
    "花果山":   ("傲来国", None, None),
    "北俱芦洲": ("傲来国", None, None),
}


def _fly_calib() -> Dict[str, tuple]:
    """载入飞行符按钮校准坐标 {地图名: (cx, cy)}；缺失/损坏返回 {}。"""
    try:
        with open(_FLY_CALIB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        for k, v in (data.get("maps") or {}).items():
            try:
                out[k] = (int(v["cx"]), int(v["cy"]))
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _fly_supported(target_map: str) -> bool:
    """目标图是否可由飞行符直达（校准文件存在且该图已校准）。"""
    key = _FLY_MAP_KEYS.get(str(target_map))
    if not key:
        return False
    return key in _fly_calib()


def _open_bag_by_icon(gateway: str, verbose: bool = True) -> bool:
    """后台鼠标点击背包图标打开行囊（用户 2026-09-01 定案：不用 Lua CALL 开包，
    只 LUA 查背包是否开启）。图标客户区坐标 = (695,601)（用户提供，屏幕 766,672
    换算客户区后微调）。

    ★2026-09-01 用户补充：背包图标下方可能有怪物/NPC，点击会触发对话/战斗弹窗
    —— 每次点击后检测弹窗（对话栏可视/引擎错误弹窗），有则关闭弹窗后重新点击，
    直到背包成功打开或重试上限。返回是否开包成功。"""
    def _vis():
        try:
            return _lua_expr(gateway,
                             "tostring(tp.窗口.道具行囊 and tp.窗口.道具行囊.可视 or false)") == "true"
        except Exception:
            return False

    def _dialog_open() -> bool:
        try:
            return _lua_expr(gateway,
                             "tostring(tp.窗口.对话栏 and tp.窗口.对话栏.可视 or false)") == "true"
        except Exception:
            return False

    if _vis():
        return True
    pid = _get_bound_pid()
    if pid <= 0:
        return False
    from library.common.win_utils import locate_game_window as _l
    _h = _l(pid, verbose=False)
    hwnd = _h[0] if isinstance(_h, tuple) else _h
    if not hwnd:
        return False
    import ctypes as _ct
    user32 = _ct.windll.user32
    # ★ 2026-09-01 用户实锤场景：背包图标正下方有常驻商人/NPC，固定点(695,601)
    #   每次点击必命中 NPC → 弹对话窗 → 关掉重试又点回原位 → 4 次全败 → 飞行符
    #   跨图全退 hop 链（角色看起来"一直在等瞬移"）。修复：多档点位轮换——
    #   主点(695,601)偏上是背包按钮本体；命中 NPC 后换"左偏上"副点，避开下方
    #   场景 NPC 的碰撞体积；仍失败再换"右上"点，最后才判失败交 hop 链兜底。
    _CLICK_SPOTS = [(695, 601), (677, 585), (712, 590), (695, 570)]
    for _i in range(4):
        # 点击前若有残留对话栏（上次误点留下的）→ 先关
        if _dialog_open():
            _close_dialog(gateway)
            __tm.sleep(0.4)
        # 后台点击背包图标（带抖动，模拟真实点击；命中 NPC 后轮换避让点位）
        _spot = _CLICK_SPOTS[_i % len(_CLICK_SPOTS)]
        jx = _spot[0] + random.randint(-2, 2)
        jy = _spot[1] + random.randint(-2, 2)
        lp = (int(jy) << 16) | (int(jx) & 0xFFFF)
        user32.PostMessageW(_ct.c_void_p(hwnd), 0x0200, 0, lp)   # MOUSEMOVE 先到
        __tm.sleep(0.06)
        user32.PostMessageW(_ct.c_void_p(hwnd), 0x0201, 1, lp)   # 左键 down
        __tm.sleep(0.08)
        user32.PostMessageW(_ct.c_void_p(hwnd), 0x0202, 0, lp)   # 左键 up
        __tm.sleep(0.7)
        # 点后优先看行囊是否打开
        if _vis():
            return True
        # 未打开且出现对话栏（点到图标下方怪物/NPC）→ 关闭弹窗，下一轮重试
        if _dialog_open():
            if verbose:
                print("[开包] 点击触发对话弹窗（图标下有NPC/怪物），关闭后重试", flush=True)
            _close_dialog(gateway)
            _dismiss_engine_error_dialog()
            __tm.sleep(0.5)
            continue
        # 未开包也无对话栏：可能是坐标点偏/引擎弹窗 → 检查并重试
        _dismiss_engine_error_dialog()
        __tm.sleep(0.4)
    return _vis()


def _fly_open_bag_refresh(gateway: str) -> bool:
    """确保行囊打开（飞行符使用前置条件）：已开则保持，未开则**后台点背包图标**
    打开（用户 2026-09-01 定案：不用 Lua CALL 开包，避免 CALL 崩溃风险）。
    仅 Lua 查开包状态（可视=true）。"""
    return _open_bag_by_icon(gateway)


def _fly_find_charm_cell(gateway: str) -> Optional[tuple]:
    """在行囊物品表里找「飞行符」格子中心（客户区坐标）。找不到返回 None。"""
    code = r'''
local out = ""
local B = tp.窗口.道具行囊
if type(B) == "table" and type(B.物品) == "table" then
  for i = 1, #B.物品 do
    local c = B.物品[i]
    if type(c) == "table" then
      local nm = tostring((c.物品 and c.物品.名称) or "")
      if nm:find("飞行符") then
        out = tostring(c.x) .. "," .. tostring(c.y)
        break
      end
    end
  end
end
_G.__out = out
'''
    try:
        raw = _lua(gateway, code)
    except Exception:
        return None
    if raw and "," in raw:
        x, y = raw.split(",", 1)
        try:
            return int(x) + 26, int(y) + 26
        except Exception:
            return None
    return None


def _fly_open_panel(gateway: str, verbose: bool = True) -> Optional[tuple]:
    """打开飞行符界面：行囊右键「飞行符」格子。
    :return: (hwnd, charm_cell_客户区) 或 None（打开失败/无飞行符）
    """
    pid = _get_bound_pid()
    if pid <= 0:
        if verbose:
            print("[飞行符] 未绑定游戏 PID，无法打开界面", flush=True)
        return None
    from library.common.win_utils import locate_game_window as _l
    _h = _l(pid, verbose=False)
    hwnd = _h[0] if isinstance(_h, tuple) else _h
    if not hwnd:
        if verbose:
            print("[飞行符] 找不到游戏窗口", flush=True)
        return None
    # 前置：打开行囊（用户 2026-09-01 要求：用飞行符前必须确认背包打开；
    # 且不用 Lua CALL 开包，改后台点背包图标）
    if not _fly_open_bag_refresh(gateway):
        if verbose:
            print("[飞行符] 行囊打不开，无法使用飞行符", flush=True)
        return None
    # 图标开包后物品表已加载；若仍读不到（首次打开瞬间），稍等重读一次即可
    cell = _fly_find_charm_cell(gateway)
    if not cell:
        __tm.sleep(1.0)
        cell = _fly_find_charm_cell(gateway)
    if not cell:
        if verbose:
            print("[飞行符] 行囊里没有飞行符（请确认背包有飞行符道具）", flush=True)
        return None
    cx, cy = cell
    import ctypes as _ct
    user32 = _ct.windll.user32
    lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
    user32.PostMessageW(_ct.c_void_p(hwnd), 0x0200, 0, lp)   # MOUSEMOVE
    __tm.sleep(0.05)
    user32.PostMessageW(_ct.c_void_p(hwnd), 0x0204, 0, lp)   # 右键 down（打开飞行符）
    __tm.sleep(0.08)
    user32.PostMessageW(_ct.c_void_p(hwnd), 0x0205, 0, lp)   # 右键 up
    __tm.sleep(1.2)
    ok = False
    try:
        ok = _lua_expr(gateway,
                       "tostring(tp.窗口.飞行符 and tp.窗口.飞行符.可视 or false)") == "true"
    except Exception:
        ok = False
    if not ok and verbose:
        print("[飞行符] 右键飞行符后界面未弹出", flush=True)
    return (hwnd, cell) if ok else None


def _fly_tap_map(hwnd, key: str, verbose: bool = True) -> bool:
    """在飞行符界面左键点击目标图按钮（校准坐标，无确认按钮直接传送）。"""
    calib = _fly_calib()
    pt = calib.get(key)
    if not pt:
        return False
    cx, cy = pt
    import ctypes as _ct
    user32 = _ct.windll.user32
    lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
    user32.PostMessageW(_ct.c_void_p(hwnd), 0x0200, 0, lp)   # MOUSEMOVE 先到
    __tm.sleep(0.06)
    user32.PostMessageW(_ct.c_void_p(hwnd), 0x0201, 1, lp)   # 左键 down
    __tm.sleep(0.08)
    user32.PostMessageW(_ct.c_void_p(hwnd), 0x0202, 0, lp)   # 左键 up
    if verbose:
        print(f"[飞行符] 左键点 {key} @ 客户区({cx},{cy})", flush=True)
    return True


def _fly_cross_map(gateway: str, target_map: str, x: int = None, y: int = None,
                   verbose: bool = True) -> dict:
    """飞行符直达目标图（目标图必须在飞行符可传列表）。
    成功后瞬移落点（已知坐标直达 / 无则地图随机）。失败返回 ok=False（调用方回退 hop 链）。
    """
    key = _FLY_MAP_KEYS.get(str(target_map))
    if not key:
        return {"ok": False, "error": f"目标图 {target_map} 不在飞行符可传列表", "via": "fly_none"}
    calib = _fly_calib()
    if key not in calib:
        return {"ok": False, "error": f"飞行符校准缺 {key}（运行 calibrate_fly_map.py）", "via": "fly_nocalib"}
    opened = _fly_open_panel(gateway, verbose=verbose)
    if not opened:
        return {"ok": False, "error": "飞行符界面打开失败（行囊无飞行符/右键无效）", "via": "fly_open_fail"}
    hwnd, _cell = opened
    # 左键点目标图（界面刚弹出可能还在加载 → 短等再点）
    __tm.sleep(0.3)
    _fly_tap_map(hwnd, key, verbose=verbose)

    # 等地图切换（轮询目标图 ID；清掉飞行符/行囊窗口光线遮蔽问题靠 hop 后冷却）
    try:
        start_id = _cur_map_id(gateway)
    except Exception:
        start_id = None
    target_id = _MAP_NAME_TO_ID.get(MAP_ID_TO_NAME.get(str(target_map), target_map))
    changed = False
    for _ in range(20):   # 最长 ~10s
        __tm.sleep(0.5)
        try:
            cur = _cur_map_id(gateway)
        except Exception:
            cur = None
        if verbose:
            print(f"  [飞行符] 等切图 地图={cur} (目标={target_id})", flush=True)
        if cur is not None and target_id is not None:
            if int(cur) == int(target_id):
                changed = True
                break
        elif cur is not None and start_id is not None and cur != start_id:
            changed = True
            break
    # 兜底：按地图名判定（ID 映射缺失时）
    if not changed:
        try:
            if _map_same(_cur_map_name(gateway), target_map):
                changed = True
        except Exception:
            pass
    if not changed:
        if verbose:
            print(f"[飞行符] 点 {key} 后 10s 地图未变（可能是误点/界面卡住），回退 hop 链", flush=True)
        _fly_close_panel(gateway)
        return {"ok": False, "error": "飞行符传送未切图", "via": "fly_no_switch"}
    __tm.sleep(HOP_SETTLE_S if False else 0.9)   # 落地静默窗（对齐 hop 后冷却）
    # ★2026-09-01 用户定案顺序：切图后**先关行囊/飞行符界面**，再瞬移落点——
    #   行囊窗口残留会挡瞬移落点/后续扫描战斗（此前顺序反了：先瞬移后关包）。
    _fly_close_panel(gateway)
    # ★2026-09-01 用户追问"为什么飞行符后又瞬移到别处再瞬移到BOSS附近"：
    #   飞行符落地本身已把角色放到目标图的固定落点——**除非调用方明确给了
    #   目标坐标（公告带坐标/指名落点），否则不再做随机落点瞬移**，直接交
    #   后续主循环扫描打怪（避免每图白瞬移一次拖延节奏；201 的"1145→长寿村"
    #   实例：飞行符落点后多余随机瞬移 → 用户要求去掉）。
    if x is not None and y is not None:
        tx, ty = int(x), int(y)
        tx, ty, note = _norm_grid_xy(tx, ty, target_map)
        if note:
            logger.warning(f"飞行符落点坐标守门: ({x},{y}) → ({tx},{ty}) [{note}]")
        tp_r = _http_json(gateway, "/api/act/teleport",
                          {"x": int(tx), "y": int(ty), "sync": True, "jump": True},
                          timeout=20.0)
        return {"ok": bool(tp_r.get("ok")), "error": tp_r.get("error"),
                "via": "fly_charm+teleport", "teleport": tp_r.get("result", tp_r),
                "land": (tx, ty)}
    return {"ok": True, "error": None, "via": "fly_charm",
            "land": None, "note": "飞行符已落点，未指定坐标不额外瞬移"}


def _fly_close_panel(gateway: str) -> None:
    """关闭飞行符界面 + 道具行囊（用户 2026-09-01 要求：使用飞行符成功后
    关闭背包，避免残留窗口挡后续扫描/战斗操作）。"""
    try:
        _lua(gateway, "local F=tp.窗口.飞行符; if F then F.可视=false end")
    except Exception:
        pass
    try:
        _lua(gateway, r'''
local w = tp.窗口.道具行囊
if w then
  pcall(function()
    if type(w.关闭) == "function" then w:关闭()
    elseif type(w.关) == "function" then w:关() end
  end)
  w.可视 = false
end
''')
    except Exception:
        pass


def _gw_cross_map(gateway: str, target_map: str, x: int = None, y: int = None) -> dict:
    """跨图传送到目标地图（2026-08-27 BFS 实测终版）：

    优先级：
      1. 当前图传送表直达（三级匹配：精确终点 / '进'前缀 / substring）；
      2. ★ 实测链路 _HOP_CHAINS：服务器对 desc 全局查表、不校验当前图和坐标，
         链式拼接从任意位置直达目标；
      3. 旧两段式（回长安枢纽再查表）——链路表未覆盖时的兜底。

    2026-08-30 00:45 修复（用户指正，参照 SYHS._wait_map_switch）：
      跨图包发出后**轮询 `tp.当前地图` 变为 target_map 的 ID** 才认为到位，
      替代旧逻辑"依赖网关固定 sleep(3000~3500) + 行数/宽度(旧图残留误判)"。
      网关侧 cross_map 内部也有 wait 逻辑，这里再轮询地图 ID 双保险——
      杜绝"旧图数据还在就瞬移→新图未加载→画面格子/点击崩溃"。

    2026-08-30 用户要求：跨图方法统一用 SYBUZ2 同款（= 调 SYHS）——
      SYHS((x,y), target_location=目标图, wait_stable=False) 内部完成
      _ONE_HOP 一步直达（map_switch → 轮询 tp.当前地图 → teleport），
      SYBUZ2 整套实机跑稳；SYHS 未收录 target_map（花果山/北俱芦洲/
      傲来国/大唐境外等）时回退下方 HOP 链/传送表两步式（同款骨架）。
      禁止修改 SYBUZ2.py / SYHS.py。
    """
    _target_id = _MAP_NAME_TO_ID.get(target_map) if target_map else None

    # ★ 2026-09-01 用户定案：目标图在飞行符可传列表 → 优先飞行符直达
    #   （单次界面点击代替多段瞬移 hop；跨图密集瞬移是战斗脚本装载崩溃触发器之一）。
    #   飞行符失败（无道具/界面未开/未切图）→ 静默回退下方 hop 链 / SYHS。
    if _fly_supported(target_map):
        _fr = _fly_cross_map(gateway, target_map, x, y, verbose=True)
        if _fr.get("ok") and _map_same(_cur_map_name(gateway), target_map):
            return _fr
        if not _fr.get("ok"):
            logger.warning(f"飞行符跨 {target_map} 失败（{_fr.get('via')}: {_fr.get('error')}），回退 hop 链")
        _fly_close_panel(gateway)   # 失败也确保关掉背包窗口

    # ★ 2026-09-01 飞行符二级中转：目标图不在飞行符直达，但可 飞行符→中转图 →
    #   守卫/驿站对话 或 hop 链 到达（如 建邺城守卫→江南野外，实测 1501→1193 成功）。
    #   守卫已实测的（opt 非空）：飞中转图 → 守卫对话直达 → return。
    #   守卫未实测的（opt 为空）：飞中转图后交棒下方 hop 链（基于中转图找路，
    #   比从任意位置多段瞬移更稳；飞行符落地=软跨图，规避高密瞬移触发崩溃）。
    _trans = _FLY_TRANSIT.get(str(target_map))
    if _trans and not _fly_supported(target_map):
        _hub, _opt, _guard = _trans
        if _fly_supported(_hub) and _cur_map_name(gateway) != target_map:
            if _guard:
                _STATION_POINTS.setdefault(_hub, _guard)
            _fok = _fly_cross_map(gateway, _hub, verbose=False).get("ok", False) \
                and _map_same(_cur_map_name(gateway), _hub)
            if _fok and _opt:
                # 守卫对话直达（柔和 CALL → 点传送选项 → 切图）
                _ok2 = _station_dialog_cross(gateway, verbose=True, opt_text=_opt)
                if _ok2 and _map_same(_cur_map_name(gateway), target_map):
                    print(f"  ✓ 飞行符中转跨图：{_hub}→{target_map}（守卫对话）", flush=True)
                    return {"ok": True, "via": "fly_charm+station",
                            "hub": _hub, "target": target_map,
                            "result": "对话传送到位"}
                logger.warning(f"飞行符中转 {_hub}→{target_map} 守卫对话未切图，回退 hop 链")
            elif _fok:
                logger.info(f"飞行符中转：已到 {_hub}（守卫入口未配置），交棒 hop 链找路到 {target_map}")
            else:
                logger.warning(f"飞行符中转 {_hub} 落点失败，回退 hop 链")

    # ★ 2026-08-30 提速（用户实锤"站着不动/速度不理想"）：目标图在 _HOP_CHAINS 内 →
    #   **跳过 SYHS 直接走链路**。原因：SYHS 内表把 长寿村/长寿郊外 都归为 ID 1070、
    #   one_hop desc 也仅指向郊外 → 去长寿村必先白等 15~20s 失败再回退（16:03 实测
    #   map_changed_ms=20178）；其余图 SYHS 多数也 no-op（ok=True 但未切图）白耗一次
    #   网关往返。而 HOP 链 desc 实测全局直达（不受来源图校验），长安→大唐国境→
    #   大唐境外→驿站→… 已覆盖全部监控图，链式 5~15s 即可到图。
    _chain_skip_syhs = bool(target_map and _HOP_CHAINS.get(target_map))

    def _confirm_map_switch(timeout: float = 12.0) -> bool:
        """轮询 tp.当前地图 变为目标 ID（SYHS 同款，实测切图 ~340ms）。"""
        if not _target_id:
            return True   # 无名可查 → 不阻塞，靠网关侧兜底
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                cur = str(_cur_map_id(gateway) or "")
                if str(_target_id) == cur:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    # ---- 主路径（SYBUZ2 同款跨图）：SYHS 一步直达 + 落坐标复核 ----
    # （2026-08-30：链内目标图 _chain_skip_syhs=True 时跳过，直接走下方 HOP 链）
    if not _chain_skip_syhs:
        try:
            from tasks.library.SYHS import SYHS as _SYHS_cross
            _cx, _cy = DEFAULT_MAP_CENTER.get(target_map, (80, 80))
            if x is not None and y is not None:
                _cx, _cy = int(x), int(y)
            _sr = _SYHS_cross((_cx, _cy), target_location=target_map,
                              gateway=gateway, wait_stable=False, verbose=False)
            if _sr.get("ok"):
                # SYHS 返回值 map_switch 非空 = 判定需跨图并完成切图；
                # 为空 = 同图瞬移/不跨图。均复核地图名，到位即成功返回。
                if _map_same(_cur_map_name(gateway), target_map):
                    return {"ok": True, "error": _sr.get("message"),
                            "via": "SYHS" if _sr.get("map_switch") else "SYHS_no_switch",
                            "map_switch": _sr.get("map_switch"),
                            "detail": _sr.get("detail")}
            logger.info(f"cross_map: SYHS 未切到 {target_map} "
                        f"(map_switch={_sr.get('map_switch')} ok={_sr.get('ok')})，回退 HOP 链")
        except Exception as e:
            logger.warning(f"cross_map: SYHS 跨图异常({e})，回退 HOP 链")

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
        # ★ 2026-08-30 用户指正（参照 SYHS/DSHNPC 同款两步式跨图）：
        #   第 1 步只切图（/api/act/map_switch 发 1003，画面不动）→
        #   轮询 tp.当前地图 变为目标 ID（不 sleep 盲等）→
        #   第 2 步确认切图成功后才 teleport 落坐标（防止旧图残留/新图未加载
        #   → 画面格子 + 点击崩溃）。若跨图失败则不瞬移，返回失败。
        ms_resp = _http_json(gateway, "/api/act/map_switch",
                             {"desc": desc}, timeout=25.0)
        map_ok = _confirm_map_switch()
        if not map_ok:
            logger.warning(f"cross_map desc={desc} 地图未切到 {target_map} "
                           f"(目标ID={_target_id})，放弃瞬移")
            return {"ok": False, "error": f"跨图未完成: desc={desc}",
                    "map_switch": ms_resp.get("result", ms_resp)}
        # 切图成功后：瞬移落坐标（复用 teleport；含 1002 同步服务端）
        tp_r = _http_json(gateway, "/api/act/teleport",
                          {"x": int(tx), "y": int(ty), "sync": True, "jump": True},
                          timeout=20.0)
        return {"ok": bool(tp_r.get("ok")), "error": tp_r.get("error"),
                "map_switch": ms_resp.get("result", ms_resp),
                "teleport": tp_r.get("result", tp_r), "via": "map_switch+teleport"}
    # 实测链路兜底（2026-08-27）：desc 全局查表 → 链式拼接从任意位置直达。
    # 2026-08-28 B6 修复：旧实现每步发完请求不查结果，链中一步被吞整链错位
    # （后续 hop 都基于错误起点）。现在每步查 HTTP ok，失败静默重发一次。
    # 2026-08-30：每步改为"map_switch + 轮询地图 ID"，切到才算成功。
    # 2026-08-30 驿站对话跨图：某些入口无 desc（如大唐境外→碗子山只能点驿站
    # 老板"送我过去"），hop 链里用特殊标记 __STATION_DIALOG__ 占位，走到该步时
    # 点驿站老板对话（CALL 事件开始 → PostMessage 点"送我过去"即切图）。
    chain = _HOP_CHAINS.get(target_map)
    if chain:
        _chain_len = len(chain)
        for _ci, desc in enumerate(chain):
            _is_last = (_ci == _chain_len - 1)
            if desc == "_STATION_DLG_":
                if not _station_dialog_cross(gateway, verbose=False):
                    return {"ok": False, "error": "驿站对话跨图失败",
                            "via": "station_dialog"}
                continue
            for _attempt in (1, 2):
                r = _http_json(gateway, "/api/act/map_switch",
                               {"desc": desc}, timeout=25.0)
                if isinstance(r, dict) and r.get("ok"):
                    break
                logger.warning(f"hop 链步骤失败({'重试' if _attempt == 1 else '放弃'}): "
                               f"desc={desc} resp={r}")
                time.sleep(1.0)
            if _is_last:
                # ★ 最后一步：轮询地图 ID 变到目标图（2026-08-30 提速：目标 ID 判定
                #   保留——必须确认到位才能瞬移落点，防未到图就瞬移崩格子）
                if _confirm_map_switch(timeout=6.0):
                    break
                _bid = _cur_map_id(gateway)
                _chg = False
                for _p in range(6):   # 最长 3s
                    time.sleep(0.5)
                    _now = _cur_map_id(gateway)
                    if _now is not None and _now != _bid:
                        _chg = True
                        break
                if _confirm_map_switch(timeout=2.0):
                    break
                if not _chg:
                    logger.warning(f"hop 链末步未切图: desc={desc} 地图未变"
                                   f"({_bid}→{_cur_map_id(gateway)})")
            else:
                # ★ 2026-08-30 22:59 用户提速：中间跳【不轮询 Lua】——服务器全局查表、
                #   不校验当前图，中间 map_switch 连发即可（上一步是否到位不影响下一步）。
                #   只留固定 1.2s 客户端切图渲染静默窗（无 Lua 往返），到目的地才 Lua。
                time.sleep(1.2)
        # 链条切到目标图后：瞬移落坐标（2026-08-30 补，防止停在图入口）
        # ★ 2026-08-30 用户定案：默认落点改**地图范围内随机**（不再固定 100,100
        #   或地图中心）——落点分散不扎堆，且随机点通常比中心更靠近某片怪物刷新区；
        #   已知目标坐标（x,y 传入）仍直达，不随机。
        if x is not None and y is not None:
            tx, ty = int(x), int(y)
        else:
            _bnds = _load_map_bounds(target_map)
            if _bnds:
                _ix = max(2, int(_bnds[0] * 0.08))
                _iy = max(2, int(_bnds[1] * 0.08))
                tx = random.randint(_ix, max(_ix + 1, _bnds[0] - _ix))
                ty = random.randint(_iy, max(_iy + 1, _bnds[1] - _iy))
            else:
                tx, ty = random.randint(5, 100), random.randint(5, 100)
        tx, ty, note = _norm_grid_xy(tx, ty, target_map)
        if note:
            logger.warning(f"hop_chain 坐标守门: ({x},{y}) → ({tx},{ty}) [{note}]")
        tp_r = _http_json(gateway, "/api/act/teleport",
                          {"x": int(tx), "y": int(ty), "sync": True, "jump": True},
                          timeout=20.0)
        return {"ok": bool(tp_r.get("ok")), "error": tp_r.get("error"),
                "via": "hop_chain", "teleport": tp_r.get("result", tp_r)}
    # 两段式：回长安枢纽
    hub_hop = (_find_exact_hop(gateway, "长安")
               or _find_exact_hop(gateway, "长安", sep="进", prefix_match=True))
    if hub_hop:
        h_desc, h_x, h_y = hub_hop
        # 2026-08-30：统一 map_switch + 轮询地图 ID（替换旧 cross_map+固定sleep）
        ms1 = _http_json(gateway, "/api/act/map_switch",
                         {"desc": h_desc}, timeout=25.0)
        _chg1 = _confirm_map_switch(timeout=10.0)
        if not _chg1:
            return {"ok": False, "error": f"回长安未完成: {h_desc}",
                    "map_switch": ms1.get("result", ms1)}
        hop2 = _find_exact_hop(gateway, target_map)
        if hop2:
            desc2, x2, y2 = hop2
            _http_json(gateway, "/api/act/map_switch", {"desc": desc2}, timeout=25.0)
            _chg2 = _confirm_map_switch(timeout=10.0)
            if not _chg2:
                return {"ok": False, "error": f"长安→{target_map} 未完成: {desc2}"}
            tp2 = _http_json(gateway, "/api/act/teleport",
                             {"x": int(x2), "y": int(y2), "sync": True, "jump": True},
                             timeout=20.0)
            return {"ok": bool(tp2.get("ok")), "error": tp2.get("error"),
                    "via": "hub_chain", "teleport": tp2.get("result", tp2)}
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


def _cur_map_id(gateway: str) -> Optional[int]:
    """读取当前地图数字 ID（tp.当前地图）；失败返回 None。"""
    try:
        v = _lua_expr(gateway, "tostring(tp.当前地图 or '')").strip()
        if v:
            return int(v)
    except Exception:
        pass
    return None


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
        # ★2026-08-30 21:57 实锤修复：window_manager 未绑定会让 hwnd=0，
        #   solve_v7 的 PostMessage 点击发到 0 句柄必然失败 → 验证码一直解不掉
        #   → 游戏端验证码超时强制下线。与 MPCG._bind_hwnd 同思路：
        #   直解前先按网关 PID 强制重绑窗口，保证 hwnd 有效。
        hwnd = int(getattr(window_manager, "hwnd", 0) or 0)
        if hwnd <= 0:
            try:
                _ensure_walker_bound(gateway, verbose=False)
            except Exception:
                pass
            hwnd = int(getattr(window_manager, "hwnd", 0) or 0)
        # ★2026-08-30 21:57 加固：引擎被致命弹窗卡死刚恢复的瞬间，Lua 读答案/
        #   按钮坐标（captcha_v7._lua 无挂起重试，4s 超时即弃）会失败一次；
        #   失败（非 no_captcha）时短歇后重试一轮，避免卡死瞬点丢弹窗。
        for attempt in (1, 2):
            ok, detail = solve_v7(hwnd, gateway=gateway)
            if ok:
                if verbose:
                    print(f"  验证码 V7 直解成功 答案={detail.get('answer')}", flush=True)
                return True
            if detail.get("reason") == "no_captcha":
                return False
            if attempt == 1:
                if verbose:
                    print(f"  验证码 V7 首轮未解成功({detail.get('reason')})，1.5s 后重试...",
                          flush=True)
                _sleep_stoppable(1.5)
        if verbose:
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


def _fast_foot_click(map_name: str, gx: int, gy: int, pid: int = None,
                     background: bool = True, verbose: bool = False) -> dict:
    """轻量寻路点击：换算像素 → 单发左键 → 立即返回（走路通道专用）。

    ★2026-08-30 用户定案："打开地图点击坐标之后马上关闭地图，不要到位置再关闭"——
      旧实现 `_walk_to` 走的是地图包 `_click_background`：点击后 `sleep(2.0)寻路 +
      sleep(2.0)到达 + sleep(0.5)` ≈ **4.7s 阻塞等待**，期间大地图一直开着，
      等到位时才由 `_close_big_map` 关图再 CALL——白白耽误 CALL 时机。
      本函数：TAB 开图（由调用方预同步保证状态）→ 单发左键寻路 → 立即返回，
      调用方随即关图并启动"边走边CALL"——走路的同时图已关闭，CALL 提前开始。
      寻路由游戏侧寻路系统完成，无需本地等待到达；到达判定由 _walk_and_call
      的"移动检测"轮询接管（命中即 CALL，未中就边走边补）。
    :return: {"ok": True, "message": ...} 或 {"ok": False, "message": ...}
    """
    try:
        from library.common.win_utils import locate_game_window as _lgw
        from library.map_packs.DHW import _press_tab as _ptab
        import ctypes as _ct
        from ctypes import wintypes as _wt
    except Exception as e:
        return {"ok": False, "message": f"轻量寻路点击导入失败: {e}"}
    pid = pid or _get_bound_pid()
    if pid <= 0:
        return {"ok": False, "message": "未绑定游戏 PID，无法走路"}
    # 与 _walk_to 一致的 UI 避让（防点击被 UI 面板遮挡）
    try:
        from core.map_ui_block import map_coord_ui_avoid
        _gx, _gy, _ui = map_coord_ui_avoid(map_name, int(gx), int(gy))
        if (_gx, _gy) != (int(gx), int(gy)):
            if verbose:
                print(f"  [UI避让] {map_name} ({gx},{gy}) → ({_gx:.0f},{_gy:.0f})（{_ui}）")
            gx, gy = int(_gx), int(_gy)
    except Exception:
        pass
    hwnd, _title = _lgw(pid, verbose=False)
    if not hwnd:
        return {"ok": False, "message": f"未找到游戏窗口 (PID={pid})"}
    # ★ 2026-08-30 修复：像素换算必须与 _walk_to 同源——不同地图包/校准图
    #   的 origin/scale 各不相同（DHW:359,199/2.36，CSC:393,200/1.34 等）。
    #   旧版硬编码 DHW.game_to_pixel 会把点算到错误位置导致走路未启动。取
    #   对应地图包模块的 game_to_pixel；无地图包则用校准数据 origin/scale。
    _gtp = None
    _walker_mod = _get_map_walker(map_name)
    if _walker_mod is not None:
        try:
            _mod = __import__(f"library.map_packs.{_walker_mod.__name__.rsplit('.', 1)[-1]}",
                              fromlist=["game_to_pixel"])
            _gtp = getattr(_mod, "game_to_pixel", None)
        except Exception:
            _gtp = None
    if _gtp is None:
        calib = _load_calibration(map_name)
        if calib is not None:
            _ox, _oy = calib["origin"]
            _sx, _sy = calib["scale"]
            _gtp = lambda ggx, ggy: (_ox + int(ggx) * _sx, _oy + int(ggy) * _sy)  # noqa: E731
    if _gtp is None:
        return {"ok": False, "message": f"地图 '{map_name}' 无地图包且无校准数据"}
    px, py = _gtp(int(gx), int(gy))
    _ptab(hwnd, background=background)   # 开图
    # 单发左键寻路（后台 PostMessage，不抢焦点、光标不动）
    user32 = _ct.windll.user32
    lp = (int(py) << 16) | (int(px) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0200, 0, lp)                  # WM_MOUSEMOVE
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0201, 1, lp)                  # WM_LBUTTONDOWN
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0202, 0, lp)                  # WM_LBUTTONUP
    # ★ 2026-08-30 修复：点击后给游戏 ~0.6s 落地窗处理寻路点击，再让调用方 TAB 关图。
    #   旧版点击后立即返回→外面马上 TAB 关图，两条消息几乎同时到达，TAB 会冲掉
    #   刚发出的寻路点击（实测第一段走路"6s 未启动"）。0.6s 仅为处理点击的窗口，
    #   远小于原地图包 4.7s（2s寻路+2s到达+0.5s），仍大幅提前关图与 CALL。
    time.sleep(0.6)
    # 立即返回，不等寻路/到达（调用方随即关图 + 边走边CALL 接管）
    if verbose:
        print(f"  → 轻量寻路点击 {map_name} ({gx},{gy}) → 像素({px:.1f},{py:.1f})"
              f"（点完提前关图开CALL）", flush=True)
    return {"ok": True, "message": f"轻量寻路点击 ({gx},{gy})"}


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
    chat_gw = _CHAT_GW or gateway   # 2026-08-29 分离网关：公告走独立聊天网关
    r = _http_json(chat_gw, "/api/net/recvall", None, timeout=30.0)
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


def _match_map_in_text(chunk: str, extra_maps: List[str] = None) -> Optional[str]:
    """从地点片段里挑出已知地图名（最长匹配优先）。

    二十八星君公告的地点后面常跟"附近/一带"等修饰，且不保证在监控轮换表里。
    这里对全部已知地图名（调用方监控表 + 地图包表 + MAP_ID_TO_NAME + 默认落点）
    取最长命中，天然剔除"东海湾附近搜寻有仙缘之人"这类尾巴。
    """
    cands = list(extra_maps or []) + list(_MAP_MODULE_NAMES) \
        + list(MAP_ID_TO_NAME.values()) + list(DEFAULT_MAP_CENTER)
    hit = None
    for mp in cands:
        # 2026-08-29 用户定案：城镇枢纽图（长安/长安城）永不刷 BOSS，
        # 即便已注册地图包也不作为跨图目标解析出来。
        if mp and mp not in NO_BOSS_CITY_MAPS and mp in chunk \
                and (hit is None or len(mp) > len(hit)):
            hit = mp
    return hit



def _pick_boss_name(boss_names) -> str:
    """从命中集合里挑【优先级最高】的 BOSS 名（同级按名称稳定排序）。

    2026-08-29 修复：旧逻辑 sorted(...)[0] 是按字典序取，
    “妖魔头领气得正在傲来国寻衅闹事”会同时命中「妖魔」与「妖魔头领」，
    字典序取到「妖魔」(P5 杂鱼) → 该公告被 LOW_PRIORITY_BOSSES 过滤，
    妖魔头领公告永远不触发跨图。改为按 _boss_priority 取最高优先级。
    """
    return sorted(boss_names, key=lambda b: (
        99 if _boss_priority(b) is None else _boss_priority(b), b))[0]



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
    # 0.5) 二十八星君公告专用锚点（2026-08-29 新增）
    #   句式："玉皇大帝特派二十八星君之一的娄金狗到东海湾附近……"
    #   星君名（娄金狗）与地点（东海湾）都在句中，但地点可能不在监控轮换表里，
    #   通用解析器（"文本里出现了哪个监控地图名"）会整条漏掉 → 专用正则提
    #   [星君名] + [地点]，命中即返回。
    #   注意：这里必须按调用方传入的 target_bosses 过滤——外层查财神爷公告时
    #   传的是 [三界财神爷]，若不加过滤会把星君公告误判成财神爷公告。
    m_sl = _STAR_LORD_SPAWN_RE.search(t)
    if m_sl:
        sl_name = (m_sl.group(1) or "").strip()
        sl_map = _match_map_in_text(m_sl.group(2) or "", monitored_maps)
        # 星君名可能夹颜色码/语气词，兜底：句中出现的二十八星宿具体名
        if sl_name not in _28_STAR_BOSSES:
            for _s in _28_STAR_BOSSES:
                if _s in t:
                    sl_name = _s
                    break
        if sl_map and sl_name in set(target_bosses):
            return {"boss": sl_name, "map": sl_map, "maps": [sl_map],
                    "text": t, "map_source": "starlord_notice"}

    # 1) 展开公告中的 BOSS 关键词为实体名集合
    for kw, aliases in _BOSS_ALIASES.items():
        if kw in t:
            boss_names.update(aliases)
    # 直接提到的目标 BOSS 名（星宿具体名等）
    for b in target_bosses:
        if b and b in t:
            boss_names.add(b)
    # 1b) 后缀匹配（2026-08-29）：公告里的 BOSS 全名前缀不定
    #     （"避世头领""净神头领"…），只有后缀"头领"恒定，全名进不了白名单。
    #     按后缀抽 token 单独收集，下方跳过白名单过滤、改由 _boss_priority 校验。
    suffix_names = set()
    for suf, _rx in _SUFFIX_TOKEN_RES.items():
        for m_suf in _rx.finditer(t):
            tok = (m_suf.group(1) or "").strip()
            if tok:
                suffix_names.add(tok)
    if not boss_names and not suffix_names:
        return None
    # 过滤到目标集
    tgt = set(target_bosses)
    boss_names = {b for b in boss_names if b in tgt}
    # 后缀名按定义不在白名单里 → 靠后缀规则命中即放行
    boss_names |= {b for b in suffix_names if _boss_priority(b) is not None}
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
    # 有地图包的图一律可定位（即使不在监控轮换表里，也能跨图去打）。
    # 2026-08-29 用户定案：长安/长安城 是城镇枢纽、永不刷 BOSS，虽注册地图包
    # 也不作为跨图目标（否则脚本会跑到城里空转找怪）。
    for extra in _MAP_MODULE_NAMES:
        if extra in NO_BOSS_CITY_MAPS:
            continue
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
        return {"boss": _pick_boss_name(boss_names), "map": fallback[0],
                "maps": fallback, "text": t, "map_source": "spawn_table"}
    boss = _pick_boss_name(boss_names)
    # 2026-08-29 修复：多图公告（系统：妖魔在 A、B、C 出没）原先永远取 monitored_maps
    # 顺序第一张（东海湾），导致多图事件永远只去同一个图。改为随机抽取一张作为
    # 首次跨图目标，并在返回结果里标记 force_cross——多图事件属于系统召唤，
    # 即使是妖魔/鬼怪等 LOW_PRIORITY 也应触发跨图（否则公告等于没意义）。
    if len(maps_found) > 1:
        chosen_map = random.choice(maps_found)
        force_cross = True
    else:
        chosen_map = maps_found[0]
        force_cross = False
    return {"boss": boss, "map": chosen_map, "maps": maps_found,
            "text": t, "map_source": "notice", "force_cross": force_cross}


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
    """扫描 tp.场景.场景人物 + tp.临时Npc，返回匹配目标 BOSS 的候选列表。

    ★2026-08-30 瘦身（方案A，用户实锤"存活时长∝扫描频率倒数"的累积注入模型）：
      Lua 侧按白名单先过滤，只输出命中实体（旧版把全场 80+ 实体全部拼串输出，
      Python 再过滤——实体密集图单次注入体积巨大）。另设输出条数上限防单图过载。
      行为保持：Lua 用宽松匹配（exact全等 / substring / 后缀），Python 侧仍做
      原有严格判定兜底，不会漏。"""
    tlist_lit = _lua_str_list(list(target_bosses))
    exact_lit = _lua_str_list(list(exact_match))
    suf_lit = _lua_str_list(list(SUFFIX_MATCH_BOSSES))
    code = f'''
-- 2026-08-29 23:40 根因修复（lua51 not enough memory 直杀 exit）：扫描前触发
-- 增量式 GC，释放跨图/脚本装载堆起的 Lua 内存，缓解 lua51 分配失败退出。
collectgarbage("collect", 0)
local tlist = {tlist_lit}
local exact = {exact_lit}
local sufs  = {suf_lit}
local function hit(name)
  for _, b in ipairs(tlist) do
    if b ~= "" then
      local eq = false
      for _, e in ipairs(exact) do if e == b then eq = true break end end
      if eq then
        if name == b then return true end
      else
        if string.find(name, b, 1, true) then return true end
      end
    end
  end
  for _, s in ipairs(sufs) do
    if s ~= "" and #name >= #s and name:sub(-#s) == s then return true end
  end
  return false
end
local out = {{}}
local scan_n = 0
local function scan(tbl, src)
  if type(tbl) ~= "table" then return end
  for id, u in pairs(tbl) do
    if type(u) == "table" then
      local name = tostring(u.名称 or u.名字 or "")
      if hit(name) then
        -- 2026-08-30 上限 30 条：防白名单密集图（长寿郊外 80+ 新冠）单次注入过载
        if scan_n >= 30 then return end
        scan_n = scan_n + 1
        local model = tostring(u.模型 or u.模型名 or "")
        -- 2026-08-28 量纲修复：格子x/格子y 本身是网格；兜底字段 u.x/u.y 是内部像素(×20)，在源头÷20
        local gx = tonumber(u.格子x) or ((tonumber(u.x) or -20) / 20)
        local gy = tonumber(u.格子y) or ((tonumber(u.y) or -20) / 20)
        local bsid = tostring(u.标识 or "")
        out[#out+1] = string.format("%s|%s|%s|%s|%s|%s|%s",
          tostring(id), name, gx, gy, model, src, bsid)
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
        hit = None
        for boss in target_bosses:
            matched = (name == boss) if boss in exact_match else ((boss in name) or (name == boss))
            if matched:
                hit = boss
                break
        if hit is None:
            # 后缀匹配（2026-08-29）：BOSS 全名前缀不固定（"避世头领""净神头领"…），
            # 只有后缀"头领"恒定。若按完整名进白名单，不同前缀的实体会被整体漏掉，
            # 这里改为 endswith 命中，不再要求全名登记。
            for suf in SUFFIX_MATCH_BOSSES:
                if name.endswith(suf):
                    hit = suf
                    break
        if hit is not None:
            try:
                # 2026-08-28 A4 修复：格子x/格子y 可能是浮点（如 "10.5"），
                # 旧 int("10.5") 直接 ValueError → 实体被静默丢掉
                bgx, bgy = int(float(gx)), int(float(gy))
                # 2026-08-28 守门：实体兜底字段 u.x/u.y 可能是内部像素坐标，
                # >网格上限×15 判为像素（内部=网格×20）→ ÷20 转网格，否则环带瞬移会出界。
                # 2026-08-30 二修：老逻辑拿"边界本身/全局 400"当阈值，会把贴边/略超边的
                #   合法格坐标（大唐国境 349>344、大唐境外 533、y330 等）误判成像素 ÷20
                #   → 东/南半图怪物定位全错、反复落错点空转（实测 38s 等待根因之一）。
                _bnd = _load_map_bounds(_cur_map_name(gateway) or "")
                _lim = (max(_bnd) * 15.0) if _bnd else GRID_SANITY_MAX
                if abs(bgx) > _lim or abs(bgy) > _lim:
                    bgx, bgy = round(bgx / 20.0), round(bgy / 20.0)
                    logger.warning(f"BOSS 坐标守门: {name} 原始=({gx},{gy}) → ({bgx},{bgy}) [像素→网格÷20]")
                cands.append({
                    "id": uid, "name": name,
                    "gx": bgx, "gy": bgy, "model": model,
                    "src": src, "boss_pattern": hit,
                    "bsid": bsid,
                })
            except ValueError:
                pass
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
if not u or type(u) ~= "table" then _G.__out = "NOTFOUND"; return end
-- 2026-08-29 类型守卫：uid 兜底路径取到的槽位可能是数字/字符串残值，
-- 非法实体喂给 事件开始 会触发引擎原生错误，先验再 CALL
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


def _lua_str_list(items) -> str:
    """把 Python 字符串列表序列化成 Lua table 字面量（转义双引号/反斜杠）。"""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    return "{" + ", ".join(f'"{esc(str(x))}"' for x in items) + "}"


def call_dialog_battle(gateway: str, keywords: List[str]) -> Tuple[bool, str]:
    """在对话栏选项中匹配战斗关键词并 CALL 事件解析(跳转链接)。

    黑名单优先：含“你认错人了”等拒绝措辞的选项绝不点
    （2026-08-27 星官实测：选错=拒绝赐福，白跑一趟）。

    ★ 2026-08-29 原子化重写（堵 0xC0000005 崩溃）：旧版“chunk1 读链接 →
    Python 匹配 → chunk2 事件解析”两次 Lua 往返之间存在 TOCTOU——边走边CALL
    节拍密集时对话栏可能在间隙被关掉/重渲染，失效链接喂给 事件解析 会触发
    引擎原生致命错误（this arg is not a userdata! → 0xC0000005，crash 命中
    lua51+0x339d）。pcall 兜不住访问违例，唯一正解是让坏调用永不发生：
    “读选项→黑名单→关键词→取链接→事件解析”全部并入同一个 Lua chunk，
    原子执行零间隙。"""
    deny_lit = _lua_str_list(_BATTLE_DENY_OPTIONS)
    kw_lit = _lua_str_list(keywords)
    soft_lit = _lua_str_list(["杀", "灭", "打", "战", "应战", "教训",
                              "领教", "收拾", "降服", "制服",
                              "消毒", "口罩"])   # 2026-08-30 补：新冠实测选项 酒精消毒/戴上口罩
    code = f'''
local deny = {deny_lit}
local kws = {kw_lit}
local dlg = tp.窗口.对话栏
if not (dlg and dlg.可视) then _G.__out = "false|NODLG|"; return end
local opts = dlg.选项
if type(opts) ~= "table" then _G.__out = "false|NOOPTS|"; return end
local function opt_text(o)
  return tostring(o.基本内容 or "") .. "|" .. tostring(o.文字 or o.标签 or "")
    .. "|" .. tostring(o.跳转链接 or "")
end
local function in_list(text, list)
  for _, w in ipairs(list) do
    if w ~= "" and string.find(text, w, 1, true) then return true end
  end
  return false
end
-- ① 先按选项顺序找第一个非黑名单、命中关键词的选项（保持旧版优先级语义）
local hit_i, hit_text = nil, nil
for i = 1, 20 do
  local o = opts[i]
  if type(o) ~= "table" then break end
  local text = opt_text(o)
  if in_list(text, kws) and not in_list(text, deny) then
    hit_i, hit_text = i, tostring(o.基本内容 or "")
    break
  end
end
-- ①b 2026-08-29 宽松兜底：具体名无词条（如"新型冠状病毒"尚无实测文案）时，
--     选第一个 含战斗动作字 + 非黑名单 + 有跳转链接 的选项，保证能开战。
if not hit_i then
  local soft_kw = {soft_lit}
  for i = 1, 20 do
    local o = opts[i]
    if type(o) ~= "table" then break end
    local text = opt_text(o)
    if tostring(o.跳转链接 or "") ~= "" and not in_list(text, deny) then
      for _, w in ipairs(soft_kw) do
        if w ~= "" and string.find(text, w, 1, true) then
          hit_i, hit_text = i, tostring(o.基本内容 or "")
          break
        end
      end
    end
    if hit_i then break end
  end
end
if not hit_i then _G.__out = "false|NOMATCH|"; return end
-- ② 原子内二次确认：选项仍挂在当前对话栏上，链接非空才允许喂给引擎
local link = tostring(opts[hit_i].跳转链接 or "")
if link == "" then _G.__out = "false|EMPTYLINK|" .. hit_text; return end
local ok, ret = pcall(function() return dlg:事件解析(link) end)
_G.__out = tostring(ok) .. "|" .. hit_text .. "|" .. tostring(ret or "")
'''
    raw = _lua(gateway, code)
    parts = raw.split("|", 2)
    ok = parts[0] == "true" if parts else False
    tag = parts[1] if len(parts) > 1 else ""
    detail = parts[2] if len(parts) > 2 else ""
    return ok, f"选项[{tag}] ok={ok} {detail}".strip()


def _call_and_fight(gateway: str, boss: dict, keywords: List[str]):
    """★2026-09-01 柔和 CALL（用户定案：CALL 太快会崩，BOSS 同理）：
    拆为两步 Lua + 中间 2s 装载等待，替代旧"单次原子 Lua 连续
    查战斗→CALL→读对话→点击"（CALL 后 0 等待撞引擎装载未就绪 →
    this arg is not a userdata → 崩游戏，00:47 整夜启动 8s 即崩实锤）。

    第一步（call chunk）：查战斗 + 找实体 + CALL 事件开始，返回就绪状态。
    第二步（dlg chunk）：等待 2s 后读对话 + 匹配 + 事件解析点击。

    :return: ("battle", None) 已在战斗中 / ("gone", None) 目标消失 /
             ("clicked", text) 已点战斗选项（等战斗态确认） /
             ("nodlg", None) 对话未弹出（可短等重试） / ("miss", info) 无匹配可点
    """
    uid_lit = (str(boss.get("id") or "")).replace('"', "")
    bsid_lit = (str(boss.get("bsid") or "")).replace('"', "")
    deny_lit = _lua_str_list(_BATTLE_DENY_OPTIONS)
    kw_lit = _lua_str_list(keywords)
    soft_lit = _lua_str_list(["杀", "灭", "打", "战", "应战", "教训",
                              "领教", "收拾", "降服", "制服",
                              "消毒", "口罩"])

    # ---- 第一步：查战斗 + CALL 事件开始（只 CALL，不读对话）----
    call_code = f'''
local u = nil
if tp.战斗中 then _G.__out = "battle"; return end
if "{bsid_lit}" ~= "" then
  local pools = {{tp.场景.场景人物, tp.临时Npc}}
  for _, t in ipairs(pools) do
    if type(t) == "table" then
      for _, e in pairs(t) do
        if type(e) == "table" and tostring(e.标识 or "") == "{bsid_lit}" then u = e; break end
      end
      if u then break end
    end
  end
end
if not u and "{uid_lit}" ~= "" then
  local n = tonumber("{uid_lit}")
  local t = tp.场景.场景人物 or {{}}
  if n then u = t[n] end
  if not u then u = t["{uid_lit}"] or (tp.临时Npc or {{}})["{uid_lit}"] end
end
if not u or type(u) ~= "table" then _G.__out = "gone"; return end
local mt = getmetatable(u)
local ev = (mt and mt.__index and mt.__index.事件开始) or u["事件开始"]
if type(ev) ~= "function" then _G.__out = "miss|nofn"; return end
local okc = pcall(function() return ev(u) end)
-- CALL 后不立即读对话：交给第二步（Python 侧等 2s 装载，柔和防崩）
_G.__out = "called"
'''
    raw = _lua(gateway, call_code)
    if raw == "battle":
        return "battle", None
    if raw == "gone":
        return "gone", None
    if raw == "miss|nofn":
        return "miss", "nofn"

    # ---- 柔和呼吸：CALL 后等引擎装载对话脚本（2026-09-01 用户定案 2s；0s 崩）----
    time.sleep(2.0)

    # ---- 第二步：读对话 + 匹配 + 点击（无 CALL，纯读+点）----
    dlg_code = f'''
local kws = {kw_lit}
local deny = {deny_lit}
local soft = {soft_lit}
local dlg = tp.窗口.对话栏
if not (dlg and dlg.可视) then _G.__out = "nodlg"; return end
local opts = dlg.选项
local function opt_text(o)
  return tostring(o.基本内容 or "") .. "|" .. tostring(o.文字 or o.标签 or "") .. "|" .. tostring(o.跳转链接 or "")
end
local function in_list(text, list)
  for _, w in ipairs(list) do
    if w ~= "" and string.find(text, w, 1, true) then return true end
  end
  return false
end
local hit_i = nil
for i = 1, 20 do
  local o = opts[i]
  if type(o) ~= "table" then break end
  local text = opt_text(o)
  if in_list(text, kws) and not in_list(text, deny) then hit_i = i; break end
end
if not hit_i then
  for i = 1, 20 do
    local o = opts[i]
    if type(o) ~= "table" then break end
    local text = opt_text(o)
    if tostring(o.跳转链接 or "") ~= "" and not in_list(text, deny) then
      local sf = false
      for _, w in ipairs(soft) do
        if string.find(text, w, 1, true) then sf = true; break end
      end
      if sf then hit_i = i; break end
    end
  end
end
if not hit_i then _G.__out = "miss|nomatch"; return end
local hit = opts[hit_i]
local link = tostring(hit.跳转链接 or "")
if link == "" then _G.__out = "miss|emptylink"; return end
local okr, ret = pcall(function() return dlg:事件解析(link) end)
_G.__out = (okr and "clicked|" or "miss|execfail|") .. tostring(hit.基本内容 or "")
'''
    raw2 = _lua(gateway, dlg_code)
    if raw2 == "nodlg":
        return "nodlg", None
    if raw2.startswith("clicked|"):
        return "clicked", raw2.split("|", 1)[1]
    return "miss", raw2 or ""


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
    # 后缀匹配（2026-08-29）：实体名前缀不定（"避世头领""净神头领"…），
    # 只有后缀固定 → 追加该后缀的代表类别，保证专用战斗文案排在最前
    # （如"避世头领"拿到 妖魔头领 的"让我来收拾你"）。
    for suf, cat in BOSS_SUFFIX_CATEGORY.items():
        if boss_name != suf and boss_name.endswith(suf):
            names.append(cat)
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


def _wait_battle_start(gateway: str, timeout: float = 3.0, poll: float = 0.5) -> bool:
    """点了战斗选项后，等待 tp.战斗中 变 true（真进战斗的权威验证）。

    pcall(事件解析) 返回 ok 不代表进战斗（2026-08-27 实测假击杀 14 连：
    pcall ok=true 但战斗根本没触发）。必须以 tp.战斗中 为准。
    2026-09-01 柔和轮：poll 0.25 → 0.5（降低战斗态轮询 Lua 密度，防引擎
    装载期高频往返触发崩溃；真触发时战斗态 1~2s 内出现，0.5s 粒度足够）。
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


# hop 落地冷却（2026-08-29，治标双保险）：地图名刷新 ≠ 场景重建完成，
# 立即扫描/事件 Lua 会撞 "this arg is not a userdata!" 致命分支
#（08:16/08:22 两场事故时序实锤：hop 后 0.3~0.5s 内高频 Lua 调用触发）。
# 根治靠 gateway fatal_guard（运行时补丁），这里只兜底。
HOP_SETTLE_S = 0.9   # 2026-08-30 压缩：1.5→0.9（跨图落地静默窗，链后续 teleport 自带生效）


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
                # 2026-08-29 hop 后冷却（治标双保险）：落地静默等场景重建完
                _sleep_stoppable(HOP_SETTLE_S)
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
            if r == "miss":
                # ★2026-09-01 用户定案：读到对话但无战斗选项 = 被他人锁定 →
                #   立即放弃本怪（不再继续走路/重CALL浪费时间），交给外层换目标
                if verbose:
                    print(f"  ! 边走边CALL miss（{time.time()-t0:.1f}s）→ 锁定/无战斗选项，"
                          f"立即放弃本怪", flush=True)
                return "miss"
            if r == "fail" and _dialog_is_too_far(gateway):
                # far 信号：超距确认框 → 继续走（靠近后自动命中）
                pass
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
             "walked" 走完仍未中 / "gone" 目标消失 / "miss" 锁定/无战斗选项（立即放弃）/
             "teleported" 瞬移兜底 / "far" 全部手段失败
    """
    rg = _role_grid(gateway)
    if rg is not None and _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE:
        return "close"
    _d0 = _grid_dist(rg, boss_gx, boss_gy) if rg else 99.0

    # ★ 2026-08-30 用户定案：大唐境外禁用走路通道，全瞬移——图太大，跨图走路动辄
    #   几十秒纯浪费。命中列表直接跳过下方整段"真实走路"，落到瞬移环带兜底。
    #   ★ 2026-08-30 提速（用户：速度优先）：目标过远（>TELEPORT_FAST_DIST）同样
    #   直接瞬移环带贴近——"战斗结束→只CALL一次最近BOSS→失败马上瞬移/走路"。
    if cur_map in _TELEPORT_ONLY_MAPS or _d0 > TELEPORT_FAST_DIST:
        if verbose and cur_map not in _TELEPORT_ONLY_MAPS:
            print(f"  → 距离 {_d0:.0f} 格过远（>TELEPORT_FAST_DIST={TELEPORT_FAST_DIST:.0f}），"
                  f"不走路直接瞬移贴近 BOSS", flush=True)
    # 1) 有地图包或校准数据 → 真实走路（拟人优先，防举报）
    elif _get_map_walker(cur_map) or _load_calibration(cur_map):
        # lazy-bind：未绑定 PID 时现场绑定（farm 主流程已绑，独立调用/重连后兜底），
        # 否则走路必然报"未绑定 PID"退化成瞬移（2026-08-28 实测暴露）。
        if _get_bound_pid() <= 0:
            _ensure_walker_bound(gateway, verbose=verbose)
        dist0 = _grid_dist(rg, boss_gx, boss_gy) if rg else 30.0
        rh = int(rg[0]) if rg is not None else 0
        rv = int(rg[1]) if rg is not None else 0

        def _walk_leg(tx: int, ty: int, label: str):
            """单段"走路 + 启动门控 + 边走边CALL"。返回走完仍否未中（供二次走路）。
            :return: "ok_hit" 命中战斗 / "gone" 目标消失 / "ok_miss" 走完未中（可二次走）/
                     "no_walk" 走路未启动（转瞬移）
            """
            if verbose:
                _d = _grid_dist((rh, rv), tx, ty) if rg is not None else -1.0
                _est = max(3.0, _d / WALK_SPEED_GRID_SEC + WALK_TIME_MARGIN)
                print(f"  → {label} {cur_map} ({tx},{ty})（距落点≈{_d:.0f}格，"
                      f"边走边CALL上限 {_est:.0f}s）", flush=True)
            # ★ 状态感知预同步：地图/校准走路第一步是 TAB 开图，开着时先 TAB 关掉
            try:
                from library.common.win_utils import locate_game_window as _lgw
                _pid = _get_bound_pid()
                _hwnd = 0
                if _pid > 0:
                    _hwnd, _ = _lgw(_pid, verbose=False)
                if _hwnd:
                    _press_tab_if(_hwnd, False, gateway, verbose)
            except Exception:
                pass
            walk_res = _fast_foot_click(cur_map, tx, ty, background=walk_background,
                                        verbose=verbose)
            if not walk_res.get("ok"):
                if verbose:
                    print(f"  ! {label}未到位（{walk_res.get('message')}）", flush=True)
                return "no_walk"
            # ★ 点完目标坐标立即关大地图，马上 CALL
            _close_big_map(verbose, gateway=gateway)
            # 移动启动门控：点击没生效（角色完全没动）→ 转瞬移兜底
            # ★ 2026-08-30 防定身：点击有时会落在野怪/召唤兽 NPC 上（弹出"我来瞧瞧
            #   你的啥"之类对话栏），角色被对话定身原地不动 → 每拍先关掉杂散对话，
            #   若连续 2 拍仍无位移直接判 no_walk（不等满 6s，提前交瞬移，不傻站）。
            t0s = time.time()
            base = _role_grid(gateway)
            moving = False
            _still_ticks = 0
            while time.time() - t0s < WALK_START_TIMEOUT:
                rg2 = _role_grid(gateway)
                if rg2 and base and _grid_dist(rg2, base[0], base[1]) > 0.5:
                    moving = True
                    break
                if rg2 and base is None:
                    base = rg2
                _still_ticks += 1
                if _still_ticks >= 2 and base is not None:
                    # 两拍坐标都没动 → 先清掉可能的杂散对话（点击落 NPC 定身）
                    try:
                        _close_dialog(gateway)
                    except Exception:
                        pass
                    if _still_ticks >= 3:
                        break
                # 启动探测期不空等——每拍顺手 CALL 一次
                if call_fn is not None:
                    r = call_fn()
                    if r == "battle":
                        return "ok_hit"
                    if r == "gone":
                        return "gone"
                    if r == "miss":
                        return "miss"   # 2026-09-01：锁定 → 立即放弃
                time.sleep(0.5)
            if not moving:
                if verbose:
                    print(f"  ! {label}走路未启动（{WALK_START_TIMEOUT:.0f}s 内角色坐标无变化，"
                          f"点击没生效），转瞬移兜底", flush=True)
                return "no_walk"
            if call_fn is not None:
                # ★ 边走边CALL：每 WALK_CALL_INTERVAL 秒 CALL 一次，走完补 CALL 兜底
                r = _walk_and_call(gateway, boss_gx, boss_gy, dist0, verbose, call_fn)
                if r == "gone":
                    return "gone"
                if r == "miss":
                    return "miss"   # 2026-09-01：锁定/无战斗选项 → 立即放弃本怪
                return "ok_hit" if r == "walked_call_ok" else "ok_miss"
            # 兼容旧调用（无 call_fn）：按落点 ±WALK_ARRIVAL_BOX 轮询到位
            t0w = time.time()
            last_rg, last_move_t = base, time.time()
            while time.time() - t0w < WALK_ARRIVAL_TIMEOUT:
                rg3 = _role_grid(gateway)
                if rg3 is not None:
                    if _grid_dist(rg3, last_rg[0], last_rg[1]) > 0.3:
                        last_rg, last_move_t = rg3, time.time()
                    elif time.time() - last_move_t > WALK_STALL_TIMEOUT:
                        break
                    if _grid_dist(rg3, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE:
                        return "ok_hit"
                    if (abs(rg3[0] - tx) <= WALK_ARRIVAL_BOX
                            and abs(rg3[1] - ty) <= WALK_ARRIVAL_BOX):
                        return "ok_miss"
                time.sleep(0.4)
            return "ok_miss"

        # ★ 2026-08-30 用户定案：第一段落点 = 怪周边 10±5 格随机提前就位点
        #   （提前就位即可 CALL，无需精确站上怪坐标；±5 容错避免每次都同一点）
        lead = random.uniform(WALK_APPROACH_LEAD_MIN, WALK_APPROACH_LEAD_MAX)
        ang = random.uniform(0.0, _math.tau)
        lx = max(0, int(round(boss_gx + _math.cos(ang) * lead)))
        ly = max(0, int(round(boss_gy + _math.sin(ang) * lead)))
        res = _walk_leg(lx, ly, "提前就位点走路")
        if res == "ok_hit":
            return "walked_call_ok"
        if res == "gone":
            return "gone"
        if res == "miss":
            return "miss"   # 2026-09-01：锁定 → 立即放弃
        # 提前点未中（ok_miss / no_walk 但走路可用）→ ★2026-08-30 二次精确走怪坐标±2
        if _get_map_walker(cur_map) or _load_calibration(cur_map):
            jx = max(0, int(boss_gx) + random.randint(-2, 2))
            jy = max(0, int(boss_gy) + random.randint(-2, 2))
            res2 = _walk_leg(jx, jy, "精确坐标走路")
            if res2 == "ok_hit":
                return "walked_call_ok"
            if res2 == "gone":
                return "gone"
            if res2 == "miss":
                return "miss"   # 2026-09-01：锁定 → 立即放弃

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
        # ★2026-08-30 瞬移冷却（用户实锤："走路没到位会在目标范围瞬移2次"，两次
        #   间隔仅 0.5s，连发瞬移是崩溃高危点）：瞬移后至少等 TELEPORT_GAP 再落下
        #   一次（坐标落地稳定 + 减少连发 Lua/同步包冲击）。
        last_tp_t = time.time()
        # 2026-08-30 提速：落地稳定由"轮询坐标变化"改为**固定短等 0.9s**——坐标
        # 轮询每拍都是 1 次节流 Lua（每拍 ≥1s），3~4 拍就把落地后的攻击拖到 3~4s；
        # 瞬移落地本质是空间跳变，0.9s 足够同步包/坐标刷新完成（无需逐拍验证静止）。
        time.sleep(0.9)
        rg = _role_grid(gateway)
        if rg is None or _grid_dist(rg, boss_gx, boss_gy) <= APPROACH_GRID_DISTANCE + 1:
            # ★ 2026-08-30 提速（用户：瞬移后应马上攻击）：落地后已在可 CALL 距离
            #   （环带 2~4 格 ≈ 命中区），立即试 CALL 一次——命中当场进战斗，
            #   不再等外层"补 CALL 兜底"白跑一轮；未中则按 teleported 返回交兜底。
            if call_fn is not None:
                _rr = call_fn()
                if _rr == "battle":
                    return "walked_call_ok"
                if _rr == "gone":
                    return "gone"
                if _rr == "miss":
                    # ★2026-09-01：锁定/无战斗选项 → 立即放弃本怪（不再补CALL/重瞬移）
                    if verbose:
                        print("  ! 瞬移落地 CALL miss → 锁定/无战斗选项，放弃本怪", flush=True)
                    return "miss"
            return "teleported"
        # 需要第二发瞬移时，也强制冷却满 TELEPORT_GAP（2026-08-30 防连发）
        _gap = TELEPORT_GAP - (time.time() - last_tp_t)
        if _gap > 0:
            time.sleep(_gap)
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
         每 WALK_CALL_INTERVAL(1.5s) CALL 一次，超时上限=距离/预计走路速度+余量，
         走完仍未中 → 落点补一次 CALL 兜底；接近即可命中，无需精确站上坐标；
      3) 走路不可用/未启动/走完仍超距 → 瞬移环带拉近（approach 内部）→ 落地补 CALL。
    CALL 成功立即进战斗，整个移动链（走路→瞬移）都在 _approach_boss 内一次完成。
    """
    moves = 0

    # ★ 2026-08-30 用户定案：顶级公告（财神/星宿/头领）优先跨图——本图杂鱼的
    #   第一次 CALL 不拖延跨图。主循环已设置 _TOP_PIN_MAP（指向他图），直接中止。
    if _TOP_PIN_MAP and not _map_same(_TOP_PIN_MAP, cur_map):
        return {"ok": False, "reason": "abort_top_ann",
                "msg": f"顶级公告优先，先跨图 → {_TOP_PIN_MAP}"}
    global _FARM_START_TS
    _FARM_START_TS = __tm.time()
    # ★2026-08-30 提速：上一场刚结束（结算动画窗口）→ 先等齐动画再开打，
    #   避免攻击请求落在动画窗口被引擎打回、反复 nodlg 重试白耗 ~8s。
    #   ★2026-09-01 再提速：需要走路/瞬移的目标（距离>15格）不在此处等——走路
    #   本身耗时 3.6~10s 必然覆盖结算动画，白等 1.6s。结算等待挪到下方"原地
    #   CALL"分支内，仅近距离目标保留（见 _d0 判定后）。
    _post_wait_ts = _POST_BATTLE_TS

    def _call_once() -> str:
        """单次完整 CALL 尝试。返回 "battle"/"gone"/"far"/"fail"。

        ★2026-09-01 用户定案：找不到/怪物战斗中就**立即换目标**，不做长重试。
        旧逻辑 nodlg 重试 3 次（每次等 1.5s）→ 一只被锁定的怪耗 ~5s+。现在：
        nodlg 只补 1 次（2s 装载后仍无对话框 = 这怪当前打不了，快速放弃）；
        miss（读到了对话但无战斗选项 = 被他人锁定）同样快速放弃，交外层换目标。"""
        global _BATTLE_START_TS
        for _t in range(2):
            st, dt = _call_and_fight(gateway, boss, battle_keywords)
            if st == "battle":
                _BATTLE_START_TS = __tm.time()
                return "battle"
            if st == "gone":
                return "gone"
            if st == "clicked":
                # ↔ 已点战斗选项：真进战斗以 tp.战斗中 为准（假击杀防御，见注释）
                if _wait_battle_start(gateway, timeout=3.0):
                    _BATTLE_START_TS = __tm.time()
                    if verbose:
                        print(f"    ⌛开战（farm入后 {__tm.time()-_FARM_START_TS:.1f}s）",
                              flush=True)
                    return "battle"
                close_dialog(gateway)
                if verbose:
                    print(f"  [CALL] 已点选项({dt or '?'})但未进战斗，立即放弃本怪", flush=True)
                return "far"
            if st == "nodlg":
                # 柔和：CALL 已等 2s 装载；补 1 次仍无对话框 = 打不了 → 快速放弃
                __tm.sleep(1.0)
                continue
            return "miss"   # 读到了对话但无战斗选项 = 被锁定 → 立即放弃换目标
        return "fail"

    # 1) 原地立即 CALL（怪就在面前 → 直接命中，不移动）
    # ★ 2026-08-30 用户：距离过远直接跳过原地 CALL（省超距弹窗/幽灵对话空转），
    #   交给下方移动（走路/瞬移）贴近后再 CALL。
    _rg0 = _role_grid(gateway)
    _d0 = _grid_dist(_rg0, boss["gx"], boss["gy"]) if _rg0 else 99.0
    if _d0 > CALL_SKIP_DIST:
        if verbose:
            print(f"  [CALL] 距离 {_d0:.0f} 格过远（>{CALL_SKIP_DIST:.0f}），不原地CALL，"
                  f"先移动过去", flush=True)
        r = "far"
    else:
        # ★2026-09-01 结算等待仅限"原地CALL"近距离目标（防首击打回）；
        #   走路/瞬移目标在上方入口已跳过（移动耗时覆盖结算动画）。
        _post_wait = _POST_BATTLE_SETTLE - (__tm.time() - _post_wait_ts)
        if _post_wait > 0 and _post_wait_ts > 0:
            if verbose:
                print(f"    ⏳ 战斗结算收尾等 {_post_wait:.1f}s（动画对齐，首击必中）",
                      flush=True)
            __tm.sleep(_post_wait)
        r = _call_once()
    if r == "battle":
        ended = _wait_battle_end(gateway, timeout=battle_timeout)
        if not ended:
            close_dialog(gateway)   # 战斗真结束 → 对话必然已收，跳过（省 1 个节流 Lua 位）
        return {"ok": True, "battle_ended": ended, "gap_s": _battle_gap_metric(ended),
                "msg": "call_ok", "attempts": 1, "approached": False}
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
        if not ended:
            close_dialog(gateway)   # 战斗真结束 → 对话必然已收，跳过（省 1 个节流 Lua 位）
        return {"ok": True, "battle_ended": ended, "gap_s": _battle_gap_metric(ended),
                "msg": "walk_call_ok", "attempts": 2, "approached": True}
    if mode == "gone":
        return {"ok": False, "reason": "gone", "msg": "目标已消失（走近途中）"}
    if mode == "miss":
        return {"ok": False, "reason": "no_battle_option",
                "msg": "怪物被他人锁定/战斗中（无战斗选项），立即放弃换目标"}
    if mode == "far":
        return {"ok": False, "reason": "unreachable", "msg": "走近失败仍超距"}

    # 3) 到位/瞬移落地后仍未中 → 最后补一次 CALL 兜底
    r = _call_once()
    if r == "battle":
        ended = _wait_battle_end(gateway, timeout=battle_timeout)
        if not ended:
            close_dialog(gateway)   # 战斗真结束 → 对话必然已收，跳过（省 1 个节流 Lua 位）
        return {"ok": True, "battle_ended": ended, "gap_s": _battle_gap_metric(ended),
                "msg": "final_call_ok", "attempts": 3, "approached": moves > 0}
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


# ============ 摄妖香 定时使用（2026-08-30 用户定案 A + 结果反查 + 成功重置） ============
#   需求：启动先确保身上有摄妖香BUFF；此后每 300 分钟补一次；
#   到点时在"战斗结束+结算对齐后、挑下一个目标前"暂停补香再继续。
#   实现：道具无 Lua 直接"使用"接口 → 打开 道具行囊 窗口，用 PostMessage 悬停+
#   窗口.道具行囊.提示文字 确定性定位"摄妖香"格子（无需猜坐标），然后右键使用；
#   用 数量-1 判定成功，未-1 视为"已生效/未命中"加固。
_XIANG_INTERVAL = 300 * 60          # 300 分钟
_XIANG_LAST_USE = 0.0
_XIANG_NEXT_TRY = 0.0               # 定位/使用失败后的下次重试时间戳（失败冷却）
_XIANG_RETRY_GAP = 180.0
# ★2026-08-30 摄妖香槽位校准：data\xiang_slot.json 存在则直接使用该客户区格子坐标
#   （一次性真实光标校准，覆盖笨重的网格扫描；未校准则退回网格扫描兜底）。
_XIANG_SLOT_FILE = os.path.join(_PROJECT_ROOT, "data", "xiang_slot.json")


def _xiang_slot_calibrated() -> Optional[tuple]:
    try:
        if not os.path.exists(_XIANG_SLOT_FILE):
            return None
        with open(_XIANG_SLOT_FILE, "r", encoding="utf-8") as _f:
            d = json.load(_f)
        cx, cy = int(d["cx"]), int(d["cy"])
        if cx > 0 and cy > 0:
            return cx, cy
    except Exception:
        pass
    return None

# 悬停扫描网格（背包内道具区）：5 列 × 9 行，格子步距 34px，起点=窗口内左上偏移
# （窗口中已有实测 x=80,y=140；内边距按经典 5 列背包经验值，(28,30) 内侧起点）
_XIANG_GRID_COLS = 5
_XIANG_GRID_ROWS = 9
_XIANG_CELL_STEP = 34
_XIANG_GRID_X0 = 28
_XIANG_GRID_Y0 = 30


def _xiang_count(gateway) -> Optional[int]:
    """读 背包里 摄妖香 的数量（tp.道具列表 中 名称==摄妖香 的 数量；无道具返回 None）。"""
    raw = _lua(gateway, r'''
local n = nil
for k, v in pairs(tp.道具列表 or {}) do
  if type(v) == "table" and tostring(v.名称 or "") == "摄妖香" then
    n = tonumber(v.数量) or 0
  end
end
_G.__out = tostring(n)
''')
    try:
        return int(float(str(raw)))
    except Exception:
        return None


def _xiang_open_bag(gateway) -> bool:
    """打开 道具行囊 窗口：**后台鼠标点背包图标**（用户 2026-09-01 定案：不用
    Lua CALL 开包，避免 CALL 崩溃风险；只 LUA 查开包状态）。返回是否成功打开。"""
    return _open_bag_by_icon(gateway)


def _xiang_close_bag(gateway) -> None:
    """关闭 道具行囊（关闭/关 方法兜底 + 可视=false）。"""
    _lua(gateway, r'''
local w = tp.窗口.道具行囊
if w then
  pcall(function()
    if type(w.关闭) == "function" then w:关闭()
    elseif type(w.关) == "function" then w:关()
    end
  end)
  w.可视 = false
end
''')


def _xiang_locate_hover(gateway) -> Optional[tuple]:
    """悬停扫描定位"摄妖香"格子客户区中心。
    PostMessage 移入候选格子 → 读 窗口.道具行囊.提示文字 → 含"摄妖香"即命中。
    :return: (cx, cy) 或 None（找不到/开包失败）
    """
    import ctypes as _ct
    hwnd = 0
    pid = _get_bound_pid()
    if pid > 0:
        from library.common.win_utils import locate_game_window as _l
        _h = _l(pid, verbose=False)
        hwnd = _h[0] if isinstance(_h, tuple) else _h
    if not hwnd:
        return None
    user32 = _ct.windll.user32
    # 窗口原点（道具行囊 x=80,y=140 为窗口原点绝对客户区坐标）
    ox, oy = 80, 140
    for r in range(_XIANG_GRID_ROWS):
        for c in range(_XIANG_GRID_COLS):
            cx = ox + _XIANG_GRID_X0 + c * _XIANG_CELL_STEP
            cy = oy + _XIANG_GRID_Y0 + r * _XIANG_CELL_STEP
            lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
            user32.PostMessageW(hwnd, 0x0200, 0, lp)   # WM_MOUSEMOVE 悬停
            __tm.sleep(0.10)
            tip = _lua(gateway, r'''
local t = tp.窗口.道具行囊 and tp.窗口.道具行囊.提示文字 or ""
_G.__out = tostring(t)
''')
            if tip and "摄妖香" in tip and "右键" not in tip:
                return cx, cy
        # 每行后停一次，减轻持续悬停对客户端的负载
        __tm.sleep(0.05)
    return None


def _xiang_find_cell(gateway) -> Optional[tuple]:
    """动态扫描行囊物品表，按名称找「摄妖香」格子中心（客户区坐标）。
    与飞行符 _fly_find_charm_cell 同款（2026-09-01 用户定案：随机格子可找，
    取代校准槽位+网格悬停扫描）。找不到返回 None。"""
    code = r'''
local out = ""
local B = tp.窗口.道具行囊
if type(B) == "table" and type(B.物品) == "table" then
  for i = 1, #B.物品 do
    local c = B.物品[i]
    if type(c) == "table" then
      local nm = tostring((c.物品 and c.物品.名称) or "")
      if nm:find("摄妖香") then
        out = tostring(c.x) .. "," .. tostring(c.y)
        break
      end
    end
  end
end
_G.__out = out
'''
    try:
        raw = _lua(gateway, code)
    except Exception:
        return None
    if raw and "," in raw:
        x, y = raw.split(",", 1)
        try:
            return int(x) + 26, int(y) + 26
        except Exception:
            return None
    return None


def _use_xiang(gateway: str, verbose: bool = True) -> bool:
    """补一次 摄妖香（到点调用）。成功使用（数量-1）→ 重置 300 分钟计时。
    :return: True=成功使用或已上身（本次已处理）；False=没补上（缺道具/定位失败）
    """
    global _XIANG_LAST_USE, _XIANG_NEXT_TRY
    # ★2026-08-30 22:37 实测修复：tp.道具列表 只有 道具行囊 打开后才填充
    #   （未开包=0条目）。旧逻辑先 _xiang_count 后开包 → 永远读到空 → 误判
    #   "背包里没有摄妖香"。改为先开包再读数量（_xiang_open_bag 无副作用）。
    if not _xiang_open_bag(gateway):
        if verbose:
            print("[摄妖香] 打开行囊失败", flush=True)
        _XIANG_NEXT_TRY = __tm.time() + _XIANG_RETRY_GAP
        return False
    __tm.sleep(0.5)
    cnt0 = _xiang_count(gateway)
    if cnt0 is None:
        if verbose:
            print("[摄妖香] 背包里没有摄妖香！", flush=True)
        _xiang_close_bag(gateway)
        _XIANG_NEXT_TRY = __tm.time() + _XIANG_RETRY_GAP
        return False
    # ★2026-09-01 用户定案：摄妖香定位改为与飞行符同款动态扫描（按名称找格子，
    #   随机格子位置都能找到；取代"一次性校准槽位 + 网格悬停"旧机制）。
    pos = _xiang_find_cell(gateway)
    if pos is None:
        # 首次打开瞬间物品表可能未加载 → 稍等重扫一次即可（图标开包）
        __tm.sleep(1.0)
        pos = _xiang_find_cell(gateway)
    if not pos:
        _xiang_close_bag(gateway)
        _XIANG_NEXT_TRY = __tm.time() + _XIANG_RETRY_GAP
        if verbose:
            print(f"[摄妖香] 未定位到摄妖香格子（动态扫描未命中；本次 "
                  f"{_XIANG_RETRY_GAP:.0f}s 后重试）", flush=True)
        return False
    cx, cy = pos
    # 悬停到位后右键使用（同驿站/战斗选项的 PostMessage 后台点击）
    import ctypes as _ct
    from library.common.win_utils import locate_game_window as _l
    pid = _get_bound_pid()
    _h = _l(pid, verbose=False) if pid > 0 else (0, 0)
    hwnd = _h[0] if isinstance(_h, tuple) else _h
    user32 = _ct.windll.user32
    lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0204, 1, lp)   # WM_RBUTTONDOWN
    __tm.sleep(0.06)
    user32.PostMessageW(hwnd, 0x0205, 0, lp)   # WM_RBUTTONUP
    if verbose:
        print(f"[摄妖香] 右键用香 @ 客户区({cx},{cy})", flush=True)
    __tm.sleep(1.2)
    cnt1 = _xiang_count(gateway)
    _xiang_close_bag(gateway)
    if cnt1 is not None and cnt1 == cnt0 - 1:
        _XIANG_LAST_USE = __tm.time()
        if verbose:
            print(f"[摄妖香] ✓ 使用成功（{cnt0}→{cnt1}），计时重置 300 分钟", flush=True)
        return True
    if cnt1 is not None and cnt1 != cnt0:
        _XIANG_LAST_USE = __tm.time()
        if verbose:
            print(f"[摄妖香] ✓ 数量变化 {cnt0}→{cnt1}，按成功处理", flush=True)
        return True
    if verbose:
        print(f"[摄妖香] 数量未变（{cnt0}→{cnt1}）→ 已生效，计时重置 300 分钟"
              f"（不再 180s 空转重试）", flush=True)
    # ★2026-09-01 提速：数量未变 = 香已生效（摄妖香无法叠加，右键不消耗）。
    #   旧逻辑设 _XIANG_NEXT_TRY=now+180 每 180s 重试一次 → 8 次用香全"数量未变"
    #   白耗 40s。已生效即重置 300 分钟计时，彻底消灭空转重试。
    _XIANG_LAST_USE = __tm.time()
    _XIANG_NEXT_TRY = __tm.time() + _XIANG_RETRY_GAP
    return True


def _xiang_due() -> bool:
    """是否到点补香（挂机一启动先补一次，此后每 300 分钟；失败后不超过冷却即可重试）。"""
    if _XIANG_LAST_USE <= 0:
        return __tm.time() >= _XIANG_NEXT_TRY
    return (__tm.time() - _XIANG_LAST_USE) >= _XIANG_INTERVAL


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
    cross_map: bool = True,
    # ★2026-08-30 摄妖香定时使用（GUI 可配置）：
    xiang_enabled: bool = True,
    xiang_interval_min: int = 300,
) -> dict:
    """世界BOSS自动监控 farming 主入口。

    优先级（2026-08-29 用户定案，数字越小越优先）：
      P0 三界财神爷 ＞ P1 二十八星宿
         ＞ P2 *头领 = 统领 = 知了王
         ＞ P3 其余白名单(灵猴/十二生肖/天罡地煞)
         ＞ P4 妖族杂鱼(妖魔鬼怪/妖魔/鬼怪)垫底
      0) 顶级目标抢占（P0~P2）：
         本图实扫到 三界财神爷，或聊天公告出现 三界财神爷 → 进入抢占；
         抢占期间只打 财神爷 ＞ 二十八星宿 ＞ *头领 = 知了王，绝不碰 P3/P4；
         顶级全无（连扫 CAISHEN_SCAN_MISS_LIMIT 次）→ 解除抢占；
      1) 解除抢占后：先按优先级清本图其余白名单 BOSS（不被公告拉走），
         本图清空才响应聊天公告跨图；
      2) 聊公告天（入口信号） > 到图 Lua 实扫白名单怪（权威）；
      3) 本图实扫无任何白名单 BOSS → 立即瞬移换图，换图后仍按上述优先级链打；
      4) 妖族杂鱼(P4)公告不触发跨图（LOW_PRIORITY_BOSSES 过滤），
         只在场景内顺手清；未登记实体（_boss_priority=None）=
         非目标，不排序不攻击（六定案）；
      5) 换图优先排除近期去过的 3 张图，避免在清过的图之间打转。

    ★2026-08-30「本图模式」对照实验（cross_map=False / 环境变量 WORLDBOSS_NO_CROSS=1，
      或标记文件 E:/DS/WORLDBOSS_NO_CROSS.flag 存在即开）：用户观察"只有被 GUI 自动化
      的角色掉线、其余未操作角色永不掉线"→ 崩溃嫌疑收敛到"高密操作（跨图1003+战斗CALL）
      触发客户端固有 bug"。本模式禁用一切跨图（财神爷追击/公告跨图/无怪轮换全部短路），
      只在本图打怪——用于定位"跨图是否掉线触发器"。注意：GUI 由 Explorer 启动时
      **继承不到 setx 的新环境变量**，故提供同名 flag 文件开关（创建/删除即开/即关）。

    ★2026-08-30「摄妖香定时使用」（GUI 可配 xiang_enabled / xiang_interval_min）：
      每 N 分钟在"战斗结束+结算对齐后、挑下一目标前"暂停补一次摄妖香（后台开包→
      校准槽位右键→数量反查），成功使用后重新计时；设置 xiang_enabled=False 关闭。

    :param xiang_enabled: 是否启用摄妖香定时补香（True=启用，挂机启动即先补一次）
    :param xiang_interval_min: 补香间隔（分钟），默认 300（与摄妖香单次持续时长对齐）
    """
    if not cross_map or os.environ.get("WORLDBOSS_NO_CROSS") == "1" \
       or os.path.exists(r"E:\DS\WORLDBOSS_NO_CROSS.flag"):
        cross_map = False
    # ★2026-08-30 本图模式（闭包辅助，不用局部 def 覆盖全局名——会触发 UnboundLocalError）：
    #   跨图禁用时 _go_map 短路（同图直判成功、异图不跨返 False）；开启时转真实 _ensure_on_map。
    def _go_map(gw, _name, _x, _y):
        if not cross_map:
            _cur = _cur_map_name(gw) or ""
            if _name and _map_same(_cur, _name):
                return True
            if verbose:
                print(f"[本图模式] 跳过跨图 → {_name}（当前 {_cur or '?'}）", flush=True)
            return False
        return _ensure_on_map(gw, _name, _x, _y)
    # ★2026-08-30 摄妖香定时（GUI 可配置 xiang_enabled / xiang_interval_min）：
    #   启用 → 每 xiang_interval_min 分钟补香（挂机启动先补一次），
    #   在"战斗结束+结算对齐后、挑下一目标前"暂停补香再继续；禁用 → 永不触发。
    global _XIANG_INTERVAL
    if xiang_enabled:
        _XIANG_INTERVAL = max(1, int(xiang_interval_min)) * 60
        if verbose:
            print(f"[摄妖香] 定时启用：每 {int(xiang_interval_min)} 分钟补一次"
                  f"（槽位 {_XIANG_SLOT_FILE}）", flush=True)
    else:
        _XIANG_INTERVAL = 10 ** 18   # 禁用（时间戳永达不到）
        if verbose:
            print("[摄妖香] 定时禁用（xiang_enabled=False）", flush=True)
    monitored_maps = monitored_maps or list(DEFAULT_MONITORED_MAPS)
    target_bosses = target_bosses or list(DEFAULT_TARGET_BOSSES)
    # ★2026-08-30 对照实验开关：E:/DS/WORLDBOSS_SKIP_COVID.flag 存在 → 从目标名单
    #   剔除「新型冠状病毒」。用于隔离"新冠战斗路径是否掉线触发器"（08:35 实锤
    #   多开器外+本图模式 3.5 分钟仍崩且零异常，长寿郊外满屏新冠为最大嫌疑）。
    if os.path.exists(r"E:/DS/WORLDBOSS_SKIP_COVID.flag"):
        before = len(target_bosses)
        target_bosses = [b for b in target_bosses if "新冠" not in b]
        if len(target_bosses) != before:
            print("[新冠剔除] WORLDBOSS_SKIP_COVID.flag 生效：本次不目标 新型冠状病毒",
                  flush=True)
    # ★2026-08-30 对照实验：scan_only 纯扫描模式（WORLDBOSS_SCAN_ONLY.flag）——
    #   farm 照常扫图/轮换，但绝不 CALL BOSS/进战斗。用于隔离"战斗 CALL"与
    #   "注入+高频扫描"哪个是掉线触发器（昨晚30分钟0崩但今早密集战斗几轮全崩）。
    scan_only = os.path.exists(r"E:/DS/WORLDBOSS_SCAN_ONLY.flag")
    if scan_only:
        print("[扫描模式] WORLDBOSS_SCAN_ONLY.flag 生效：只扫描不CALL不战斗", flush=True)
    # ★2026-08-30 固化为默认：扫描降频 3s（无 flag 也生效；flag 存在仅日志冗余）。
    #   依据：纯扫描 2 分钟即崩（08:51 实锤）而实体少/负载低时稳定，3s 一拍负载 x1/3。
    if boss_scan_interval < 3.0:
        boss_scan_interval = 3.0
    if os.path.exists(r"E:/DS/WORLDBOSS_SCAN_SLOW.flag"):
        print("[扫描降频] 固化 3s（flag 冗余，行为无差异）", flush=True)
    # ★2026-08-30 全局 Lua 节流【固化默认生效】：无论 flag 是否存在都启用 0.4s 节流。
    #   依据：9:07-9:30 attach 静置 23 分钟零崩溃 vs farm 持续注入 1-8 分钟随机崩；
    #   0.4s 实测 60 杀零崩溃，farm入→开战 1.6~3s、战间 4~7s。
    #   可用环境变量 WORLDBOSS_LUA_GAP 覆盖（如 1.0 保命）。
    global _LUA_MIN_GAP
    _LUA_MIN_GAP = float(os.environ.get("WORLDBOSS_LUA_GAP", "0.4"))
    global WALK_CALL_INTERVAL
    WALK_CALL_INTERVAL = 3.0    # 走路边走边CALL 降频（1.5s→3.0s，2026-08-30）
    if os.path.exists(r"E:/DS/WORLDBOSS_LUA_SLOW.flag"):
        print(f"[Lua节流] 固化生效：全局 Lua 注入最小间隔 {_LUA_MIN_GAP}s"
              f"（flag 冗余，含走路通道边走边CALL 3s 一拍）", flush=True)
    else:
        print(f"[Lua节流] 固化默认生效：全局 Lua 注入最小间隔 {_LUA_MIN_GAP}s"
              f"（环境变量 WORLDBOSS_LUA_GAP 可覆盖；含走路通道边走边CALL 3s 一拍）",
              flush=True)
    spawn_patterns = spawn_patterns or list(DEFAULT_SPAWN_PATTERNS)
    battle_keywords = battle_keywords or list(DEFAULT_BATTLE_KEYWORDS)
    # 2026-08-29 平级交叉攻击配套：登记本次运行目标名单，供 _boss_priority 对
    # "名单内但未映射档位"的名字兜底为白名单档（如用户新增"新型冠状病毒"类），
    # 避免被 _live_bosses 当"未登记非目标"剔除漏打。
    global _RUN_TARGET_BOSSES
    global _TOP_PIN_MAP
    _RUN_TARGET_BOSSES = frozenset(target_bosses)
    # 2026-08-28 B8 修复：监控表去重——同图双名（如 建邺城/宝象国 同为 1501）
    # 只保留首个，否则轮换会在两名之间空转切图（_map_same 归一后再判重）。
    _deduped: List[str] = []
    for _m in monitored_maps:
        if not any(_map_same(_m, _k) for _k in _deduped):
            _deduped.append(_m)
    monitored_maps = _deduped
    # 2026-08-29 用户定案：剔除“永不刷 BOSS 的城镇枢纽图”——既不进 farming 轮换、
    # 也不作公告跨图目标（长安城实测无怪物 BOSS，跑过去只空转）。双名归一防漏判。
    monitored_maps = [m for m in monitored_maps
                      if not any(_map_same(m, c) for c in NO_BOSS_CITY_MAPS)]

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
    # 2026-08-29 用户定案：顶级目标（P0 财神爷 / P1 星宿 / P2 头领=知了王）抢占状态
    caishen_pinned = None       # {"map","text","src"}：抢占激活中（期间只打 P0~P2）
    top_ann_seen = set()        # 已消费的顶级目标公告原文（防同一条反复抢占）
    caishen_scan_miss = 0       # 抢占图内连续无顶级目标的复扫计数
    last_name = None   # 2026-08-29 平级交叉攻击：上一次选中目标的名字
    # 2026-08-30 防发呆：记录当前外层轮内是否击杀过怪（战斗后不白等满
    # boss_scan_interval），纯扫描/换图轮才保留完整扫描间隔。
    _farmed_this_outer_round = False
    print("=== WORLD_BOSS_auto_farm 开始 ===", flush=True)
    print(f"  监控地图={monitored_maps}", flush=True)
    print(f"  目标BOSS={target_bosses[:10]}{'...' if len(target_bosses)>10 else ''}", flush=True)

    stopped = False
    _just_battle_ended = False   # 2026-08-30 提速：战斗确认结束后轮顶跳过冗余战斗态查询
    _last_kill_ts = t0            # 2026-08-30 排查：上一次击杀时刻（pin 打印用）
    while time.time() - t0 < max_runtime:
        # 2026-08-30 防发呆：外层每轮重置"本轮是否击杀过怪"标志
        _farmed_this_outer_round = False
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

        just_unpinned = False    # 本轮是否刚解除顶级抢占（解除后先清本图）
        # 0.4) 战斗态守门（2026-08-28 A3 修复）：战斗超时退出后角色可能仍在战斗中，
        #      主循环此前无守门，会在战斗态跨图/瞬移（瞬移包被服务器丢弃还浪费轮次）。
        #      战斗中等待自然结束。
        # 2026-08-28 B5 修复：每轮只做一次全量场景扫描，0.4 与 step2 共享结果
        # （旧逻辑 0.4 扫一次 + step2 再扫一次，双倍 Lua dump 开销）。
        # ★ 2026-08-30 提速：_wait_battle_end 刚确认战斗结束 → 轮顶直接跳过 _in_battle
        #   （CALL 路径内部 _call_once 自带战斗态自检兜底），省掉每个击杀后一次
        #   节流 Lua 的纯等待（~1s）；其余场景仍先走战斗态守门再扫描。
        in_battle = False if _just_battle_ended else _in_battle(gateway)
        _just_battle_ended = False
        scanned = None  # 本轮场景扫描结果（0.4/step2 共享；跨图后置 None 强制重扫）
        if in_battle:
            if verbose:
                print(f"[{int(time.time()-t0)}s] 战斗中（超时未决/战斗收尾），原地等待...", flush=True)
            # 2026-08-30 提速：2.0→1.0s 一拍（_in_battle 是轻量 Lua 查询走全局节流），
            # 战斗结束最多 1s 察觉，不傻站。仍保留节流不增压。
            if not _sleep_stoppable(1.0):
                stopped = True
                break
            continue
        # ★2026-08-30 摄妖香定时（300 分钟/次，用户定案）：在非战斗、战斗结束+结算
        #   对齐之后、挑下一目标之前——到点就暂停补香，用后继续（全程后台操作）。
        if _xiang_due():
            _use_xiang(gateway, verbose)
        scanned = scan_scene_bosses(gateway, target_bosses)
        live_here = _live_bosses(scanned, excluded)

        # 0.5) 顶级目标抢占模式（2026-08-29 用户定案，全局最高优先级）
        #   优先级链：三界财神爷(P0) ＞ 知了王(P1) ＞ 妖魔头领(P2)
        #             ＞ 其余白名单(P3) ＞ 妖族杂鱼(P4)
        #   进入条件（满足任一）：
        #     A) 本图实扫到 三界财神爷 实体 → 就地抢占，绝不切图；
        #     B) 聊天公告出现 三界财神爷 → 抢占并瞬移到公告图；
        #     C) 已抢占中且图内仍有 P0~P2 顶级目标 → 维持抢占。
        #   抢占期间只打 P0~P2（财神爷 ＞ 星宿 ＞ 头领=知了王），三者全无 →
        #   解除抢占，回落普通模式：本图其余白名单 BOSS 按 P3/P4 优先级打。
        if caishen_pinned is None:
            _TOP_PIN_MAP = None   # 未抢占 → 清中断标记（防上一轮残留）
            cs_here = [x for x in live_here if x["name"] == CAISHEN_BOSS]
            if cs_here:
                # A) 财神爷就在面前：就地抢占
                caishen_pinned = {"map": _cur_map_name(gateway) or cur_map or "",
                                  "text": None, "src": "scene"}
                caishen_scan_miss = 0
                if verbose:
                    print(f"[{int(time.time()-t0)}s] ⚡ 财神爷就在面前（{cur_map or '?'}）"
                          f" → 进入抢占模式，就地打顶级目标", flush=True)
            else:
                # B) 聊天公告
                cs_ann = find_latest_spawn(gateway, [CAISHEN_BOSS],
                                           monitored_maps, spawn_patterns)
                if cs_ann and cs_ann.get("text") not in top_ann_seen:
                    top_ann_seen.add(cs_ann.get("text"))
                    caishen_pinned = {"map": cs_ann["map"], "text": cs_ann.get("text"),
                                      "src": "chat"}
                    caishen_scan_miss = 0
                    if verbose:
                        print(f"[{int(time.time()-t0)}s] ⚡ 财神爷公告抢占 → {cs_ann['map']}",
                              flush=True)

        if caishen_pinned:
            cs_map = caishen_pinned["map"]
            # ★ 2026-08-30 顶级公告优先跨图：当前不在公告图 → 悬挂中断标记，
            #   让正在进行的本图 boss 尝试在 _farm_one_boss 启动时立即中止（先跨图）。
            if cs_map in unreachable and time.time() < unreachable[cs_map]:
                if verbose:
                    print(f"  ⚡ 财神爷图 {cs_map} 跨图冷却中 → 放弃抢占，回落普通模式",
                          flush=True)
                caishen_pinned = None
                _TOP_PIN_MAP = None
                continue
            # 已在本图则不重复跨图（_map_same 归一：建邺城 == 宝象国）
            real_now = _cur_map_name(gateway) or ""
            # 同步"顶级公告指向他图"中断标记（跨图/解除后由下一轮重新计算归零）
            _TOP_PIN_MAP = cs_map if not _map_same(real_now, cs_map) else None
            if not (real_now and _map_same(real_now, cs_map)):
                if not _go_map(gateway, cs_map, None, None):
                    unreachable[cs_map] = time.time() + 600
                    if verbose:
                        print(f"  ⚡ 跨图到财神爷图 {cs_map} 失败 → 放弃抢占", flush=True)
                    caishen_pinned = None
                    _TOP_PIN_MAP = None
                    continue
                cur_map = cs_map
                recent_maps.append(cur_map)
                scanned = None
                live_here = _live_bosses(scan_scene_bosses(gateway, target_bosses), excluded)
            # 抢占期间：只打顶级目标，同优先级取距离近的
            rg = _role_grid(gateway)
            gx0, gy0 = (rg[0], rg[1]) if rg else (0.0, 0.0)
            b = _pick_target(live_here, gx0, gy0, only_top=True, last_name=last_name)
            if b is not None:
                last_name = b["name"]
                caishen_scan_miss = 0
                if verbose:
                    print(f"[{int(time.time()-t0)}s] ⚡ 抢占模式 → {b['name']}"
                          f"(P{_boss_priority(b['name'])}) @ {_cur_map_name(gateway) or cur_map or '?'}"
                          f" {b['gx']},{b['gy']}"
                          f"（距上杀 {time.time()-_last_kill_ts:.1f}s）", flush=True)
                real_map = _cur_map_name(gateway) or cur_map or ""
                kw = _boss_battle_keywords(b["name"], list(battle_keywords))
                if scan_only:
                    print(f"  [扫描模式] 发现 {b['name']}@ {cur_map} {b['gx']},{b['gy']} 不CALL不战", flush=True)
                    excluded.add(_boss_key(b))
                    continue
                res = _farm_one_boss(gateway, b, kw, battle_timeout,
                                     walk_background, verbose, real_map)
                if res.get("reason") == "abort_top_ann":
                    continue   # 顶级公告优先 → 不计数不拉黑，下一轮 pin 逻辑跨图
                if res.get("ok") and res.get("battle_ended"):
                    farmed_total += 1
                    _farmed_this_outer_round = True   # 2026-08-30 防发呆标记
                    _just_battle_ended = True         # 2026-08-30 提速：轮顶跳过冗余战斗查询
                    _g = res.get("gap_s")
                    _gstr = (f"（上战结束→本场开战 {_g:.1f}s）"
                             if isinstance(_g, (int, float)) else "")
                    print(f"  ✓ 击杀 {b['name']} @ {cur_map}（累计 {farmed_total}）{_gstr}", flush=True)
                    _last_kill_ts = time.time()
                else:
                    # gone = 没了；no_battle_option = 被人锁定/占领 → 拉黑，下轮换目标
                    print(f"  ✗ {b['name']} 跳过: {res.get('reason')} {res.get('msg')}",
                          flush=True)
                    excluded.add(_boss_key(b))
                continue      # 维持抢占：零等待直接回外层重扫，按优先级切下一目标
            # 顶级三目标全无：公告先到怪未刷 / 已被击杀 / 被人锁定 → 复扫几轮再判
            caishen_scan_miss += 1
            if caishen_scan_miss >= CAISHEN_SCAN_MISS_LIMIT:
                if verbose:
                    print(f"  ⚡ 财神爷/知了王/妖魔头领 均无（连扫 {caishen_scan_miss} 次）"
                          f" → 解除抢占，回落普通模式打本图其余白名单 BOSS", flush=True)
                caishen_pinned = None
                _TOP_PIN_MAP = None
                just_unpinned = True   # 本轮先清本图，不被公告拉走
            else:
                if not _sleep_stoppable(CAISHEN_SCAN_MISS_GAP):
                    stopped = True
                    break
                continue
        # 未抢占 / 刚解除抢占 → 落到 step1(公告跨图) / step2(本图按优先级清怪)

        # 1) 聊天公告 → 目标地图
        # 2026-08-28 修复"过期公告拉扯"：recv 缓存里的老公告没有时间戳，
        # find_latest_spawn 永远返回它 → 跨图去打→12s 清图→又被拉回，无限打转。
        # 记忆机制：同一条公告对应的图已被判清图（ann_cleared=True）后，
        # 这条公告作废，直到缓存里出现新文本才重新生效。
        # 2026-08-29 用户定案 3：刚解除顶级抢占且本图仍有白名单 BOSS →
        # 先按优先级清完本图，不被公告拉走；本图清空后才响应公告跨图。
        if just_unpinned and live_here:
            spawn = None
        else:
            spawn = find_latest_spawn(gateway, target_bosses, monitored_maps, spawn_patterns)
        if spawn and spawn.get("text") == last_ann_text and ann_cleared:
            spawn = None  # 过期公告：对应图已清过，不再拉回
        elif spawn:
            if spawn.get("text") != last_ann_text:
                last_ann_text = spawn.get("text")
                ann_cleared = False
        # 2026-08-28 五定案：妖魔鬼怪/妖魔/鬼怪=最低优先级——公告不再为它们跨图。
        # 2026-08-29 补充：多图系统公告（如"妖魔在 A、B、C 出没，前往剿灭"）
        # 属于系统召唤事件，force_cross=True，即便 BOSS 是 LOW_PRIORITY 也触发跨图。
        # 2026-08-30 补充：二十八星宿公告同样不触发跨图（NO_CROSS_BOSSES，用户定案）。
        # ★2026-08-31 00:12 方案1曾改成"仅顶级公告跨图"（用户试跑后于 00:4x 撤销：
        #   恢复原公告优先级判定，跨图行为与原版一致；崩溃根因已另锁定 captcha
        #   monitor，跨图不再是背锅项）。
        if spawn and spawn.get("boss") in NO_CROSS_BOSSES and not spawn.get("force_cross"):
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
                if not _go_map(gateway, spawn["map"], None, None):
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
            # 2026-08-29 修复（桩测试实锤）：旧逻辑一上来就随机切图，两个后果——
            #   1) 启动首轮盲跳：角色身边站着知了王也会被传送走，白丢一轮跨图；
            #   2) 抢占模式下 cur_map 始终为 None（0.5 分支 continue 永远到不了这里），
            #      解除抢占后本图还有 P3/P4 白名单怪，却被当成"未指派地图"随机跳走。
            # 新逻辑：先认领角色当前真实地图，本轮照常走 step2 实扫按优先级打；
            # 本图真的没有白名单 BOSS 时，才由 step3 负责换图。
            cur_map = _cur_map_name(gateway) or None
            if cur_map is None:
                # 连真实地图名都读不到（网关异常/场景未加载）→ 退化成原逻辑随机待命
                cur_map = _pick_random_map(None, monitored_maps, tuple(recent_maps))
                no_boss_since = None
                # 2026-08-28：初始切图也要核实——失败则以真实地图名为准（防标签说谎）
                if _go_map(gateway, cur_map, None, None):
                    recent_maps.append(cur_map)
                else:
                    unreachable[cur_map] = time.time() + 600
                    cur_map = _cur_map_name(gateway) or cur_map
                scanned = None  # 跨图后 0.4 的扫描属旧图，作废

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
        bosses = _live_bosses(scanned, excluded)
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
                # 0.5) 顶级目标(P0~P2)公告抢占检查：每打一只前查一次（单扫覆盖
                #      财神爷/知了王/妖魔头领）——
                #      财神爷公告 → 立即 pin，交外层瞬移；
                #      知了王/妖魔头领公告且不在本图 → 放弃本图杂鱼，交外层 step1
                #      跨图（防 P3/P4 杂鱼把高优先级目标饿死）。
                _ann = find_latest_spawn(gateway, list(TOP_TIER_BOSS_NAMES),
                                         monitored_maps, spawn_patterns)
                _ann_text = (_ann or {}).get("text")
                _ann_boss = (_ann or {}).get("boss")
                if _ann and _ann_text and _ann_text not in top_ann_seen:
                    top_ann_seen.add(_ann_text)
                    if len(top_ann_seen) > 500:
                        top_ann_seen.clear()      # 防长跑无界膨胀
                    if _ann_boss == CAISHEN_BOSS:
                        caishen_pinned = {"map": _ann["map"], "text": _ann_text,
                                          "src": "chat"}
                        caishen_scan_miss = 0
                        if verbose:
                            print(f"  ⚡ 财神爷公告抢占: {_ann['map']} → 放弃当前目标",
                                  flush=True)
                        break
                    if not _map_same(_ann.get("map") or "", cur_map or ""):
                        if verbose:
                            print(f"  ⚡ 顶级目标公告 {_ann_boss} @ {_ann['map']}"
                                  f"（非本图）→ 放弃本图杂鱼", flush=True)
                        break
                # 每击杀一只后重扫：战斗后场景人物槽位/实例会重排（SYBUZ2 同款坑），
                # 静态列表的 id/bsid 会错位导致 CALL 错实体（2026-08-27 实测）。
                live = _live_bosses(scan_scene_bosses(gateway, target_bosses), excluded)
                if not live:
                    break
                try:
                    rg0 = _role_grid(gateway)
                    gx0, gy0 = (rg0[0], rg0[1]) if rg0 else (0.0, 0.0)
                except Exception:
                    gx0, gy0 = 0.0, 0.0
                # 2026-08-30 用户新定案：普通模式严格按 BOSS_PRIORITY 排序
                #   P0 三界财神爷（抢占独占）＞ P1 头领=统领=知了王 ＞
                #   P2 其余全部（灵猴/星宿/生肖/天罡地煞/新冠/妖魔鬼怪一律平级）；
                #   同优先级一律按"距角色坐标由近到远"取最近（平级交叉战斗，
                #   战斗结束只对最近 BOSS CALL一次，失败马上走路/瞬移贴近）。
                #   未登记实体 = _boss_priority 返回 None = 非目标，已由 _live_bosses 剔除。
                b = _pick_target(live, gx0, gy0, last_name=last_name)
                if b is not None:
                    last_name = b["name"]
                if b is None:          # 理论不可达（live 非空必有目标），防御性兜底
                    break
                this_keywords = _boss_battle_keywords(b["name"], list(battle_keywords))
                # 2026-08-28：走路/校准一律用实读地图名——cur_map 标签万一错了
                # （跨图未到达），拿错图的校准数据点屏幕会全错（长寿郊外点花果山像素事故）
                # 2026-08-28 提速轮：内层循环内地图不会变，每只怪读一次 → 进图读一次缓存
                if not real_map_cache[0]:
                    real_map_cache[0] = _cur_map_name(gateway) or cur_map
                real_map = real_map_cache[0]
                if scan_only:
                    print(f"  [扫描模式] 发现 {b['name']}@ {cur_map} {b['gx']},{b['gy']} 不CALL不战", flush=True)
                    excluded.add(_boss_key(b))
                    continue
                res = _farm_one_boss(gateway, b, this_keywords, battle_timeout,
                                     walk_background, verbose, real_map)
                if res.get("reason") == "abort_top_ann":
                    continue   # 顶级公告优先 → 不计数不拉黑，下一轮 pin 逻辑跨图
                if res.get("ok") and res.get("battle_ended"):
                    farmed_total += 1
                    _farmed_this_outer_round = True   # 2026-08-30 防发呆标记
                    _just_battle_ended = True         # 2026-08-30 提速：轮顶跳过冗余战斗查询
                    _g = res.get("gap_s")
                    _gstr = (f"（上战结束→本场开战 {_g:.1f}s）"
                             if isinstance(_g, (int, float)) else "")
                    print(f"  ✓ 击杀 {b['name']} @ {cur_map}（累计 {farmed_total}）{_gstr}", flush=True)
                    _last_kill_ts = time.time()
                else:
                    # battle_ended=False = 根本没进战斗（假触发），同样按失败处理
                    reason = res.get("reason") or ("no_battle_start" if res.get("ok") else "failed")
                    print(f"  ✗ {b['name']} 跳过: {reason} {res.get('msg')}", flush=True)
                    excluded.add(_boss_key(b))
                if not _sleep_stoppable(0.1):  # 2026-08-30 提速轮：1.0→0.3→0.2→0.1，连续击杀不间断
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
                re = _live_bosses(scan_scene_bosses(gateway, target_bosses), excluded)
                if re:
                    continue
                # 复扫仍空 → 立即轮换（公告记忆同步作废，防老公告拉回）
                # ★2026-08-31 00:12 方案1曾临时改为"驻留等刷新"（用户 00:4x 撤销：
                #   恢复原版随机换图轮换，跨图行为与原版一致；崩溃根因已另锁定
                #   captcha monitor）。
                ann_cleared = True
                nxt = _pick_random_map(cur_map, monitored_maps, tuple(recent_maps))
                if verbose:
                    print(f"[{int(time.time()-t0)}s] {cur_map} 实扫无白名单怪，立即换图 → {nxt}",
                          flush=True)
                no_boss_since = None
                if _go_map(gateway, nxt, None, None):
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
                if _go_map(gateway, nxt, None, None):
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

        if not _sleep_stoppable(boss_scan_interval if not _farmed_this_outer_round else 0.1):
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
        chat_gw = _CHAT_GW or gateway   # 2026-08-29 分离网关：缓存清理走独立聊天网关
        r = _http_json(chat_gw, "/api/net/clear", None, timeout=15.0)
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
