# S-0 版本基线报告：备份并 git 纳管 ZGUI.py

> 任务：T1 · P0（阻塞项 B2）｜执行：eng-lead-2（程基岩）｜日期：2026-09-03
> 仓库根：`E:\DS\mhxy-gui-automation`

---

## 0. 执行说明（重要）

本任务派发给我时，**备份与提交动作已由 `eng-lead` 先行完成**（commit `2677663`，备份 `backup/ZGUI.py.bak_20260903_1847`）。

我没有重复造轮子，而是把工作量放在了**独立复核**与**尚未产出的 diff 摘要报告**上：

- 逐项验证备份/提交的正确性（不采信 commit message 的自述，全部实测比对）
- 生成原本缺失的 `docs\production\S0-version-baseline.md`（即本文件）

复核结论：**基线有效，可安全用于 Phase 6 改动回退。**

---

## 1. 备份验证

| 项 | 值 |
|---|---|
| 备份绝对路径 | `E:\DS\mhxy-gui-automation\backup\ZGUI.py.bak_20260903_1847` |
| 源文件 | `E:\DS\mhxy-gui-automation\tasks\library\ZGUI.py` |
| 源行数 | **1417** |
| 备份行数 | **1417** |
| 一致性 | ✅ 行数一致、字节数一致（均为 58036 B）、MD5 一致 |

**三方哈希比对（最强证据）：**

```
git hash-object tasks/library/ZGUI.py              → be8f020c6f28ea17c98c5ca2953610e2fa99b5bc
git hash-object backup/ZGUI.py.bak_20260903_1847   → be8f020c6f28ea17c98c5ca2953610e2fa99b5bc
git rev-parse HEAD:tasks/library/ZGUI.py           → be8f020c6f28ea17c98c5ca2953610e2fa99b5bc
MD5（源 / 备份）                                    → E6DF6F5B267432442DB8305B503457E7
```

工作区文件 = 备份文件 = 已提交 blob，三者完全同一内容。

**⚠ 行数口径偏差（需更正记录）**
commit message 中写的是「1416 行」，实测为 **1417 行**。原因：文件末尾无换行符（`EndsWith("\n") == False`），不同计数口径会差 1。以字节数 + MD5 + git blob 三方一致为准，内容 100% 正确，仅注释里的数字需更正。**不影响回退可用性。**

`backup/` 目录既有文件（`black_screen.pyw`、`night_guard.py`）未被触碰。

---

## 2. 纳管提交

| 项 | 值 |
|---|---|
| **完整 commit hash** | **`2677663a6509afdbb93deb7a7e646b8b43a80d3b`** |
| 短 hash | `2677663` |
| 父提交 | `c3733f7 fix(brain): P1黑名单过滤移到 real_map 就绪后` |
| message | `chore(baseline): 纳管 ZGUI.py，为 Phase 6 打磨建立回退基线` |

**回退命令（改动搞砸时）：**

```powershell
git checkout 2677663 -- tasks/library/ZGUI.py
# 或直接用备份覆盖：
Copy-Item backup\ZGUI.py.bak_20260903_1847 tasks\library\ZGUI.py
```

---

## 3. 验证输出（原始）

### 3.1 `git log --oneline -1`

```
2677663 chore(baseline): 纳管 ZGUI.py，为 Phase 6 打磨建立回退基线
```

### 3.2 `git show --name-status HEAD`（证明提交只含 ZGUI.py）

```
commit 2677663a6509afdbb93deb7a7e646b8b43a80d3b
Author: ym774011-dot <ym774011@gmail.com>
Date:   Thu Sep 3 18:48:12 2026 +0800

    chore(baseline): 纳管 ZGUI.py，为 Phase 6 打磨建立回退基线

    即将改动 _bag_visible 与 _wait_task_done，先建立版本基线以便改动失败时精确回退。
    备份：backup/ZGUI.py.bak_20260903_1847（1416 行，MD5 e6df6f5b267432442db8305b503457e7）
    本次仅纳管 ZGUI.py，其余工作区改动保持未提交。

A	tasks/library/ZGUI.py
```

唯一变更条目 `A tasks/library/ZGUI.py` —— **提交干净，未夹带任何其它文件**。

### 3.3 `git status --short`

```
 M config/group1/settings.json
 M config/settings.json
 M core/gateway_guard.py
 M core/task_engine.py
 M data/task_sequence_autosave.json
 M gui/config_panel.py
 M gui/main_window.py
 M tasks/library/BRAIN.py
 M tasks/library/WORLD_BOSS.py
 M "\345\207\275\346\225\260\344\270\223\347\224\250/run.log"
?? backup/ZGUI.py.bak_20260903_1847
?? core/relogin.py
?? docs/production/
?? run_unlimited_test.py
?? test_data/
```

