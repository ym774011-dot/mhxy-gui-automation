"""验证所有坐标图的识别效果"""
import sys, numpy as np, os
from PIL import Image
sys.path.insert(0, '.')
from core.glyph_recognizer import GlyphRecognizer, COORD_WHITE_RULE
from core.glyph_coord_reader import parse_location_text

engine = GlyphRecognizer()
img_dir = r'E:\DS\梦幻西游脚本函数包\地图数据\字库图片'

coord_files = sorted([f for f in os.listdir(img_dir) if f.endswith('.png') and '任务' not in f])
expected = {
    '东海湾.png':     ('东海湾', 70, 93),
    '建邺城.png':     ('建邺城', 65, 112),
    '建邺城1.png':    ('建邺城', 153, 82),
    '江南野外.png':   ('江南野外', 109, 20),
    '江南野外1.png':  ('江南野外', 97, 23),
    '江南野外2.png':  ('江南野外', 116, 18),
    '江南野外3.png':  ('江南野外', 123, 24),
    '江南野外4.png':  ('江南野外', 135, 16),
    '长安城.png':     ('长安城', 508, 275),
    '长安城1.png':    ('长安城', 241, 101),
}

print(f'{"文件":16s} {"识别文本":30s} {"解析结果":25s} 状态')
print('-' * 80)
ok = 0
for fname in coord_files:
    img = Image.open(os.path.join(img_dir, fname)).convert('RGBA')
    arr = np.array(img)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4].astype(float) / 255.0
        arr = (arr[:, :, :3] * alpha).astype(np.uint8)

    result = engine.recognize(arr, rule=COORD_WHITE_RULE)
    loc = parse_location_text(result.raw_text)

    exp = expected.get(fname)
    if loc and exp:
        match_map = loc['map'] == exp[0]
        match_x = abs(loc['x'] - exp[1]) <= 5
        match_y = abs(loc['y'] - exp[2]) <= 5
        status = '✅' if (match_map and match_x and match_y) else '⚠️'
        if status == '✅':
            ok += 1
        loc_str = f'{loc["map"]}({loc["x"]},{loc["y"]})'
    else:
        status = '❌'
        loc_str = f'raw={result.raw_text!r}'

    print(f'  {fname:16s} {result.raw_text!r:28s} {loc_str:25s} {status}')

print(f'\n通过: {ok}/{len(coord_files)}')
