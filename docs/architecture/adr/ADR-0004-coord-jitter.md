# ADR-0004 · 坐标与抖动统一约定（后台点击）

- **状态**：已采纳（Accepted）— 约定已收敛，实现待集中（Phase 4 重构）
- **范围**：所有后台点击的坐标系统一、抖动逻辑、光标同步
- **关联缺陷**：已知缺陷 #5
- **证据**：`library/map_packs/ALG.py:147`（`_JITTER_MODE`）、`:153`（`_click_background`）、`:186-196`（抖动+1~6 偏移/超界反转）、`core/task_engine.py:1899`（`_set_map_jitter_mode` 跨包置位）、`core/input_controller.py:797-799`（IAT hook 废弃）、`:860`（`_post_click`）、`:891/:895`（`cursor_sync_click=False` 默认）

## 背景（Context）
- 9 个地图包（ALG/BXG/CAC/CSC/DHW/JNYW/JYC/XLNR/ZZG）各自实现 `_click_background` + 模块级 `_JITTER_MODE`（`library/map_packs/ALG.py:147,153`）。抖动逻辑**已收敛**：原坐标→随机 1~6 游戏坐标偏移→超 `MAP_MAX_GAME_COORD` 反转（`ALG.py:186-196`），引擎经 `_set_map_jitter_mode`（`task_engine.py:1899`）遍历所有已加载地图模块置位（到达失败→抖动、到达成功→复位）。
- **问题**："各包各自为政"仍是复制 / 漂移风险（缺陷 #5）——9 份近似实现，改一处要改九处。
- **IAT Hook 现状**：GetCursorPos IAT hook 光标同步方案**已废弃**（`input_controller.py:797-799`：实测导致游戏全部闪退，galaxy2d.dll 的 GetCursorPos 是运行时 `GetProcAddress` 动态解析，无 IAT 可 hook）。当前默认**纯 PostMessage（光标完全不动）**，`cursor_sync_click` 默认 `False`（`:891/:895`）。

## 决策（Decision）
1. **统一入口**：所有后台点击必须经统一入口——地图包内点击走 `_click_background`，引擎 / 事件点击走 `_do_click`（`click_mixin.py:35`）→ `input_controller._post_click`（`input_controller.py:860`）；**禁止**包内直接调 `win32gui.PostMessage` 绕过。
2. **坐标系统一客户区坐标**：抖动偏移在**游戏坐标**域计算（`pixel_to_game` / `game_to_pixel`），落点转回客户区像素再 PostMessage；禁止在屏幕坐标域混算。
3. **抖动逻辑集中**：`_JITTER_MODE` 与抖动序列（左键原→2s→左键抖动→2s→左键点回原→右键）抽入 `library/common`（如 `win_utils` 或新 `click_helper`），9 包 import 复用，消除 9 份复制。
4. **光标同步默认关闭**：`cursor_sync_click=False`；IAT hook 方案**作废**；如需开启仅在实测纯 PostMessage 失效时，且接受光标闪入游戏（`input_controller.py:891` 注释）。
5. **跨包置位保留**（到达失败→抖动、到达成功→复位），但经由**共享状态**而非遍历各模块 `_JITTER_MODE`（`task_engine.py:1899` 改为置位共享标志）。

## 后果（Consequences）
- ✅ 点击行为一致、易维护，消除 9 份复制漂移。
- ⚠️ 需一次集中重构（Phase 4 实现，非本次 Phase 3）。
- ⚠️ 纯 PostMessage 在个别新客户端版本可能失效——保留 `cursor_sync_click` 逃生口。

## 风险与缓解（Risks & Mitigations）
| 风险 | 缓解 |
|---|---|
| R1 集中重构引入回归 | 先补 `_click_background` 行为单测（左键原/抖动/点回原/右键序列 + 超界反转）再抽 |
| R2 各包 `MAP_MAX_GAME_COORD` 不同 | 抖动逻辑参数化地图极值，按当前包传入 |
| R3 纯 PostMessage 新客户端失效 | 保留 `cursor_sync_click` 逃生口 + `input.debug_click` 诊断（`:902`） |
| R4 抖动误点导致角色走偏 | 抖动幅度保守（1~6）；到达验证兜底（`arrival_verifier`） |

## 后续
- Phase 4：执行抖动逻辑集中重构；补 `_click_background` 单测。
- 本次 Phase 3 仅固化约定，不改业务代码。
