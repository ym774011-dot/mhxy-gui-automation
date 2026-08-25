# -*- coding: utf-8 -*-
"""
字模坐标 + JHRW 任务信息读取器。

两个独立功能：
  A. 左上角当前坐标读取 (15,19)-(147,43)，#FFFFFF 白色字模
     内容格式：地图名[X,Y]  如「长安城[248,100]」

  B. JHRW 任务追踪栏读取 (837,120)-(996,236)，颜色分段
     #FFFF00 黄 → 目标地图名（如「江南野外」）
     #FF0000  红 → 任务名（如「初出江湖」）+ 进度
     #FFFFFF  白 → 指令文字、NPC名、坐标数字
     #00FF00  绿 → NPC 名部分

替代方案对比：
    - game_coord_reader: 内存扫描，地址不稳定，已证实不可靠
    - ocr_coord_reader: OCR 统计模型，85~98% 准确率
    - 本模块: 字模指纹精确匹配，确定性 100%（库中有该字符时）
"""
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import cv2

from core.glyph_recognizer import (
    Glyph,
    GlyphLibrary,
    GlyphRecognizer,
    RecognitionResult,
    # 区域 A：左上角坐标（白色）
    COORD_WHITE_RULE,
    # 区域 B：JHRW 任务栏（颜色分段）
    JHRW_YELLOW_RULE,
    JHRW_RED_RULE,
    JHRW_WHITE_RULE,
    JHRW_GREEN_RULE,
    JHRW_ALL_TEXT_RULE,
)
from core.screen_capture import screen_capture
from utils.logger import logger

# ======================================================================
# ROI 定义（客户区相对坐标，从截图精确测量）
# ======================================================================

# 区域 A：左上角当前地图名 + 坐标
COORD_ROI = (15, 19, 132, 24)       # (x, y, w, h) — 白色文字

# 区域 B：JHRW 任务追踪面板（默认值，可从 config/settings.json 的
# recognition.jhrw_roi 覆盖；窄范围能减少噪声字符误识）
_JHRW_ROI_DEFAULT = (840, 130, 150, 103)  # (x, y, w, h) — 多色文字


def get_jhrw_roi() -> Tuple[int, int, int, int]:
    """返回 JHRW 任务面板 ROI（优先读取 settings 配置，缺失时用默认值）。

    2026-08-25 分辨率自适应：ROI 按设计基准（1000x600）配置，
    窗口缩放到其他尺寸时换算为当前客户区物理坐标。
    """
    try:
        from config.config import config
        v = config.get("recognition.jhrw_roi")
        if isinstance(v, (list, tuple)) and len(v) == 4:
            x, y, w, h = int(v[0]), int(v[1]), int(v[2]), int(v[3])
        else:
            x, y, w, h = _JHRW_ROI_DEFAULT
    except Exception:
        x, y, w, h = _JHRW_ROI_DEFAULT
    try:
        from core.resolution import logical_rect
        return logical_rect(x, y, w, h)
    except Exception:
        return (x, y, w, h)


# 兼容旧引用：模块级常量（写死旧值会与 settings 冲突，故也跟随配置）
JHRW_ROI = get_jhrw_roi()


# ======================================================================
# 黄通道地图名 —— 整块指纹匹配（绕过字符切分问题）
# ======================================================================
#
# 原理：黄通道只有 3 个候选值（东海湾/建邺城/江南野外），且不同图片
# 的渲染略有差异（字间距/抗锯齿）导致逐字切分时合并块 hash 不稳定。
# 方案：对整个黄色掩码做 32×32 归一化 → md5 → 查表。
#
# 指纹来源：从 7 张面板测试图实测采集，每张图的黄色掩码独立计算。

from core.glyph_recognizer import apply_color_mask as _apply_color_mask
from core.glyph_recognizer import normalize_bitmap as _normalize_bitmap

_MAP_NAME_FINGERPRINTS: Dict[str, str] = {
    # {md5_hex: map_name} — 黄通道『仅地图名区域』(裁剪掉 (x,y) 坐标数字)
    # 32×32 归一化后 md5。坐标无关：建邺城(251,23) 与 建邺城(28,22) 同指纹。
    # 所有指纹在 RGB 通道约定 + JHRW_YELLOW_RULE 范围模式下，从真实面板采集。
    # 旧 BGR 时期 / 含坐标数字的整块指纹均已失效，已移除。
    "da4fda5f921bb28ad6960a6e847b1e4d": "建邺城",        # 2026-08-03 建邺城 JHRW 面板 BMP（坐标无关）
    "34d2da204de704e35e1a984ca8a6a46f": "东海湾",        # 2026-08-03 用户面板（旧渲染变体）
    "f1a480ad2064391c9eb2398b9335ef38": "东海湾",        # 2026-08-05 用户面板（新 ROI 渲染变体）
    "4b70472283d4ec7c8b8f4cb79831021f": "江南野外",      # 2026-08-03 region_B_jhrw_x4.png 4×→1×
}

# 反向索引：map_name → set of valid fingerprints（用于快速验证）
_MAP_NAME_REVERSE: Dict[str, set] = {}
for _h, _m in _MAP_NAME_FINGERPRINTS.items():
    _MAP_NAME_REVERSE.setdefault(_m, set()).add(_h)


# 已知 JHRW 目标地图全集（用于地图名模糊匹配回退）。
# quest 级白名单见 jhrw_controller._QUEST_TARGET_MAPS；这里列出全集，
# 识别阶段仅做字符级子序列匹配，quest 级白名单由下游再过滤。
KNOWN_JHRW_MAPS: frozenset = frozenset({"江南野外", "建邺城", "东海湾"})

# COORD 区（左上角「地图名[X,Y]」）可能出现的全部地图。
# 用于模糊归一化：识别到"江南野"（"外"被吞/粘连丢失）→ 子序列匹配 → "江南野外"。
# 覆盖游戏地图全集（含 JHRW 三图，避免两套表不一致）。
KNOWN_COORD_MAPS: tuple = (
    "江南野外", "东海湾", "建邺城", "长安城", "傲来国", "长城",
    "大唐国境", "大唐境外", "长寿村", "北俱芦洲", "龙宫", "天宫",
    "地府", "普陀山", "五庄观", "女儿村", "方寸山", "化生寺",
    "盘丝洞", "阴曹地府", "宝象国", "朱紫国", "西凉女国", "比丘国",
    "乌鸡国", "车迟国", "大唐官府", "化生寺", "魔王寨", "狮驼岭",
    "魔王岭", "花果山", "水帘洞", "傲来国境", "女儿国", "海底迷宫",
)


def _normalize_map_name(seq: str) -> str:
    """把识别文本（可能缺字/多字）归一化为已知地图名。

    用户需求（2026-08-05 00:16）：字模识别"江南野"应等于"江南野外"。
    字符常因抗锯齿粘连/被吞而缺字（如"外"与"["粘连成块被识别为"["）。

    匹配顺序：
      1. 完全相等 → 直接返回
      2. 子序列匹配：seq 所有字符按顺序出现在 name 中（容忍缺字）
      3. 重叠兜底：字符集合重叠数 ≥ 3 且唯一领先 → 取之
      4. 无法匹配 → 原样返回
    """
    if not seq:
        return seq
    if seq in KNOWN_COORD_MAPS:
        return seq
    # 2) 子序列匹配（顺序保持、允许缺字）
    cands = []
    for name in KNOWN_COORD_MAPS:
        it = iter(name)
        if all(c in it for c in seq):
            cands.append(name)
    if len(cands) == 1:
        return cands[0]
    if cands:
        return cands[0]
    # 3) 重叠兜底（≥3 字符，唯一领先才采用）
    seq_set = set(seq)
    scored = []
    for name in KNOWN_COORD_MAPS:
        overlap = sum(1 for c in name if c in seq_set)
        if overlap >= 3:
            scored.append((overlap, -len(name), name))
    if scored:
        scored.sort(reverse=True)
        top = scored[0]
        if len(scored) == 1 or top[0] > scored[1][0]:
            return top[2]
    return seq


