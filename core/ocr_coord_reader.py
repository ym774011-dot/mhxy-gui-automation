# -*- coding: utf-8 -*-
"""
OCR 坐标识别模块。

通过截图 + OCR 识别游戏左上角显示的当前坐标。
作为内存坐标读取的辅助验证手段。

坐标区域：客户区 (9, 21) 到 (138, 42)，宽 129，高 21 像素。
仅识别数字字符，提高识别准确率。
"""
import time
import re
from typing import Optional, Tuple

import numpy as np

from core.screen_capture import screen_capture
from utils.logger import logger

# 坐标区域（客户区相对坐标）
# 用户指定：左上角(9,21)，右下角(138,42)
# 宽度=138-9=129，高度=42-21=21
COORD_REGION = (9, 21, 129, 21)  # (x, y, w, h)

# OCR 仅识别数字字符（坐标区域只需数字）
_OCR_DIGIT_ALLOWLIST = '0123456789'

# OCR 引擎缓存
_ocr_engine = None
_ocr_engine_initialized = False


def _get_ocr_engine():
    """获取/初始化 OCR 引擎（延迟初始化，避免启动慢）。"""
    global _ocr_engine, _ocr_engine_initialized
    if _ocr_engine_initialized:
        return _ocr_engine
    _ocr_engine_initialized = True

    # 尝试导入 easyocr
    try:
        import easyocr
        # 只识别英文数字，速度更快
        _ocr_engine = easyocr.Reader(['en'], gpu=False, verbose=False)
        logger.info("OCR 引擎初始化成功: easyocr (CPU模式)")
        return _ocr_engine
    except Exception as e:
        logger.warning(f"easyocr 初始化失败: {e}")

    # 尝试导入 pytesseract
    try:
        import pytesseract
        from PIL import Image
        _ocr_engine = ('pytesseract', pytesseract, Image)
        logger.info("OCR 引擎初始化成功: pytesseract")
        return _ocr_engine
    except Exception as e:
        logger.warning(f"pytesseract 初始化失败: {e}")

    logger.error("无可用的 OCR 引擎，请安装 easyocr 或 pytesseract")
    return None


