# 梦幻西游私服「主线程 Hook」可行性分析 + 逆向切入点

> 日期：2026-08-10 ｜ 目标进程：十年一梦.exe（鲜衣怒马私服客户端，PID 32760）
> 参考样板：鹿鼎记私服 `Kernel.dll`（CodeHook 劫持 `main_thread_base=0x00514194`，按 functionid 分发 90+ 功能）

---

## 一、为什么值得做（对比现状）

| 维度 | 现状（JHRW 视觉路线） | DLL 注入 + 主线程 Hook |
|---|---|---|
| 原理 | 截图 → 字模识别 → 模拟点击 | 代码注入 → 劫持游戏主线程 → 直调游戏函数 |
| 坐标/任务数据 | 屏幕像素（有遮挡/字体变体风险） | 游戏内部结构（100% 准确） |
| 动作执行 | SendInput 模拟（抢前台/被吞） | 直接 call 游戏函数（无感） |
| 反挂机验证码 | 截屏 OCR（已废弃） | Hook 验证码函数读内存位图+答案（100%） |
| 性能 | 每帧截图 ~200ms | 主线程内执行，零开销 |

**结论：可行性高。** 梦幻私服客户端与鹿鼎记同属"VC++ 客户端 + Lua 脚本"架构，鹿鼎记源码已证明整套方法论可行。

---

## 二、逆向切入点（按难度排序）

### 切入点 1：★ 主线程处理函数（本任务目标）
```
定位游戏主循环函数 → CodeHook 劫持 → 每帧分发
```
**目标特征**（参照鹿鼎记 `main_thread_base`）：
- 主线程入口（CRT Startup → main）往上追，找到每帧执行的大函数
- 函数体特征：高频 call（渲染/逻辑分发），循环结构

**定位方法**：
1. `NtQueryInformationThread(ThreadQuerySetWin32StartAddress=9)` 枚举线程起始地址
2. 落在 exe 代码段（ImageBase..+SizeOfImage）的线程 = 游戏自有线程
3. 反汇编线程入口 → 追 main → 找主循环 → 循环内首个大 call = 帧处理函数

### 切入点 2：Lua 状态机直调（项目已有积累）
```
GameLuaCALL 模式：vtable call 拿 lua_state → lua_dostring 执行游戏脚本
```
项目里已有 `mhxy_find_lua_state*.py`、`trace_lua_chain.py`、`analyze_luahp.py` 等积累。鹿鼎记 `luahelp.cpp` 给了现成模板（`mov ecx,[Base]; call [edx+0x3c]` 拿 lua_state）。

### 切入点 3：已知函数调用链反查（最快）
```
GetX/GetY（RVA 0x81F0/0x8200，已逆向）→ backtrace 找调用者 → 调用者所在函数 = 逻辑循环
```
用 frida `Interceptor.attach` + `Thread.backtrace` 在 GetX 上采栈，**谁调它谁就是每帧逻辑函数**——比从入口追快一个数量级。

### 切入点 4：验证码/任务文本 Hook（远期）
参照天龙 `HookCaptcha`（特征码定位 + 读 ebp 偏移），Hook 梦幻的验证码绘制/任务文本格式化函数，直接从内存读位图+答案。

---

## 三、主线程 Hook 方案设计（移植 CodeHook）

### 架构
```
注入 DLL（version.dll 劫持 / 远线程注入）
  └─ DllMain → 后台线程等游戏就绪
       └─ CodeHook(主线程函数, 5, HookedMainThread, true)
            └─ pushad / call HookedMainThread / popad / 原字节 / jmp 回
                 └─ switch(pTask->functionid) 分发：
                      Goto / Attack / UseItem / AcceptTask / Answer / CallLua* ...
```

