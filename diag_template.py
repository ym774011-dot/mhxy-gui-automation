# -*- coding: utf-8 -*-
"""模板匹配诊断工具 - 简化版"""
import sys
import os
import time

sys.path.insert(0, "E:/DS/mhxy-gui-automation")

import cv2
import numpy as np

# 直接导入模块（假设已经在主程序中初始化过）
from config.config import config
from core.image_recognition import image_recognition
from core.screen_capture import screen_capture

def main():
    template_path = r"E:\DS\梦幻西游脚本函数包\图片数据\杜少海.bmp"
    
    print("=" * 60)
    print("模板匹配诊断")
    print("=" * 60)
    
    # 1. 检查模板文件
    print("\n[1] 检查模板文件")
    if not os.path.exists(template_path):
        print(f"  ✗ 文件不存在: {template_path}")
        return
    print(f"  ✓ 文件存在")
    
    # 读取模板
    template = cv2.imdecode(
        np.fromfile(template_path, dtype=np.uint8),
        cv2.IMREAD_COLOR
    )
    if template is None:
        print(f"  ✗ 无法解码图片")
        return
    h, w = template.shape[:2]
    print(f"  ✓ 模板尺寸: {w}x{h}")
    
    # 2. 检查截图
    print("\n[2] 检查屏幕截图")
    
    if not screen_capture.is_bound():
        print("  ⚠ 窗口未绑定")
        print("  请先在主程序中绑定游戏窗口")
        return
    
    screenshot = screen_capture.capture()
    if screenshot is None:
        print("  ✗ 截图失败")
        return
    
    sh, sw = screenshot.shape[:2]
    print(f"  ✓ 截图成功: {sw}x{sh}")
    
    # 3. 测试不同阈值
    print("\n[3] 测试模板匹配 (不同阈值)")
    
    for thr in [0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]:
        pos, conf = image_recognition.find_template(
            template_path, threshold=thr
        )
        status = "✓" if pos else "✗"
        print(f"  {status} 阈值 {thr:.2f}: 置信度={conf:.3f}" + (f", 位置={pos}" if pos else ""))
    
    # 4. 测试多尺度
    print("\n[4] 测试多尺度匹配")
    pos, conf, scale = image_recognition.find_template_multiscale(
        template_path, threshold=0.6,
        scales=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]
    )
    status = "✓" if pos else "✗"
    print(f"  {status} 多尺度: 置信度={conf:.3f}, 尺度={scale}" + (f", 位置={pos}" if pos else ""))
    
    # 5. 总结
    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