✅ 9 个业务文件仍为 `M` 未提交，符合预期。
（`函数专用/run.log` 显示为 `M` 说明它是**已跟踪**文件，与派单描述的「未跟踪」不符 —— 但同样未提交，不影响。另 `run_unlimited_test.py` / `test_data/` 属 T2 同事产出，非本任务范围。）

---

## 4. diff 摘要（9 个未提交文件）

> 派单写「8 个文件」，实际列出 9 个，此处按 **9 个**全部覆盖。
> 合计：`1018 insertions(+), 70 deletions(-)`

### 4.1 `config/settings.json` （+38/-3）— **风险：中**

- **改了什么**：`window.title` 换成 `胖子西游- (二号美人[412646])`，角色从「然学」切到「二号美人」；**`window.pid` 由 `14956` 改为 `null`**；新增 `logging.auto_clean_days=7`；任务库新增 `ZGUI` 模块条目（enabled=true）；新增 `relogin` 配置块（enabled=**false**，含 5 步登录坐标）。
- **影响面**：全局配置。角色/客户端整体从「鲜衣怒马-怀旧江南版」切到「胖子西游」。
- **风险**：`pid: null` 会让窗口绑定在启动时无 PID 可用，依赖运行时重新绑定；若绑定流程未覆盖，抓鬼链路第一步就断。ZGUI 已注册进任务库（这是对的，否则 GUI 里选不到抓鬼模块）。

### 4.2 `config/group1/settings.json` （+9/-3）— **风险：低**

- **改了什么**：角色列表 `["然学"]` → `["二号美人"]`，新增 `pid: 15592` 与 `title: "胖子西游- (二号美人[412646])"`；纯格式化展开（gateway JSON 由单行展开为多行）。
- **影响面**：仅 group1 分组窗口绑定。
- **风险**：低。与 4.1 同向切换，但**这里 pid=15592、那里 pid=null，两处不一致**，需确认哪份是生效配置。

### 4.3 `core/gateway_guard.py` （+2/-2）— **风险：低（正向修复）**

- **改了什么**：`_is_game_process()` 的游戏进程名白名单加入 `"胖子西游"`（psutil 分支 + tasklist 兜底分支各一处）。
- **影响面**：网关进程合法性判定。
- **风险**：低。**必要修改** —— 不加的话换客户端后网关会认为目标进程「不是游戏」而拒绝 attach，属配套适配。

### 4.4 `core/task_engine.py` （+12/-0）— **风险：中**

- **改了什么**：`_on_click` 系列在坐标解析后、调用 `_do_click` 前，插入随机抖动：`x += randint(-jitter_x, jitter_x)`，同理 y。事件参数 `jitter_x/jitter_y` 缺省 0 = 不偏移。整段包在 `try/except: pass` 内。
- **影响面**：**所有点击事件**。反外挂拟人化（防固定像素被识别）。
- **风险**：中。`random` 已在模块第 30 行 import（已核实，不会 NameError）。但**抖动会改变实际点击像素** —— 若后续抓鬼链路的点击坐标是精密校准值（如对话框按钮、天眼图标），开启 jitter 会导致点偏。当前 `data/task_sequence_autosave.json` 里已有一个事件设了 `jitter_x:6 / jitter_y:5`（右键 327,345），需评估该点是否容错。

### 4.5 `data/task_sequence_autosave.json` （+203/-4）— **风险：低（但信息量大）**

- **改了什么**：空的「任务 4」被填充为完整的**「抓鬼」任务序列**：`ZGUI.zhuagui_take_task`（接钟馗任务）→ 右键点击(327,345) → `ZGUI.zhuagui_use_tianyan`（使用天眼）→ `ZGUI.main`（主循环）→ 图像识别「自动战斗.bmp」`wait_disappear`（战斗中等待）→ …（后续 200 行）。
- **影响面**：这就是**当前正在跑的抓鬼序列**，是 Phase 6 攻坚的实际载体。
- **风险**：低（属运行时自动存档）。**但它确认了三件事**：① 抓鬼入口是 `zhuagui_take_task`；② 主循环是 `ZGUI.main`；③ 完成判定依赖模板 `自动战斗.bmp` 的 `wait_disappear`。改动 `ZGUI.py` 时这几个签名不能动。

### 4.6 `gui/config_panel.py` （+130/-7）— **风险：高（见 §5.1）**

- **改了什么**：新增 `pyqtSignal` + `QPlainTextEdit` 导入；新增 `relogin_requested` 信号；新增「定时重新登录」分组 UI（启用勾选 / 间隔 SpinBox 1~43200 分 / 客户端 exe 浏览 / 登录坐标多行编辑 / 立即重登按钮）；`_load_*` 与 `_save_ui_to_config` 双向读写 `relogin.*` 配置。
- **影响面**：配置面板启动即加载。
- **风险**：**高** —— 模块顶层 `from core.relogin import DEFAULT_CLICK_POINTS`，而 `core/relogin.py` 未纳管（详见 §5.1）。

