# -*- coding: utf-8 -*-
"""
字模指纹识别引擎 (Glyph Fingerprint Engine)。

原理：
    游戏使用固定点阵字体渲染 UI 文字，同一字符每次渲染的像素完全一致。
    因此「识别」退化为「位图 → hash → 字典查表」，是精确匹配，无阈值、无歧义。

    这不是 OCR。OCR 是统计模型（Tesseract/PaddleOCR），结构上给不了 100%。
    字模指纹是确定性查表，要么命中返回正确字符，要么明确报 UNKNOWN。

流水线：
    1. 截屏 / 接收图像
    2. 颜色精确掩码（提取目标颜色像素，排除背景）
    3. 连通域分析（findContours 切分独立字符）
    4. 归一化（统一尺寸、去边距、二值化）
    5. Hash 查表（md5 of 归一化位图 → 字符）
    6. 后处理（拼接文本、解析坐标格式）

依赖：仅 numpy + Pillow（OpenCV 可选，用于 findContours）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from utils.logger import logger


# ======================================================================
# 数据结构
# ======================================================================

@dataclass
class Glyph:
    """单个识别出的字符/符号。"""

    char: str              # 识别结果（'UNKNOWN' 表示库中无匹配）
    confidence: float = 1.0  # 确信度（字模匹配恒为 1.0，预留字段）
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (x, y, w, h) 原图坐标
    normalized_hash: str = ""  # 归一化位图的 md5
    bitmap: Optional[np.ndarray] = None  # 归一化后的二值位图 (H x W)


@dataclass
class RecognitionResult:
    """一次识别的结果。"""

    glyphs: List[Glyph] = field(default_factory=list)
    raw_text: str = ""           # 拼接后的原始文本
    success: bool = True
    elapsed_ms: float = 0
    unknown_count: int = 0       # UNKNOWN 字符数
    debug_image_path: Optional[str] = None  # 调试图路径（如有）


# ======================================================================
# 字模库
# ======================================================================

DEFAULT_GLYPH_LIB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "glyph_library.json"
)


class GlyphLibrary:
    """
    字模库（JSON 持久化）。

    结构::
        {
            "version": 1,
            "metadata": {"created": "...", "font_name": "..."},
            "entries": {
                "<md5_hex>": "长",      // hash -> 字符
                "<md5_hex>": "安",
                ...
            }
        }
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or DEFAULT_GLYPH_LIB_PATH
        self._entries: Dict[str, str] = {}  # md5 -> char
        self._reverse: Dict[str, str] = {}  # char -> md5 (用于快速查找已知字符)
        self._load()

    def _load(self):
        """从 JSON 加载字模库。"""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._entries = data.get("entries", {})
                self._reverse = {v: k for k, v in self._entries.items()}
                logger.info(f"字模库已加载: {len(self._entries)} 个字符, 路径={self._path}")
            except Exception as e:
                logger.warning(f"字模库加载失败: {e}, 将使用空库")
                self._entries = {}
                self._reverse = {}

    def save(self):
        """保存到 JSON。"""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            data = {
                "version": 1,
                "metadata": {
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "entry_count": len(self._entries),
                },
                "entries": self._entries,
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"字模库已保存: {len(self._entries)} 个字符")
        except Exception as e:
            logger.error(f"字模库保存失败: {e}")

    def lookup(self, md5_hex: str) -> Optional[str]:
        """通过 hash 查找字符。"""
        return self._entries.get(md5_hex)

    def add(self, md5_hex: str, char: str, autosave: bool = True) -> None:
        """添加一个字模条目。"""
        if md5_hex in self._entries and self._entries[md5_hex] != char:
            logger.warning(
                f"字模冲突: hash={md5_hex} 已映射到 '{self._entries[md5_hex]}', "
                f"新值 '{char}' 将覆盖"
            )
        self._entries[md5_hex] = char
        self._reverse[char] = md5_hex
        if autosave:
            self.save()

    def remove(self, md5_hex: str, autosave: bool = True) -> None:
        """删除一个字模条目。"""
        if md5_hex in self._entries:
            char = self._entries.pop(md5_hex)
            self._reverse.pop(char, None)
            if autosave:
                self.save()

    @property
    def size(self) -> int:
        return len(self._entries)

    def __contains__(self, char: str) -> bool:
        return char in self._reverse

    def __len__(self) -> int:
        return len(self._entries)

    def export_unknowns(
        self, unknown_glyphs: List[Glyph], output_dir: str
    ) -> List[str]:
        """
        将未识别的字模导出为独立 PNG 文件，供人工标注后回填。

        :return: 导出的文件路径列表
        """
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        ts = time.strftime("%H%M%S")
        for i, g in enumerate(unknown_glyphs):
            if g.bitmap is not None:
                fname = f"unknown_{ts}_{i:02d}_hash_{g.normalized_hash[:8]}.png"
                fpath = os.path.join(output_dir, fname)
                # 放大 4 倍便于肉眼查看
                img = Image.fromarray((g.bitmap * 255).astype(np.uint8))
                img = img.resize((img.width * 4, img.height * 4), Image.NEAREST)
                img.save(fpath)
                paths.append(fpath)
        return paths