def _first_coord_x(yellow_result: "RecognitionResult") -> Optional[int]:
    """
    在黄通道识别结果中找『坐标起始列』——即 '(' 或坐标数字串的最左 x。
    地图名始终位于其左侧；以此为界裁剪即可让指纹与坐标数字无关。

    稳健性：中文笔画碎片常被误识别为数字且位于最左侧，故不取『最左数字』，
    而是优先 '(' 命中；其次取『彼此靠近（<24px）的数字串』最左块，排除孤立
    误识数字。
    """
    glyphs = sorted(yellow_result.glyphs, key=lambda g: g.bbox[0])
    # 1) '(' 字库命中（最可靠）
    for g in glyphs:
        if g.char == "(":
            return g.bbox[0]
    # 2) 坐标数字串：找彼此靠近的数字块，取该串最左块
    digits = [g for g in glyphs if g.char.isdigit()]
    if len(digits) >= 2:
        digits.sort(key=lambda g: g.bbox[0])
        run_start = digits[0]
        for a, b in zip(digits, digits[1:]):
            if (b.bbox[0] - (a.bbox[0] + a.bbox[2])) <= 24:
                continue  # 仍在同一数字串内
            else:
                # 串断裂：串起点为 run_start，当前 b 开启新串
                # 若 run_start 处已凑够 2 个数字则采用，否则继续
                if run_start is not None:
                    return run_start.bbox[0]
                run_start = b
        return run_start.bbox[0] if run_start is not None else None
    # 3) 无坐标：整块即地图名
    return None


def _map_name_fingerprint_hash(
    image_rgb: np.ndarray, yellow_result: Optional["RecognitionResult"] = None
) -> Optional[str]:
    """
    计算『仅地图名区域』的 32×32 归一化指纹（排除 (x,y) 坐标数字）。

    与坐标无关：建邺城(251,23) 与 建邺城(28,22) 得到相同指纹。
    """
    mask = _apply_color_mask(image_rgb, JHRW_YELLOW_RULE)
    if not mask.any():
        return None
    if yellow_result is not None:
        boundary = _first_coord_x(yellow_result)
        if boundary is not None:
            mask = mask[:, :boundary]
    if not mask.any():
        return None
    _, h32 = _normalize_bitmap(mask, target_size=(32, 32))
    return h32


def recognize_map_name_fingerprint(
    image_rgb: np.ndarray, yellow_result: Optional["RecognitionResult"] = None
) -> Optional[str]:
    """
    从 JHRW 面板图像中识别黄通道地图名（整块指纹匹配，坐标无关）。

    :param image_rgb: JHRW 面板的 RGB 图像 (已裁剪到 JHRW_ROI)
    :param yellow_result: 已用 JHRW_YELLOW_RULE 识别的结果（用于定位坐标起始列）
    :return: 地图名字符串 或 None
    """
    h32 = _map_name_fingerprint_hash(image_rgb, yellow_result)
    if h32 is None:
        return None
    return _MAP_NAME_FINGERPRINTS.get(h32)


def add_map_name_fingerprint(
    image_rgb: np.ndarray,
    map_name: str,
    yellow_result: Optional["RecognitionResult"] = None,
) -> str:
    """
    注册一个新的地图名指纹（发现新渲染变体时调用）。坐标无关版本。
    """
    h32 = _map_name_fingerprint_hash(image_rgb, yellow_result)
    if not h32:
        return ""
    _MAP_NAME_FINGERPRINTS[h32] = map_name
    _MAP_NAME_REVERSE.setdefault(map_name, set()).add(h32)
    logger.info(f"新增地图名指纹: {h32[:16]}.. -> {map_name}")
    return h32


def _map_name_subsequence(yellow_result: "RecognitionResult") -> Optional[str]:
    """
    字符级回退：从黄通道识别结果中提取地图名（抗 CJK 断笔碎片）。

    黄通道中文常因笔画被 blob 切分而碎成多块（如 邺 → 2 个 UNKNOWN），
    逐字匹配失效。本函数只取『坐标起始列左侧、已识别的非数字中文』按序组成
    子序列，再与已知地图名做子序列匹配——断笔产生的 UNKNOWN 块被自然忽略。

    模糊回退：当精确子序列无解时（如 江 的三点水碎片被 blob 切掉 → 序列
    退化为 [南, 野, 外, 外]），改用字符重叠数匹配——找与已识别字符重叠
    最多（且 ≥ 3 字符重叠）的已知地图，避免无脑返回第一个候选导致误判。
    """
    glyphs = yellow_result.glyphs
    if not glyphs:
        return None
    boundary = _first_coord_x(yellow_result)
    name_glyphs = [
        g
        for g in glyphs
        if (boundary is None or g.bbox[0] < boundary)
        and not g.char.isdigit()
        and g.char not in ("(", ")", "UNKNOWN")
    ]
    seq = [g.char for g in sorted(name_glyphs, key=lambda g: g.bbox[0])]
    if not seq:
        return None
    # 1) 精确子序列匹配：seq 是 name 的子序列（按顺序但不必连续）
    cands = []
    for name in KNOWN_JHRW_MAPS:
        it = iter(name)
        if all(c in it for c in seq):
            cands.append(name)
    if len(cands) == 1:
        return cands[0]
    if cands:
        return cands[0]

    # 2) 模糊匹配：江三点水被吞、外重复识别时用重叠数（≥3 字符）找最佳
    seq_set = set(seq)
    scored = []
    for name in KNOWN_JHRW_MAPS:
        overlap = sum(1 for c in name if c in seq_set)
        if overlap >= 3:
            # 重叠数优先；并列时取名字最短的（更精确）
            scored.append((overlap, -len(name), name))
    if scored:
        scored.sort(reverse=True)
        top = scored[0]
        # 唯一最佳 或 重叠数明显领先 才采用
        if len(scored) == 1 or top[0] > scored[1][0]:
            return top[2]
    return None


# ======================================================================
# 文本解析
# ======================================================================

_COORD_PATTERN = re.compile(
    r"^(?P<map>.+?)\s*[\[（]?\s*(?P<x>\d{1,4})\s*[,，]\s*(?P<y>\d{1,4})\s*[\)]]?"
)

_PROGRESS_PATTERN = re.compile(
    r"当前第\s*(\d+)\s*次"
)

_COORD_PAIR_PATTERN = re.compile(
    r"(\d{1,4})\s*[,，]\s*(\d{1,4})"
)


def parse_location_text(text: str) -> Optional[dict]:
    """
    从识别文本中解析地图名和坐标。

    支持格式：长安城[248,100] / 建邺城(86,78) / 江南野外 34,116
    """
    clean = text.replace("UNKNOWN", "").strip()
    if not clean:
        return None

    m = _COORD_PATTERN.match(clean)
    if m:
        map_part = m.group("map").strip()
        # map 非贪婪匹配可能把 '(' / '[' 抢进 map（如 "建邺(251,23)" → "建邺("）
        # 剥离尾部括号后再做模糊归一化
        map_part = map_part.rstrip("([（")
        return {
            "map": _normalize_map_name(map_part),
            "x": int(m.group("x")),
            "y": int(m.group("y")),
        }

    digits = re.findall(r"\d{1,4}", clean)
    if len(digits) >= 2:
        map_part = clean[: clean.rfind(digits[-2])].strip()
        map_part = re.sub(r"[\d\[\](),，\s]+$", "", map_part).strip()
        return {
            "map": _normalize_map_name(map_part) or "UNKNOWN",
            "x": int(digits[-2]),
            "y": int(digits[-1]),
        }

    return None


def parse_progress_text(text: str) -> Optional[int]:
    """从进度文本中提取次数。如 '身份(当前第229次)' → 229

    容错（三级降级）：
      1. 精确匹配「当前第N次」
      2. 容错「第N」（次字缺失时）
      3. 兜底：红通道唯一的多位数字即进度（UNKNOWN 阻隔导致 第/N 不相邻时）
    """
    m = _PROGRESS_PATTERN.search(text)
    if m:
        return int(m.group(1))
    m2 = re.search(r"第\s*(\d+)", text)
    if m2:
        return int(m2.group(1))
    # 兜底：红通道中唯一的多位数字就是进度计数
    m3 = re.search(r"(\d{2,})", text)
    return int(m3.group(1)) if m3 else None


