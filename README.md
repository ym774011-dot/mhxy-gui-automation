# 梦幻西游 GUI 自动化平台（胖子西游·十年一梦）

基于 **Lua 注入（pzxy worker）+ PostMessage 后台点击 + GUI 看护** 的多开抓鬼/门派闯关自动化平台。
当前主力链路：**5 开组队抓鬼**（队长接任务→天眼瞬移→找鬼 CALL→完成判定→顺手打稀有怪→出售）+ **门派闯关**（报名→传送→CALL 护法→放马过来），由 PP GUI 一体机负责启动、播种、掉线重连与组队协调。

---

## 1. 目录结构（关键路径）

```
mhxy-gui-automation/
├─ tools/
│  ├─ pp_gui.py            # ★PP GUI 一体机：启动/播种/掉线重连/组队协调/任务拉起（5开主力入口）
│  ├─ squad_auto_team.py   # 组队链路：走位锚点/建队/申请/批准/天覆阵 + 队长联动信号
│  ├─ zhuagui_squad.py     # 5开编排器（登录播种→组队→拉任务）+ clean_pid_ipc
│  └─ member_sell_loop.py  # 队员纯出售循环（--pid --gateway）
├─ run_unlimited_test.py   # 队长抓鬼主循环（无限跑批 + 闯关调度）
├─ tasks/library/
│  ├─ ZGUI.py              # 抓鬼核心库：IPC/Lua/点击/天眼/组队/自动战斗/稀有怪/出售
│  ├─ CHUANGGUAN.py        # 门派闯关（17 门派 + 无校准直接 CALL + 摄妖香）
│  ├─ WORLD_BOSS.py        # 世界 BOSS farming
│  └─ JHRW*/SYBUZ2/SYHS 等 # 江湖任务/江湖人物/顺手江湖等任务包
├─ library/map_packs/      # 9+1 地图功能包（ALG/BXG/CAC/CSC/DHW/JNYW/JYC/MPCG/XLNR/ZZG）
├─ main.py                 # 函数专用 GUI（Qt，任务编排器，非 5 开主力）
├─ library/pzxy_ipc.py     # 文件 IPC 客户端（PzxyWorker，GBK，通道 pzxy_p<pid>）
├─ PP-GUI.bat              # ★双击启动 PP GUI
├─ start_group1.bat / start_group2.bat  # 函数专用 GUI 组1(蓝)/组2(绿)
├─ requirements.txt
├─ test_data/              # 配置与运行数据（pp_gui_config.json / team_link.json / jsonl 日志）
└─ logs/                   # task_p<pid>_run.log（任务脚本尸检日志）等
```

## 2. 快速开始

1. `git clone` 本仓库 → `pip install -r requirements.txt`（另需 PyQt5，见 requirements）。
2. 双击 **PP-GUI.bat** 启动 PP GUI → 选择游戏路径 →【启动队长】/【启动队员】拉起 5 个游戏实例。
3. 实例停在登录界面后 GUI 自动**播种 worker**（通道 `pzxy_p<pid>`）。
4. 打开【记录登录点击】手动登录一次（每号录一次，落 `test_data/pp_gui_config.json`）；此后掉线重登自动重放。
5. 点【启动脚本】：自动完成 组队（传送/走位/建队/申请/批准/天覆阵）→ 按角色拉任务
   （队长 = `run_unlimited_test.py`，队员 = `member_sell_loop.py`）。
6. 此后全自动：掉线重启闭环、缺员补组、闯关调度均无人值守。

> 备份与恢复（换机 3 步）见文末第 8 节。

## 3. 核心模块

| 模块 | 职责 | 关键点 |
|---|---|---|
| `tools/pp_gui.py` | 一体机 GUI：启动实例、播种、录登录、掉线重启、组队协调、任务拉起、卫生自洁 | 配置 `test_data/pp_gui_config.json` |
| `tools/squad_auto_team.py` | 组队原语 + **队长联动信号**（publish/read/revoke） | 锚点 [139,80]（世界 2780,1600） |
| `run_unlimited_test.py` | 队长跑批：接任务→天眼→CALL→判定→顺手打→闯关调度 | 输出 jsonl + 轮次统计 |
| `tasks/library/ZGUI.py` | 抓鬼全链路函数库（3600+ 行） | `_lua_call` 经 `file://pzxy_p<pid>` 文件 IPC（GBK） |
| `tasks/library/CHUANGGUAN.py` | 门派闯关 | 17 门派表（含天机城/女魃墓），无校准门派落地直接 CALL |
| `library/pzxy_ipc.py` | Python 侧 IPC worker 客户端 | `--WB:<cid>\n<lua>`，tmp+replace 原子写 |

## 4. 关键流程（与代码行为一一对应）

### 4.1 队长先行联动（组队状态机）
- 信号文件：`test_data/team_link.json`（`epoch`+`leader_pid`+`cap_world`+`ready`，TTL 30 分钟）。
- **队长侧**：走到大唐官府 [139,80]（±3 格实测确认）→ 建队成功（或队伍仍在）→ `publish_link`。
- **队员侧**：只有收到信号才传送+申请；初始组队/缺员补组均由该信号驱动。
- **队长掉线/重启**：`_begin_restart` 立即撤销信号 → 队员原地等待，绝不凭旧信号传送。

### 4.2 队长任务启动闸
- `_spawn_task` 对队长分支做 `_leader_wait_reason` 校验：所有队员实例在线 **且** 队长顶栏队伍数 ≥ 注册总人数。
- 未到齐 → 拒绝启动并在日志列出缺谁（如 `未到齐：这是帅哥 p15652（掉线/未登录）…`）；队员出售脚本不受此限。

