# 任务清单

## P1 修复任务

### Task 1: 修复模板变量替换逻辑
- [ ] 验证 `${var}` 在所有事件类型中的正确替换
- [ ] 测试嵌套变量访问（如 `${result.target_coord.0}`）

### Task 2: 完善错误处理机制
- [ ] 统一异常捕获和日志记录
- [ ] 添加更详细的错误上下文信息

### Task 3: 优化图像识别性能
- [ ] 减少不必要的截图保存
- [ ] 优化模板匹配算法

### Task 4: 增强函数调用模块
- [ ] 支持更多参数类型
- [ ] 添加返回值验证

### Task 5: 改进任务编辑器UI
- [ ] 优化事件编辑界面
- [ ] 添加拖拽排序功能

### Task 6: P1修复 - Condition分支控制流
- [x] 修改`core/task_engine.py`的`_execute_condition`方法，实现真正的分支控制流
  - [x] simple模式：执行条件判断后，根据结果执行true_branch或false_branch事件序列
  - [x] switch模式：匹配case后，执行该case对应的actions事件序列
  - [x] 支持嵌套condition（最多3层），通过depth参数控制
  - [x] 添加`_evaluate_simple_condition`方法提取条件判断逻辑
  - [x] 添加`_execute_event_with_depth`方法支持递归执行
  - [x] 添加`_dispatch_with_retry_and_depth`方法传递depth参数
  - [x] 添加`_execute_switch_condition_with_depth`和`_execute_switch_actions`方法
  - [x] 删除旧的`_execute_switch_condition`和`_execute_switch_action`方法
  - [x] 修改`_dispatch`方法传入完整的event对象给`_execute_condition`

### Task 7: P1修复 - 模板变量解析增强
- [ ] 验证 `${var}` 在所有事件类型中的正确替换
- [ ] 测试嵌套变量访问（如 `${result.target_coord.0}`）

### Task 8: P2修复 - 统一点击逻辑
- [x] 修改`core/task_engine.py`,将分散的点击逻辑统一到_do_click公共方法
  - [x] 抽取`_do_click`方法，支持click_type和delay参数
  - [x] 重构`_execute_image`的附加点击逻辑使用`_do_click`
  - [x] 重构`_execute_condition`的switch动作使用`_do_click`
  - [x] 统一坐标文件查找逻辑到`_lookup_coord_from_file`

### Task 9: P3改善 - 扫描替换print为logger
- [x] 使用Grep工具搜索所有`print(`调用
- [x] 替换核心模块中的print为logger调用:
  - [x] config/config.py: 添加logger导入，替换为logger.error
  - [x] gui/event_editor.py: 替换为logger.debug
- [x] 保留以下位置的print:
  - utils/logger.py:81 - logger模块内部的错误输出
  - core/image_recognition.py:22 - 文档字符串中的示例代码
  - examples/detect_colored_text.py - 示例脚本（可选处理）
- [x] 验证: 使用Grep再次搜索确认核心模块无print残留

### Task 10: P3改善 - 添加核心模块类型注解
- [x] 为 `core/task_engine.py` 添加完整类型注解
  - [x] 添加 typing 模块导入 (Dict, List, Optional, Any, Tuple, Union)
  - [x] 为 TaskEngine 类属性添加类型注解
  - [x] 为公开方法添加参数和返回值类型注解 (start, pause, resume, stop)
  - [x] 为核心内部方法添加类型注解 (_run_sequence, _run_task, _execute_event等)
- [x] 为 `core/image_recognition.py` 添加完整类型注解
  - [x] 添加 typing 和 numpy 类型导入
  - [x] 为所有公开方法添加类型注解 (find_template, find_all_templates等)
  - [x] 使用 ndarray 类型注解标注 numpy 数组
- [x] 为 `models/event.py` 添加完整类型注解
  - [x] 添加 typing 模块导入 (Dict, List, Optional, Any)
  - [x] 将 EventType 改为 Enum 类型
  - [x] 为 Event 类添加属性类型注解
  - [x] 为构造函数和方法添加类型注解
- [x] 验证: 更新 tasks.md 中的 Task 10 为已完成