def parse_coord_pair(text: str) -> Optional[Tuple[int, int]]:
    """从文本中提取坐标对。如 '(105,25)' → (105, 25)"""
    m = _COORD_PAIR_PATTERN.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def extract_coord_spatial(
    result: "RecognitionResult",
    recognizer: Optional[GlyphRecognizer] = None,
) -> Optional[Tuple[int, int]]:
    """
    空间邻域法从白通道提取坐标 (X, Y)。

    背景：白通道文本（前往(X,Y)处查明…）逐字切分后按 x 全局排序，
    因坐标区换行/位置差异导致字符散落混乱，正则无法匹配。本函数不依赖
    全局文本顺序，直接利用 ``( 数字 , 数字 )`` 的局部几何结构：

      * '('  窄高块（优先字库命中，否则几何 w<=6 & h>=9）
      * 其右侧最近的 ')'（按 x 就近，忽略 y —— 容忍坐标跨行换行）
      * 两者之间最窄的非数字块即 ','（几何兜底）
      * '('~',' 之间的数字 = X；','~')'（或逗号右侧同行的剩余数字）= Y

    :param result: 已用 JHRW_WHITE_RULE 识别得到的 RecognitionResult
    :param recognizer: 兼容保留参数（result 给定时不需要）
    :return: (x, y) 或 None（调用方应回退正则）
    """
    if result is None:
        return None
    glyphs = result.glyphs
    if not glyphs:
        return None

    def cyc(g):
        return g.bbox[1] + g.bbox[3] / 2.0

    def is_open_paren(g):
        # 仅当字库命中 '(' 或 UNKNOWN 窄高块；字库 ')' 绝不当作 '('，
        # 否则上一帧坐标的 ')' 残影会被几何兜底误判为开括号候选。
        _, _, w, h = g.bbox
        return g.char == "(" or (
            g.char == "UNKNOWN" and 2 <= w <= 6 and h >= 9
        )

    def is_close_paren(g):
        # 优先字库命中；几何兜底仅当字库未识别（UNKNOWN）时，
        # 限制 h ≤ 14 排除任务面板装饰的高块（h=15+ 通常是"任务追踪?" 之类装饰）
        if g.char == ")":
            return True
        return g.char == "UNKNOWN" and (2 <= g.bbox[2] <= 6 and 9 <= g.bbox[3] <= 14)

    def is_comma(g):
        # 优先字库命中；几何兜底仅当字库未识别（UNKNOWN）时，
        # 否则窄数字（如 '3' w3）会被误判为逗号
        if g.char == ",":
            return True
        return g.char == "UNKNOWN" and (g.bbox[2] <= 4 and g.bbox[3] <= 14)

    def is_digit(g):
        return g.char.isdigit()

    # 候选 '('：优先字库命中的 '('，其次几何候选
    opens = [g for g in glyphs if is_open_paren(g)]
    opens.sort(key=lambda g: 0 if g.char == "(" else 1)
    for op in opens:
        ox, oy, ow, oh = op.bbox
        op_right = ox + ow
        op_cy = cyc(op)

        # 最近的 ')'（跨行场景容错：'(' 右侧没 ')' 时，行 2 续接的 ')' 在 '(' 左侧）
        # 按 (|x 距离| + 2*|y 距离|) 加权打分，同行的 ')' 优先（y 距离=0）
        # 优先 `)'` 字模命中；UNKNOWN 几何兜底限制同 y 行（避免任务面板装饰字符假阳性）
        def _close_score(g):
            dx = abs(g.bbox[0] - op_right)
            dy = abs(cyc(g) - op_cy)
            return dx * 0.5 + dy * 2.0
        close_candidates = [g for g in glyphs if is_close_paren(g)]
        char_closes = [g for g in close_candidates if g.char == ")"]
        unk_closes = [
            g for g in close_candidates
            if g.char == "UNKNOWN" and abs(cyc(g) - op_cy) <= 12
        ]
        if char_closes:
            # `)'` 字符命中：按 _close_score 排序（同行或跨行最佳）
            closes = sorted(char_closes, key=_close_score)
        elif unk_closes:
            closes = sorted(unk_closes, key=_close_score)
        else:
            closes = []
        cp = None
        cp_is_virtual = False
        if closes and _close_score(closes[0]) < 100:
            cp = closes[0]
        else:
            # 截图右侧被裁掉 / 字模库 ')' 未命中 / 坐标跨行换行：
            # 构造虚拟右括号（位于 '(' 右边最后一个数字的右边界，
            # 或行 2 续接时 '(' 左边最后一个数字的左边界），
            # 让后续逗号识别 / 数字位数硬切分支继续跑通，否则返回 None
            # 让上层错误地回落到白通道拿到更差的结果（如 (3, 3)）。
            digits_after = [g for g in glyphs if is_digit(g) and g.bbox[0] > ox]
            digits_before = [g for g in glyphs if is_digit(g) and g.bbox[0] < ox]
            if digits_after:
                rightmost = max(g.bbox[0] + g.bbox[2] for g in digits_after)
                cp = Glyph(char=")", bbox=(rightmost, oy, 1, oh))
                cp_is_virtual = True
            elif digits_before:
                # 跨行：')' 在行 2 行首，cp 取最后一个跨行数字左边界
                leftmost = min(g.bbox[0] for g in digits_before)
                cp = Glyph(char=")", bbox=(leftmost, oy, 1, oh))
                cp_is_virtual = True
            if cp:
                logger.debug(
                    "extract_coord_spatial: ')' 未识别，构造虚拟右括号走数字位数硬切"
                )
        if cp is None:
            continue

        # 逗号：'(' 右侧 30px 内（行 1 末，跨行场景时 ')' 在 '(' 左不影响）
        commas = [g for g in glyphs if is_comma(g) and ox < g.bbox[0] <= op_right + 30]
        if not commas:
            # 兜底候选必须与 '(' 同一水平线（垂直中心接近），否则坐标行上方/下方
            # 的噪声块（如残影、行首装饰）会被误选为逗号，把 cm_left 推得过右，
            # 导致 X 吞掉所有数字、Y 为空 → 整体 return None 回落白通道。
            between = [
                g for g in glyphs
                if min(ox, cp.bbox[0]) < g.bbox[0] <= max(op_right, cp.bbox[0] + cp.bbox[2])
                and not is_digit(g)
                and not is_open_paren(g)
                and not is_close_paren(g)
                and abs(cyc(g) - cyc(op)) <= 12
            ]
            if between:
                commas = [min(between, key=lambda g: g.bbox[2])]
        # 二级兜底：逗号实在太小被过滤掉时（如黄通道 '(58,55)' 中逗号只有 2×3px），
        # 取 '(' 与 ')' 之间数字块的最大 x 间隙作为 X/Y 分界。
        # 仅当最大间隙**明显大于**其他典型数字字间距时才采纳（避免在所有数字等距
        # 排布时误选第一个间隙 → 把首字当 X、其余当 Y，得 (3, 966) 这种错位）。
        if not commas:
            between_digits = sorted(
                [g for g in glyphs
                 if is_digit(g)
                 and min(ox, cp.bbox[0]) < g.bbox[0]
                 <= max(op_right, cp.bbox[0] + cp.bbox[2])],
                key=lambda g: g.bbox[0],
            )
            n = len(between_digits)
            if n >= 2:
                gaps = []
                for i in range(n - 1):
                    gap = between_digits[i + 1].bbox[0] - (between_digits[i].bbox[0] + between_digits[i].bbox[2])
                    gaps.append((gap, i))
                gaps.sort(key=lambda x: x[0], reverse=True)
                best_gap, best_idx = gaps[0]
                other_gaps = [g for g, _ in gaps[1:]]
                other_avg = sum(other_gaps) / len(other_gaps) if other_gaps else 0
                # 阈值：≥ 4px 且 > 其他典型字间距 1.5× → 才是逗号导致的真间隙
                if best_gap >= 4 and best_gap > other_avg * 1.5:
                    left_d = between_digits[best_idx]
                    right_d = between_digits[best_idx + 1]
                    cm = Glyph(
                        char=",",
                        bbox=(left_d.bbox[0] + left_d.bbox[2], left_d.bbox[1], best_gap, left_d.bbox[3]),
                    )
                    commas = [cm]
        # 三级兜底：逗号+间隙都没有，按位数中点硬切。
        # 真实场景：逗号被 blob 过滤掉（如 4 位 "3966" 实为 "(39,66)"），
        # 数字块间隙也相近 → 大间隙 fallback 拿不到。梦幻西游坐标常用：
        #   4 位 → 2+2（如 39,66）、6 位 → 3+3（如 248,100）、5 位 → 2+3
        if not commas:
            between_digits = sorted(
                [g for g in glyphs
                 if is_digit(g)
                 and min(ox, cp.bbox[0]) < g.bbox[0]
                 <= max(op_right, cp.bbox[0] + cp.bbox[2])],
                key=lambda g: g.bbox[0],
            )
            n = len(between_digits)
            if n >= 4:
                # 默认切分点（X 一般 ≤ Y 位数）
                if n == 4:
                    split = 2
                elif n == 5:
                    split = 2  # 2+3
                elif n == 6:
                    split = 3  # 3+3
                else:
                    split = n // 2
                left_d = between_digits[split - 1]
                right_d = between_digits[split]
                cm = Glyph(
                    char=",",
                    bbox=(left_d.bbox[0] + left_d.bbox[2], left_d.bbox[1], 1, left_d.bbox[3]),
                )
                commas = [cm]
                logger.debug(
                    f"extract_coord_spatial: 逗号被吞，按位数 {split}+{n - split} 硬切"
                )
        if not commas:
            continue
        cm = commas[0]
        cm_left = cm.bbox[0]
        cm_cy = cyc(cm)

        # 垂直跨度覆盖 '(' 与 ')' 两行（坐标换行时）
        y_top = min(oy, cp.bbox[1]) - 2
        y_bot = max(oy + oh, cp.bbox[1] + cp.bbox[3]) + 2

        # X：'(' 右 ~ 逗号左，跨度内
        x_digits = sorted(
            [
                g for g in glyphs
                if is_digit(g)
                and g.bbox[0] >= op_right
                and g.bbox[0] + g.bbox[2] <= cm_left
                and y_top <= cyc(g) <= y_bot
            ],
            key=lambda g: g.bbox[0],
        )
        # Y：逗号右 ~ （若 ')' 在逗号右侧则到 ')' 右界+容差；否则跨行换行到行尾）
        if cp.bbox[0] > cm_left:
            y_upper = cp.bbox[0] + cp.bbox[2] + 3
        else:
            y_upper = 10 ** 9
        y_digits = sorted(
            [
                g for g in glyphs
                if is_digit(g)
                # 同行 Y：逗号右侧 + ')' 范围内
                and (g.bbox[0] >= cm_left
                     and g.bbox[0] + g.bbox[2] <= y_upper
                     and abs(cyc(g) - cyc(cm)) <= 12)
                # 跨行 Y：逗号左侧（行 2 续接），y 与 '(' 不同行
                or (g.bbox[0] < cm_left
                    and abs(cyc(g) - op_cy) >= 12
                    and g.bbox[1] >= cp.bbox[1])
                and y_top <= cyc(g) <= y_bot
            ],
            # 跨行场景按"读图顺序"排序：先读完行 1（`(` 右侧 `,` 左侧），再读行 2
            # （`)` 左侧续接）。同 y 按 x 排序。避免行 2 数字（x 小）排到行 1 数字（x 大）前面。
            key=lambda g: (g.bbox[1], g.bbox[0]),
        )

        xs = "".join(g.char for g in x_digits)
        ys = "".join(g.char for g in y_digits)

        # 跨行续接（2026-08-04 23:52 live log）：
        # 面板过窄时坐标被换行拆开 —— 第一行尾部 "(109, 1"，第二行行首 "05)"。
        # 此时虚拟括号右侧没有更多数字，需检查下一行（y 约 +16px）行首是否有
        # 以 ')' 结尾的数字段，拼接到 Y 后面（"1" + "05" = "105"）。
        if cp_is_virtual and len(ys) == 1 and ys.isdigit() and xs.isdigit():
            nl_closes = [
                g for g in glyphs
                if is_close_paren(g)
                and g.bbox[0] > 0                       # 行首附近（换行后从行首开始）
                and g.bbox[0] < op_right + 20           # 不远离 '(' 所在列
                and abs(cyc(g) - (op_cy + 16)) <= 8     # 下一行（一行高约 16px）
            ]
            if nl_closes:
                nl_cp = min(nl_closes, key=lambda g: g.bbox[0])
                # 下一行 ')' 左侧紧邻的数字（与 ')' 同行、x 在 ')' 之前）
                cont = sorted(
                    [
                        g for g in glyphs
                        if is_digit(g)
                        and abs(cyc(g) - cyc(nl_cp)) <= 8
                        and g.bbox[0] < nl_cp.bbox[0]
                        and g.bbox[0] >= nl_cp.bbox[0] - 30  # 紧邻 ')'（数字串不超过 3 位）
                    ],
                    key=lambda g: g.bbox[0],
                )
                if cont:
                    cont_str = "".join(g.char for g in cont)
                    ys += cont_str
                    logger.debug(
                        f"extract_coord_spatial: 坐标跨行续接 Y += {cont_str!r} → {ys!r}"
                    )

        if xs.isdigit() and ys.isdigit():
            return (int(xs), int(ys))
    return None


