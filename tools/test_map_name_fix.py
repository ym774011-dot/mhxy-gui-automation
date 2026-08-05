"""验证 map-name 修复：对三张真实面板跑完整 _do_recognize_jhrw。"""
import cv2, sys, os
import numpy as np
from PIL import Image
sys.path.insert(0, os.getcwd())
from core.glyph_coord_reader import jhrw_reader

CASE_DIR = r"C:\Users\Administrator\.workbuddy\clipboard-images"
CASES = [
    ("建邺城", r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片\建邺城.bmp", None, "pil"),
    ("东海湾", os.path.join(CASE_DIR, "clipboard-2026-08-03T13-20-02-591Z-79f5de34.png"), None, "cv"),
    ("江南野外", "debug_capture/region_B_jhrw_x4.png", (159, 116), "cv"),
]


def load_bgr(path, dsize, mode):
    if mode == "pil":
        img = np.array(Image.open(path).convert("RGB"))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        img = cv2.imread(path)
        if img is None:
            return None
    if dsize:
        img = cv2.resize(img, dsize, interpolation=cv2.INTER_NEAREST)
    return img


for expected, path, dsize, mode in CASES:
    if not os.path.exists(path):
        print(f"[跳过] 文件缺失: {path}")
        continue
    img = load_bgr(path, dsize, mode)
    if img is None:
        print(f"[跳过] 无法读取: {path}")
        continue
    info = jhrw_reader._do_recognize_jhrw(img=img)
    tl = info["target_location"]
    ok = (tl == expected)
    print(f"期望={expected:6s} 实际={tl!r:20s} coord={info['target_coord']} "
          f"quest={info['quest_name']!r} {'OK' if ok else 'FAIL'}")