### Task 11: 创建单元测试框架
- [x] 创建`tests/`目录结构
- [x] 创建`tests/__init__.py`(空文件)
- [x] 创建`tests/conftest.py`配置共享fixtures
- [x] 创建测试文件`test_var_context.py`, `test_task_engine.py`, `test_coord_transform.py`
- [x] 更新`requirements.txt`添加测试依赖(pytest>=7.0.0, pytest-cov>=4.0.0, pytest-mock>=3.10.0)
- [x] 创建`pytest.ini`配置文件
- [x] 验证: 运行`pytest --collect-only`确认能发现20个测试

### Task 12: 编写变量解析单元测试
- [x] 创建`models/var_context.py`实现VarContext类
  - [x] 实现基础变量操作方法(set, get, update, clear)
  - [x] 实现模板替换方法(replace, replace_variables)
  - [x] 支持嵌套访问和列表索引访问
  - [x] 添加类型注解和文档字符串
- [x] 更新`models/task.py`添加var_context属性
- [x] 完善`tests/test_var_context.py`测试文件
  - [x] 基础变量操作测试(set/get/update/clear)
  - [x] 变量模板替换测试
  - [x] 嵌套访问测试(dict和list)
  - [x] 异常场景测试(不存在变量、无效模板、无效路径)
  - [x] 其他功能测试(contains, len, repr)
- [x] 验证: 运行`pytest tests/test_var_context.py -v`,所有17个测试通过,覆盖率达到96%

### Task 13: 编写事件分发单元测试
- [x] 完善`tests/test_task_engine.py`测试文件，测试TaskEngine的事件分发逻辑:
  - [x] 事件类型执行测试(点击、键盘、等待)
  - [x] 重试机制测试(成功重试、全部失败、异常处理)
  - [x] 异常处理策略测试(retry/skip/stop)
- [x] 验证: 运行`pytest tests/test_task_engine.py -v`确认所有测试通过
- [x] 更新tasks.md中的Task 13为已完成

### Task 14: 编写坐标换算单元测试
- [x] 完善`tests/test_coord_transform.py`测试文件
- [x] 编写基础坐标转换测试:
  - [x] 客户区坐标转屏幕坐标(client_to_screen)
  - [x] 屏幕坐标转客户区坐标计算
  - [x] 未绑定窗口场景测试
  - [x] 异常处理测试
- [x] 编写窗口偏移计算测试:
  - [x] 测试get_client_rect方法
  - [x] 测试get_client_size方法
  - [x] 测试update_rect方法
  - [x] 测试窗口偏移计算
- [x] 编写边界场景测试:
  - [x] 负坐标处理
  - [x] 超窗口范围坐标
  - [x] 坐标边界值测试
- [x] 编写窗口管理测试:
  - [x] 按标题绑定窗口
  - [x] 按PID绑定窗口
  - [x] 窗口移动后更新矩形
  - [x] 窗口有效性检查
  - [x] 获取所有窗口列表
  - [x] 单例模式验证
- [x] 验证: 运行`pytest tests/test_coord_transform.py -v`,所有17个测试通过

### Task 15: P3改善 - 更新用户手册
- [x] 更新`docs/user_manual.md`,补充新功能的说明
  - [x] 添加验证码监控说明(Task 4新增功能)
  - [x] 添加YOLO事件配置说明(Task 5修复说明)
  - [x] 添加Condition分支使用示例(Task 6新增功能)
  - [x] 添加事件重试机制说明(Task 7修复说明)
- [x] 验证: 检查文档格式和内容完整性
- [x] 更新tasks.md中的Task 16为已完成

## 完成状态

- **Task 15 已完成** ✅ (2026-07-31)
  - 更新了用户手册，补充了四个新功能的说明
  - 添加了验证码监控说明（自动启用、自动点击、故障排查）
  - 添加了YOLO事件配置说明（模型配置、自动降级、检测结果格式）
  - 添加了Condition分支使用示例（simple模式、switch模式、嵌套示例）
  - 添加了事件重试机制说明（参数配置、重试流程、使用建议）
  - 文档格式规范，内容完整，符合用户手册标准

- **Task 13 已完成** ✅ (2026-07-31)
  - 完善了事件分发单元测试，新增32个测试用例
  - 覆盖了事件类型执行、重试机制、异常处理策略等核心功能
  - 包含点击、键盘、等待等基础事件测试
  - 包含重试成功、全部失败、异常处理等重试机制测试
  - 包含retry/skip/stop三种错误处理策略测试
  - 所有测试通过，测试覆盖率从21%提升至23%
  - 提升了代码的可靠性和可维护性

