# S1 · T3 背包判据改造报告 —— `_bag_visible` 改用「本类开关==true」

> 任务：T3 · P1｜执行：eng-lead-2（程基岩）｜日期：2026-09-03
> 代码改动：`tasks/library/ZGUI.py:794-815`（工作区，**未提交 git**）
> 验证脚本：`tools/_verify_bag_judge.py`（只读，零点击）

---

## 1. 改动内容（diff 摘要）

**位置**：`tasks/library/ZGUI.py:794-815`（旧 794-810，+5 行）

**Lua 判据变更：**

```
旧（物品数据计数>0）                          新（面板开关布尔值）
─────────────────────────────────────       ─────────────────────────────────────
local j = tp.主界面 and …界面数据            local j = tp.主界面 and …界面数据
local pd = j and j[3] and j[3].物品数据      local pd = j and j[3]
if type(pd) ~= 'table' then 'no'            if type(pd) ~= 'table' then 'false'
local c = 0                                 local sw = pd.本类开关
for _,v in pairs(pd) do … c=c+1             -- 兼容布尔 true 与字符串 'true'
__out = (c > 0) and 'true' or 'false'       __out = (sw==true or tostring(sw)=='true') and 'true' or 'false'
```

要点：
- 返回值约定不变：仍经 `__out` 返回 `'true'/'false'`，Python 侧仍 `== "true"`。**对外契约零变化**，3 个调用方无需改动。
- 旧判据在 `type(pd)~='table'` 时返回 `'no'`（`!= 'true'` → False）；新判据统一返回 `'false'`，语义更准确（no_table = 未打开）。
- 兼容 `本类开关` 落库为布尔 `true` 或字符串 `'true'` 两种形态（网关序列化差异，防御性，不改变语义）。
- docstring 按 `★2026-09-03` 现有风格更新，写明旧判据缺陷与本判据依据。

**旧判据的实际缺陷**（改造动机）：背包**打开但物品栏为空**时 `计数>0` 不成立 → 误判"未打开" → `_bag_ensure_open` 会去点背包按钮 → **把打开的背包点关**，直接违反「背包保持打开」硬约束，且关包后天眼符/合成旗坐标全丢。新判据读面板自带开关位，与物品是否为空无关。

**语法校验**：`python -m py_compile tasks/library/ZGUI.py` → exit 0。

---

## 2. 上游影响评估

调用关系（grep 全仓库实测）：

```
_bag_visible        ← _bag_ensure_open(:829,836,840) ×3、_bag_ensure_close(:845,852,854) ×3
_bag_ensure_open    ← zhuagui_use_tianyan(:919)、zhuagui_go_back_changan(:955)
_bag_ensure_close   ← （无任何调用方，见 2.2）
tianyan_read_pos    ← zhuagui_use_tianyan(:918,922)   【不经过 _bag_visible】
```

### 2.1 `_bag_ensure_open`（:829-840）—— 影响：**正向改善，无新增风险**

- 行为：`_bag_visible()==True` 即直接返回不点击；False 才点背包按钮。
- 新判据下"背包打开但为空"的场景从误判 False（→ 多余点击 → 关包）修正为 True（→ 不点击）。**风险下降**。
- 调用方 `zhuagui_use_tianyan`(:919) 与 `zhuagui_go_back_changan`(:955) 均只在"目标物品读不到"时才走到 `_bag_ensure_open`，逻辑不变。

### 2.2 `_bag_ensure_close`（:843-854）—— 风险路径**不可达**（已 grep 全仓库确认）

用户硬约束是「背包保持打开不得关闭」，风险 = 新判据误判导致 `_bag_ensure_close` 去点背包按钮。结论：

- **`_bag_ensure_close` 当前在全仓库没有任何调用方。** grep ` _bag_ensure_close` 命中仅三处：定义本身（:843）、`backup/ZGUI.py.bak_20260903_1847`（历史备份）、`ZGUI.py:931` 的**注释**（"因此不再调用 _bag_ensure_close，保持背包打开状态"）。
- 即该函数是**死代码**，风险路径**不可达**，本次判据改动不会触发任何关包点击。
- 遗留建议（不在本次范围，未动）：该函数留着就是一颗"未来谁顺手一调就关包"的雷。建议后续要么删除、要么在 docstring 首行加显式警告「⚠ 违反'背包保持打开'硬约束，禁止在抓鬼链路调用」。是否处理请用户定夺。

### 2.3 `tianyan_read_pos`（:857）/ `zhuagui_use_tianyan`（:898）—— **判据改动不影响**

