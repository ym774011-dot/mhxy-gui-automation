# S2 · 运行时文件出库提案（.gitignore 增补）

> 版本：v1 · 2026-09-03 · 负责人：quality-lead（严守真）
> 性质：**🟡 待拍板预备材料**。本文只列提案与影响分析，**未改 `.gitignore`、未执行任何 git 命令**（git 操作由主理人拍板后执行）。
> 依据：`git status --porcelain` 现场（见 §1）、`git ls-files` 跟踪清单、`.gitignore` 现状（已含 `logs/`、`data/current_quest.json`、`*.png` 等）。

---

## 0. 关键原理（执行者必读）

1. **`.gitignore` 只对未跟踪文件生效。** 已入库的文件（`git ls-files` 里有、`git status` 显示 ` M`）不会因加一行忽略就停止跟踪——必须先 `git rm --cached <path>` 把它从索引撤出（**工作树文件不删**），再提交。
2. **撤出并提交后，其它克隆 `git pull` 会删除该文件。** 对「活配置」（autosave.json、config/settings.json）这是真实风险：队友 pull 后 GUI 可能读到空序列/空任务库。必须先在仓库里留好模板副本，并通知队友 pull 前备份本地副本。
3. 当前工作树有大量未提交改动（`core/`、`tasks/`、`gui/` 等多个 ` M`），说明仓库处于演进中。**撤出+提交动作应单独成一次 commit**，不要和这些功能改动混在同一笔提交里。

---

## 1. 现场事实（git status 摘录）

```
 M config/group1/settings.json          ← 含本机 pid:15592（机器态）
 M config/settings.json                 ← 含本机 pid/window.title/绝对路径/重登客户端路径
 M data/task_sequence_autosave.json     ← GUI 运行时回写（updated_at 常变，持续脏）
 M 函数专用/run.log                     ← 运行时日志
?? backup/ZGUI.py.bak_20260903_1847     ← T1 备份（未跟踪）
?? test_data/                           ← T2 跑批输出目录（未跟踪）
?? docs/production/                     ← T2/T7 文档（未跟踪）
```

已跟踪且会持续产生机器态/运行时产物的文件：
- `data/task_sequence_autosave.json`（runtime 回写）
- `config/settings.json` + `config/group1/settings.json`（含 pid/窗口标题/绝对路径）
- `函数专用/run.log`（runtime 日志）
- `test_after_fix.log` / `test_after_unreg.log`（历史测试证据日志，已跟踪）

---

## 2. 提案清单（逐项：路径 / 现状 / 含机器态 / 忽略后影响 / 建议）

| # | 路径 pattern | 当前 git 状态 | 含机器态 | 忽略后影响 | 建议动作 | 风险 |
|---|---|---|---|---|---|---|
| 1 | `data/task_sequence_autosave.json` | tracked, ` M`（常脏） | 是（GUI 实时序列） | 不入库后，其它克隆 pull 会删本地序列；新机 GUI 读空 | 先存模板→撤出→忽略 | 🔴高 |
| 2 | `函数专用/run.log` | tracked, ` M` | 是（日志） | 仅丢失日志，无功能影响 | 撤出→忽略 | 🟢低 |
| 3 | `test_data/*.jsonl` | untracked（??） | 否（测量产物） | 不入库，仅本地留档 | 直接加忽略（保留 `.gitkeep`） | 🟢低 |
| 4 | `test_data/*.meta.json` | untracked（??） | 否 | 同上 | 加忽略 | 🟢低 |
| 5 | `backup/` | untracked（??） | 否（备份） | 不入库，本地保留 | 加忽略 | 🟢低 |
| 6 | `config/group*/settings.json` | tracked, ` M`（含 pid） | 是 | 不入库后新机失 group 配置（pid/port/角色） | 🟡 见 §4 | 🟡中 |
| 7 | `config/settings.json` | tracked, ` M`（含 pid/路径） | 是（pid+绝对路径+**共享 task_library 注册表**） | 见 §4 决策点 | 🟡 见 §4 | 🟡中 |
| 8 | `data/worldmap_shot/tp_test_result.json` | tracked | 否（探测输出） | 仅丢失探测缓存 | 可忽略 | 🟢低 |

