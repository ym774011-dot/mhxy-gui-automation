"""门派闯关任务识别器

从游戏任务栏 ROI(150x113/131) 识别:
  - 地图名（黄色字，通过整词模板匹配，15 张 BMP 模板）
  - 完成次数（红色数字 0-9，通过字模库）

输出格式: "{地图名}，{n次}"

设计要点（吸取反挂机验证码教训）：
  - 绝不依赖 OCR（"天宫"会被识别成"夭宫"）
  - 地图名 = 文件名拼音→中文真值映射 + cv2 整词模板匹配
  - 数字 = 列间隙切字符 + md5 查字模库
"""
import os, hashlib
from functools import lru_cache
import cv2
import numpy as np

# ===== 配置 =====
# 项目内模板目录（2026-08-10 内化：从外部目录复制 15 张 BMP 到 assets/game_data/门派闯关/）
# 优先使用项目内路径；外部目录存在时也可用（兼容旧引用）
_PROJ_BMP_DIR = os.path.join(os.path.dirname(__file__), '..', 'assets', 'game_data', '门派闯关')
_EXT_BMP_DIR = r'E:/DS/梦幻西游脚本函数包/地图数据/字库图片'
BMP_DIR = _PROJ_BMP_DIR if os.path.isdir(_PROJ_BMP_DIR) else _EXT_BMP_DIR
LIB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'glyph_library.json')

# 文件名 → 中文地图名（真值，整词模板匹配的标签）
MAP_NAMES = {
    'dt':   '大唐官府',
    'fcs':  '方寸山',
    'hss':  '化生寺',
    'lbc':  '凌波城',
    'lg':   '龙宫',
    'mw':   '魔王寨',
    'nrc':  '女儿村',
    'psd':  '普陀山',
    'pts':  '盘丝洞',
    'sml':  '神木林',
    'stl':  '狮驼岭',
    'tg':   '天宫',
    'wdd':  '无底洞',
    'wz':   '五庄观',
    'ycdf': '阴曹地府',
    'hgs': '花果山',
}

# 颜色阈值（与 add_sect_glyphs.py 保持一致）
RED_RANGES = [
    ((0, 100, 100), (10, 255, 255)),
    ((170, 100, 100), (180, 255, 255)),
]
YELLOW_RANGES = [
    ((20, 80, 80), (35, 255, 255)),
]

# 数字识别阈值（可配置：游戏改版/换字体时调整这里，无需改算法）
DIGIT_Y_TOP = 80        # 数字区起始行（"成功完成了N次考验" 区域）
DIGIT_W_MIN = 3         # 单数字最小宽度（px）
DIGIT_W_MAX = 8         # 单数字最大宽度（px，汉字"次"更宽会被排除）
DIGIT_BITMAP_SIZE = 14  # 归一化位图尺寸（与字模库 md5 计算一致）


def _color_mask(hsv, ranges):
    m = np.zeros(hsv.shape[:2], dtype=bool)
    for (lo, hi) in ranges:
        m |= cv2.inRange(hsv, np.array(lo), np.array(hi)) > 0
    return m


@lru_cache(maxsize=1)
def _load_templates():
    """加载 15 张 BMP 模板，返回 [(filename, map_name, gray, shape)] 列表。

    用 lru_cache 缓存：模板文件不变时只读盘一次（任务循环每帧调用也不重复 IO）。
    需要热重载（如新增 BMP 后）时调用 _load_templates.cache_clear()。
    """
    from PIL import Image
    templates = []
    for fname in sorted(os.listdir(BMP_DIR)):
        if not fname.endswith('.bmp'):
            continue
        key = fname[:-4]
        if key not in MAP_NAMES:
            continue
        map_name = MAP_NAMES[key]
        img = np.array(Image.open(os.path.join(BMP_DIR, fname)).convert('RGB'))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        templates.append((fname, map_name, gray, img.shape[:2]))
    return templates