def extract_coord_global(
    results: List[Optional["RecognitionResult"]],
) -> Optional[Tuple[int, int]]:
    """
    全括号扫描提取坐标 (X, Y) —— 用户思路的落地版。

    假设 `(X,Y)` 100% 就是坐标：不管 '(' ')' 落在第几行，只要括号框住的
    区域里存在数字对，就作为候选。收集**所有** '(' 候选逐一尝试，对每个
    '(' 找最佳 ')'（允许跨行，最多 3 行），把括号间所有数字按读图顺序
    拼成 (X串, Y串)，再用评分选出最像坐标的一对。

    与 extract_coord_spatial 的区别：
      - spatial 只试"第一个 '(' + 最近 ')'"，本函数穷举所有 '('
      - 本函数明确排除括号内混入中文的候选（如 `(当前第290次)`）
      - 本函数对跨行续接天然支持（`(66,10` + `3)` → (66, 103)）

    评分规则（可调常量）:
      +100  数字总位数 4~6（典型坐标 `(66,103)`=5 / `(248,100)`=6 / `(58,55)`=4）
      -50   数字总位数 1~3（易把进度数字 `(3,3)` 误识为坐标）
      +30   括号内存在字库 ',' 命中（说明逗号真实存在）
      -100  任一数字 > 200（高概率是进度计数，如 `第290次`）
      +20   跨行拼接（')' 与 '(' 不同行，说明坐标被换行拆开）
      +10   X、Y 都 ≤ 3 位（梦幻西游坐标范围 0~999）

    :param results: 一个或多个 RecognitionResult（通常 [黄色, 白色]），
                    按顺序独立尝试，取第一个成功结果
    :return: (x, y) 或 None
    """
    for r in results:
        if r is None:
            continue
        got = _extract_coord_global_from_glyphs(r.glyphs)
        if got is not None:
            return got
    return None