def _preprocess_coord_image(img: np.ndarray) -> np.ndarray:
    """预处理坐标区域图像，提高OCR识别率。

    游戏坐标区域特点：
    - 黑底白字或黄字
    - 字体较小（约12-14像素）
    - 坐标格式如 [35,96] 或 35,96

    处理步骤：
    1. 转换为灰度
    2. 简单二值化（Otsu自动阈值，更稳定）
    3. 放大4倍（提高小字体识别率）
    """
    import cv2

    # 灰度化
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    # Otsu 自动阈值二值化（比 adaptiveThreshold 更稳定）
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 放大4倍（小字体需要更高分辨率）
    h, w = binary.shape
    scale = max(2, 60 // max(h, 1))  # 目标高度约60像素
    if scale > 1:
        binary = cv2.resize(binary, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

    return binary


def read_coord_ocr(timeout: float = 3.0, retry_interval: float = 0.3) -> Optional[Tuple[int, int]]:
    """通过 OCR 读取游戏当前坐标。

    截取左上角坐标区域，用 OCR 识别坐标数字。

    :param timeout: 超时时间（秒）
    :param retry_interval: 重试间隔（秒）
    :return: (x, y) 坐标元组，失败返回 None
    """
    start_time = time.time()
    last_error = None
    debug_saved = False  # 只保存一次调试图

    while time.time() - start_time < timeout:
        try:
            # 1. 截取坐标区域
            x, y, w, h = COORD_REGION
            img = screen_capture.capture_region(x, y, w, h)
            if img is None:
                last_error = "截图失败"
                time.sleep(retry_interval)
                continue

            # 2. 预处理图像
            processed = _preprocess_coord_image(img)

            # 3. OCR 识别
            result = _run_ocr(processed)
            if result is None:
                last_error = "OCR 识别无结果"
                # 保存调试图像（仅第一次）
                if not debug_saved:
                    _save_debug_image(processed, "ocr_no_result")
                    debug_saved = True
                time.sleep(retry_interval)
                continue

            # 4. 解析坐标
            coords = _parse_coord_text(result)
            if coords is not None:
                logger.debug(f"OCR 坐标识别成功: {coords}, 原文: {result!r}")
                return coords
            else:
                last_error = f"坐标解析失败: {result!r}"
                # 保存调试图像（仅第一次）
                if not debug_saved:
                    _save_debug_image(processed, f"ocr_parse_fail_{result.strip()[:20]}")
                    debug_saved = True

        except Exception as e:
            last_error = str(e)
            logger.debug(f"OCR 坐标读取异常: {e}")

        time.sleep(retry_interval)

    logger.warning(f"OCR 坐标读取失败: {last_error}")
    return None


def _save_debug_image(img: np.ndarray, suffix: str):
    """保存调试图像到临时目录，便于诊断。"""
    import os
    try:
        debug_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_ocr')
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = time.strftime('%H%M%S')
        filename = f"ocr_{suffix}_{timestamp}.png"
        filepath = os.path.join(debug_dir, filename)
        from PIL import Image
        Image.fromarray(img).save(filepath)
        logger.info(f"OCR 调试图像已保存: {filepath}")
    except Exception:
        pass


def _run_ocr(img: np.ndarray) -> Optional[str]:
    """执行 OCR 识别，返回识别文本。

    尝试多种配置组合以提高识别率：
    1. pytesseract + PSM 6（统一文本块）+ 数字白名单
    2. pytesseract + PSM 7（单行）+ 数字白名单
    3. pytesseract + PSM 6（无白名单，允许逗号括号）
    """
    engine = _get_ocr_engine()
    if engine is None:
        return None

    try:
        if isinstance(engine, tuple) and engine[0] == 'pytesseract':
            import pytesseract
            from PIL import Image
            pil_img = Image.fromarray(img)

            # 尝试多种 PSM 配置
            # PSM 6: 统一的文本块（适合整个区域都是坐标文本）
            # PSM 7: 单行文本
            # PSM 13: 原始行（不做任何假设）
            psm_modes = [6, 7, 13]
            best_text = None

            for psm in psm_modes:
                # 配置1: 纯数字白名单
                config = f'--psm {psm} -c tessedit_char_whitelist={_OCR_DIGIT_ALLOWLIST}'
                try:
                    text = pytesseract.image_to_string(pil_img, config=config).strip()
                    digits_only = re.findall(r'\d+', text)
                    if len(digits_only) >= 2:
                        # 找到至少2组数字，足够解析坐标
                        if best_text is None or len(text) > len(best_text):
                            best_text = text
                except Exception:
                    pass

                # 配置2: 无白名单（允许逗号括号等分隔符）
                config2 = f'--psm {psm}'
                try:
                    text2 = pytesseract.image_to_string(pil_img, config=config2).strip()
                    digits_only2 = re.findall(r'\d+', text2)
                    if len(digits_only2) >= 2:
                        if best_text is None or len(text2) > len(best_text):
                            best_text = text2
                except Exception:
                    pass

            if best_text:
                return best_text
            return None
        else:
            # easyocr 路径
            result = engine.readtext(
                img,
                allowlist=_OCR_DIGIT_ALLOWLIST,
                paragraph=False,
                detail=0
            )
            if result:
                return ' '.join(result).strip()
            return None
    except Exception as e:
        logger.debug(f"OCR 引擎执行失败: {e}")
        return None


def _parse_coord_text(text: str) -> Optional[Tuple[int, int]]:
    """从 OCR 识别文本中解析坐标。

    由于 OCR 仅识别数字字符，分隔符（逗号、括号、空格等）会被丢弃，
    easyocr 通常会把坐标识别为多个独立的数字文本块（如 "71" "87"）。

    支持的格式（兼容历史调用）：
    - [71, 87] / (71, 87) / 71, 87 / 71 87（带分隔符，兼容旧版）
    - "71 87"（多个独立数字块，easyocr 常见输出）
    - "7187"（连续数字串，无分隔符时的兜底处理）

    :param text: OCR 识别的文本
    :return: (x, y) 坐标，失败返回 None
    """
    if not text:
        return None

    # 清理文本
    cleaned = text.strip()

    # 尝试各种格式（兼容带分隔符的输出）
    # 格式1: [x, y] 或 [x,y]
    m = re.search(r'\[(\d{1,4})\s*[,，]\s*(\d{1,4})\]', cleaned)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # 格式2: (x, y) 或 (x,y)
    m = re.search(r'\((\d{1,4})\s*[,，]\s*(\d{1,4})\)', cleaned)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # 格式3: x, y 或 x,y
    m = re.search(r'(\d{1,4})\s*[,，]\s*(\d{1,4})', cleaned)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # 格式4: 多个独立数字块（如 "71 87"，easyocr 常见输出）
    digits = re.findall(r'\d{1,4}', cleaned)
    if len(digits) >= 2:
        return (int(digits[0]), int(digits[1]))

    # 格式5: 连续数字串无法分隔时，按游戏坐标常见位数拆分
    # 游戏坐标通常为 1~3 位数，假设前一半为X、后一半为Y
    if len(digits) == 1:
        num_str = digits[0]
        if len(num_str) >= 2 and len(num_str) % 2 == 0:
            mid = len(num_str) // 2
            return (int(num_str[:mid]), int(num_str[mid:]))
        # 奇数长度：尝试 1+n 或 n+1 拆分（游戏坐标最小1位）
        if len(num_str) >= 3:
            # 优先尝试前1位+剩余（如 "7187" -> 不适用，跳过到偶数拆分）
            # 此处返回 None，避免错误拆分导致误判
            pass

    return None


# 便捷函数：快速验证 OCR 是否可用
def is_ocr_available() -> bool:
    """检查 OCR 引擎是否可用。"""
    return _get_ocr_engine() is not None


# 便捷测试
if __name__ == '__main__':
    print("OCR 坐标识别测试")
    print(f"OCR 可用: {is_ocr_available()}")
    if is_ocr_available():
        coord = read_coord_ocr()
        if coord:
            print(f"识别到坐标: {coord}")
        else:
            print("识别失败")
