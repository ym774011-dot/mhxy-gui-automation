"""门派闯关任务字模录入工具
从 15 张门派地图 BMP 模板中提取：
  - 黄色字（地图名，地图名→整词模板匹配用，不进字模库）
  - 红色字（任务名+数字，其中数字 0-9 进字模库用于次数识别）

设计原则（吸取反挂机验证码教训）：
  1. 绝不依赖 OCR 给字模打标签（OCR 错误率高，"天宫"会被识别成"夭宫"）
  2. 地图名通过文件名拼音映射的真值（dt=大唐官府, tg=天宫, ycdf=阴曹地府）
  3. 红字数字位图直接从 BMP 中按列间隙切，按真值标签录入
  4. 录入前检查字模库冲突（已有 md5 不同字符 → 报警不录入）

用法：
    E:/py/python.exe tools/add_sect_glyphs.py           # 录入
    E:/py/python.exe tools/add_sect_glyphs.py --preview # 仅预览，不写库
"""
import os, sys, hashlib, json
import cv2
import numpy as np

# 让项目根可导入
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.glyph_recognizer import GlyphLibrary, segment_characters

# ===== 配置 =====
BMP_DIR = r'E:/DS/梦幻西游脚本函数包/地图数据/字库图片'
LIB_PATH = os.path.join(ROOT, 'data/glyph_library.json')

# 已知真值：文件名 → 中文地图名
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
}

# 颜色阈值
RED_RANGES = [
    ((0, 100, 100), (10, 255, 255)),    # 红 H 0-10
    ((170, 100, 100), (180, 255, 255)),  # 红 H 170-180
]
YELLOW_RANGES = [
    ((20, 80, 80), (35, 255, 255)),     # 黄
]


def color_mask(hsv, ranges):
    m = np.zeros(hsv.shape[:2], dtype=bool)
    for (lo, hi) in ranges:
        m |= cv2.inRange(hsv, np.array(lo), np.array(hi)) > 0
    return m


def extract_red_digits(red_mask):
    """从红色掩码中提取所有底部红字数字字符位图（按从左到右顺序）。

    策略：
      1. 只看底部 y>=80 行（"成功完成了N次考验" 区域）
      2. 在该区域按列投影找红字段
      3. 单字符段（宽度 3-8px）= 数字候选；宽度 > 8 可能是汉字 "次"，跳过
      4. 返回按 x 排序的所有数字候选 [(x, y, w, h), ...]
    """
    H, W = red_mask.shape
    bottom = red_mask[80:H]
    col_has = bottom.any(axis=0)
    runs = []
    in_run = False; start = 0
    for c in range(W):
        if col_has[c] and not in_run:
            start = c; in_run = True
        elif not col_has[c] and in_run:
            runs.append((start, c-1))
            in_run = False
    if in_run:
        runs.append((start, W-1))
    # 单字符段（数字）
    digit_bboxes = []
    for (cs, ce) in runs:
        width = ce - cs + 1
        if 3 <= width <= 8:  # 单数字宽度
            ys = np.where(bottom[:, cs:ce+1].any(axis=1))[0]
            if len(ys) == 0: continue
            y = 80 + ys[0]
            h = 80 + ys[-1] - y + 1
            digit_bboxes.append((cs, y, width, h))
    # 按 x 从小到大排序（数字从左到右）
    digit_bboxes.sort(key=lambda b: b[0])
    return digit_bboxes


def digit_mask(red_mask, x, y, w, h):
    """提取 (x,y,w,h) 范围的掩码，去空白边，归一化大小"""
    roi = red_mask[y:y+h, x:x+w].astype(np.uint8)
    rows = np.any(roi, axis=1)
    cols = np.any(roi, axis=0)
    if not rows.any() or not cols.any():
        return None
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    cropped = roi[r0:r1+1, c0:c1+1]
    # 居中填充到固定大小，便于字模库归一化
    h2, w2 = cropped.shape
    size = max(h2, w2) + 4
    canvas = np.zeros((size, size), dtype=np.uint8)
    y_off = (size - h2) // 2
    x_off = (size - w2) // 2
    canvas[y_off:y_off+h2, x_off:x_off+w2] = cropped
    return canvas


def md5_of_mask(mask):
    return hashlib.md5(mask.tobytes()).hexdigest()


def preview_one(bmp_path, fname):
    from PIL import Image
    img = np.array(Image.open(bmp_path).convert('RGB'))
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red_mask = color_mask(hsv, RED_RANGES)
    digit_bbox = extract_red_digit_from_roi(red_mask, None)
    print(f'{fname:8s} ({img.shape[1]}x{img.shape[0]}) 红字数字bbox: {digit_bbox}')


def main():
    preview_only = '--preview' in sys.argv

    lib = GlyphLibrary(LIB_PATH)
    print(f'当前字模库: {len(lib)} 条')

    # 已有的 md5 缓存，避免重复添加
    cached_md5 = set(lib._entries.keys())

    added = 0
    conflicts = 0
    for f in sorted(os.listdir(BMP_DIR)):
        if not f.endswith('.bmp'):
            continue
        bmp_path = os.path.join(BMP_DIR, f)
        from PIL import Image
        img = np.array(Image.open(bmp_path).convert('RGB'))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        red_mask = color_mask(hsv, RED_RANGES)
        digit_bboxes = extract_red_digits(red_mask)
        if not digit_bboxes:
            print(f'  {f}: ✗ 未找到红字数字')
            continue
        print(f'  {f}: 找到 {len(digit_bboxes)} 个红字数字字符')
        # 收集所有字符的 mask
        masks = []
        for (x, y, w, h) in digit_bboxes:
            mask = digit_mask(red_mask, x, y, w, h)
            if mask is not None:
                masks.append(mask)
        if mask is None:
            print(f'  {f}: ✗ 数字位图为空')
            continue
        md5 = md5_of_mask(mask)

        # 推断真值数字：基于 "门派闯关" 常见值（0/1 居多），目前样本有限
        # 实际策略：根据文件已知 OCR 结果（dt=0, ycdf=3, tg=6, lg=1, stl=1, hss=1）
        # 其他默认打 ? 让人工确认
        # 这里不预判，留到第二步让用户标注
        char = '?'

        for i, mask in enumerate(masks):
            md5 = md5_of_mask(mask)
            existing = lib.lookup(md5)
            if existing and existing != char:
                conflicts += 1
                print(f'    [{i}] 冲突 已有字符={existing} md5={md5[:10]}')
                continue
            if not preview_only:
                lib.add(md5, char, autosave=False)
                added += 1
            print(f'    [{i}] 待标={char}  mask={mask.shape} md5={md5[:10]}')

    print(f'\\n汇总: 新增 {added} 条, 冲突 {conflicts} 条')
    if not preview_only and added > 0:
        lib.save()
        print('已保存到', LIB_PATH)


if __name__ == '__main__':
    main()