def _extract_coord_global_from_glyphs(
    glyphs: List[Glyph],
) -> Optional[Tuple[int, int]]:
    """从单通道 glyphs 中全括号扫描提取坐标（见 extract_coord_global）。"""
    if not glyphs:
        return None

    def _cyc(g: Glyph) -> float:
        return g.bbox[1] + g.bbox[3] / 2.0

    # '(' 候选：字库命中优先；UNKNOWN 窄高块几何兜底
    opens = [
        g for g in glyphs
        if g.char == "("
        or (g.char == "UNKNOWN" and 2 <= g.bbox[2] <= 6 and g.bbox[3] >= 9)
    ]
    # ')' 候选：字库命中优先；UNKNOWN 窄高块（高度 ≤14 排除面板装饰）
    char_closes = [
        g for g in glyphs if g.char == ")"
    ]
    unk_closes = [
        g for g in glyphs
        if g.char == "UNKNOWN" and 2 <= g.bbox[2] <= 6 and 9 <= g.bbox[3] <= 14
    ]
    if not opens or not (char_closes or unk_closes):
        return None

    def _close_score(op: Glyph, cl: Glyph) -> float:
        dx = abs(cl.bbox[0] - (op.bbox[0] + op.bbox[2]))
        dy = abs(_cyc(cl) - _cyc(op))
        return dx * 0.5 + dy * 2.0

    best: Optional[Tuple[int, int]] = None
    best_score: float = float("-inf")

    for op in opens:
        ox, oy, ow, oh = op.bbox
        op_right = ox + ow
        op_cy = _cyc(op)
        # 最佳 ')'：跨行最多 3 行（一行约 16px → dy ≤ 48）。
        # 字库命中的 ')' 绝对优先（真实 ')' 在字库中；UNKNOWN 仅兜底，
        # 否则跨行时行首的 ')'（dx 大）会被 '(' 右侧的 UNKNOWN 窄块抢走）。
        nearby_char = [
            c for c in char_closes if abs(_cyc(c) - op_cy) <= 48
        ]
        nearby_unk = [
            c for c in unk_closes
            if abs(_cyc(c) - op_cy) <= 48
            and abs(c.bbox[0] - op_right) <= 40  # 兜底块需贴近 '('
        ]
        if nearby_char:
            cp = min(nearby_char, key=lambda c: _close_score(op, c))
        elif nearby_unk:
            cp = min(nearby_unk, key=lambda c: _close_score(op, c))
        else:
            continue
        if _close_score(op, cp) >= 100:
            continue
        cxx, cyy, cww, chh = cp.bbox

        # 括号间内容收集：同行 / 跨行两种布局
        #   同行：op 行内 [op_right, cp_left)（cp 截断，避免收到 ')' 右侧中文）
        #   跨行：op 行 x >= op_right（行尾续接）+ cp 行 x <= cp_left（行首续接）
        # 这样天然避开 ')' 右侧的「处查明」等中文，也不依赖包围盒。
        if abs(_cyc(cp) - op_cy) <= 10:
            inside = [
                g for g in glyphs
                if abs(_cyc(g) - op_cy) <= 12
                and g.bbox[0] >= op_right
                and g.bbox[0] < cxx
            ]
        else:
            inside = [
                g for g in glyphs
                if abs(_cyc(g) - op_cy) <= 12
                and g.bbox[0] >= op_right
            ]
            inside += [
                g for g in glyphs
                if abs(_cyc(g) - _cyc(cp)) <= 12
                and g.bbox[0] + g.bbox[2] <= cxx
            ]
        # 去重（跨行时两段可能重叠，如 '3' 同时靠近 cp 与某数字）
        _uniq = set()
        _deduped = []
        for g in inside:
            k = (g.bbox[0], g.bbox[1], g.bbox[2], g.bbox[3], g.char)
            if k not in _uniq:
                _uniq.add(k)
                _deduped.append(g)
        inside = _deduped

        # 括号间有识别成功的中文（非标点/非数字/非 UNKNOWN）→ 不是坐标
        # 例：`(当前第290次)`（红通道不该传入，但白/黄通道兜底排除）
        has_cjk = any(
            g.char not in "(),UNKNOWN" and not g.char.isdigit() and g is not op and g is not cp
            for g in inside
        )
        if has_cjk:
            continue

        digits = sorted(
            [g for g in inside if g.char.isdigit()],
            key=lambda g: (g.bbox[1], g.bbox[0]),  # 读图顺序：先上后下，同行左→右
        )
        if not digits:
            continue
        commas = [g for g in inside if g.char == ","]
        has_comma = bool(commas)
        cross_line = abs(cyc_cp := _cyc(cp) - op_cy) > 10

        # ── UNKNOWN 窄块补位（0 变体未入库时防丢位）──
        # 用户 live log 2026-08-05 13:18：(130,47) 被识别成 (13,47)，
        # 因黄通道 `0` 是该渲染变体未入库 → UNKNOWN，digits 缺一位。
        # 若括号间存在「数字大小」的 UNKNOWN 窄高块（宽 2~6、高 9~14，
        # 与数字同行），它极可能是丢失的数字：把它插入 digits 的
        # 几何顺序位置，用占位符 '?' 参与拼接，切分后 '?' 处用 0~9
        # 穷举补全，与原始候选一起评分（带 '?' 的候选降分，仅当
        # 有 '?' 的补全结果合理才可能胜出）。
        unknown_narrow = [
            g for g in inside
            if g.char == "UNKNOWN"
            and 2 <= g.bbox[2] <= 6
            and 9 <= g.bbox[3] <= 14
            and abs(_cyc(g) - op_cy) <= 12  # 与 '(' 同行（坐标行）
            and g is not op and g is not cp
        ]
        # 只在无逗号（逗号常被吞）或逗号存在但 X 侧疑似缺位时启用补位
        if unknown_narrow and not commas:
            # 把 digits 与 UNKNOWN 窄块按读图顺序合并，'?' 占位
            merged = sorted(
                digits + unknown_narrow,
                key=lambda g: (g.bbox[1], g.bbox[0]),
            )
            # 检测 UNKNOWN 是否真的夹在数字之间（首尾是数字才算）
            has_q = merged[0].char.isdigit() and merged[-1].char.isdigit() \
                and any(g.char == "UNKNOWN" for g in merged)
            if has_q:
                num_with_q = "".join(g.char if g.char.isdigit() else "?" for g in merged)
                nq = len(num_with_q)
                if nq >= 4:
                    # 为每个 '?' 穷举 0~9 太贵（最多 1 个 '?' 才启用），
                    # 生成带 ? 的切分候选，在切分后逐 '?' 补 0~9
                    pass  # 具体补位逻辑在下方候选循环内处理
                else:
                    has_q = False
            else:
                has_q = False
        else:
            has_q = False

        # 候选坐标对列表：每个元素 (x_str, y_str, has_comma, cross_line)
        coord_candidates: List[Tuple[str, str, bool, bool]] = []

        if commas:
            cm = min(commas, key=lambda g: g.bbox[0])  # 取第一个逗号
            cm_cy = _cyc(cm)
            # X：与 '(' 同行（避免跨行续接数字混入 X），'(' 右侧 ~ 逗号左侧
            x_digits = [
                g for g in digits
                if abs(_cyc(g) - op_cy) <= 12
                and g.bbox[0] + g.bbox[2] <= cm.bbox[0]
            ]
            # Y（同行）：与逗号同行，逗号右侧，且紧贴逗号（真实 Y 数字串
            # 与逗号连续；远处同一水平线的干扰数字（如另一对括号）被排除）
            y_digits = [
                g for g in digits
                if abs(_cyc(g) - cm_cy) <= 12
                and g.bbox[0] >= cm.bbox[0] + cm.bbox[2]
                and g.bbox[0] - (cm.bbox[0] + cm.bbox[2]) <= 15
            ]
            if cross_line:
                # 跨行续接：逗号左侧、下一行行首的数字也属于 Y
                # （例 `(66,10` + 行2 `3)` → Y = "10" + "3" = "103"）
                for g in digits:
                    if (
                        g.bbox[0] + g.bbox[2] <= cm.bbox[0]
                        and abs(_cyc(g) - op_cy) >= 12
                    ):
                        y_digits.append(g)
                y_digits.sort(key=lambda g: (g.bbox[1], g.bbox[0]))
            xs = "".join(g.char for g in x_digits)
            ys = "".join(g.char for g in y_digits)
            coord_candidates.append((xs, ys, True, cross_line))
        else:
            # 无逗号：逗号 2×3px 常被连通域过滤掉，digit 序列按读图顺序
            # (y, x) 排序（跨行时行 2 的数字排后面，避免行首数字 x 小
            # 排到最前导致间隙计算错乱）。
            # 1) 优先「最大间隙分界」：逗号被吞但留下空隙，X/Y 交界处
            #    间隙明显大于普通字间距（如 130,47 → 间隙在 0|4 之间）。
            # 2) 间隙不显著 → 位数硬切兜底（4→2+2 / 6→3+3；5 位时
            #    (66,103) 需 2+3 而 (130,47) 需 3+2，两种都生成交给评分）。
            digits = sorted(digits, key=lambda g: (g.bbox[1], g.bbox[0]))
            num_str = "".join(g.char for g in digits)
            n = len(num_str)
            if n < 4:
                continue
            # 间隙只在同一行相邻数字之间计算（跨行数字不参与间隙比较）
            gaps = []
            for i in range(n - 1):
                a, b = digits[i], digits[i + 1]
                if abs(_cyc(a) - _cyc(b)) > 12:
                    continue  # 跨行：跳过，间隙仅同行的逗号位置有意义
                gap = b.bbox[0] - (a.bbox[0] + a.bbox[2])
                gaps.append((gap, i))
            gaps.sort(key=lambda x: x[0], reverse=True)
            best_gap, best_idx = gaps[0] if gaps else (0, -1)
            other_gaps = [g for g, _ in gaps[1:]]
            other_avg = sum(other_gaps) / len(other_gaps) if other_gaps else 0
            gap_is_real = best_gap >= 4 and best_gap > other_avg * 1.5
            if gap_is_real:
                split = best_idx + 1
                coord_candidates.append((num_str[:split], num_str[split:], False, cross_line))
            elif n in (4, 6):
                split = n // 2
                coord_candidates.append((num_str[:split], num_str[split:], False, cross_line))
            elif n == 5:
                # 5 位歧义：2+3 (66,103 / 251,23) vs 3+2 (130,47)。
                # 两种切法都生成交给评分/合理性过滤。先验上 2+3 更常见
                # （X 一般 ≤ Y 位数），但 (130,47) 是 3+2 —— 评分无法区分
                # 二者时按候选顺序取 2+3；若 2+3 因 x>999 被合理性过滤，
                # 则 3+2 胜出（如 130,47 的 "130" 若被吞 0 则位数变 4）。
                coord_candidates.append((num_str[:2], num_str[2:], False, cross_line))
                coord_candidates.append((num_str[:3], num_str[3:], False, cross_line))
            else:
                split = n // 2
                coord_candidates.append((num_str[:split], num_str[split:], False, cross_line))

            # UNKNOWN 补位：原始 digits 里缺位（如 0 变体未入库），
            # 把 '?' 占位串按同样切法生成候选，'?' 在评分循环内穷举补全。
            if has_q:
                # 按几何间隙/位数同样策略切 num_with_q
                _nq = len(num_with_q)
                if _nq in (4, 6):
                    _sp = _nq // 2
                    coord_candidates.append(
                        (num_with_q[:_sp], num_with_q[_sp:], False, cross_line)
                    )
                elif _nq == 5:
                    coord_candidates.append(
                        (num_with_q[:2], num_with_q[2:], False, cross_line)
                    )
                    coord_candidates.append(
                        (num_with_q[:3], num_with_q[3:], False, cross_line)
                    )

        for xs, ys, cand_has_comma, cand_cross in coord_candidates:
            if not (xs.isdigit() and ys.isdigit()):
                # 含 '?' 的候选：穷举补全（'?' 出现次数 ≤ 1 才启用）
                if ("?" in xs or "?" in ys) and (xs.count("?") + ys.count("?")) == 1:
                    for d in "0123456789":
                        xs_f = xs.replace("?", d)
                        ys_f = ys.replace("?", d)
                        if not (xs_f.isdigit() and ys_f.isdigit()):
                            continue
                        x, y = int(xs_f), int(ys_f)
                        if not (0 < x <= 999 and 0 < y <= 999):
                            continue
                        score = 100.0  # 位数 4~6
                        if cand_has_comma:
                            score += 30
                        if x > 200 or y > 200:
                            score -= 100
                        if cand_cross:
                            score += 20
                        if len(xs_f) <= 3 and len(ys_f) <= 3:
                            score += 10
                        # UNKNOWN 窄块补位不降分：该块已通过几何验证
                        # （数字大小 + 夹在数字之间），缺位是事实而非猜测。
                        # 0 丢失常见于 X 侧（X 3 位而 Y 2 位），`?` 在原始
                        # xs 时加几何证据分；`?` 在 ys（如 '13','?47'）则
                        # 不加，避免补位出 (13,47) 与原始候选平局抢占
                        # (130,47) 的位置。
                        if "?" in xs:
                            score += 5
                        if score > best_score:
                            best_score = score
                            best = (x, y)
                continue
            x, y = int(xs), int(ys)
            # 坐标合理性：梦幻西游坐标 1~999
            if not (0 < x <= 999 and 0 < y <= 999):
                continue

            # ── 评分 ──
            score = 0.0
            total_digits = len(xs) + len(ys)
            if 4 <= total_digits <= 6:
                score += 100
            else:
                score -= 50
            if cand_has_comma:
                score += 30
            if x > 200 or y > 200:
                score -= 100
            if cand_cross:
                score += 20
            if len(xs) <= 3 and len(ys) <= 3:
                score += 10

            if score > best_score:
                best_score = score
                best = (x, y)

    return best


