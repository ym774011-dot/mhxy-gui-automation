# -*- coding: utf-8 -*-
"""
把 JHRW 任务栏截图里「未录入」的字与数字，按 ASCII 逐字确认的标签，
合并写入现有的 glyph_library.json（坐标区字库不动，JHRW 标签在其上追加）。

标注依据（从 7 张 JHRW 截图 decode + ASCII 人工确认）：
  黄 = 目标地图名(紧排会合并) + ( + 坐标数字(合并块) + , + 坐标数字 + )
  红 = 初出江湖 / 当 / 前第 / 次 / )   （进度模板 "(当前第N次)" 的拆分）
  白 = 前 往 处 查 明 的 身 份          （指令文字）
  绿 = 江 湖 / 大 盗 / 蟊 / 贼          （NPC 名，按 2+2 合并）
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.glyph_recognizer import DEFAULT_GLYPH_LIB_PATH

LIB_PATH = DEFAULT_GLYPH_LIB_PATH

# hash -> 字符
NEW_ENTRIES = {
    # ── 黄：地图名（合并块，按 3 个白名单地图） ──
    "24b112e75c366b42c6d8a6da9c153fc2": "海湾",      # 东海湾 尾
    "da4fda5f921bb28ad6960a6e847b1e4d": "建邺城",    # 建邺城任务/2
    "ba227eabe5d6d8b1a367eaf581c52286": "建邺城",    # 建邺城任务1 (1px 变体)
    "d85385bd74368ce75281e263ce010879": "江南野",    # 江南野外 头
    "5517bf22f98ca0274588b26c1a4496a3": "外",        # 江南野外 尾
    # ── 黄：标点 ──
    "1535f9ccd1cce6c8586bbc6074ed18ec": "(",
    "6e45ec070b783e60647e6e9d9030818c": ")",
    "5226d309a97d7e080de83518a5e5f8dd": ")",
    "426650841d29d60c2026d9ed664299ad": ")",
    # ── 黄：坐标数字（合并块，按截图实际渲染标注） ──
    "04b7f82d7de1e2bde82704564646f258": "70",        # 东海湾 x
    "8f7b4b523324dc011da754ca42da3f91": "93",        # 东海湾 y
    "cedf1b4404bfad5cdcc24417f20505bb": "93",        # 建邺城 x
    "e6c85c60535c221270bdcf2f6f3734ba": "112",       # 建邺城 y
    "5c182293299bb93dd35027ba9f7b8c26": "53",        # 建邺城1 x 尾
    "f55cfcf9c2b4818cc9e912f4e2de657b": "2",         # 建邺城1 y 尾
    "25d29fdb975d351fcae909a26c080fcb": "13",        # 江南野外 x
    "fd8d0f67ed897a22eec6f881fe426ba3": "1",         # 江南野外 y 首
    "5ea4e30f02ad3474909e1d4b7a1aeec4": "1",         # 江南野外2 y 首
    "273bfd08e7fd8ac4c2006c6c863f6ae3": "3",         # 江南野外2 x 首
    # ── 红：任务名 + 进度模板 ──
    "f31e1454f31268dbc6aaa5f7dca9308e": "初出江湖",
    "4756b32d472d9a60222f077778166e30": "当",
    "c855809b16bbef5f2aec469548dc6042": "前第",
    "63a6e7cf7573c44aee33c222c0d91c16": "次",        # 东海湾
    "d2570db495c1073fb1ad348f50238798": "次",        # 建邺城
    "8583c789d6d90406a5343f992dadccd0": "次",        # 建邺城1
    "ea993eacbf61a0e201afc00c2d4467ca": ")",         # 建邺城1 尾
    "e69b0621c1ce619b6217c7fc33badc1a": "次",        # 建邺城2
    "a0e86126192484fce0686bc0facce3c8": "次",        # 江南野外
    "d96e0518ee412a0fc6ded273e1b622a2": "次",        # 江南野外1
    "36d679a0966198a3d9499e182d886528": "次",        # 江南野外2
    # ── 白：指令文字 ──
    "6405bde3d0377cdba76c260dd4991399": "前",
    "947b7151d5df4798fa9e18ee6323d4ab": "往",
    "718c2b633abfe8cd6cc24314fd8e9d9e": "处",
    "e47740f0311db283b434c295d51455d9": "查",
    "9f71ea0f22ada5f87a4b87e74cc1b9da": "明",
    "80a519272c2b9aaf0bfd2a600f1ed90f": "的",
    "1c7fac2b83b353826f15dcdc9b5957ba": "身",
    "0a71b24a84fcdce2107d9de9332364db": "份",
    "4da975bce328de82d3ffc6f88e2c82d0": "身",        # 江南野外/2 变体
    "81ff7fd5231342b141914e1cfe481c20": "身",        # 江南野外1 变体
    # ── 绿：NPC 名（初出江湖：江湖大盗 / 蟊贼） ──
    "d92d3b067f684fc809eb46e0dbb52cba": "江湖",
    "e8ade2dc5c25364649983d28f3e44252": "大盗",
    "5c4bf31f4c0d410126d8f02014cb5699": "蟊",
    "a35bd018222b6868139b6c79e9fb14c8": "贼",
}


def main():
    with open(LIB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.setdefault("entries", {})
    added, skipped = [], []
    for h, ch in NEW_ENTRIES.items():
        if h in entries:
            if entries[h] == ch:
                skipped.append((h, ch))
            else:
                print(f"[冲突] {h}: 库='{entries[h]}' 新='{ch}' 保留库值")
        else:
            entries[h] = ch
            added.append((h, ch))
    data["metadata"] = data.get("metadata", {})
    data["metadata"]["entry_count"] = len(entries)
    data["metadata"]["updated"] = "jhrw-glyphs-added"
    with open(LIB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"新增 {len(added)} 条，跳过(已存在) {len(skipped)} 条，当前字库共 {len(entries)} 条")
    for h, ch in added:
        print(f"  + {h[:10]} -> {ch}")


if __name__ == "__main__":
    main()
