# Task 8: P2修复 - 统一点击逻辑

## 完成时间
2025-07-31

## 修改概述
将分散的点击逻辑统一到 `_do_click` 公共方法，提高代码可维护性和一致性。

## 详细修改

### 1. 增强 `_do_click` 方法

**修改位置**: `core/task_engine.py` 第1440-1467行

**修改内容**:
- 添加完整的类型注解
- 支持 `click_type` 参数（left/right/double）
- 支持 `delay` 参数（点击后延迟）
- 返回布尔值表示执行成功与否

```python
def _do_click(self, target_coord: tuple, click_type: str = "left", delay: float = 0.0) -> bool:
    """统一点击逻辑"""
    # ... 统一的点击实现
```

### 2. 重构 `_execute_mouse_click` 方法

**修改位置**: `core/task_engine.py` 第924-949行

**修改内容**:
- 使用 `_do_click` 方法替代直接的 `input_controller` 调用
- 简化代码逻辑

### 3. 重构 `_do_additional_click` 方法

**修改位置**: `core/task_engine.py` 第1469-1507行

**修改内容**:
- 使用 `_do_click` 方法替代分散的点击逻辑
- 统一错误处理

### 4. 重构 `_execute_single_switch_action` 方法

**修改位置**: `core/task_engine.py` 第2334-2427行

**修改内容**:
- 使用 `_do_click` 方法处理 switch 动作中的点击
- 使用简化后的 `_lookup_coord_from_file` 方法

### 5. 重构 `_execute_yolo_fallback` 方法

**修改位置**: `core/task_engine.py` 第1776-1784行

**修改内容**:
- 使用 `_do_click` 方法替代直接的 `input_controller` 调用

### 6. 增强 `_lookup_coord_from_file` 方法

**修改位置**: `core/task_engine.py` 第1509-1600行

**修改内容**:
- 支持 JSON 格式坐标文件：`{"地图名": [x, y], ...}`
- 保留原有文本格式支持：每行 "地图名 X,Y"
- 简化方法签名，更灵活的参数传递
- 自动检测文件格式（JSON 或文本）

## 新增功能

### JSON 格式坐标文件支持

现在支持两种坐标文件格式：

1. **JSON 格式**（推荐）:
```json
{
  "东海湾": [735, 383],
  "长安城": [500, 300],
  "建邺城": [200, 150]
}
```

2. **文本格式**（向后兼容）:
```
# 地图坐标对照表
东海湾   735,383
长安城   500,300
建邺城   200,150
```

## 代码质量改进

1. **统一性**: 所有点击操作都通过 `_do_click` 方法执行
2. **可维护性**: 点击逻辑集中在一处，便于修改和调试
3. **类型安全**: 添加完整的类型注解
4. **错误处理**: 统一的异常捕获和日志记录
5. **向后兼容**: 保持原有接口不变，平滑升级

## 测试验证

所有测试通过：
- ✓ _do_click 方法统一性测试
- ✓ JSON 格式坐标文件查找测试
- ✓ 文本格式坐标文件查找测试
- ✓ 点击重构完整性测试

测试结果见: `test_task8_refactor.py`

## 影响范围

- 修改文件: `core/task_engine.py`
- 新增测试: `test_task8_refactor.py`
- 更新文档: `tasks.md`

## 后续建议

1. 考虑将坐标文件格式统一为 JSON（更结构化、易维护）
2. 可以为 `_do_click` 添加点击前的随机延迟（防检测）
3. 考虑添加点击失败的重试机制