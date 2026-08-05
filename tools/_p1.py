"""精确修改 extract_coord_spatial 的 commas/between/between_digits/y_digits 过滤（支持跨行）"""
import sys

path = "core/glyph_coord_reader.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

old = """        commas = [g for g in glyphs if is_comma(g) and ox < g.bbox[0] <= cp.bbox[0]]"""
new = """        # 跨行：'(' 在行 1，')' 在行 2 左 → 逗号可能在 '(' 右侧或 ')' 右侧
        commas = [
            g for g in glyphs
            if is_comma(g)
            and min(ox, cp.bbox[0]) < g.bbox[0] <= max(op_right, cp.bbox[0] + cp.bbox[2])
        ]"""
assert text.count(old) == 1
text = text.replace(old, new)

old = """            between = [
                g for g in glyphs
                if ox < g.bbox[0] <= cp.bbox[0]
                and not is_digit(g)
                and not is_open_paren(g)
                and not is_close_paren(g)
                and abs(cyc(g) - cyc(op)) <= 12
            ]"""
new = """            between = [
                g for g in glyphs
                if min(ox, cp.bbox[0]) < g.bbox[0] <= max(op_right, cp.bbox[0] + cp.bbox[2])
                and not is_digit(g)
                and not is_open_paren(g)
                and not is_close_paren(g)
                and abs(cyc(g) - cyc(op)) <= 12
            ]"""
assert text.count(old) == 1
text = text.replace(old, new)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("patch 1-2 applied")