### 4.3 掉线重启闭环
- 进程死/窗口消失/标题退回登录界面/tp 被服务器抹掉 → `_begin_restart`：
  杀旧任务脚本 → 强杀旧进程 → 重启游戏 → 补种（先清该 PID 旧 IPC）→ 重放登录点击 → 按角色拉任务。
- 战斗中不做缺员判定（防误杀）；tp 健康检查连续 3 次明确 `tp=nil` 才重启。

### 4.4 自动战斗会话闸
- 「自动」开启一次后跨战斗常开；**每个游戏登录会话只点一次**（首登/重启后第一次进战斗）。
- 闸 key = 游戏 PID + 窗口标题（标题尾嵌登录时间戳，重登即刷新）；`_AUTO_ONCE["done"]` 已检查，
  本会话后续一律返回 `auto_on` 不再点（已知代价：会话中被意外点关不补救）。

### 4.5 卫生自洁（不影响游戏操作）
- 卫生线程：启动 20s 首轮，之后每 24h 一轮。
- IPC 死文件：`E:\DS\tmp\pzxy_p*` 按 PID 分组，非托管 + 整组 mtime 超 24h + **进程已死** 才删。
- 日志轮转：`pp_gui.log` / `logs/automation.log` 超 20MB 转 `.bak`；被占用时 copy+truncate 兜底。
- 播种前：`plant()` 先清该 PID 旧 IPC 三件套（防 Windows PID 复用读到陈旧通道）。

### 4.6 门派闯关
- 调度：队长抓鬼 ok 计数达标（如 16/25 次）自动触发，闯关完成/失败后回到抓鬼。
- 流程：报名（旗回长安→点 [469,66]→活动使者→参加活动）→ 摄妖香（25 分钟闸防连环消费）→
  背包传送按钮直传门派 → CALL 护法（按门派名/护法扫地图单位，与位置无关）→
  「放马过来」点标定矩形 (123,307)-(160,317) → 自动战斗。
- 门派表 `SECTS` 17 个；任务追踪解析兜底 `立即前往#X#` 独立彩色段；无校准门派不走路直接 CALL。

### 4.7 顺手打稀有怪
- 抓鬼间隙顺带：知了王/星宿/远古/恶作剧大王/地煞星/天罡星；
  星宿与恶作剧大王按称谓匹配，其余按名称；对话框优先红字行检测，退标定矩形。

## 5. 参数说明（CLI）

**run_unlimited_test.py（队长）**
| 参数 | 默认 | 说明 |
|---|---|---|
| `--gateway` | 自动探测 | IPC 通道，如 `file://pzxy_p5012` |
| `--role` | 二号美人 | 角色名（窗口标题匹配） |
| `--rounds` | 0（无限） | 跑批轮数上限 |
| `--timeout` | 20.0 | 单轮完成判定超时（秒） |
| `--wait-dialog` | 1.2 | 对话框等待 |
| `--min-interval` / `--max-interval` | 15 / 30 | 轮间随机节奏（秒） |
| `--sample-interval` | 1.5 | 轮内采样间隔 |
| `--reset-every` | 10 | 每 N 轮重置统计 |
| `--tag` | 空 | 运行标签（进 jsonl 文件名，A/B 分组用） |

**member_sell_loop.py（队员）**：`--pid`（必填）、`--gateway`、`--min-count`（0）、`--interval`（75s 出售节奏）。

**zhuagui_squad.py（5 开编排器）**：`--stop`（停小队全部进程）、`--ports`（默认 18091-18095）、`--wait-login`（1800s）。

## 6. 配置与数据文件

| 文件 | 用途 |
|---|---|
| `test_data/pp_gui_config.json` | 游戏路径、实例角色、登录点击录制 |
| `test_data/team_link.json` | 队长联动信号（自动生成/撤销，勿手工编辑） |
| `test_data/zhuagui_*.jsonl` | 每轮明细（A/B 对比与复盘用） |
| `logs/task_p<pid>_run.log` | 任务脚本 stdout/stderr 尸检日志（崩溃 traceback 在此） |
| `data/pzxy_map_ids.json` | 地图编号→名称学习表（传送圈译码） |

## 7. 已知边界（设计取舍，非 bug）

- 「自动」会话中被意外点关，本会话不补救（用户定案的简化代价）。
- 队长联动信号 TTL 30 分钟：队长长期在线且未再走位时，队员重登以**当前队长顶栏/坐标**为准（`_leader_link_ok` 三重校验保留在历史分支，当前版以信号存在为准）。
- 闯关无校准门派走「落地直接 CALL」，个别门派CALL未中会下轮重试。

## 8. 备份与恢复（换机 3 步）

全部代码/配置/模型/模板/任务文件均在 git + GitHub：
✅ 代码与配置 ✅ YOLO 模型 `models/active.pt` ✅ 28 张模板图 ✅ 地图坐标
✅ 9 个地图函数包 ✅ 任务序列+事件配置 ✅ 字模库/禁区/UI 避让数据

```bash
git clone https://github.com/ym774011-dot/mhxy-gui-automation.git
pip install -r requirements.txt
# 双击 PP-GUI.bat 直接跑
```

---
*本文档依据 2026-09-10 代码实际行为重写（commit a2ba554）；与代码不一致时以代码为准，发现文档过期请直接改此文件。*
