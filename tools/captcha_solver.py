# -*- coding: utf-8 -*-
"""
梦幻西游验证码识别器（原型 v1）。

流程：
  1. HSV 红色检测 → 红框候选（连通域）
  2. 拆分被闭运算合并的相邻框（按内部红色间隙）
  3. 每个框：去红边框 → 放大 3x → easyocr 识别（allowlist 白名单）
  4. 输出所有候选字符串

用法：
    E:/py/python.exe tools/captcha_solver.py <图片路径>

依赖：easyocr（已装，E:/py），首次运行自动下载模型（~64MB en 模型）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import cv2
import numpy as np

# 字符白名单（验证码字符集：A-Z a-z 0-9 _ 空格）
ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ "


def detect_boxes(img):
    """HSV 红框检测 + 相邻框拆分。返回 [(x, y, w, h), ...]"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, (0, 60, 60), (10, 255, 255))
    red2 = cv2.inRange(hsv, (168, 60, 60), (180, 255, 255))
    red = red1 | red2

    # 小核闭运算连接各自边框（不合并相邻框）
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    red_close = cv2.morphologyEx(red, cv2.MORPH_CLOSE, kernel, iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(red_close, 8)

    boxes = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw > 50 and bh > 15 and 300 < area < 200000:
            boxes.append([x, y, bw, bh])

    # 拆分宽框：若宽 > 180，按「原始红色掩码」的列间隙拆（闭运算可能填掉间隙）
    split_boxes = []
    for x, y, bw, bh in boxes:
        if bw <= 180:
            split_boxes.append((x, y, bw, bh))
            continue
        inner = red[y + 3:y + bh - 3, x + 3:x + bw - 3]
        col_sum = inner.sum(axis=0) // 255
        # 找连续"有红色"列段
        segs = []
        in_seg = False
        for cx in range(len(col_sum)):
            if col_sum[cx] > 0 and not in_seg:
                seg_start = cx
                in_seg = True
            elif col_sum[cx] == 0 and in_seg:
                segs.append((seg_start, cx - 1))
                in_seg = False
        if in_seg:
            segs.append((seg_start, len(col_sum) - 1))
        # 每段宽度 > 50 才视为独立框
        sub = [((x + 3 + s0), y, s1 - s0 + 1, bh) for s0, s1 in segs if s1 - s0 >= 50]
        if sub:
            split_boxes.extend(sub)
        else:
            split_boxes.append((x, y, bw, bh))  # 拆不动保留原框
    return split_boxes


def detect_marker(img, boxes):
    """找独立于红框边框的红色连通域（箭头/划线）。

    方法：红色连通域中，bbox 不被任何红框 bbox 完全包含的 → 标记。
    返回 [(x, y, w, h, area), ...] 按面积降序。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, (0, 60, 60), (10, 255, 255))
    red2 = cv2.inRange(hsv, (168, 60, 60), (180, 255, 255))
    red = red1 | red2
    n, labels, stats, _ = cv2.connectedComponentsWithStats(red, 8)
    marks = []
    for i in range(1, n):
        x, y, mw, mh, area = stats[i]
        if area < 40:
            continue
        inside = any(
            x >= bx - 2 and y >= by - 2 and x + mw <= bx + bw + 2 and y + mh <= by + bh + 2
            for bx, by, bw, bh in boxes
        )
        if not inside:
            marks.append((x, y, mw, mh, area))
    marks.sort(key=lambda m: -m[4])
    return marks


def extract_box_text(img, box, reader, scale=3):
    """裁剪单框 → 去红边 → 放大 → easyocr 识别。返回字符串。"""
    x, y, bw, bh = box
    pad = 4
    crop = img[max(0, y - pad):y + bh + pad, max(0, x - pad):x + bw + pad].copy()
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, (0, 60, 60), (10, 255, 255))
    red2 = cv2.inRange(hsv, (168, 60, 60), (180, 255, 255))
    red = red1 | red2
    # 红色像素 → 背景色（取左上角颜色）
    bg = crop[2, 2].astype(np.int16)
    crop[red > 0] = bg.astype(np.uint8)
    big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    rgb = cv2.cvtColor(big, cv2.COLOR_BGR2RGB)
    res = reader.readtext(rgb, detail=0, allowlist=ALLOWLIST)
    return " ".join(res).strip() if res else ""


def main():
    if len(sys.argv) < 2:
        print("用法: E:/py/python.exe tools/captcha_solver.py <图片路径>")
        return
    path = sys.argv[1]
    img = cv2.imread(path)
    if img is None:
        print(f"无法读取图片: {path}")
        return

    boxes = detect_boxes(img)
    # 按 (行, 列) 排序
    boxes.sort(key=lambda b: (b[1] // 40, b[0]))
    print(f"检测到 {len(boxes)} 个候选红框\n")

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    results = []
    for i, box in enumerate(boxes):
        text = extract_box_text(img, box, reader)
        results.append((box, text))
        print(f"框{i}: ({box[0]},{box[1]}) {box[2]}x{box[3]} → {text!r}")

    # 箭头/划线标记检测
    marks = detect_marker(img, boxes)
    if marks:
        print("\n红色标记（箭头/划线，可能被 UI 噪声干扰）:")
        for x, y, mw, mh, area in marks[:6]:
            print(f"  ({x},{y}) {mw}x{mh} area={area}")
        # 标记中心 → 最近的红框 = 疑似答案框
        mx, my = marks[0][0] + marks[0][2] // 2, marks[0][1] + marks[0][3] // 2
        best_i, best_d = None, 1e9
        for i, (box, _) in enumerate(results):
            cx, cy = box[0] + box[2] // 2, box[1] + box[3] // 2
            d = (cx - mx) ** 2 + (cy - my) ** 2
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None:
            print(f"\n>>> 疑似答案框: 框{best_i} → {results[best_i][1]!r}")
    else:
        print("\n未检测到独立红色标记（箭头/划线）")
    return results


if __name__ == "__main__":
    import easyocr
    main()
