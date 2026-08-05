"""重建黄通道地图名指纹表（坐标无关版本）。

用法：python tools/build_map_fingerprints.py
从三张样本图计算 _map_name_fingerprint_hash 并打印 {地图: hash}，
把输出粘贴回 core/glyph_coord_reader.py 的 _MAP_NAME_FINGERPRINTS。
"""
import sys, os, cv2, numpy as np
from PIL import Image

sys.path.insert(0, os.getcwd())
from core.glyph_coord_reader import (
    _map_name_fingerprint_hash,
    JHRW_YELLOW_RULE,
)
from core.glyph_recognizer import GlyphRecognizer

rec = GlyphRecognizer()

# (地图名, 图像路径, 是否需裁剪 JHRW_ROI, 是否需 4x 降采样)
SAMPLES = [
    ("建邺城", r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片\建邺城.bmp", False, False),
    ("东海湾", r"C:\Users\Administrator\.workbuddy\clipboard-images\clipboard-2026-08-03T13-20-02-591Z-79f5de34.png", False, False),
    ("江南野外", r"debug_capture/region_B_jhrw_x4.png", False, True),
]


def load_rgb(path, crop_roi, downscale):
    if path.lower().endswith(".bmp"):
        arr = np.array(Image.open(path).convert("RGB"))
    else:
        arr = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    if downscale:
        arr = cv2.resize(arr, (159, 116), interpolation=cv2.INTER_NEAREST)
    if crop_roi:
        x, y, w, h = (837, 120, 159, 116)
        arr = arr[y : y + h, x : x + w]
    return arr


for name, path, crop_roi, downscale in SAMPLES:
    if not os.path.exists(path):
        print(f"# 跳过（文件缺失）: {name} @ {path}")
        continue
    img = load_rgb(path, crop_roi, downscale)
    y_res = rec.recognize(img, rule=JHRW_YELLOW_RULE, segmentation="blobs")
    h = _map_name_fingerprint_hash(img, y_res)
    print(f"{name}: {h}   (yellow_raw={y_res.raw_text!r})")
