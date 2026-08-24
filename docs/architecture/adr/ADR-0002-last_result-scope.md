# ADR-0002 · `_last_result` 变量作用域与命名约定（source_var 机制）

- **状态**：已采纳（Accepted）— `source_var` 机制已部分落地，须强制为约定
- **范围**：跨事件变量引用、`${...}` 模板解析、switch/condition 分支取值
- **关联缺陷**：已知缺陷 #2
- **证据**：`core/task_engine.py:475`（每事件后覆盖）、`:717/:719`（`_save_to_context` 写）、`:592/:593`（读 `result`/`last_result`）、`core/task_engine_mixins/switch_mixin.py:52`（`source_var`）、`core/task_engine.py:1539`（`_search_var_for_field`）

## 背景（Context）
`_last_result` 在**每个事件执行后**被覆盖（`task_engine.py:475` `self._last_result = result`），且 `_save_to_context`（`:717/:719`）也写入它。当 `switch`/`condition` 事件执行，其返回的是结果 dict `{"matched":..,"match_value":..,"action":..}`（见 `switch_mixin.py:110-115`、`:178-184`），该 dict 随即成为新的 `_last_result`。

**陷阱**：switch 之后的下游事件若写 `${result.target_coord.0}`，解析会失败——因为 `_last_result` 已是 switch 结果 dict，没有 `target_coord` 字段（`:592/:593` 读 `self._last_result`）。旧通用搜索 `_search_var_for_field`（`:1539`）在多函数事件并存时"碰运气"取错值，进一步加剧串扰。

## 决策（Decision）
固化**变量作用域与命名约定**：
1. **上游函数事件必须设 `var_name`**（如 `JHRW`）；下游一律用**显式** `${<var_name>.field.sub}`（如 `${JHRW.target_coord.0}`），禁止在分支 / 函数链后用裸 `${result}`/`${last_result}` 取上游结构体字段。
2. **switch/condition 显式传 `source_var`** 指向来源变量（`switch_mixin.py:52` 已支持 `params.get("source_var")`），不再依赖 `_search_var_for_field` 的通用搜索兜底。
3. `${result}`/`${last_result}` **仅允许**用于"紧邻上一事件、且上一事件非分支"的场景（如连续两个 function 调用之间）。
4. 引擎侧：`_search_var_for_field` 保留为最后兜底，但 **GUI 编辑器**（`gui/param_pages.py` / `gui/event_editor.py`）应在用户用 `${result}` 跨分支引用结构体字段时给出**警告**。

## 后果（Consequences）
- ✅ 跨事件引用稳定，多函数并存不串扰；嵌套事件能可靠引用上游结果（如 `${JHRW.target_coord.0}`）。
- ⚠️ 配置更啰嗦（要写 `var_name`）；旧序列若用 `${result}` 跨分支须迁移。
- ⚠️ 约定依赖人遵守，需工具侧强制（GUI 警告）+ review 守门。

## 风险与缓解（Risks & Mitigations）
| 风险 | 缓解 |
|---|---|
| R1 旧序列回归（`${result}` 跨分支失败） | 迁移校验脚本；CONTROL_CHECKLIST 增「跨分支须用 `${var_name}`」项 |
| R2 约定靠人记易忘 | ADR-0002 写进用户手册；GUI 编辑器加实时警告 |
| R3 `source_var` 拼写错回退到通用搜索取错值 | switch 命中 source_var 缺失时记 WARNING（`switch_mixin.py:59-62`），不静默 |

## 后续
- Phase 4：在 GUI 编辑器中实现 `${result}` 跨分支警告。
- Phase 5：补 `_resolve_value` / `_search_var_for_path` 的单测，覆盖"switch 后 `${result}` 失效、显式 `${var_name}` 生效"的反例。
