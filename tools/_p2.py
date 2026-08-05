"""patch 2: between_digits 兜底和 y_digits 跨行支持"""
import sys

path = "core/glyph_coord_reader.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# between_digits (间隙法/位数硬切 各一处) - 用更精确的上下文区分
# 第一处: 间隙法 (n>=2)
old1 = """        if not commas:
            between_digits = sorted(
                [g for g in glyphs if is_digit(g) and ox < g.bbox[0] <= cp.bbox[0]],
                key=lambda g: g.bbox[0],
            )
            n = len(between_digits)
            if n >= 2:"""
new1 = """        if not commas:
            between_digits = sorted(
                [g for g in glyphs
                 if is_digit(g)
                 and min(ox, cp.bbox[0]) < g.bbox[0]
                 <= max(op_right, cp.bbox[0] + cp.bbox[2])],
                key=lambda g: g.bbox[0],
            )
            n = len(between_digits)
            if n >= 2:"""
count1 = text.count(old1)
assert count1 == 1, f"old1 count: {count1}"
text = text.replace(old1, new1)

# 第二处: 位数硬切 (n>=4) - 注意这之后接的是 if n >= 4 分支
old2 = """        if not commas:
            between_digits = sorted(
                [g for g in glyphs if is_digit(g) and ox < g.bbox[0] <= cp.bbox[0]],
                key=lambda g: g.bbox[0],
            )
            n = len(between_digits)
            if n >= 4:"""
new2 = """        if not commas:
            between_digits = sorted(
                [g for g in glyphs
                 if is_digit(g)
                 and min(ox, cp.bbox[0]) < g.bbox[0]
                 <= max(op_right, cp.bbox[0] + cp.bbox[2])],
                key=lambda g: g.bbox[0],
            )
            n = len(between_digits)
            if n >= 4:"""
count2 = text.count(old2)
assert count2 == 1, f"old2 count: {count2}"
text = text.replace(old2, new2)

# y_digits 跨行
old3 = """        y_digits = sorted(
            [
                g for g in glyphs
                if is_digit(g)
                and g.bbox[0] >= cm_left
                and g.bbox[0] + g.bbox[2] <= y_upper
                and y_top <= cyc(g) <= y_bot
            ],
            key=lambda g: g.bbox[0],
        )"""
new3 = """        y_digits = sorted(
            [
                g for g in glyphs
                if is_digit(g)
                # 同行 Y：逗号右侧 + ')' 范围内
                and (g.bbox[0] >= cm_left
                     and g.bbox[0] + g.bbox[2] <= y_upper
                     and abs(cyc(g) - cyc(cm)) <= 12)
                # 跨行 Y：逗号左侧（行 2 续接），y 与 '(' 不同行
                or (g.bbox[0] < cm_left
                    and abs(cyc(g) - op_cy) >= 12
                    and g.bbox[1] >= cp.bbox[1])
                and y_top <= cyc(g) <= y_bot
            ],
            key=lambda g: g.bbox[0],
        )"""
count3 = text.count(old3)
assert count3 == 1, f"old3 count: {count3}"
text = text.replace(old3, new3)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print(f"applied: between_digits_gap={count1}, between_digits_split={count2}, y_digits={count3}")