# ======================================================================
# 颜色掩码规则（从游戏截图精确采样）
# ======================================================================

@dataclass
class ColorMaskRule:
    """颜色掩码规则。"""

    name: str                          # 规则名称
    # RGB 精确值（精确匹配模式）
    exact_rgb: Optional[Tuple[int, int, int]] = None
    # RGB 范围约束（范围匹配模式，与 exact_rgb 二选一）
    r_min: int = 0
    r_max: int = 255
    g_min: int = 0
    g_max: int = 255
    b_min: int = 0
    b_max: int = 255
    # 容差（当设置 exact_rgb 时自动生成范围）
    tolerance: int = 0
    # 最小面积过滤（像素数）
    min_area: int = 0


# ── 区域 A：左上角当前坐标 (15,19)-(147,43) ──
# 内容：地图名[ X , Y ]  全部白色 #FFFFFF

COORD_WHITE_RULE = ColorMaskRule(
    name="coord_white",
    exact_rgb=(255, 255, 255),
    tolerance=0,  # 精确纯白
)


# ── 区域 B：JHRW 任务追踪栏 (837,120)-(996,236) ──
# 游戏颜色码渲染后映射为精确纯色：
#   #Y/ → #FFFF00 黄色（目标地图名）
#   #R  → #FF0000 红色（任务名、进度）
#   #W  → #FFFFFF 白色（指令文字、NPC名、坐标数字）
#   #G  → #00FF00 绿色（NPC名部分）

# 游戏实际渲染非纯色（抗锯齿导致通道偏移）。实测：
#   YELLOW mean=(243,243,17) 边界(156,154,0)~(255,255,123) —— 非纯黄，须范围模式
#   RED    mean=(225,26,21)   边界(151,0,0)~(255,123,79)   —— 核心够纯，精确±0 可用
#   WHITE  mean=(252,252,249) 边界(220,225,204)            —— 接近纯白，精确±0 可用
#   GREEN  mean=(0,255,0)                                   —— 纯绿，精确±0 可用
# 2026-08-05 放宽：r_min/g_min 180→140，b_max 140→170，让弱抗锯齿的 `3`（任务目标末位）
# 也能进入 mask。背景绿色 R=50-60 仍被 (R>=140) 过滤，不会误识。
JHRW_YELLOW_RULE = ColorMaskRule(
    name="jhrw_yellow",       # 目标地图名（如"江南野外"）+ 任务目标坐标
    r_min=140, r_max=255,
    g_min=140, g_max=255,
    b_min=0, b_max=170,
)

JHRW_RED_RULE = ColorMaskRule(
    name="jhrw_red",          # 任务名（如"初出江湖"）+ 进度
    exact_rgb=(255, 0, 0),
    tolerance=0,
)

