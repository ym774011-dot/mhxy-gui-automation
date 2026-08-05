# 位置数据容器使用指南

全局位置数据容器用于存储和跨事件访问地图位置信息。当函数调用（如 JHRW）返回 "江南野外 145，35" 格式的数据时，系统会自动解析并存入容器。

## 自动解析格式

支持以下返回格式：

```python
# 1. 字符串格式
"江南野外 145，35"
"建邺城 100,200"

# 2. 字典格式（完整信息）
{
    "target_location": "江南野外 145，35"
}

# 3. 分离坐标格式
{
    "target_location": "江南野外",
    "target_coord": [145, 35]
}
```

## 模板变量语法

在任何事件参数中使用 `${location.地图名.字段}` 来访问位置数据：

```python
${location.江南野外}           # 获取完整数据字典
${location.江南野外.x}         # 获取 X 坐标 (145)
${location.江南野外.y}         # 获取 Y 坐标 (35)
${location.江南野外.location}  # 获取地图名称 ("江南野外")
```

## 在不同事件中使用

### 1. 鼠标点击事件

**场景**：点击江南野外地图上的坐标 (145, 35)

```json
{
    "event_type": "click",
    "params": {
        "x": "${location.江南野外.x}",
        "y": "${location.江南野外.y}",
        "button": "left"
    }
}
```

**GUI 操作**：
1. 打开"鼠标点击"事件编辑器
2. 在"位置数据容器"区域选择地图"江南野外"
3. 点击"填入 X 坐标"按钮 → X 坐标自动填充为 `${location.江南野外.x}`
4. 点击"填入 Y 坐标"按钮 → Y 坐标自动填充为 `${location.江南野外.y}`
5. 或点击"填入坐标对 (X, Y)" → 同时填充 X 和 Y

### 2. 图像识别事件

**场景**：在江南野外地图识别模板图像

```json
{
    "event_type": "image",
    "params": {
        "source_mode": "dynamic",
        "dyn_field": "target_location",
        "dir_path": "E:/DS/梦幻西游脚本函数包/图片数据",
        "region": [
            "${location.江南野外.x}",
            "${location.江南野外.y}",
            100,
            50
        ]
    }
}
```

### 3. 条件分支事件

**场景**：判断当前是否在特定地图

```json
{
    "event_type": "condition",
    "params": {
        "mode": "switch",
        "match_field": "地图位置",
        "cases": [
            {
                "value": "${location.江南野外.location}",
                "branch": ["执行江南野外任务"]
            },
            {
                "value": "${location.建邺城.location}",
                "branch": ["执行建邺城任务"]
            }
        ],
        "default_branch": ["未知地图"]
    }
}
```

### 4. 函数调用事件

**场景**：获取江南野外的坐标作为参数

```json
{
    "event_type": "function",
    "params": {
        "module": "地图模块",
        "function": "移动到",
        "args": [
            "${location.江南野外.x}",
            "${location.江南野外.y}"
        ]
    }
}
```

## 任务流程示例

完整的任务流程：

```
1. 函数调用 JHRW
   → 返回 {"target_location": "江南野外 145，35"}
   → 自动存入位置容器

2. 鼠标点击
   → X = ${location.江南野外.x} (解析为 145)
   → Y = ${location.江南野外.y} (解析为 35)

3. 图像识别
   → 模板路径使用地图名
   → region 使用位置坐标

4. 条件分支
   → 判断位置是否正确

5. 键盘输入
   → 输入任务指令
```

## API 接口

通过 `TaskEngine` 实例访问：

```python
# 获取位置容器
location_container = task_engine.get_location_container()

# 获取指定地图的位置
location_data = task_engine.get_location("江南野外")
# 返回: {"location": "江南野外", "x": 145, "y": 35}

# 获取坐标
coords = task_engine.get_location_coordinates("江南野外")
# 返回: (145, 35)

# 获取所有位置
all_locations = task_engine.get_all_locations()
# 返回: {"江南野外": {...}, "建邺城": {...}, ...}
```

## 生命周期

1. **任务开始时**：容器自动重置，支持的地图列表设置为 `["江南野外", "建邺城", "东海湾"]`
2. **任务执行中**：每次函数调用成功后自动解析并存入位置数据
3. **任务结束时**：容器自动清空，所有数据被清理

## 注意事项

- 位置数据在函数调用事件执行后才会存入容器
- 如果函数调用失败或返回格式不正确，位置数据不会存入
- 支持的地图列表可通过 `LocationDataContainer.set_supported_maps()` 修改
- 容器线程安全，可在多线程环境下使用
