"""聚类所有坐标区字模并导出供标注"""
import sys, numpy as np, os, hashlib
from PIL import Image
sys.path.insert(0, '.')
from core.glyph_recognizer import apply_color_mask, COORD_WHITE_RULE, extract_glyph_blobs, normalize_bitmap

img_dir = r'E:\DS\梦幻西游脚本函数包\地图数据\字库图片'
coord_files = sorted([f for f in os.listdir(img_dir) if f.endswith('.png') and '任务' not in f])

all_glyphs = []

for fname in coord_files:
    img = Image.open(os.path.join(img_dir, fname)).convert('RGBA')
    arr = np.array(img)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4].astype(float) / 255.0
        arr = (arr[:, :, :3] * alpha).astype(np.uint8)

    mask = apply_color_mask(arr, COORD_WHITE_RULE)
    blobs = extract_glyph_blobs(mask)

    for x, y, w, h, crop in blobs:
        _bmp, norm_hash = normalize_bitmap(crop, target_size=(32, 32))
        padded = np.zeros((crop.shape[0] + 2, crop.shape[1] + 2), dtype=np.uint8)
        padded[1:-1, 1:-1] = crop.astype(np.uint8)
        exact_hash = hashlib.md5(padded.tobytes()).hexdigest()

        all_glyphs.append({
            'norm_hash': norm_hash,
            'exact_hash': exact_hash,
            'bitmap': crop,
            'bbox': (x, y, w, h),
            'source': fname,
        })

clusters = {}
for g in all_glyphs:
    nh = g['norm_hash']
    if nh not in clusters:
        clusters[nh] = []
    clusters[nh].append(g)

print(f'总字模: {len(all_glyphs)} | 聚类: {len(clusters)}')

out = 'debug_clusters'
os.makedirs(out, exist_ok=True)
for i, (nh, members) in enumerate(sorted(clusters.items())):
    sources = set(m['source'] for m in members)
    rep = members[0]
    bmp = Image.fromarray((rep['bitmap'] * 255).astype(np.uint8))
    bmp6 = bmp.resize((bmp.width * 6, bmp.height * 6), Image.NEAREST)
    fname = f'{out}/c{i:03d}_n{len(members)}_{nh[:10]}.png'
    bmp6.save(fname)
    print(f'  [{i:3d}] n={len(members):2d}  {",".join(sorted(sources))}')

print(f'\n=> {out}/')
