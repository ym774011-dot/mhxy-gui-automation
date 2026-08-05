# 贡献指南 · `mhxy-gui-automation`

> 本文档定义了代码评审标准、分支管理策略和质量门禁，确保项目代码质量和团队协作效率。

---

## 一、代码评审清单（Senior 必查项）

提交 PR 前，作者自查；reviewer 逐条确认：

- [ ] **没有"写了没接上"的代码**：新增的模块/函数，必须有调用方；否则先接上，或注明 TODO 并建 issue。
- [ ] **命名诚实**：类型/函数名要反映真实行为。`YOLO` 事件就不能偷偷走模板匹配。
- [ ] **没有死配置**：params 里写的字段，必须被消费；消费不到的字段要么删、要么实现，不允许"看起来有用实则无效"。
- [ ] **不复制粘贴**：超过 ~15 行的重复逻辑，抽成 `_do_xxx` 公共方法。
- [ ] **线程安全**：跨线程共享状态用 `Lock`/`RLock`；停止标志用 `threading.Event`（比裸 bool 可见性更稳）。
- [ ] **异常不吞**：`try/except` 必须至少 `logger.error` 或向上抛；禁止空 `except:`。
- [ ] **坐标体系一致**：GUI/输入/截图统一"客户区坐标"，禁止混用屏幕坐标。
- [ ] **无 scratch 文件进仓库**：一次性 patch 脚本、备份副本（如 `_sc_correct.py`）不入 `main`，移 `scratch/` 或删除。
- [ ] **类型注解 + docstring**：公开函数签名加 `typing`，复杂逻辑加一行意图说明。

---

## 二、分支与 PR 约定

### 分支策略
- `main` 受保护，**禁止直接 push**
- 功能分支命名规范：
  - 新功能：`feat/xxx`
  - 缺陷修复：`fix/xxx`
  - 重构：`refactor/xxx`

### PR 要求
- **必须关联 issue**：在 PR 描述中引用相关 issue 编号
- **说明改动动机**：解释为什么要做这个改动，解决了什么问题
- **提供验证步骤**：本项目涉及游戏操作，手写验证清单即可
- **至少 1 名 reviewer 通过**
- **涉及 `core/task_engine.py` 的改动需 senior 复核**

---

## 三、质量门禁

### pre-commit 配置

零成本可立即接入，统一全队代码风格：

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks: [{ id: black }]
  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks: [{ id: isort }]
  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks: [{ id: flake8 }]
```

### 安装步骤

```bash
# 安装 pre-commit
pip install pre-commit

# 在项目根目录安装 git hooks
pre-commit install

# 手动运行所有检查（可选）
pre-commit run --all-files
```

### 可选进阶工具
- `mypy`：类型校验
- `pytest`：CI 跑单测

---

## 四、日志与可观测性标准

### 日志规范
- 统一用项目已有的 `utils.logger.Logger`（自带 PyQt 信号）
- **禁止 `print` 调试残留进 `main`**

### 日志级别语义
- **DEBUG**：坐标细节
- **INFO**：步骤进入/完成
- **WARNING**：重试/降级
- **ERROR**：失败已处理
- **CRITICAL**：需人工介入

### 可观测性要求
任务执行路径必须能从彩色日志区完整还原——这是本项目唯一的"运行时可观测性"，写代码时想着"出问题时日志能不能定位"。

---

## 五、新人上手路径

按此顺序读代码，1 天内能上手改：

1. **[docs/user_manual.md](docs/user_manual.md)** —— 先懂"能做什么"
2. **[models/event.py](models/event.py)** + **[models/task.py](models/task.py)** —— 懂"数据长什么样"
3. **[core/task_engine.py](core/task_engine.py)** —— 懂"怎么跑起来"（重点看 `_execute_*` 分发）
4. **[gui/event_editor.py](gui/event_editor.py)** —— 懂"用户怎么配"
5. 再碰 `window_manager` / `input_controller` / `image_recognition` / `yolo_detector`

### 能力补强资源（对应本项目技术栈）
- **Python 多线程/线程安全**：《Python Cookbook》第 12 章
- **PyQt5 信号槽**：官方 `QObject` 文档 + 本项目 `status_panel.py` 作范例
- **OpenCV 模板匹配**：`cv2.matchTemplate` + NMS
- **测试**：`pytest` 官方文档，从给 `_var_context` 解析函数写第一个测试开始

---

## 六、开发环境设置

### 克隆仓库
```bash
git clone <repository-url>
cd mhxy-gui-automation
```

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行项目
```bash
python main.py
```

---

## 七、常见问题

### Q: 如何处理坐标体系？
**A:** 本项目统一使用"客户区坐标"，禁止混用屏幕坐标。所有 GUI/输入/截图操作必须保持一致。

### Q: scratch 文件如何处理？
**A:** 一次性 patch 脚本、备份副本不入 `main` 分支。可移至 `scratch/` 目录或直接删除。

### Q: 如何确保线程安全？
**A:** 跨线程共享状态必须用 `Lock`/`RLock`；停止标志用 `threading.Event`，比裸 bool 可见性更稳。

---

## 八、联系方式

如有疑问，请：
1. 创建 issue 描述问题
2. 在 PR 中 @ 相关 reviewer
3. 参考现有代码实现作为范例

---

> 参考：[team_engineering_standards.md](docs/team_engineering_standards.md)