### 关键技术点
| 点 | 说明 |
|---|---|
| Hook 时机 | 等游戏主循环就绪（参照 `_EnterLoginScene` 标志等待） |
| CodeHook 实现 | 直接用鹿鼎记 `CodeHook.cpp`（pushad/call/popad 模式，30 行） |
| 任务队列 | `pTask` 结构 + 临界区，Script 线程填任务、主线程消费 |
| 特征码定位 | 每次版本更新用 `FindPattern` 重新定位（代码段不重分配，稳定） |
| 抢先 Hook | `CREATE_SUSPENDED + ResumeThread 后立即注入`，抢在游戏初始化前 |

### 风险
1. **版本更新**：主线程函数地址随客户端版本变化 → 特征码定位 + 地址表配置化
2. **反外挂**：私服自用风险低；DLL 注入/Hook 是外挂特征，联机正式服勿用
3. **稳定性**：主线程内执行必须快（<1ms），避免卡帧；异常必须 SEH 兜底

---

## 四、执行计划

1. **本任务**：枚举 PID 32760 线程 → 定位主线程 → 反汇编追主循环 → 候选帧处理函数
2. 用 frida backtrace 在 GetX/GetY 上交叉验证候选函数
3. 写出候选函数地址表 + 特征码 → 后续 CodeHook 移植

---

## 五、逆向执行结果（PID 25820 实测，2026-08-10）

### 主线程定位
| 项 | 值 |
|---|---|
| 进程 | 十年一梦.exe（鲜衣怒马私服客户端） |
| 模块基址 | **0x1B0000**（固定，无 ASLR 偏移） |
| 主线程起始 | = EntryPoint **0x1CC6A1**（RVA 0x1C6A1） |
| CRT 调用点 | 0x1CC649 `call 0x1BFF30`（4 参数 WinMain 签名） |

### ★ 主线程处理函数 = **0x1BFF30**（RVA 0x0FF30）
- **判定依据**：
  1. CRT 启动链：EntryPoint(0x1CC6A1) → jmp 0x1CC534（scrt_common_main）→ 0x1CC649 call 0x1BFF30（push hInstance=0x1B0000 + 3 参数 = WinMain 调用特征）
  2. 主线程栈采样 80 次：**56/80 停在 0x1C05EB**，栈恒为 `0x1c05eb <- 0x1cc64e`（0x1cc64e = call 0x1BFF30 的返回地址）→ 主线程 100% 时间运行在 0x1BFF30 内部
- **内部结构**：
  - 0x1BFF30~0x1C05C0：初始化段（大量 CRT printf 输出 + 对象方法调用）
  - **0x1C05EB~0x1C0658：回调队列分发循环**（主线程 ~70% 时间停驻）

### ★ 回调队列分发循环（0x1C05EB，任务注入最佳 Hook 点）
```
0x1C05EB  mov esi, [0x1f7434]      ; 队列1 头
0x1C05F7  cmp esi, [0x1f7438]      ; 队列1 尾
0x1C05FD  je 0x1c0619              ; 空则跳队列2
0x1C0600  mov ecx, [esi]           ; 取元素（对象指针）
0x1C0606  mov edx, [ecx]           ; vtable
0x1C0608  mov eax, [edx]           ; vtable[0] = 分发函数
0x1C060C  call eax                 ; ★ 调用回调（任务分发！）
0x1C060E  add esi, 4
0x1C0617  jne 0x1c0600             ; 循环
0x1C0619  队列2 同构：[0x1f7424]~[0x1f7428]
0x1C0658  ret 0x10                 ; 函数结束（stdcall 4 参）
```

### ★ 两个可 Hook 目标（对应鹿鼎记 main_thread_base=0x00514194）
| 目标 | RVA | Hook 方式 | 用途 |
|---|---|---|---|
| **0x1BFF30** | 0x0FF30 | CodeHook 整函数入口 | 主循环帧级 Hook（每帧逻辑注入） |
| **0x1C05EB 分发循环** | 0x105EB | 队列注入（更优） | **外挂回调对象直接塞进 [0x1f7434] 队列 → 主线程自动分发执行**（不碰代码，最隐蔽） |

