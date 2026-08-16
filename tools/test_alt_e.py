# -*- coding: utf-8 -*-
"""ALT+E 打开背包实测（验证 SendInput + 扫描码 + 焦点校验方案）

流程：
  1. 绑定游戏窗口（鲜衣怒马）
  2. 截图 + 模板匹配 背包.bmp → baseline（背包当前开/关）
  3. input_controller.press_key("ALT+E")（后台模式自动降级 SendInput 前台注入）
  4. 等 1.5s 截图 + 模板匹配 → 判断背包是否打开
  5. 输出结论

用法：
  E:/py/python.exe tools/test_alt_e.py [--title 鲜衣怒马] [--threshold 0.8]
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.window_manager import window_manager
from core.input_controller import input_controller
from core.image_recognition import image_recognition

BAG_TEMPLATE = os.path.join(ROOT, "assets", "game_data", "图片数据", "背包.bmp")
WAIT_AFTER_KEY = 1.5  # 按键后等待背包打开


def check_bag(threshold):
    """模板匹配判断背包界面是否打开，返回 (是否找到, 置信度, 位置)"""
    pos, conf = image_recognition.find_template(BAG_TEMPLATE, threshold=threshold)
    return (pos is not None, conf, pos)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="鲜衣怒马")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="按键后等待背包出现的最大秒数")
    args = parser.parse_args()

    # 1. 绑定窗口
    print(f"[1] 绑定窗口 title={args.title!r} ...")
    if not window_manager.bind(title=args.title):
        print("    ✗ 未找到游戏窗口，请确认游戏已启动")
        return 1
    print(f"    ✓ 已绑定 hwnd={window_manager.hwnd} pid={window_manager.pid}")
    print(f"    客户区: {window_manager.client_size}")

    # 2. baseline 截图
    print("[2] baseline 背包状态检测 ...")
    found, conf, pos = check_bag(args.threshold)
    print(f"    背包 {'已打开' if found else '未打开'} (conf={conf:.3f}, pos={pos})")
    baseline_open = found

    # 3. 按 ALT+E（打开/关闭背包切换）
    print("[3] press_key('ALT+E') ...")
    t0 = time.time()
    input_controller.press_key("ALT+E")
    print(f"    按键调用返回，耗时 {time.time() - t0:.2f}s")

    # 4. 等待 + 复检
    print(f"[4] 等待 {WAIT_AFTER_KEY}s 后复检 ...")
    time.sleep(WAIT_AFTER_KEY)
    found, conf, pos = check_bag(args.threshold)
    print(f"    背包 {'已打开' if found else '未打开'} (conf={conf:.3f}, pos={pos})")

    # 5. 结论
    expected_open = not baseline_open  # 按键后背包状态应翻转
    if baseline_open:
        # baseline 已开 → ALT+E 应关闭背包 → 复检应找不到背包
        success = not found
        action_desc = "关闭"
    else:
        # baseline 未开 → ALT+E 应打开背包 → 复检应找到背包
        success = found
        action_desc = "打开"

    print()
    print("=" * 50)
    print(f"基线: 背包{'开' if baseline_open else '关'} → 按键后背包{'开' if found else '关'}")
    print(f"预期: ALT+E 应{action_desc}背包")
    print(f"结果: {'✓ 成功' if success else '✗ 失败'}")
    print("=" * 50)
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())