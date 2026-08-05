#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断「回城」模板匹配不上问题。

用法：
    E:/py/python.exe tools/diag_huicheng.py [pid]

游戏开着时跑，会输出：
    1. 全客户区用 0.5 阈值宽松匹配的最佳位置（看模板是否还在游戏里）
    2. 区域 [353, 377, 248, 46] 内的最高匹配分数（看是否真在原 region）
    3. 模板原图 / 区域截图 / 模板最佳匹配位置裁剪图（debug_capture/ 下）
    4. 客户区尺寸 + 建议下一步

如果最佳匹配位置 ≠ 原 region → 游戏窗口尺寸变了，需要更新 region
如果全屏都找不到 → 模板过时，需要重新截图做模板
"""

import sys
import os
import cv2
import numpy as np

# 允许从项目根目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def diag(pid: int = 27076):
    from core.window_manager import window_manager
    from core.screen_capture import screen_capture

    # 1) 绑定窗口
    window_manager.bind(title=None, pid=pid)
    if not window_manager.bound:
        print(f"[FAIL] PID={pid} 未绑定成功，请确认游戏已启动")
        return 1

    client = window_manager.client_rect
    print(f"[OK] 绑定 PID={pid}, 客户区: {client}")
    print(f"    客户区尺寸: {client[2]} x {client[3]}")

    # 2) 加载模板（中文路径用 imdecode）
    tpl_path = r"E:\DS\梦幻西游脚本函数包\图片数据\回城.bmp"
    tpl = cv2.imdecode(np.fromfile(tpl_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if tpl is None:
        print(f"[FAIL] 模板加载失败: {tpl_path}")
        return 1
    th, tw = tpl.shape[:2]
    print(f"[OK] 模板 {tpl_path}")
    print(f"    模板尺寸: {tw} x {th}, BGR 均值: {tpl.reshape(-1, 3).mean(axis=0).round(1)}")

    # 3) 截原 region
    rx, ry, rw, rh = 353, 377, 248, 46
    region = screen_capture.capture_region(rx, ry, rw, rh)
    if region is None:
        print(f"[FAIL] 原 region 截图失败 ({rx}, {ry}, {rw}, {rh})")
        return 1
    print(f"[OK] 原 region 截图成功: {region.shape}")

    # 4) 在原 region 内用当前阈值 (0.8) 匹配
    result = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    print(f"\n[原 region 匹配 @ 阈值 0.8]")
    print(f"    最高分: {max_val:.3f}  位置(局部): {max_loc}")
    print(f"    -> {'通过 ✓' if max_val >= 0.8 else '失败 ✗ (你的日志就是这种情况)'}")

    # 5) 在原 region 内用宽松阈值 (0.5) 匹配 - 看模板是否存在
    _, max_val_loose, _, max_loc_loose = cv2.minMaxLoc(result)
    print(f"\n[原 region 匹配 @ 阈值 0.5 宽松]")
    print(f"    最高分: {max_val_loose:.3f}  位置(局部): {max_loc_loose}")

    # 6) 全客户区宽松匹配 - 看模板是否在别处
    full = screen_capture.capture()
    if full is not None:
        fh, fw = full.shape[:2]
        print(f"\n[全客户区 ({fw}x{fh}) 宽松匹配 @ 阈值 0.5]")
        if th > fh or tw > fw:
            print(f"    模板 {tw}x{th} 大于客户区 {fw}x{fh}，无法全屏匹配")
        else:
            result_full = cv2.matchTemplate(full, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val_full, _, max_loc_full = cv2.minMaxLoc(result_full)
            print(f"    最高分: {max_val_full:.3f}  位置(客户区左上角): {max_loc_full}")
            if max_val_full >= 0.7:
                cx = max_loc_full[0] + tw // 2
                cy = max_loc_full[1] + th // 2
                print(f"    最佳匹配中心: ({cx}, {cy})")
                print(f"    原 region 起点: ({rx}, {ry})")
                print(f"    偏差: dx={cx - (rx + rw // 2)}, dy={cy - (ry + rh // 2)}")
                if abs(cx - (rx + rw // 2)) > 50 or abs(cy - (ry + rh // 2)) > 30:
                    print(f"    -> 模板在游戏里还在，但位置与原 region 偏差较大")
                    print(f"    -> 可能原因: 游戏窗口尺寸变了 / UI 缩放变了")
                else:
                    print(f"    -> 位置基本一致，可能是模板内容小幅变动（截图 0.8 阈值太严）")
            else:
                print(f"    -> 全屏都找不到这个模板，说明模板已过时（游戏 UI / 图标换了）")
                print(f"    -> 需要重新截图制作新模板")

    # 7) 保存可视化
    os.makedirs("debug_capture", exist_ok=True)
    cv2.imwrite("debug_capture/huicheng_diag_region.png", region)
    cv2.imwrite("debug_capture/huicheng_diag_template.png",
                cv2.resize(tpl, (tw * 10, th * 10), interpolation=cv2.INTER_NEAREST))
    if full is not None:
        annotated = full.copy()
        # 原 region 框（蓝色）
        cv2.rectangle(annotated, (rx, ry), (rx + rw, ry + rh), (255, 0, 0), 2)
        # 模板最佳匹配位置框（绿色）
        if max_val_full >= 0.5:
            cv2.rectangle(annotated, max_loc_full,
                          (max_loc_full[0] + tw, max_loc_full[1] + th), (0, 255, 0), 2)
            cv2.putText(annotated, f"{max_val_full:.2f}",
                        (max_loc_full[0], max_loc_full[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        # 缩到 1/2 便于查看
        h2, w2 = annotated.shape[:2]
        annotated = cv2.resize(annotated, (w2 // 2, h2 // 2))
        cv2.imwrite("debug_capture/huicheng_diag_full.png", annotated)
    print(f"\n[保存可视化]")
    print(f"    debug_capture/huicheng_diag_region.png  原 region 截图")
    print(f"    debug_capture/huicheng_diag_template.png 模板 10x")
    print(f"    debug_capture/huicheng_diag_full.png    全客户区（蓝=原region, 绿=模板最佳匹配）")

    return 0


if __name__ == "__main__":
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 27076
    sys.exit(diag(pid))