JHRW_WHITE_RULE = ColorMaskRule(
    name="jhrw_white",        # 指令、NPC名、坐标数字
    exact_rgb=(255, 255, 255),
    tolerance=0,
)

JHRW_GREEN_RULE = ColorMaskRule(
    name="jhrw_green",        # NPC 名部分
    exact_rgb=(0, 255, 0),
    tolerance=0,
)

# 组合规则：JHRW 区域所有非黑色文字（用于整栏提取）
JHRW_ALL_TEXT_RULE = ColorMaskRule(
    name="jhrw_all_text",
    r_min=200, r_max=255,
    g_min=0, g_max=255,
    b_min=0, b_max=255,
    min_area=10,
)


def apply_color_mask(
    image: np.ndarray, rule: ColorMaskRule
) -> np.ndarray:
    """
    应用颜色掩码规则，返回二值掩码 (bool array, H x W)。

    支持两种模式：
      1. exact_rgb + tolerance：精确匹配（容差内算命中）
      2. r/g/b_min~max：范围匹配

    :param image: RGB numpy 数组 (H x W x 3)
    :param rule: 颜色掩码规则
    :return: bool 掩码，True = 目标颜色像素
    """
    r = image[:, :, 0].astype(np.int32)
    g = image[:, :, 1].astype(np.int32)
    b = image[:, :, 2].astype(np.int32)

    if rule.exact_rgb is not None:
        # 精确匹配模式（带容差）
        tr, tg, tb = rule.exact_rgb
        tol = rule.tolerance
        mask = (
            (np.abs(r - tr) <= tol)
            & (np.abs(g - tg) <= tol)
            & (np.abs(b - tb) <= tol)
        )
    else:
        # 范围匹配模式
        mask = (
            (r >= rule.r_min) & (r <= rule.r_max)
            & (g >= rule.g_min) & (g <= rule.g_max)
            & (b >= rule.b_min) & (b <= rule.b_max)
        )

    return mask


# ======================================================================
# 连通域切字
# ======================================================================

def extract_glyph_blobs(
    binary_mask: np.ndarray,
    min_width: int = 2,
    min_height: int = 4,      # 提高最小高度过滤噪声
    max_width: int = 60,
    max_height: int = 60,
    min_area: int = 8,        # 最小像素面积（过滤 2x2 噪点）
    sort_by: str = "x_asc",  # "x_asc" | "y_asc"
) -> List[Tuple[int, int, int, int, np.ndarray]]:
    """
    从二值掩码中提取连通域（字符候选）。

    使用 floodFill 或 findContours 分割连通区域。
    优先用 OpenCV findContours（快），回退到纯 numpy 实现。

    :param binary_mask: 二值掩码 (bool 或 uint8)
    :param min_width/min_height: 过滤太小的噪点
    :param max_width/max_height: 过滤太大的区域（非单字符）
    :param sort_by: 排序方式
    :return: [(x, y, w, h, crop_mask), ...] 按 x 坐标排序
    """
    blobs = []

    try:
        import cv2

        mask_uint8 = (binary_mask.astype(np.uint8)) * 255
        contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w < min_width or h < min_height or w > max_width or h > max_height:
                continue
            # 裁剪后检查实际像素面积（不用 cv2.contourArea，它对细笔画严重低估）
            crop = binary_mask[y : y + h, x : x + w].copy()
            if crop.sum() < min_area:
                continue
            blobs.append((int(x), int(y), int(w), int(h), crop))

    except ImportError:
        # 无 OpenCV 时用纯 numpy 实现（较慢但可用）
        blobs = _extract_blobs_numpy(
            binary_mask, min_width, min_height, max_width, max_height, min_area
        )

    # 排序
    if sort_by == "x_asc":
        blobs.sort(key=lambda b: b[0])
    elif sort_by == "x_desc":
        blobs.sort(key=lambda b: b[0], reverse=True)
    elif sort_by == "y_asc":
        blobs.sort(key=lambda b: b[1])

    return blobs