- **Task 12 已完成** ✅ (2026-07-31)
  - 创建了VarContext类实现变量管理功能
  - 支持基础变量操作(set/get/update/clear)
  - 支持模板替换功能(${var}格式)
  - 支持嵌套访问和列表索引访问
  - 完善了测试文件，包含17个测试用例
  - 所有测试通过，VarContext类覆盖率达到96%
  - 更新了Task类以包含var_context属性

- **Task 10 已完成** ✅ (2025-07-31)
  - 为核心模块添加了完整的类型注解
  - task_engine.py: 添加了typing导入、类属性注解、所有公开方法和核心内部方法的类型注解
  - image_recognition.py: 添加了typing和numpy类型导入、所有公开方法的类型注解
  - models/event.py: 将EventType改为Enum，为Event类添加属性和方法类型注解
  - 提升了代码的类型安全性和可维护性，符合PEP 484标准

- **Task 6 已完成** ✅ (2025-07-31)
  - 实现了真正的分支控制流
  - simple模式现在会执行true_branch/false_branch中的事件序列
  - switch模式现在会执行case对应的actions事件序列
  - 支持最多3层嵌套condition
  - 保持了向后兼容性

- **Task 14 已完成** ✅ (2026-07-31)
  - 完善了坐标换算单元测试文件 test_coord_transform.py
  - 编写了17个测试用例,覆盖WindowManager的核心功能
  - 基础坐标转换测试: 客户区坐标转屏幕坐标、未绑定场景、异常处理
  - 窗口偏移计算测试: get_client_rect、get_client_size、update_rect方法
  - 边界场景测试: 负坐标处理、超窗口范围坐标、坐标边界值
  - 窗口管理测试: 按标题/PID绑定、窗口移动更新、有效性检查、单例模式
  - 所有测试通过,window_manager.py覆盖率达到48%
  - 使用mock技术模拟Windows API调用,确保测试独立性

- **Task 11 已完成** ✅ (2025-07-31)
  - 创建了完整的pytest单元测试框架
  - 创建了tests/目录和基础文件结构
  - 创建了conftest.py配置共享fixtures
  - 编写了20个单元测试用例覆盖核心功能
  - 配置了pytest和测试覆盖率报告
  - 所有测试均能正常收集和运行

- **Task 8 已完成** ✅ (2025-07-31)
  - 统一了点击逻辑到`_do_click`方法
  - 重构了图像识别和条件分支中的点击调用
  - 简化了坐标文件查找逻辑

- **Task 9 已完成** ✅ (2025-07-31)
  - 扫描并替换核心模块中的print为logger调用
  - config/config.py: 添加logger导入，替换2处print为logger.error
  - gui/event_editor.py: 替换2处print为logger.debug
  - 保留了合理的print位置（logger模块内部、文档示例、示例脚本）
  - 提升了日志系统的规范性和可维护性

---

## 跟踪项（Phase 3 质量门豁免登记）

### Issue VM-EXEMPT · verification_monitor 引擎内重接入（豁免中）
- **来源**：Phase 3 架构评审门 B1（`docs/architecture/REVIEW.md`）；ADR-0003
- **状态**：⚠️ 显式豁免（用户 2026-08-24 拍板）—— 当前阶段不自动处理验证码，依赖用户独立 `captcha_monitor.py` 外部监控 + 手动解谜
- **影响**：引擎内无验证码/防卡死监控，遇验证码弹窗可能卡死/失控
- **重新启用触发条件（满足任一即须按 ADR-0003 在 Phase 4 重接入）**：
  1. 某次私服更新后频繁弹验证码，外部 `captcha_monitor.py` 无法稳定覆盖
  2. 出现验证码未处理导致任务链卡死/失控的生产事故
  3. 用户决定启用自动防挂机（不再人工介入）
- **方案**：引擎内轻量探测（image_recognition 模板/状态识别）+ 专用 signal 上报 GUI；与 gateway_guard 解耦；状态用 threading.Event；禁用旧线程类与裸 except（见 ADR-0003）
- **关联**：CONTROL_CHECKLIST 门禁在 PR 对照