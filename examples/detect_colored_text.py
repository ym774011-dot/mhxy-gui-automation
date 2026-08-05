# -*- coding: utf-8 -*-
"""
颜色文字检测示例脚本。

功能：在游戏画面中检测白色(#FFFFFF)和红色(#FF0000)的文字，
      使用颜色范围提取 + 连通域分析，返回每个颜色区域的位置和面积。

使用方法：
    1. 先启动游戏并打开验证界面
    2. 运行: python examples/detect_colored_text.py
    3. 程序会自动绑定窗口、截图、检测颜色区域
    4. 按 ESC 退出

依赖：
    - PyQt5 (用于窗口绑定)
    - OpenCV (cv2)
    - numpy
    - mss (用于截图)
"""
import os
import sys
import time

import cv2
import numpy as np

# 将项目根目录添加到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.window_manager import window_manager
from core.screen_capture import screen_capture
from core.image_recognition import image_recognition
from utils.logger import logger


# ============================================================
# 颜色检测辅助函数
# ============================================================

def detect_color_regions(image, hex_color, tolerance=15, min_area=10):
    """
    检测图像中指定颜色的连通区域。

    :param image: BGR 图像
    :param hex_color: 目标颜色（如 "ffffff", "ff0000"）
    :param tolerance: 颜色容差
    :param min_area: 最小区域面积（像素），低于此值的区域会被过滤
    :return: [(x, y, w, h, area), ...] — 每个区域的位置和面积
    """
    b, g, r = image_recognition._hex_to_bgr(hex_color)

    # 提取颜色掩码
    mask = image_recognition._extract_color_mask(image, hex_color, tolerance)

    if mask is None:
        return []

    # 形态学操作：去噪 + 填充
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    # 找连通域
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        regions.append((x, y, w, h, area))

    # 按面积降序排列
    regions.sort(key=lambda r: r[4], reverse=True)
    return regions