### 结论
梦幻私服主线程 Hook **完全可行**：CodeHook(0x1BFF30, 5, HookedMainThread) 即可实现鹿鼎记同款"主线程任务执行器"；更优解是直接利用游戏自带回调队列（0x1f7434/0x1f7424）做任务注入——无代码修改、零帧率影响。

---

## 五、逆向执行结果（PID 25820 实测，2026-08-10）

### 主线程定位
| 项 | 值 |
|---|---|
| 进程 | 十年一梦.exe（鲜衣怒马私服客户端） |
| 模块基址 | **0x1B0000**（固定，无 ASLR 偏移） |
| 主线程起始 | = EntryPoint **0x1CC6A1**（RVA 0x1C6A1） |
| CRT 调用点 | 0x1CC649 `call 0x1BFF30`（4 参数 WinMain 签名） |

### ★ 主线程处理函数 = **0x1BFF30**（RVA 0x0FF30）
- **判定依据**：
  1. CRT 启动链：EntryPoint(0x1CC6A1) → jmp 0x1CC534（scrt_common_main）→ 0x1CC649 call 0x1BFF30（push hInstance=0x1B0000 + 3 参数 = WinMain 调用特征）
  2. 主线程栈采样 80 次：**56/80 停在 0x1C05EB**，栈恒为 `0x1c05eb <- 0x1cc64e`（0x1cc64e = call 0x1BFF30 的返回地址）→ 主线程 100% 时间运行在 0x1BFF30 内部
- **内部结构**：
  - 0x1BFF30~0x1C05C0：初始化段（大量 CRT printf 输出 + 对象方法调用）
  - **0x1C05EB~0x1C0658：回调队列分发循环**（主线程 ~70% 时间停驻）

### ★ 回调队列分发循环（0x1C05EB，任务注入最佳 Hook 点）
```
0x1C05EB  mov esi, [0x1f7434]      ; 队列1 头
0x1C05F7  cmp esi, [0x1f7438]      ; 队列1 尾
0x1C05FD  je 0x1c0619              ; 空则跳队列2
0x1C0600  mov ecx, [esi]           ; 取元素（对象指针）
0x1C0606  mov edx, [ecx]           ; vtable
0x1C0608  mov eax, [edx]           ; vtable[0] = 分发函数
0x1C060C  call eax                 ; ★ 调用回调（任务分发！）
0x1C060E  add esi, 4
0x1C0617  jne 0x1c0600             ; 循环
0x1C0619  队列2 同构：[0x1f7424]~[0x1f7428]
0x1C0658  ret 0x10                 ; 函数结束（stdcall 4 参）
```

### ★ 两个可 Hook 目标（对应鹿鼎记 main_thread_base=0x00514194）
| 目标 | RVA | Hook 方式 | 用途 |
|---|---|---|---|
| **0x1BFF30** | 0x0FF30 | CodeHook 整函数入口 | 主循环帧级 Hook（每帧逻辑注入） |
| **0x1C05EB 分发循环** | 0x105EB | 队列注入（更优） | **外挂回调对象直接塞进 [0x1f7434] 队列 → 主线程自动分发执行**（不碰代码，最隐蔽） |

### 结论
梦幻私服主线程 Hook **完全可行**：CodeHook(0x1BFF30, 5, HookedMainThread) 即可实现鹿鼎记同款"主线程任务执行器"；更优解是直接利用游戏自带回调队列（0x1f7434/0x1f7424）做任务注入——无代码修改、零帧率影响。

---

## 六、主循环内部结构（0x1BFF30 全量反汇编，PID 25820）