# ======================================================================
# A. 当前坐标读取器
# ======================================================================

def _dedupe_neighbor_same_char(glyphs):
    """合并坐标区识别结果中相邻的同字符 blob。

    背景（user live log 2026-08-04 00:58 / 01:04）：
        游戏字体抗锯齿下，单独一个 "1" 常被 blob splitter 切成 2 个独立
        连通域（不同 hash 但 char 都是 "1"），于是 "19" 被识别成 "119"。
        同时，**真正相邻的两个字符**（如 "100" 里的两个 0）若间距太近也
        不能误去重。

    区分"同一字符的毛刺合并" vs "真实相邻字符去重"的关键：
      - 真字符高度（h）一致（游戏字模的 "0"/"1"/"9" 主体高度一致）
      - 毛刺高度通常比主体矮 ≥ 1px（抗锯齿残影）
      - 实测：'1' 真 h=12，'1' 毛刺 h=10（差 2）；'0' 真两个 h=10 一致

    合并规则（仅在以下条件同时满足时去掉后一个）：
      - char 相同
      - 垂直重叠 > 0（同一行）
      - x 间距 <= 5px（远小于正常字符间距 ~8~10px）
      - 第二个字符 h **严格小于**第一个 h（毛刺矮于主体；高度一致的真
        字符如 "100" 不会被误去重）

    :param glyphs: RecognitionResult.glyphs 列表（顺序无关）
    :return: 去重后的列表（按 x 升序）
    """
    if not glyphs:
        return glyphs
    sorted_g = sorted(glyphs, key=lambda g: g.bbox[0])
    result = [sorted_g[0]]
    # 标点不参与合并（避免 "1,1" 误去重 → "1,"）
    NON_DEDUPE = {"(", ")", "[", "]", ",", ".", ":", ";", "-", "+", " "}
    for g in sorted_g[1:]:
        last = result[-1]
        lx, ly, lw, lh = last.bbox
        gx, gy, gw, gh = g.bbox
        gap = gx - (lx + lw)
        vy_overlap = min(ly + lh, gy + gh) - max(ly, gy)
        # 毛刺判定：第二个字符 h 严格小于第一个（高度一致的真字符不去重）
        is_frag = gh < lh - 1   # gh 至少比 lh 矮 2px
        if (
            last.char == g.char
            and g.char not in NON_DEDUPE
            and gap <= 5
            and vy_overlap > 0
            and is_frag
        ):
            # 跳过重复字符（保留第一个主体）
            continue
        result.append(g)
    return result


