# -*- coding: utf-8 -*-
"""
MPCG - 门派闯关专用识别任务
============================
功能: 截取任务栏 ROI(840,156,150,131) → 识别门派地图名（黄色整词模板匹配）
      + 完成次数（红色数字字模库）→ 返回 {map_name, count, text}

输出示例: "天宫，10次" / "化生寺，12次"

设计要点（吸取反挂机验证码教训）:
  - 绝不依赖 OCR（easyocr 会把"天宫"识别成"夭宫"）
  - 地图名 = 15 张 BMP 整词模板匹配（score=1.000 满分，已 15/15 验证）
  - 次数 = 列间隙切字符 + md5 查字模库（0-9 已录入 data/glyph_library.json）
  - 模板/字模库均项目内路径，clone 即用

依赖: core.screen_capture（截图通道）、core.sect_task_recognizer（识别引擎）

使用方式:
  1. 任务序列（GUI「函数调用」事件）:
     module=MPCG, function=MPCG_recognize
     → 结果 dict 存入变量，后续可用 ${MPCG_recognize.map_name} /
       ${MPCG_recognize.count} / ${MPCG_recognize.text} 引用

  2. 命令行:
     python MPCG.py                   # 识别当前游戏窗口
     python MPCG.py -p 12345          # 指定PID
"""
# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# ============================================================
__function_meta__ = {
    "MPCG_recognize": {
        "title": "门派闯关: 识别当前任务栏地图名与次数",
        "args": {
            "pid": "游戏进程 PID（默认用任务库已绑定 PID；找不到窗口时自动枚举游戏进程兜底）",
            "roi": "识别区域 (x, y, w, h)，默认 (840,156,150,131)",
            "verbose": "是否打印识别过程日志",
        },
    },
    "main": {
        "title": "命令行测试入口",
        "args": {},
    },
}
import os
import sys

# ============================================================
# 项目路径：让本文件可作为库模块加载 core.*
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.sect_task_recognizer import recognize_sect_task, _load_templates
from core.window_manager import window_manager
from core.screen_capture import screen_capture
from utils.logger import logger

# 默认识别区域（客户区坐标，与 user 提供的 840,156,990,287 即 150x131 一致）
DEFAULT_ROI = (840, 156, 150, 131)


def MPCG_recognize(pid=None, roi=None, verbose=True):
    """
    识别门派闯关任务栏: 地图名 + 完成次数。

    :param pid: 游戏进程 PID；None 时用 window_manager 已绑定 PID，
                仍未绑定时自动枚举游戏进程兜底
    :param roi: 识别区域 (x, y, w, h) 客户区坐标，默认 (840,156,150,131)
    :param verbose: 是否打印过程日志
    :return: dict {
        'map_name': '天宫',       # 黄字整词模板匹配（None=未识别）
        'count': '10',            # 红字数字字模识别（'?'=字模缺失）
        'text': '天宫,10次',       # 组合输出（map_name + ',' + count + '次'）
        'best_score': 1.0,        # 模板匹配最高分
        'roi': (840, 156, 150, 131),
    }
    """
    if roi is None:
        roi = DEFAULT_ROI
    x, y, w, h = roi

    # ---- 1. 确保窗口绑定 ----
    if pid is not None:
        if not window_manager.is_valid() or getattr(window_manager, "pid", None) != pid:
            window_manager.bind(pid=pid)
    if not window_manager.is_valid():
        # 自动枚举游戏进程兜底
        pid = _find_game_pid()
        if pid:
            window_manager.bind(pid=pid)
    if not window_manager.is_valid():
        logger.warning("MPCG_recognize: 未绑定游戏窗口，无法截图")
        return {"map_name": None, "count": "?", "text": "?,?次",
                "best_score": 0.0, "roi": list(roi), "error": "窗口未绑定"}

    # ---- 2. 截取 ROI（客户区坐标，screen_capture 自动转屏幕坐标）----
    img_bgr = screen_capture.capture_region(x, y, w, h)
    if img_bgr is None:
        logger.warning(f"MPCG_recognize: ROI({x},{y},{w},{h}) 截图失败")
        return {"map_name": None, "count": "?", "text": "?,?次",
                "best_score": 0.0, "roi": list(roi), "error": "截图失败"}

    # ---- 3. 识别（整词模板 + 红字数字字模）----
    templates = _load_templates()
    detail = recognize_sect_task(img_bgr, templates=templates, return_detail=True)

    result = {
        # 主字段（匹配 GUI 事件"目标地点"字段名约定）：用户截图1中
        # 选字段=目标地点 → ${函数调用3.target_location} 才能拼模板路径
        "target_location": detail["map_name"],
        # 兼容旧字段名（不破坏已有调用）
        "map_name": detail["map_name"],
        # 次数（用户截图也用得上：${函数调用3.count}）
        "count": detail["count"],
        # 组合输出 "天宫,10次"
        "text": detail["text"],
        # 模板匹配分数（调试/质量监控）
        "best_score": detail["best_score"],
        # 识别 ROI 客户区坐标
        "roi": list(roi),
    }
    if verbose:
        logger.info(f"MPCG_recognize: {detail['text']}"
                    f" (score={detail['best_score']:.3f}, digits={detail['digit_count']})")
    return result


# ============================================================
# 工具：自动枚举游戏进程
# ============================================================
def _find_game_pid():
    """枚举 十年一梦.exe 进程，返回第一个 PID（None=未找到）。"""
    try:
        import subprocess, csv, io
        r = subprocess.run(["tasklist", "/V", "/FO", "CSV"],
                           capture_output=True, text=True, encoding="gbk", errors="ignore")
        for row in csv.reader(io.StringIO(r.stdout)):
            if len(row) >= 2 and "十年一梦.exe" in row[0]:
                try:
                    return int(row[1])
                except ValueError:
                    continue
    except Exception as e:
        logger.debug(f"枚举游戏进程失败: {e}")
    return None


def main():
    """命令行入口: python MPCG.py [-p PID]"""
    import argparse
    ap = argparse.ArgumentParser(description="门派闯关任务识别")
    ap.add_argument("-p", "--pid", type=int, default=None, help="游戏PID")
    args = ap.parse_args()

    result = MPCG_recognize(pid=args.pid)
    print("=" * 50)
    print(f"识别结果: {result.get('text', '?,?次')}")
    print(f"地图名:   {result.get('map_name')}")
    print(f"次数:     {result.get('count')}")
    print(f"匹配分:   {result.get('best_score'):.3f}")
    print("=" * 50)


if __name__ == "__main__":
    main()