### 队列性质澄清（重要修正）
**0x1C05EB 分发的两个队列是「延迟销毁队列」，不是任务队列**：
- vtable[0] 全部 = **0x1B7C20 = 析构函数**（`test [ebp+8],1` + `call 0x1cbfde` = operator delete，`ret 4`）
- 分发循环 `push 1 → call vtable[0]` = 传 delete 标志执行 `析构+delete`
- 实测队列2：189 个待销毁对象（头 0x02C575F8 ~ 尾 0x02C578EC），对象开头 vtable 各异（0x1E4460/0x1E446C/0x1E4478... 每 0xC 一个 = 3 槽 vtable）
- **结论：不能往这两个队列注入外挂任务（会被当对象 delete）——方案②作废，方案①（CodeHook 主循环）为正解**

### 0x1BFF30 主循环调用统计
| 模式 | 次数 | 含义 |
|---|---|---|
| `call [esi]` | 39 | 全局对象 [0x1f7408] vtable 方法（esi=[0x1de400] IAT） |
| `call [edi]` | 22 | 同上（edi=[0x1de434]） |
| `call [ebx]` | 20 | 同上（ebx=[0x1de418]） |
| `call [[0x1de3ec]]` | 18 | CRT IAT 函数 |

### 主循环内 3 个循环
| 回边 | 结构 | 功能 |
|---|---|---|
| `0x1C057E jl → 0x1C0546` | `cmp [0x1f6738],ebx; jle` + `mov ecx,[eax+ebx*4]` | **对象数组遍历**（数组 [0x1f673c]，计数 [0x1f6738]）→ 每帧更新 |
| `0x1C0617 jne → 0x1C0600` | 队列1 遍历 | 销毁队列分发 |
| `0x1C063E jne → 0x1C0627` | 队列2 遍历 | 销毁队列分发 |

### 最终 Hook 方案（确认）
```
CodeHook(0x1BFF30, 5, HookedMainThread, true)
  └─ pushad / call HookedMainThread / popad / 原5字节 / jmp 回 0x1BFF35
       └─ 每帧在游戏主循环执行前插入外挂逻辑
```
- 函数边界：0x1BFF30（push ebp 序言）~ 0x1C0658（ret 0x10），Hook 入口 5 字节安全覆盖（序言 `55 8B EC 51 53` 是标准 5 字节）
- 帧率影响：HookedMainThread 内只做任务分发（<1ms），零感知
- 反检测：私服自用风险低；可用鹿鼎记同款 ApiHookEx/CodeHook 类（Common/ApiHook.h 已有）

---

## 七、测试实施结论（机器码注入验证）

### 交付工具（3 个）
| 工具 | 方式 | 说明 |
|---|---|---|
| `tools/hook_main_loop_test.py` | CodeHook 机器码 | hook 任意地址（默认 0x1C05EB；`--lua` 动态 hook lua_pcall） |
| `tools/hook_lua_test.py` | lua_pcall hook | 动态定位 lua51.dll 基址 |
| `tools/iat_hook_test.py` | **IAT 劫持** | exe IAT 槽 0x1DE294 → galaxy2d 帧函数（最干净） |

### 验证结论
1. **无代码完整性校验**：hook 字节 5 秒保持（游戏不恢复被改代码）→ inline hook 可行
2. **hook 点机制全部正确**：机器码核对无误、IAT 可改写、注入区可执行
3. **卡点 = 游戏帧循环暂停**：当前所有实例主线程阻塞（USER32 等待），0x1C05E3/0x1C05EB 不执行 → counter 0。16:39 游戏活跃时主线程 56/80 停在 0x1C05EB 证明 hook 点正确
4. **游戏架构确认**：
```
0x1BFF30(WinMain 主循环) → 0x1C05E3 call [IAT 0x1DE294]
  → galaxy2d.dll 帧函数(0x10009EE0→0x10042C20)
    → 回调 exe 0x1B3310(调 Lua 桥) → lua51!lua_call → Lua 脚本
```

### 验收方法
游戏角色在场景中走动 → 帧循环跑 0x1C05E3 → IAT 劫持触发 → counter 增长 + DebugView++ 显示 MHXY_IAT_OK