class GlyphCoordReader:
    """
    字模坐标读取器 —— 读左上角「地图名[X,Y]」。

    用法::
        from core.glyph_coord_reader import glyph_coord_reader
        coord = glyph_coord_reader.read_coord()      # (248, 100) or None
        loc  = glyph_coord_reader.read_location()     # {'map':'长安城','x':248,'y':100}
    """

    def __init__(self):
        self._recognizer = GlyphRecognizer()
        self._last_result: Optional[RecognitionResult] = None
        self._last_location: Optional[dict] = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def read_coord(
        self, timeout: float = 3.0, retry_interval: float = 0.3
    ) -> Optional[Tuple[int, int]]:
        """读取当前坐标 (x, y)，兼容 ocr_coord_reader 签名。"""
        loc = self.read_location(timeout=timeout, retry_interval=retry_interval)
        if loc and "x" in loc and "y" in loc:
            return (loc["x"], loc["y"])
        return None

    def read_location(
        self, timeout: float = 3.0, retry_interval: float = 0.3
    ) -> Optional[dict]:
        """
        读取当前位置完整信息。
        :return: {'map':str, 'x':int, 'y':int, 'raw_text':str} 或 None
        """
        start = time.time()
        last_error = None
        while time.time() - start < timeout:
            try:
                result = self._do_recognize_coord()
                if result is not None:
                    return result
            except Exception as e:
                last_error = str(e)
                logger.debug(f"字模坐标读取异常: {e}")
            time.sleep(retry_interval)

        logger.warning(f"字模坐标读取超时({timeout}s): {last_error}")
        return None

    def read_raw(self) -> Optional[str]:
        """一次识别，返回原始文本（调试/建库用）。"""
        try:
            result = self._do_recognize_coord()
            return result.get("raw_text") if result else None
        except Exception as e:
            logger.debug(f"字模原始读取失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _do_recognize_coord(self) -> Optional[dict]:
        """截取左上角区域 → 白色字模识别 → 解析坐标。

        修复：识别后对相邻同字符 blob 做去重（"1" 被毛刺切成两个独立连通域
        → "19" 被误读成 "119" 的根因，见 user live log 2026-08-04 00:58）。

        画面异常检测（2026-08-04 23:57 user live log）：
            游戏切场景/传送时画面会**旋转 90 度**动画（瞬时几秒），坐标区字符
            被严重扭曲成"梯形/拉伸"，字模 hash 完全不匹配，错误地 fallback 到
            最接近的字符（如 "7"/"0"/"4"），导致 arrival_verifier 读到假坐标
            (7, 104) 而非真实 (109, 105)。正常 mask ~50-200px / 连通域 5-10，
            旋转时 mask >300px / 连通域 >14（字符断裂边缘产生大量小连通域）。
        """
        x, y, w, h = COORD_ROI
        img = screen_capture.capture_region(x, y, w, h)
        if img is None:
            logger.warning("字模坐标读取: 截图失败")
            return None

        # 修复：screen_capture 返回 BGR，但 apply_color_mask / 字模库假设 RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 画面异常检测：旋转/动画中字符被扭曲 → 边缘产生大量断裂/毛刺小连通域。
        # 主动返回 None 让 arrival_verifier 重试，而非传假坐标误导后续判定。
        # 2026-08-05 10:06 修正：**只认连通域数**——实测正常画面（建邺城[71,116]）
        # mask 像素 331px（>320 曾误杀！），旋转画面 348px，像素阈值无法区分；
        # 但正常画面连通域 5 个 vs 旋转画面 18 个，差异显著。去掉像素阈值。
        try:
            _mask = apply_color_mask(img, COORD_WHITE_RULE).astype(np.uint8) * 255
            _contours, _ = cv2.findContours(
                _mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            _n_contours = sum(
                1 for c in _contours if cv2.contourArea(c) >= 3
            )
            # 正常画面 ≤ 10 个连通域；旋转/动画 ≥ 15 个（字符断裂成碎片）
            if _n_contours > 14:
                logger.warning(
                    f"字模坐标读取: 画面异常 连通域={_n_contours}个"
                    f"（>14），疑似旋转/动画中，跳过识别"
                )
                return None
        except Exception as _e:
            # 检测失败不阻断正常识别流程
            logger.debug(f"画面异常检测异常: {_e}")

        result = self._recognizer.recognize(
            img, rule=COORD_WHITE_RULE, segmentation="single"
        )

        # 几何兜底 [ / ] (2026-08-05 00:02 user live log)：
        # 字模库里没有 '[' / ']' 样本时，UNKNOWN 块若形状是窄高 (w<=4, h>=11)
        # 则按上下文位置标记为 '['（坐标开头前）或 ']'（' )' 前）。
        # 这样 parse_location_text 不会因缺括号而把 X 第一位数字（'1'）误并入 Y。
        # 注：'1' 的抗锯齿新 hash (2298fce8) 仍需采集样本入库才能彻底识别。
        for i, g in enumerate(result.glyphs):
            if g.char != "UNKNOWN":
                continue
            _, _, w, h = g.bbox
            if not (w <= 4 and h >= 11):
                continue
            prev = result.glyphs[i - 1] if i > 0 else None
            nxt = result.glyphs[i + 1] if i + 1 < len(result.glyphs) else None
            if prev is None or (
                not prev.char.isdigit() and prev.char not in "([（"
            ):
                g.char = "["
            elif nxt and nxt.char == ")":
                g.char = "]"
            else:
                g.char = "["

        # [1 粘连块重新切分 (2026-08-05 00:16 user live log)：
        # 游戏渲染 `[108, 103]` 时 '[' 与 '1' 抗锯齿粘连成一个宽块（如 5x10），
        # 字模库把该块识别为 '['（或 UNKNOWN→几何兜底 '['），导致 X 第一位 '1' 被吞
        # → "108" 读成 "08"。对宽 >= 5px 的 '[' 块做垂直投影，找空白列切分成
        # '[' + 数字 两部分，恢复被吞的数字。
        _mask = _apply_color_mask(img, COORD_WHITE_RULE)
        _split_glyphs: List[Glyph] = []
        for g in result.glyphs:
            if g.char == "[" and g.bbox[2] >= 5:
                bx, by, bw, bh = g.bbox
                region = _mask[by:by + bh, bx:bx + bw]
                col_sum = region.sum(axis=0)
                empty_cols = [j for j in range(bw) if col_sum[j] < 2]
                if empty_cols:
                    # 取中间空白列分割（避免取到边缘空白）
                    mid = empty_cols[len(empty_cols) // 2]
                    if 1 < mid < bw - 1:
                        left = region[:, :mid]
                        right = region[:, mid:]
                        if left.sum() >= 3 and right.sum() >= 3:
                            lbmp, lhash = _normalize_bitmap(left, target_size=(32, 32))
                            rbmp, rhash = _normalize_bitmap(right, target_size=(32, 32))
                            lchar = self._recognizer.library.lookup(lhash)
                            rchar = self._recognizer.library.lookup(rhash)
                            # 右半必须是数字才采纳切分（否则保持原样）
                            if rchar and rchar.isdigit():
                                _split_glyphs.append(Glyph(
                                    char=lchar or "[",
                                    bbox=(bx, by, mid, bh),
                                    normalized_hash=lhash, bitmap=lbmp,
                                ))
                                _split_glyphs.append(Glyph(
                                    char=rchar,
                                    bbox=(bx + mid, by, bw - mid, bh),
                                    normalized_hash=rhash, bitmap=rbmp,
                                ))
                                logger.debug(
                                    f"字模坐标: [1 粘连块切分为 [{lchar!r}]+[{rchar!r}] "
                                    f"bbox=({bx},{by},{bw},{bh})"
                                )
                                continue
            _split_glyphs.append(g)
        if len(_split_glyphs) != len(result.glyphs):
            result.glyphs = _split_glyphs

        # 重算 raw_text / unknown_count（[ / ] 兜底后）
        result = RecognitionResult(
            glyphs=result.glyphs,
            raw_text="".join(g.char for g in result.glyphs),
            success=result.success,
            elapsed_ms=result.elapsed_ms,
            unknown_count=sum(1 for g in result.glyphs if g.char == "UNKNOWN"),
            debug_image_path=result.debug_image_path,
        )

        # 合并相邻同字符 blob（"1" 在抗锯齿下常被切成 2 个连通域）
        deduped = _dedupe_neighbor_same_char(result.glyphs)
        if len(deduped) != len(result.glyphs):
            result = RecognitionResult(
                glyphs=deduped,
                raw_text="".join(g.char for g in deduped),
                success=result.success,
                elapsed_ms=result.elapsed_ms,
                unknown_count=sum(
                    1 for g in deduped if g.char == "UNKNOWN"
                ),
                debug_image_path=result.debug_image_path,
            )
            logger.debug(
                f"字模坐标: 去重相邻同字符 blob "
                f"{len(result.glyphs)}→{len(deduped)}"
            )

        self._last_result = result

        text = result.raw_text.strip()
        if not text:
            return None

        loc = parse_location_text(text)
        if loc:
            loc["raw_text"] = text
            loc["unknown_count"] = result.unknown_count
            self._last_location = loc
            logger.debug(f'字模坐标: {loc["map"]}({loc["x"]},{loc["y"]})')
            return loc

        logger.debug(f'字模坐标: 文本="{text}" 无法解析')
        return {"map": "UNKNOWN", "raw_text": text, "unknown_count": result.unknown_count}

    @property
    def last_result(self) -> Optional[RecognitionResult]:
        return self._last_result

    @property
    def last_location(self) -> Optional[dict]:
        return self._last_location

    @property
    def library(self) -> GlyphLibrary:
        return self._recognizer.library

    def enable_debug(self, directory: str = None):
        if directory is None:
            directory = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "debug_glyph"
            )
        self._recognizer.set_debug_output(directory)

    def get_status(self) -> dict:
        return {
            "library_size": self.library.size,
            "has_last_location": self.last_location is not None,
            "last_location": self.last_location,
            "last_unknown_count": (
                self._last_result.unknown_count if self._last_result else None
            ),
        }


# ======================================================================
# B. JHRW 任务追踪栏读取器
# ======================================================================

class JHRWGlyphReader:
    """
    JHRW 任务信息字模读取器 —— 颜色分段提取任务详情。

    用法::
        from core.glyph_coord_reader import jhrw_reader
        info = jhrw_reader.read_quest()   # {'quest_name','target_location','target_coord',
                                          #  'npc_name','progress','raw':{...}}
    """

    def __init__(self):
        self._recognizer = GlyphRecognizer()
        self._last_result: Dict[str, RecognitionResult] = {}

    def read_quest(
        self, timeout: float = 3.0, retry_interval: float = 0.3
    ) -> Optional[dict]:
        """
        读取当前任务追踪栏的完整信息（按颜色分段）。

        :return: dict 或 None，结构如下::

            {
                'quest_name': '初出江湖',          # 红色文字
                'target_location': '江南野外',       # 黄色文字（目标地图）
                'target_coord': (105, 25),           # 白色文字中的坐标对
                'npc_name': '江湖大盗',             # 白/绿色文字
                'progress': 229,                     # 红色文字中的进度数字
                'instruction': '前往...处查明...的身份',  # 白色指令全文
                'raw': {
                    'yellow': '江南野外',
                    'red': '初出江湖...身份(当前第229次)',
                    'white': '前往江南野外(105,25)处查明江湖大盗的身份',
                    'green': '大盗',
                },
                'unknown_count': 0,
            }
        """
        start = time.time()
        last_error = None
        while time.time() - start < timeout:
            try:
                result = self._do_recognize_jhrw()
                if result is not None:
                    return result
            except Exception as e:
                last_error = str(e)
                logger.debug(f"JHRW字模读取异常: {e}")
            time.sleep(retry_interval)

        logger.warning(f"JHRW字模读取超时({timeout}s): {last_error}")
        return None

    def _do_recognize_jhrw(self, img: Optional[np.ndarray] = None) -> Optional[dict]:
        """按颜色分别提取 JHRW 文本段。

        :param img: 可选外部图像（BGR numpy 数组）。传入时跳过截屏，
                    直接识别该图（用于离线验证 / 测试）；为 None 时
                    从屏幕捕获客户区 JHRW_ROI 区域。
        """
        # 所有图像源（screen_capture 截屏、cv2.imread 文件）均返回 BGR，
        # 而下游 apply_color_mask / 字模库约定 RGB（channel0=R）。
        # 故无论来源统一在此转换为 RGB，消除隐藏的通道序不一致 bug。
        if img is None:
            x, y, w, h = get_jhrw_roi()
            img = screen_capture.capture_region(x, y, w, h)
            if img is None:
                logger.warning("JHRW字模读取: 截图失败")
                return None
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        raw = {}
        total_unknown = 0

        # ── 黄通道：地图名识别（坐标无关指纹 + 字符级回退）──
        # 始终先逐字识别：extract_coord_spatial 提取坐标也要用该结果
        _y_result = self._recognizer.recognize(
            img, rule=JHRW_YELLOW_RULE, segmentation="blobs"
        )
        self._last_result["yellow"] = _y_result

        # 1) 坐标无关整块指纹；2) 字符级子序列（抗中文断笔碎片）
        target_map = recognize_map_name_fingerprint(img, _y_result)
        if not target_map:
            target_map = _map_name_subsequence(_y_result)

        if target_map:
            raw["yellow"] = target_map
            total_unknown += 0
        else:
            raw["yellow"] = _y_result.raw_text.strip()
            total_unknown += _y_result.unknown_count
            logger.warning(
                f"JHRW黄通道地图名识别未命中，回退原始文本: "
                f'unknown={_y_result.unknown_count} text="{raw["yellow"]}"'
            )

        # ── 红绿白通道：逐字识别 ──
        # 红通道用单字模式（每个字=一条字库），其余通道沿用合并块模式。
        # 红字体较小，CJK 偶发断笔碎片；且红通道含多行文本（任务名+描述行），
        # single 模式按 x 排序会交错混排两行字符，故用顺序无关容错解析：
        #   quest_name ← 同时包含「初」和「出」即判定（不要求连续子串）
        #   progress   ← 正则 第(\d+) 搜索（已顺序无关）
        color_rules = [
            ("red", JHRW_RED_RULE, "single"),
            ("white", JHRW_WHITE_RULE, "blobs"),
            ("green", JHRW_GREEN_RULE, "blobs"),
        ]

        for name, rule, seg in color_rules:
            result = self._recognizer.recognize(img, rule=rule, segmentation=seg)
            self._last_result[name] = result
            raw[name] = result.raw_text.strip()
            total_unknown += result.unknown_count

        # 结构化解析
        red_text = raw["red"]
        # 顺序无关：红通道多行混排，「初出」不一定连续，分别检测两字
        quest_name = "初出江湖" if ("初" in red_text and "出" in red_text) else ""
        info = {
            "quest_name": quest_name,
            "target_location": target_map or raw["yellow"].replace("\n", " ").strip(),
            # 坐标只从黄通道提取！梦幻西游把地图名+坐标一起放在 #Y/ 黄色块
            # 渲染，白通道只有「前往」「处查明…的身份」等说明文字。
            # 白通道常含上一帧/残留的 `(3,3)` 残影（历史多次被它骗出假坐标），
            # 故 2026-08-05 起彻底移除白通道坐标兜底：黄通道失败就返回 None
            # 让上层重试，绝不拿白通道残影当坐标。
            "target_coord": (
                extract_coord_global([
                    self._last_result.get("yellow"),
                ])
                or extract_coord_spatial(self._last_result.get("yellow"))
                or parse_coord_pair(raw["yellow"])
            ),
            "npc_name": (raw["white"] + raw["green"]).replace("\n", " ").strip(),
            "progress": parse_progress_text(red_text),
            "instruction": raw["white"].replace("\n", " ").strip(),
            "raw": raw,
            "unknown_count": total_unknown,
        }

        # 清理 NPC 名（去掉指令前缀和坐标）
        if info["npc_name"]:
            info["npc_name"] = _clean_npc_name(info["npc_name"], info["instruction"])

        logger.debug(f'JHRW字模: quest={info["quest_name"]} '
                     f'target={info["target_location"]} '
                     f'coord={info["target_coord"]} '
                     f'progress={info["progress"]}')
        return info

    @property
    def last_raw(self) -> Dict[str, str]:
        """最后一次各颜色段的原始文本。"""
        return {k: v.raw_text for k, v in self._last_result.items()}

    def enable_debug(self, directory: str = None):
        if directory is None:
            directory = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "debug_glyph_jhrw"
            )
        self._recognizer.set_debug_output(directory)


def _clean_npc_name(npc_raw: str, instruction: str) -> str:
    """从原始白色+绿色文本中提取 NPC 名（去除指令前缀和坐标）。"""
    # 去掉常见指令前缀
    prefixes = ["前往", "找到", "寻找", "与", "帮助", "护送", "捉拿"]
    cleaned = npc_raw
    for p in prefixes:
        if cleaned.startswith(p):
            cleaned = cleaned[len(p):]
            break
    # 去掉坐标部分
    cleaned = re.sub(r"\(?\d+\s*[,，]\s*\d+\)?", "", cleaned).strip()
    # 去掉动词后缀
    suffixes = ["处查明", "的身份", "对话", "战斗", "交付", "领取"]
    for s in suffixes:
        if cleaned.endswith(s):
            cleaned = cleaned[: -len(s)]
            break
    return cleaned.strip() or npc_raw


# ======================================================================
# 全局单例
# ======================================================================

glyph_coord_reader = GlyphCoordReader()
jhrw_reader = JHRWGlyphReader()


# ======================================================================
# 便捷函数（兼容旧接口）
# ======================================================================

def read_coord_glyph(timeout: float = 3.0, retry_interval: float = 0.3) -> Optional[Tuple[int, int]]:
    """通过字模指纹读取游戏当前坐标（兼容 read_coord_ocr 签名）。"""
    return glyph_coord_reader.read_coord(timeout=timeout, retry_interval=retry_interval)


def is_glyph_available() -> bool:
    """字模读取器始终可用。"""
    return True


# ======================================================================
# 测试入口
# ======================================================================

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("字模坐标 + JHRW 读取器测试")
    print("=" * 60)

    mode = sys.argv[1] if len(sys.argv) > 1 else "coord"

    if mode in ("coord", "both"):
        print("\n--- A. 左上角坐标 ---")
        reader = GlyphCoordReader()
        reader.enable_debug()
        print(f"字模库大小: {reader.library.size}")

        loc = reader.read_location(timeout=5.0)
        if loc:
            print(f"\n识别结果:")
            for k, v in loc.items():
                print(f"  {k}: {v}")
        else:
            print("\n读取失败")

        if reader.last_result:
            r = reader.last_result
            print(f'\n原始文本: "{r.raw_text}"')
            print(f"字符数: {len(r.glyphs)}, 未知数: {r.unknown_count}")
            print(f"耗时: {r.elapsed_ms:.1f}ms")

    if mode in ("jhrw", "both"):
        print("\n--- B. JHRW 任务栏 ---")
        jr = JHRWGlyphReader()
        jr.enable_debug()

        info = jr.read_quest(timeout=5.0)
        if info:
            print(f"\n识别结果:")
            for k, v in info.items():
                if k != "raw":
                    print(f"  {k}: {v}")
            print(f"\n  各颜色段原文:")
            for color, text in info["raw"].items():
                print(f"    {color:>6}: {text!r}")
        else:
            print("\n读取失败")