### 4.7 `gui/main_window.py` （+146/-10）— **风险：中**

- **改了什么**：新增 `threading`/`time` 导入；主窗口初始化挂 30s 轮询定时器 `_relogin_timer`；工具栏新增「🔄 定时重登」Action；连接 config_panel 的 `relogin_requested` 信号；新增 `_on_relogin_now`（停任务→后台线程 `core.relogin.relogin_client`→成功后 `task_engine.start(resume_sequence)` 自动恢复）、`_relogin_done`、`_on_relogin_tick`；**另新增 `_sync_gateway_to_bound(pid)` —— 绑定窗口后立即后台 `ensure_gateway(pid)` 换绑网关**。
- **影响面**：主窗口生命周期 + 窗口绑定流程。
- **风险**：中。重登链路是「杀进程→启客户端→登录」，为**破坏性操作**，虽有防重入标志与 `relogin.enabled=false` 默认关闭兜底，但若误开启会中断抓鬼。`_sync_gateway_to_bound` 是正向修复（修「⚠pid不匹配」徽章）。

### 4.8 `tasks/library/BRAIN.py` （+22/-8）— **风险：中**

- **改了什么**：`BLACK_FAIL_THRESHOLD` 3→**2**（拉黑门槛降低，理由是 no_battle_option 已排除污染）；`hot_weighted_pick(pool_avg)` 默认改为 `None` → **实时按击杀数加权算全池均值**（旧版写死 12.0 偏乐观）；样本采纳门槛 `kills > 0` → **`kills >= 3`**（样本不足 3 次不采信）；权重公式下限 `avg - 3.0` → `avg - 2.0`。
- **影响面**：选图策略 + 黑名单策略。
- **风险**：中。加权公式与门槛同时改动，**选图分布会明显变化**（样本 <3 的图统一按 pool_avg 处理）。属调参性质，需实测验证，不改抓鬼主链路。

### 4.9 `tasks/library/WORLD_BOSS.py` （+432/-57）— **风险：中高（改动量最大）**

- **改了什么**（按主题）：
  1. **跨图链路**：`_HOP_CHAINS` 移除 `_STATION_DLG_`（建邺城/宝象国改走全局 desc 直达）；新增 `_FLY_AURA_TRANSIT` 光圈传送（朱紫国 (5,114)→大唐境外）；飞行符开包失败路径补 `_fly_close_panel`；hop 链末步未切图时**清弹窗+关行囊后重发一次**。
  2. **防卡死/防掉线**：新增 `_dismiss_offline_dialog()`（枚举窗口点掉「验证错误/下线通知」→ 置 `relogin_requested` → break）；新增 `_captcha_try_once()`（战斗开始空闲窗口温和解一次验证码，`on_battle_started` 回调）；`_rightclick_close_center()`（后台右键画面中心关任意残留弹窗）。
  3. **调参**：`TELEPORT_FAST_DIST` 80→**50**（可用环境变量 `WORLDBOSS_TELEPORT_FAST` 覆盖回退）；`time.sleep(2.0)` → `_DLG_WAIT`（环境变量 `WORLDBOSS_DLG_WAIT`，默认仍 2.0）。
  4. **本图优先守卫**：新增 `LOCAL_STAY_MAX_S=300` + `_should_prioritize_local()`，本图有同级/更高级目标时抑制异图公告跨图，超时兜底放行。
  5. **TAB 竞态**：`_press_tab_if` 重试 2→3 次，补按前先右键清弹窗；`_fast_foot_click` 新增 `gateway` 参数并改用 `_press_tab_if` 状态感知开图。
  6. **其它**：新增 `_ensure_fly_on()`（启动开坐骑飞行）；黑名单判定收窄（`no_battle_option`/`no_battle_start`/`failed` 不再入黑名单）；修复 `this_keywords` 在 `_pick_target` 前的 `UnboundLocalError`（把赋值移到 `b` 确定之后）。
- **影响面**：WORLD_BOSS 全链路（跨图/寻路/战斗/选目标/自愈）。
- **风险**：中高。改动面极大且多处是链路级调整（跨图策略、TAB 开图时序、战斗结算等待）。**不直接触碰 ZGUI.py 抓鬼链路**，但同属 `tasks/library/`，共享 `brain` 记忆与网关；且 `TELEPORT_FAST_DIST`/`_DLG_WAIT` 已改为环境变量驱动 —— 若有人误设 `WORLDBOSS_DLG_WAIT=0` 或 `1.5`（注释明说「未验证的中间值」），会重现崩溃。

---

## 5. 高危项（不在我修改范围，但必须指出）