def segment_characters(
    mask: np.ndarray,
    gap_threshold: int = 2,
    min_width: int = 2,
    min_height: int = 3,
    max_width: int = 80,
    max_height: int = 80,
    min_area: int = 3,
    sort_by: str = "x_asc",
) -> List[Tuple[int, int, int, int, np.ndarray]]:
    """
    按「列间隙」把单行文字切成字符。

    与 extract_glyph_blobs（连通域）不同：这里把**水平方向上间隙小于
    gap_threshold 列的连通域合并成一个字符**。这样中文字符的断笔碎片
    （如「城」= 土+成、「安」的宝盖点）会被合并成完整的一个字符位图，
    从根本上消除碎片问题（不再需要 `_` 后缀丢弃规则）。

    前提：待切分文字是「单行」的（坐标区满足；JHRW 多行面板不适用）。

    :param mask: 二值掩码 (bool, H x W)
    :param gap_threshold: 列间隙 >= 此值才切分；小于则视为同一字符
    :return: [(x, y, w, h, crop), ...] 按 x 排序
    """
    col_has = mask.any(axis=0)
    h, w = mask.shape
    segs: List[Tuple[int, int, int, int, np.ndarray]] = []
    i = 0
    while i < w:
        if col_has[i]:
            last_ink = i
            k = i
            while k < w:
                if col_has[k]:
                    last_ink = k
                    k += 1
                else:
                    # 向前看空列长度
                    kk = k
                    while kk < w and not col_has[kk]:
                        kk += 1
                    if kk - k >= gap_threshold:
                        break
                    k = kk
            x0, x1 = i, last_ink
            sub = mask[:, x0 : x1 + 1]
            rows_has = sub.any(axis=1)
            if rows_has.any():
                y0 = int(np.where(rows_has)[0][0])
                y1 = int(np.where(rows_has)[0][-1])
                cw = x1 - x0 + 1
                ch = y1 - y0 + 1
                if (
                    min_width <= cw <= max_width
                    and min_height <= ch <= max_height
                    and int(sub.sum()) >= min_area
                ):
                    crop = mask[y0 : y1 + 1, x0 : x1 + 1].copy()
                    segs.append((x0, y0, cw, ch, crop))
            i = last_ink + 1
        else:
            i += 1

    if sort_by == "x_asc":
        segs.sort(key=lambda s: s[0])
    elif sort_by == "x_desc":
        segs.sort(key=lambda s: s[0], reverse=True)
    return segs


