# PR #8 — event_editor 上帝类拆分（彻底收口）

## 改动概览
将 `gui/event_editor.py` 从 ~3408 行上帝类彻底拆分为「dialog shell + 7 个独立参数页 + 独立子流程编辑器」。

### 新增 / 重写文件
| 文件 | 说明 |
|---|---|
| `gui/event_editor.py` | **重写为 dialog shell**：通用属性 + 参数区路由（`self._pages` 注册表）+ 跨页共享辅助（`_on_browse_file` / `_on_browse_dir` / `_get_previous_function_events` / `_set_combo_by_data` / `_try_parse_value`）+ 加载/写回调度（`_load_from_event` / `_apply_to_event`）+ `accept`。删除全部旧 `_build_*_page` / `_load_*_params` / `_apply_*_params`、页私有 helper、`LegacyParamPage`、`SubFlowEditorDialog`。 |
| `gui/param_pages.py` | 承载 `BaseParamPage(ABC)` + **全部 7 个真实子类**（Click / Key / Wait / Image / Yolo / Function / Condition）+ 模块级 `_legacy_case_to_event`。页面经 `self.host` 访问 dialog 共享辅助；控件引用挂自身。 |
| `gui/subflow_editor.py` | 从 event_editor 抽出的 `SubFlowEditorDialog`；惰性 import `EventEditorDialog` / `task_editor` 防循环依赖。 |
| `tests/test_event_editor_pages.py` | **新增回归**：7 页 build/load/apply 全链路冒烟 + click/wait 字段往返零变化（9 passed）。 |

### 修复的缺陷（验证步捕获）
1. `event_editor.py` 补 `QTextEdit` import（yolo 页多文件浏览触发 `isinstance(widget, QTextEdit)`）。
2. `event_editor.py` 补 `QSpinBox` import（`_build_common_group` 用）。
3. `param_pages.py` 补 `QMessageBox` import。
4. 修正 `post_delay_spin.setSingleStep` 变量名 typo（`_pre` → `_post`，恢复原 0.1 步进）。

### 测试适配
- `test_branch_switch.py`：`SubFlowEditorDialog` 改从 `gui.subflow_editor` 导入；`_apply_condition_params` → `_apply_to_event`；父→子流程透传改测 `ConditionParamPage._edit_subflow_dialog`。

## 验证结果
- 整库 pytest：**133 passed**（排除 `test_yolo_detector.py` —— torch/c10.dll 环境 DLL 故障单独跳过，与本重构无关）。
- 行为零变化：7 页 build/load/apply 全链路通过，condition switch 序列化往返与 `test_branch_switch` 既有断言全部保持一致。

## 收口后状态
- P1 #6（event_editor 上帝类）已彻底解决，审计文档同步标记 ✅。
- PR#1~#8 全部 diff 待 reviewer 逐笔审阅。