def _extract_red_digits(img_bgr):
    """提取底部红字数字字符，按列间隙切字符，返回 [(x, bitmap), ...]。

    bitmap: 居中归一化到 14x14 的字符位图（与字模库格式一致）。
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    red = _color_mask(hsv, RED_RANGES)
    H, W = red.shape
    bottom = red[DIGIT_Y_TOP:H]
    col_has = bottom.any(axis=0)
    runs = []
    in_run = False
    start = 0
    for c in range(W):
        if col_has[c] and not in_run:
            start = c
            in_run = True
        elif not col_has[c] and in_run:
            runs.append((start, c - 1))
            in_run = False
    if in_run:
        runs.append((start, W - 1))

    digit_chars = []
    for (cs, ce) in runs:
        width = ce - cs + 1
        if not (DIGIT_W_MIN <= width <= DIGIT_W_MAX):  # 单数字宽度（汉字"次"宽度更大）
            continue
        ys = np.where(bottom[:, cs:ce + 1].any(axis=1))[0]
        if len(ys) == 0:
            continue
        y_top = DIGIT_Y_TOP + ys[0]
        h = DIGIT_Y_TOP + ys[-1] - y_top + 1
        roi_mask = red[y_top:y_top + h, cs:cs + width]
        rows = np.any(roi_mask, axis=1)
        cols = np.any(roi_mask, axis=0)
        if not rows.any() or not cols.any():
            continue
        r0, r1 = np.where(rows)[0][[0, -1]]
        c0, c1 = np.where(cols)[0][[0, -1]]
        cropped = roi_mask[r0:r1 + 1, c0:c1 + 1].astype(np.uint8)
        h2, w2 = cropped.shape
        size = DIGIT_BITMAP_SIZE
        canvas = np.zeros((size, size), dtype=np.uint8)
        y_off = (size - h2) // 2
        x_off = (size - w2) // 2
        canvas[y_off:y_off + h2, x_off:x_off + w2] = cropped
        digit_chars.append((cs, canvas))
    digit_chars.sort(key=lambda x: x[0])
    return digit_chars


def _load_glyph_lib():
    """加载字模库（懒加载 + 单例缓存）。"""
    if not hasattr(_load_glyph_lib, '_lib'):
        from core.glyph_recognizer import GlyphLibrary
        _load_glyph_lib._lib = GlyphLibrary(LIB_PATH)
    return _load_glyph_lib._lib


def _match_digit_chars(digit_chars, lib):
    """从 (x, bitmap) 列表查字模库，返回识别出的字符串。"""
    result = ''
    for (x, bitmap) in digit_chars:
        md5 = hashlib.md5(bitmap.tobytes()).hexdigest()
        ch = lib.lookup(md5)
        result += ch if ch is not None else '?'
    return result


def _match_map_template(img_bgr, templates):
    """整词模板匹配找地图名。

    对每张同尺寸 BMP 模板计算归一化相关系数（类似 cv2.TM_CCOEFF_NORMED）。
    返回 (best_map_name, best_score, all_scores_sorted)
    """
    target = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    th, tw = target.shape
    best_name = None
    best_score = -1.0
    all_scores = []
    # 预筛：只比较同尺寸模板（4 字地图 131 高 vs 3 字地图 113 高，避免无效计算）
    cands = [(f, n, g, sh) for (f, n, g, sh) in templates if sh == (th, tw)]
    if not cands:
        return None, -1.0, []
    a = target.astype(np.float32)
    a -= a.mean()
    for (fname, map_name, tpl_gray, tpl_shape) in cands:
        b = tpl_gray.astype(np.float32)
        a -= a.mean(); b -= b.mean()
        denom = (np.sqrt((a * a).sum()) * np.sqrt((b * b).sum()))
        score = 0.0 if denom < 1e-6 else float((a * b).sum() / denom)
        all_scores.append((map_name, score, fname))
        if score > best_score:
            best_score = score
            best_name = map_name
    return best_name, best_score, sorted(all_scores, key=lambda x: -x[1])


def recognize_sect_task(img_bgr, templates=None, return_detail=False):
    """识别门派闯关任务面板。

    Args:
        img_bgr: ROI 截图 (150x113 或 150x131) BGR 格式
        templates: 预加载的模板列表（None 时懒加载）
        return_detail: True 返回 dict 含 scores 详情；False 返回字符串

    Returns:
        str: "{地图名}，{n次}" 或 "{地图名}，?次"（字模缺失）
        dict: {'text': str, 'map_name': str, 'count': str, 'best_score': float, 'top5': [...]}
    """
    if templates is None:
        templates = _load_templates()
    lib = _load_glyph_lib()

    # 1) 整词模板匹配拿地图名
    map_name, score, top_scores = _match_map_template(img_bgr, templates)

    # 2) 红字数字字模识别拿次数
    digit_chars = _extract_red_digits(img_bgr)
    count_str = _match_digit_chars(digit_chars, lib)

    if not count_str:
        count_str = '?'
    text = '{},{}次'.format(map_name or '?', count_str)

    if return_detail:
        return {
            'text': text,
            'map_name': map_name,
            'count': count_str,
            'best_score': score,
            'top5': top_scores[:5],
            'digit_count': len(digit_chars),
        }
    return text


def _self_test():
    print('=== 门派闯关识别器自测 ===')
    from PIL import Image
    templates = _load_templates()
    correct = 0
    total = 0
    for (fname, map_name, tpl_gray, shape) in templates:
        path = os.path.join(BMP_DIR, fname)
        img_arr = np.array(Image.open(path).convert('RGB'))
        img = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)
        detail = recognize_sect_task(img, templates=templates, return_detail=True)
        ok = 'PASS' if detail['map_name'] == map_name else 'FAIL'
        if ok == 'PASS':
            correct += 1
        total += 1
        print('  [{}] {} ->{}  score={:.3f}  top3={}'.format(
            ok, fname, detail['text'], detail['best_score'],
            [(n, '{:.2f}'.format(s)) for n, s, _ in detail['top5'][:3]]
        ))
    pct = 100.0 * correct / total if total else 0
    print('命中率: {}/{} = {:.1f}%'.format(correct, total, pct))


if __name__ == '__main__':
    _self_test()