def segment_single_chars(
    mask: np.ndarray,
    frag_w: int = 4,
    cjk_h: int = 12,
    gap_px: int = 1,
    min_width: int = 2,
    min_height: int = 3,
    max_width: int = 40,
    max_height: int = 60,
    min_area: int = 2,
    sort_by: str = "x_asc",
) -> List[Tuple[int, int, int, int, np.ndarray]]:
    """
    单字切分：每个独立汉字/数字/标点 = 一条字库。

    原理：先用连通域取出所有笔画块，再向右合并「断裂笔碎片」(断笔)，
    但不合并「相邻整字」。

    区分断笔 vs 相邻整字的关键（实测自游戏点阵字体）：
      - 字符之间的列间隙 >= 2px（城|(、3|,、,|1、1|2 都是 2~4px）
      - 断笔碎片与主体的列间隙 == 1px（邺的离体笔画、9|3、1|1 是 1px）
        → 仅在 gap <= gap_px(1) 时才考虑合并
      - 汉字高 ~13~14px（=CJK），数字/标点矮 ~10px（=非CJK）
      - 断笔碎片很窄（w <= frag_w，实测邺离体笔画 w=4）
      → 合并条件：gap<=1 且 (当前是CJK高字 且 右邻是窄碎片)
                     或 (右邻是CJK高字 且 当前是窄碎片)
      → 数字（矮、且 9/3/1 宽>=5）绝不会触发合并，9|3、1|1 保持分离
      → 汉字（高）只合并其 1px 紧贴的窄断笔，建/邺/城 各自独立成字

    :return: [(x, y, w, h, crop), ...] 按 x 排序，每个元素是一个独立字符
    """
    # 合并逻辑（断笔合并）必须左→右遍历才正确，故此处固定升序提取；
    # 最终输出顺序由末尾按请求的 sort_by 重排。
    comps = extract_glyph_blobs(
        mask, min_width=min_width, min_height=min_height,
        max_width=max_width, max_height=max_height, min_area=min_area,
        sort_by="x_asc",
    )
    if not comps:
        return []

    result_bbox = []  # (x0, y0, w, h)
    cur_x, cur_y, cur_w, cur_h = comps[0][:4]

    def _is_cjk(w0, h0):
        return h0 >= cjk_h

    def _is_frag(w0):
        return w0 <= frag_w

    for k in range(1, len(comps)):
        x, y, w, h, _crop = comps[k]
        cur_x1, cur_y1 = cur_x + cur_w, cur_y + cur_h
        gap = x - cur_x1
        if gap <= gap_px:
            cur_cjk, nxt_cjk = _is_cjk(cur_w, cur_h), _is_cjk(w, h)
            cur_frag, nxt_frag = _is_frag(cur_w), _is_frag(w)
            # 仅当一侧是「高汉字」且另一侧是「窄碎片」时才合并（= 断笔）
            if (cur_cjk and nxt_frag) or (nxt_cjk and cur_frag):
                vy_overlap = min(cur_y1, y + h) - max(cur_y, y)
                if vy_overlap > 0:
                    nx0 = min(cur_x, x)
                    ny0 = min(cur_y, y)
                    nx1 = max(cur_x1, x + w)
                    ny1 = max(cur_y1, y + h)
                    cur_x, cur_y, cur_w, cur_h = nx0, ny0, nx1 - nx0, ny1 - ny0
                    continue
        # 否则结束当前字，开始下一个
        result_bbox.append((cur_x, cur_y, cur_w, cur_h))
        cur_x, cur_y, cur_w, cur_h = x, y, w, h
    result_bbox.append((cur_x, cur_y, cur_w, cur_h))

    out = []
    for (x0, y0, w, h) in result_bbox:
        crop = mask[y0:y0 + h, x0:x0 + w].copy()
        out.append((x0, y0, w, h, crop))
    if sort_by == "x_desc":
        out.sort(key=lambda s: s[0], reverse=True)
    return out


def _extract_blobs_numpy(
    mask: np.ndarray,
    min_w: int, min_h: int, max_w: int, max_h: int,
    min_area: int = 8,
) -> List[Tuple[int, int, int, int, np.ndarray]]:
    """纯 numpy 的连通域提取（OpenCV 不可用时的降级方案）。"""
    from scipy.ndimage import label as scipy_label

    labeled, n_features = scipy_label(mask)
    blobs = []
    for i in range(1, n_features + 1):
        ys, xs = np.nonzero(labeled == i)
        if len(xs) == 0 or len(xs) < min_area:
            continue
        x0, y0 = int(xs.min()), int(ys.min())
        x1, y1 = int(xs.max()), int(ys.max())
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if w < min_w or h < min_h or w > max_w or h > max_h:
            continue
        crop = mask[y0:y1 + h, x0:x1 + w].copy()
        blobs.append((x0, y0, w, h, crop))
    return blobs


# ======================================================================
# 归一化 & Hash
# ======================================================================

