# ADR-0005 · 内存距离评分跨类别约束（design note）

- **状态**：已采纳（Accepted）— 设计约束（预防性），现有代码已按类别隔离
- **范围**：任何"按距离 / 评分匹配"的 quest / 字段匹配逻辑
- **关联缺陷**：已知缺陷 #4
- **证据**：`core/arrival_verifier.py:583`（`_calc_distance` 曼哈顿，仅到达验证）、`core/sect_task_recognizer.py:167`（`_match_map_template` 仅地图名）、`core/yolo_detector.py:292`（按类别距离升序）、`docs/location_container_usage.md`（位置容器分类存地图/NPC/坐标）

## 背景（Context）
- **现象**：距离评分对**同类数据**灵、跨类失灵。同一 quest 的"地图"分配相近但"NPC"不一定；若用同一距离 / 评分函数比较异构字段（静态 quest 系统对象 vs live quest instance 字符串），可能**距离反转**（本应命中的被低分压制）。
- **现状（已隔离，防回归为主）**：现有评分均按类别隔离——
  - `arrival_verifier._calc_distance`（`:583`）曼哈顿距离，**仅**用于到达验证（同类坐标）；
  - `sect_task_recognizer._match_map_template`（`:167`）**仅**地图名（同类字符串）评分；
  - `yolo_detector`（`:292`）按**类别**距离升序（每类独立过滤，不跨类混排）。
- **风险点**：未来若有人建"统一 quest 匹配器"并复用单一度量比较 map/NPC/coord，会触发距离反转误命中。

## 决策（Decision）
1. **禁止跨类别复用单一距离 / 评分**：map 名、NPC 名、坐标、进度数各自用独立匹配策略（精确 / 包含 / 模板 / 曼哈顿），不得混一。
2. 若需把 live quest 字符串匹配到静态 quest 对象，必须**显式字段对齐**（map→map、npc→npc、coord→coord），不允许"整体距离最小即命中"的模糊匹配。
3. 任何跨字段评分须附单测，覆盖**"地图相近但 NPC 不同"的反例**（确保不误命中）。
4. `_calc_distance` 加 docstring 标明"仅坐标到达验证用途"，防止被误用到新类别。

## 后果（Consequences）
- ✅ 匹配稳健，避免距离反转误命中；类别隔离清晰。
- ⚠️ 匹配代码更冗长（每类独立逻辑）。
- ⚠️ 主要价值是预防未来回归，当前无紧急实现项。

## 风险与缓解（Risks & Mitigations）
| 风险 | 缓解 |
|---|---|
| R1 现有代码已隔离，主要防回归 | CONTROL_CHECKLIST 增「新增 quest 匹配须字段对齐」项；code review 必查跨类别评分 |
| R2 `_calc_distance` 被误用到新类别 | docstring 标明用途 + 单测锁定"仅坐标"语义 |
| R3 未来统一匹配器冲动 | ADR-0005 作为设计红线，PR 须说明匹配策略的类别划分 |

## 后续
- 本 ADR 为设计约束，本次无需改代码；Phase 4/5 在新增匹配逻辑时遵守并写入 CONTROL_CHECKLIST。