**不提议忽略**（给出理由）：
- `test_after_fix.log` / `test_after_unreg.log`：早期修复证据，已入库。建议保留（除非你明确要清）。若想忽略，用 `test_*.log` 精确匹配，避免误伤。
- `logs/automation.log` 等：已被现有 `.gitignore` 的 `logs/` 覆盖，无需动。
- `*.png`：现有全局忽略已覆盖 `worldmap_shot.png` 等，无需动。

---

## 3. 建议追加的 .gitignore 片段（待拍板后写入）

```gitignore
# ── 运行时回写产物（S2 出库提案 2026-09-03）──
data/task_sequence_autosave.json          # GUI 实时序列，机器态
函数专用/run.log                           # 运行时日志
test_data/*.jsonl                          # 跑批测量产物（保留 .gitkeep）
test_data/*.meta.json
backup/                                    # 本地回退备份
data/worldmap_shot/tp_test_result.json     # 地图探测缓存

# 以下两条需先存模板副本再撤出（见 §4），不要直接加：
# config/group*/settings.json
# config/settings.json
```

---

## 4. 决策点 🟡（需要主理人拍板）

### 4.1 `config/settings.json` 的困境
它**混装**了两类内容：
- **共享配置**：`task_library.modules`（19 个模块注册表）、`recognition`、`resolution`——这些该入库，新机靠它才能加载任务库。
- **机器态**：`window.title`（含时间戳/帧率）、`window.pid`（当前 null 但属运行态）、`relogin.client_path`（本机 `G:/00/十年一梦.exe`）、绝对路径 `E:\DS\...`。

**两种处理路径**：
- **路径 A（推荐，但需改代码，超出本任务）**：把机器态拆到 `config/runtime_state.json`（pid/title/路径），`settings.json` 只留共享 + `runtime_state.json` 被忽略。一劳永逸，且消除 §1 里 `config/settings.json` 持续 ` M` 的噪音。
- **路径 B（短期，纯 git）**：撤出 `config/settings.json` + 存 `config/settings.example.json` 模板（填共享部分、机器态置占位），新机由 `settings.example.json` 复制成 `settings.json`。代价：共享 task_library 改动不再自动同步，需手动同步模板。

**我的建议**：本次先不碰 `config/*`（路径 A 才是正解，留待 engineering-lead 重构时一并做）；`config/settings.json` 的 ` M` 噪音短期可接受。如果你坚持现在出库，走路径 B 并务必先提交模板。

### 4.2 `config/group*/settings.json`
含 pid + 网关端口 + 角色（二号美人）。`group1` 已 ` M`。与 §4.1 同性质（机器态+半共享）。建议同样按路径 A 拆分，短期保留。

### 4.3 `data/task_sequence_autosave.json` 出库顺序（若拍板）
```
# ① 留模板（合并式：把当前序列作为 example 入库；或手动裁剪敏感窗口标题后入库）
Copy-Item data\task_sequence_autosave.json data\task_sequence_autosave.example.json
git add data\task_sequence_autosave.example.json
git commit -m "chore: 存抓鬼序列模板（出库运行时回写）"

# ② 加忽略行（见 §3 片段，含 data/task_sequence_autosave.json）
# ③ 撤出跟踪（工作树不删）
git rm --cached data/task_sequence_autosave.json
git add .gitignore
git commit -m "chore: autosave.json 出库为忽略"
```
**通知项**：其它克隆 pull 后会删除本地 `data/task_sequence_autosave.json`，队友须 pull 前自行备份，或 pull 后用 `task_sequence_autosave.example.json` 复制还原。

---

## 5. 影响总览（执行后）

| 维度 | 影响 |
|---|---|
| 工作树 | 上述文件仍在本地，开发不受限 |
| 索引 | 这些文件变为未跟踪/忽略，不再出现在 `git status` 噪音里 |
| 其它克隆 | pull 后：run.log/备份/测试数据不再传；**autosave.json 与 config/*（若拍板）会被删除**——已用 §4 模板机制缓解 |
| CI/打包 | 若构建脚本依赖 `test_data/` 或 `backup/` 内容需改；当前未见此类依赖 |
| 回滚 | `git rm --cached` 可逆：重新 `git add` 即可恢复跟踪 |

## 6. 变更记录

| 日期 | 版本 | 说明 |
|---|---|---|
| 2026-09-03 | v1 | 纯提案文档；未改 .gitignore、未执行 git 命令 |