def normalize_bitmap(
    crop_mask: np.ndarray,
    target_size: Tuple[int, int] = None,  # None = 使用精确尺寸（不缩放）
    padding: int = 1,
) -> Tuple[np.ndarray, str]:
    """
    将字符裁剪归一化为二值位图，计算其 md5。

    策略（target_size=None 时，精确模式）：
        1. 去除全零边距（trim）
        2. 加 1px padding 边框
        3. 直接 hash（不缩放，保留每个像素 → 零碰撞）

    策略（指定 target_size 时，缩放模式）：
        1. trim → 居中到 target_size → 最近邻缩放 → hash

    :param crop_mask: 字符裁剪区域 (bool array, H x W)
    :param target_size: 目标尺寸 (W, H)，None 表示精确模式
    :param padding: 内边距
    :return: (normalized_bitmap, md5_hex_string)
    """
    # 找内容边界
    rows = np.any(crop_mask, axis=1)
    cols = np.any(crop_mask, axis=0)
    if not rows.any() or not cols.any():
        empty = np.zeros((8, 8), dtype=np.uint8)
        return empty, hashlib.md5(empty.tobytes()).hexdigest()

    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    content = crop_mask[rmin : rmax + 1, cmin : cmax + 1]

    ch, cw = content.shape

    if target_size is not None:
        # 缩放模式：归一化到固定尺寸
        tw, th = target_size
        avail_w, avail_h = tw - 2 * padding, th - 2 * padding
        scale = min(avail_w / cw, avail_h / ch) if (cw > 0 and ch > 0) else 1.0
        new_cw = max(1, int(cw * scale))
        new_ch = max(1, int(ch * scale))

        img = Image.fromarray((content.astype(np.uint8)) * 255)
        img = img.resize((new_cw, new_ch), Image.NEAREST)
        scaled = (np.array(img) > 128).astype(np.uint8)

        canvas = np.zeros(target_size, dtype=np.uint8)
        offset_x = (tw - new_cw) // 2
        offset_y = (th - new_ch) // 2
        canvas[offset_y:offset_y + new_ch, offset_x:offset_x + new_cw] = scaled
        md5 = hashlib.md5(canvas.tobytes()).hexdigest()
        return canvas, md5
    else:
        # 精确模式：保留原始尺寸，只加 padding
        padded_h, padded_w = ch + 2 * padding, cw + 2 * padding
        canvas = np.zeros((padded_h, padded_w), dtype=np.uint8)
        canvas[padding:padding + ch, padding:padding + cw] = content.astype(np.uint8)
        md5 = hashlib.md5(canvas.tobytes()).hexdigest()
        return canvas, md5


# ======================================================================
# 主引擎
# ======================================================================