- 两者均**自行**用独立 Lua 直接读 `界面数据[3].物品数据`（`tianyan_read_pos` :868-886），**不经过 `_bag_visible`**，判据替换对读物品坐标零影响。
- 间接影响仅一处且为改善：`zhuagui_use_tianyan` 先 `tianyan_read_pos` 读不到 → 走 `_bag_ensure_open`。背包开着但**没天眼符**时，旧判据会误点背包按钮；新判据直接返回 True，随后 `tianyan_read_pos` 返回 (0,0) → 准确报「天眼符坐标读取失败（背包未打开或无天眼符）」。不再有无谓点击。
- `zhuagui_go_back_changan`（合成旗，:955）同理受益。

### 2.4 遗留风险（T3 之前就存在，本次未触碰，需上报）

**Lua 调用失败时的关包风险**：`_lua_call` 异常返回 `None` → `_bag_visible()` 判 False → `_bag_ensure_open` 点背包按钮 → 若此刻背包实际是打开的，会被**点关**。这是网关瞬断/超时的场景，与判据新旧无关（旧判据同样如此），本次未修。
**建议后续**：让 `_bag_visible` 区分「确定关闭」与「读取失败」（例如返回 tri-state，或失败时 `_bag_ensure_open` 直接放弃而非重试点击）。涉及函数签名变更，超出 T3 授权范围。

---

## 3. 验证结果：**网关不在线，待游戏在线后执行**

探测过程（只读，无副作用）：

| 探测 | 结果 |
|---|---|
| `Invoke-WebRequest http://127.0.0.1:18082/api/status -TimeoutSec 3`（第 1 次） | **HTTP 502 Bad Gateway** |
| 同上（第 2 次） | **连接被拒**（WinError 10061） |
| `Get-NetTCPConnection -LocalPort 18082 -State Listen` | 无监听 |
| 游戏客户端进程 | **在跑**：胖子西游 PID 6568 / 13016 / 19632 / 21160 / 22704，另有「胖子西游专用多开器」PID 14048 |

结论：**网关（mhxy-mcp-gateway）当前未就绪**（两次探测结果不一致，疑似正在启动/崩溃循环），Lua 读内存不可用 → 按派单要求走「不在线」分支，**未执行开态验证**。

脚本已写好并干跑通过（离线分支正确退出、给出恢复指引）：

```
py_compile tools/_verify_bag_judge.py → exit 0
python tools/_verify_bag_judge.py
→ [1] 网关探测 http://127.0.0.1:18082/api/status : 异常
     URLError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。
→ !! 网关不可用，无法读内存…（给出恢复指引后退出码 2）
```

### 待游戏在线后的执行清单

1. **开态验证**（背包打开时）：
   ```
   python tools/_verify_bag_judge.py --expect open
   ```
   应输出 `PASS  期望 打开(true)，判定一致`。
2. **关态验证 —— 需用户手动配合，脚本绝不代点**：
   用户自己在游戏里点一下把背包关掉，然后跑同一条命令：
   ```
   python tools/_verify_bag_judge.py --expect close
   ```
   应输出 `PASS  期望 关闭(false)，判定一致`。
3. 脚本同时打印全面板 `本类开关` 总览与面板3 详情（开关/状态/类型/物品数），若 FAIL 可直接用这些原始字段定位。

**脚本安全性**：全部操作经 `ZGUI._lua_call` 只读内存字段（3 条 Lua：全面板总览 / 面板3 详情 / 判据复现），零点击、零 PostMessage、零抓鬼循环；脚本自身异常有兜底捕获，不会对游戏产生任何影响。

---

## 4. 合规自查

| 约束 | 状态 |
|---|---|
| 只读 Lua，禁止点击/发包/PostMessage | ✅ 改动与脚本均为纯读取 |
| 不启动抓鬼循环 | ✅ |
| 背包保持打开 | ✅ 未产生任何关包动作；且评估结论为风险路径不可达（2.2） |
| 不提交 git | ✅ 改动仅在工作区 |

---

## 5. 结论

- 判据已按用户确认事实改造完成，对外契约零变化，3 个调用方行为均改善或不变。
- 「背包保持打开」硬约束下的最高风险点 `_bag_ensure_close` 已确认为**死代码、路径不可达**。
- 验证脚本就绪，**开态/关态验证均待网关恢复 + 用户手动配合关包**后执行。
- 遗留上报项：① `_bag_ensure_close` 死代码处置；② Lua 失败→误点关包的既有路径（建议 tri-state）。