### 5.1 🔴 P0 — `gui/config_panel.py` 顶层 import 了未纳管的 `core/relogin.py`

```python
# gui/config_panel.py:28
from core.relogin import DEFAULT_CLICK_POINTS as _DEFAULT_RELOGIN_POINTS
```

实测确认：

```
git ls-files --error-unmatch core/relogin.py
→ error: pathspec 'core/relogin.py' did not match any file(s) known to git
```

- 该文件**存在于磁盘但未进 git**（`?? core/relogin.py`），且是**模块顶层 import**。
- 后果：任何人克隆仓库、或在这台机器上误删该文件，**GUI 启动即 ImportError 崩溃**，整个自动化平台打不开（不只是抓鬼）。
- 同时 `gui/main_window.py` 的 `_on_relogin_now` 也 `from core.relogin import relogin_client`（函数内 import，只影响重登功能，不致命）。
- **建议**：尽快把 `core/relogin.py` 单独纳管提交（与本次 ZGUI 同性质的操作，用户已批准「备份+纳管」范式）。**但这超出本次授权范围，我没有执行**，等 team-lead 转用户定夺。

### 5.2 🟠 P1 — 两份 settings 的 `pid` 不一致

- `config/settings.json`：`"pid": null`
- `config/group1/settings.json`：`"pid": 15592`

窗口绑定到底读哪份需确认；`null` 会导致启动时无 PID。若抓鬼链路依赖启动即绑定，这会成为第一步失败点。

### 5.3 🟠 P1 — `task_engine.py` 的点击抖动是全局生效，且**与 ADR-0004 冲突**

`jitter_x/jitter_y` 作用于**所有点击事件**。抓鬼链路中的精密校准点（对话框按钮、天眼图标、「送你回地府」）若被设了 jitter，会引入随机偏移导致点偏。当前序列里已有一处右键事件设了 `jitter_x:6 / jitter_y:5`。

**更深的问题 —— 与 `docs/architecture/adr/ADR-0004-coord-jitter.md` 直接冲突：**

| ADR-0004 约定 | 本次新增实现 | 冲突 |
|---|---|---|
| 决策 #3：抖动逻辑**集中**到 `library/common`，消除 9 份复制（缺陷 #5） | 在 `task_engine.py` 又加了一套**独立**的 jitter | ❌ 现在是**两套并存**的抖动机制，缺陷 #5 回潮 |
| 决策 #2：抖动偏移必须在**游戏坐标域**算（`pixel_to_game`/`game_to_pixel`），「禁止在屏幕坐标域混算」 | 直接在**客户区像素域**做 `x += randint(-j, j)` | ❌ 违反坐标域约定；像素域抖动与游戏坐标不成比例，缩放/DPI 变化下偏移失真 |
| R4：抖动幅度保守 1~6，且靠 `arrival_verifier` 兜底 | 幅度由事件参数任意指定，**无到达验证兜底** | ❌ 点偏无自愈 |

叠加风险：地图包 `_JITTER_MODE`（到达失败时 1~6 游戏坐标抖动）与新 jitter 会**同时生效**，同一点击可能被抖两次。

**建议**：攻坚期间先把抓鬼序列所有事件的 jitter 置 0；jitter 的集中化按 ADR-0004 留给 Phase 4 重构，不要在引擎层另起炉灶。

### 5.4 🟡 P2 — `WORLD_BOSS.py` 的探针环境变量未验证

注释自述：`WORLDBOSS_DLG_WAIT=1.5` 是「未验证的中间值」，「0s/0.8s 都崩过」。若环境变量在外层被设置，会覆盖安全的 2.0s 默认值。建议攻坚前确认本机无此类环境变量。

---

## 6. 本次操作的合规性自查

| 约束 | 状态 |
|---|---|
| 未提交那 9 个文件 | ✅ 全部仍为 `M` |
| 未执行 `git add .` | ✅ 仅 `git add` 单个 ZGUI.py（由 eng-lead 执行，已复核） |
| 未提交 `core/relogin.py` | ✅ 仍为 `??` |
| 未使用 `--no-verify` / force push / `reset --hard` / `checkout --` | ✅ 均未使用 |
| 未修改 ZGUI.py 业务逻辑 | ✅ blob 与备份完全一致，未落笔 |
| 未删除 `backup/` 既有文件 | ✅ `black_screen.pyw`、`night_guard.py` 均在 |

---

## 7. 结论

- **回退基线已就绪**：`2677663a6509afdbb93deb7a7e646b8b43a80d3b` + 备份文件，三方哈希一致，可放心改动 `_bag_visible` / `_wait_task_done`。
- **Phase 5→6 门控 B2 判定：通过。**
- **待用户定夺**：§5.1（P0，relogin.py 纳管）、§5.2（pid 不一致）、§5.3（jitter 是否影响抓鬼精密点击）。