class GlyphRecognizer:
    """
    字模指纹识别引擎。

    用法::

        engine = GlyphRecognizer()
        result = engine.recognize(image_rgb, rule=COORD_WHITE_RULE)
        for g in result.glyphs:
            print(g.char, end='')
        print()  # 识别出的文本
    """

    def __init__(self, library: Optional[GlyphLibrary] = None):
        self.library = library or GlyphLibrary()
        self._debug_dir: Optional[str] = None

    def set_debug_output(self, directory: str) -> None:
        """启用调试输出（保存中间结果的图像）。"""
        self._debug_dir = directory
        os.makedirs(directory, exist_ok=True)

    def recognize(
        self,
        image: np.ndarray,
        rule: ColorMaskRule = COORD_WHITE_RULE,
        return_unknowns: bool = True,
        segmentation: str = "blobs",
        x_order: str = "asc",
    ) -> RecognitionResult:
        """
        对图像执行一次完整的字模识别。

        :param image: RGB numpy 数组 (H x W x 3)
        :param rule: 颜色掩码规则
        :param return_unknowns: 是否在结果中保留 UNKNOWN 字符
        :param segmentation: "blobs"（连通域，默认，适合多行/彩色面板）
                              "columns"（按列间隙，适合单行坐标区，自动合并断笔碎片）
                              "single"（单字切分：每个汉字/数字/标点 = 一条字库，
                               合并 1px 断笔碎片但不合并相邻整字，适合左上角坐标区）
        :param x_order: "asc"（左→右，适合左上角坐标区/左对齐文本）
                        "desc"（右→左，适合右上角右对齐任务追踪面板）
        :return: RecognitionResult
        """
        t0 = time.perf_counter()

        # Step 1: 颜色掩码
        mask = apply_color_mask(image, rule)

        # Step 2: 切字
        sort_by = "x_desc" if x_order == "desc" else "x_asc"
        if segmentation == "columns":
            blobs = segment_characters(mask, sort_by=sort_by)
        elif segmentation == "single":
            blobs = segment_single_chars(mask, sort_by=sort_by)
        else:
            blobs = extract_glyph_blobs(mask, sort_by=sort_by)

        # Step 3+4: 归一化 + Hash + 查表
        glyphs: List[Glyph] = []
        unknowns: List[Glyph] = []

        for x, y, w, h, crop in blobs:
            # 使用 32x32 长宽比保留归一化：对 1px 渲染抖动鲁棒，且能区分 6/8 等相似数字
            norm_bitmap, md5_hex = normalize_bitmap(crop, target_size=(32, 32))
            char = self.library.lookup(md5_hex)

            glyph = Glyph(
                char=char if char else "UNKNOWN",
                bbox=(x, y, w, h),
                normalized_hash=md5_hex,
                bitmap=norm_bitmap,
            )

            if char:
                glyphs.append(glyph)
            elif return_unknowns:
                unknowns.append(glyph)
                glyphs.append(glyph)

        # Step 4.5: 过滤断笔碎片（中文字符名含 '_' 的为笔画片段）
        glyphs = [g for g in glyphs if not (g.char and "_" in g.char)]
        unknowns = [g for g in unknowns if not (g.char and "_" in g.char)]

        # Step 5: 拼接文本
        raw_text = "".join(g.char for g in glyphs)

        elapsed = (time.perf_counter() - t0) * 1000
        result = RecognitionResult(
            glyphs=glyphs,
            raw_text=raw_text,
            success=(len(unknowns) == 0),
            elapsed_ms=elapsed,
            unknown_count=len(unknowns),
        )

        # 调试输出
        if self._debug_dir:
            self._save_debug_images(image, mask, result)

        logger.debug(
            f"字模识别: {len(glyphs)}个字符, "
            f"{len(unknowns)}个未知, "
            f"耗时{elapsed:.1f}ms, "
            f'文本="{raw_text}"'
        )

        return result

    def recognize_region(
        self,
        screen_capture_func,
        region: Tuple[int, int, int, int],
        rule: ColorMaskRule = COORD_WHITE_RULE,
    ) -> RecognitionResult:
        """
        便捷方法：截取指定区域并识别。

        :param screen_capture_func: callable(x,y,w,h) -> RGB ndarray 或 None
        :param region: (x, y, w, h) 客户区相对坐标
        :param rule: 颜色掩码规则
        """
        x, y, w, h = region
        img = screen_capture_func(x, y, w, h)
        if img is None:
            return RecognitionResult(success=False, raw_text="", glyphs=[])
        return self.recognize(img, rule)

    def _save_debug_images(
        self, original: np.ndarray, mask: np.ndarray, result: RecognitionResult
    ):
        """保存调试图像。"""
        if not self._debug_dir:
            return
        ts = time.strftime("%H%M%S")

        # 原始 ROI
        Image.fromarray(original).save(os.path.join(self._debug_dir, f"{ts}_roi.png"))

        # 掩码
        Image.fromarray((mask.astype(np.uint8)) * 255).save(
            os.path.join(self._debug_dir, f"{ts}_mask.png")
        )

        # 标注图（原图上画框）
        import cv2
        annotated = original.copy()
        for g in result.glyphs:
            bx, by, bw, bh = g.bbox
            color = (0, 255, 0) if g.char != "UNKNOWN" else (0, 0, 255)
            cv2.rectangle(annotated, (bx, by), (bx + bw, by + bh), color, 1)
            cv2.putText(
                annotated, g.char, (bx, by - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1,
            )
        Image.fromarray(annotated).save(
            os.path.join(self._debug_dir, f"{ts}_annotated.png")
        )

        result.debug_image_path = os.path.join(self._debug_dir, f"{ts}_annotated.png")


# ======================================================================
# 全局默认实例
# ======================================================================

_default_recognizer: Optional[GlyphRecognizer] = None


def get_glyph_recognizer() -> GlyphRecognizer:
    """获取全局字模识别器实例。"""
    global _default_recognizer
    if _default_recognizer is None:
        _default_recognizer = GlyphRecognizer()
    return _default_recognizer