def draw_regions(image, regions, color_bgr, label=""):
    """
    在图像上绘制检测到的区域。

    :param image: 原始图像
    :param regions: detect_color_regions 返回的区域列表
    :param color_bgr: 绘制颜色（BGR）
    :param label: 标签前缀
    """
    for i, (x, y, w, h, area) in enumerate(regions):
        cv2.rectangle(image, (x, y), (x + w, y + h), color_bgr, 2)
        text = f"{label}{i+1}:{area}"
        cv2.putText(
            image, text, (x, y - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 1
        )


def find_text_near_target(
    image, source_color, target_color,
    search_area, color_tolerance=15, match_threshold=0.5
):
    """
    在目标颜色区域附近查找源颜色文本。

    场景：游戏中红色验证码框在某个位置，需要在附近找到白色提示文字。

    :param image: BGR 图像
    :param source_color: 源颜色（如白色 #FFFFFF）
    :param target_color: 目标颜色（如红色 #FF0000）
    :param search_area: 搜索区域 (x, y, w, h)
    :param color_tolerance: 颜色容差
    :param match_threshold: 匹配阈值
    :return: {source_regions: [...], target_regions: [...], matches: [...]}
    """
    x, y, w, h = search_area
    roi = image[y:y+h, x:x+w].copy()

    # 检测源颜色区域
    source_regions = detect_color_regions(roi, source_color, color_tolerance)
    # 检测目标颜色区域
    target_regions = detect_color_regions(roi, target_color, color_tolerance)

    # 转换回原图坐标
    source_regions = [(sx + x, sy + y, sw, sh, area) for sx, sy, sw, sh, area in source_regions]
    target_regions = [(tx + x, ty + y, tw, th, area) for tx, ty, tw, th, area in target_regions]

    # 分析两个颜色区域的空间关系
    matches = []
    for t_region in target_regions:
        tx, ty, tw, th, t_area = t_region
        t_center = (tx + tw // 2, ty + th // 2)

        # 找最近的源颜色区域
        min_dist = float("inf")
        nearest_source = None
        for s_region in source_regions:
            sx, sy, sw, sh, s_area = s_region
            s_center = (sx + sw // 2, sy + sh // 2)
            dist = ((t_center[0] - s_center[0]) ** 2 + (t_center[1] - s_center[1]) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_source = s_region

        matches.append({
            "target": t_region,
            "nearest_source": nearest_source,
            "distance": min_dist if nearest_source else None,
        })

    return {
        "source_regions": source_regions,
        "target_regions": target_regions,
        "matches": matches,
    }


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("颜色文字检测示例")
    print("=" * 60)
    print()

    # 步骤1: 绑定窗口
    print("[1] 绑定游戏窗口...")
    window_found = False

    # 尝试按标题绑定
    if window_manager.bind(title="梦幻西游"):
        print(f"    ✓ 已绑定窗口: {window_manager.title}")
        window_found = True
    else:
        # 尝试列出所有窗口供选择
        print("    未找到'梦幻西游'窗口")
        print("    请先启动游戏，或手动输入窗口标题")
        title = input("    输入窗口标题 (或留空使用活动窗口): ").strip()
        if title:
            if window_manager.bind(title=title):
                print(f"    ✓ 已绑定窗口: {window_manager.title}")
                window_found = True
            else:
                print(f"    ✗ 绑定窗口 '{title}' 失败")

    if not window_found:
        print("\n请先启动游戏，然后重新运行本脚本。")
        return

    # 步骤2: 截图
    print("\n[2] 截取游戏画面...")
    screenshot = screen_capture.capture()
    if screenshot is None:
        print("    ✗ 截图失败")
        return
    h, w = screenshot.shape[:2]
    print(f"    ✓ 截图尺寸: {w} x {h}")

    # 保存原始截图
    save_dir = os.path.join(project_root, "assets", "detect_output")
    os.makedirs(save_dir, exist_ok=True)
    cv2.imwrite(os.path.join(save_dir, "original.png"), screenshot)
    print(f"    ✓ 原始截图已保存: assets/detect_output/original.png")

    # 步骤3: 检测白色区域
    print("\n[3] 检测白色 (#FFFFFF) 区域...")
    white_regions = detect_color_regions(screenshot, "ffffff", tolerance=10, min_area=20)
    print(f"    找到 {len(white_regions)} 个白色区域")
    for i, (x, y, w, h, area) in enumerate(white_regions[:10]):
        print(f"      白#{i+1}: 位置({x},{y}) 尺寸{w}x{h} 面积{area}px")

    # 步骤4: 检测红色区域
    print("\n[4] 检测红色 (#FF0000) 区域...")
    red_regions = detect_color_regions(screenshot, "ff0000", tolerance=20, min_area=20)
    print(f"    找到 {len(red_regions)} 个红色区域")
    for i, (x, y, w, h, area) in enumerate(red_regions[:10]):
        print(f"      红#{i+1}: 位置({x},{y}) 尺寸{w}x{h} 面积{area}px")

    # 步骤5: 可视化结果
    print("\n[5] 生成可视化结果...")
    result_img = screenshot.copy()

    # 绘制白色区域（绿色框）
    draw_regions(result_img, white_regions, (0, 255, 0), "白")

    # 绘制红色区域（蓝色框）
    draw_regions(result_img, red_regions, (255, 0, 0), "红")

    cv2.imwrite(os.path.join(save_dir, "detected.png"), result_img)
    print(f"    ✓ 检测结果已保存: assets/detect_output/detected.png")

    # 步骤6: 分析两个颜色的空间关系
    if white_regions and red_regions:
        print("\n[6] 分析颜色区域的空间关系...")
        print("    红色区域与最近白色区域的距离:")

        # 限制搜索区域在画面中央 80%
        margin_x = int(w * 0.1)
        margin_y = int(h * 0.1)
        search_area = (margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)

        analysis = find_text_near_target(
            screenshot, "ffffff", "ff0000", search_area
        )

        for match in analysis["matches"]:
            target = match["target"]
            source = match["nearest_source"]
            dist = match["distance"]

            tx, ty, tw, th, ta = target
            t_center = (tx + tw // 2, ty + th // 2)

            if source:
                sx, sy, sw, sh, sa = source
                s_center = (sx + sw // 2, sy + sh // 2)
                print(f"    红框({tx},{ty} {tw}x{th}) ← 白框({sx},{sy} {sw}x{sh}) 距离={dist:.1f}px")
            else:
                print(f"    红框({tx},{ty} {tw}x{th}) ← 无邻近白色区域")

        # 如果红色验证码框在白色提示文字附近，则判定为匹配
        print("\n    匹配结果:")
        matched = 0
        for match in analysis["matches"]:
            if match["distance"] is not None and match["distance"] < 200:
                matched += 1
        if matched > 0:
            print(f"    ✓ 找到 {matched} 对'白字+红字'关联（距离<200px）")
        else:
            print("    ⚠ 未找到匹配的白字+红字对")
            print("      提示: 可以尝试调整颜色容差或最小面积阈值")

    # 显示结果
    print(f"\n{'=' * 60}")
    print("检测完成！")
    print(f"  白色区域数: {len(white_regions)}")
    print(f"  红色区域数: {len(red_regions)}")
    print(f"  结果图片: {os.path.join(save_dir, 'detected.png')}")
    print(f"{'=' * 60}")

    # 显示结果图（可选）
    try:
        cv2.imshow("Color Detection Result", result_img)
        print("\n按任意键关闭窗口...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except Exception:
        pass


if __name__ == "__main__":
    main()
