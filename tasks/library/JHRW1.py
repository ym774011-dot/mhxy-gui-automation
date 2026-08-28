# -*- coding: utf-8 -*-
"""
JHRW1 - 江湖任务 Lua 层直读（替代 JHRW 字模指纹识别）
================================================================
功能: 通过 mhxy-mcp-gateway 读取游戏 Lua 层任务数据（不截屏、不字模识别）

数据源（2026-08-20 实测确认）:
  - tp.队伍[1].任务          任务标识数组（玩家id_类型_时间戳）
  - tp.队伍[1].主线/支线/江湖次数/师门次数  任务计数（实时）
  - tp.窗口.任务追踪栏.数据记录  追踪栏任务对象（类型/时间戳/气血/魔法）
  - tp.窗口.任务追踪栏.介绍文本.文字  任务文本渲染行（任务激活时有内容）
  - 地图名: tp.窗口.小地图.地图名称（当前地图，权威）

边界:
  - 任务名/目标地图/坐标 依赖"任务追踪栏有激活任务"（介绍文本有行）
  - 无激活任务时返回计数 + 任务标识 + 空文本字段
  - 游戏待机时网关 socket 缓存可能空，只读操作不受影响

依赖: mhxy-mcp-gateway 网关（frida 附加，HTTP 默认 18082）
"""
import json
import time
import urllib.request
from typing import Optional, Tuple

try:
    from utils.logger import logger
except Exception:  # 独立运行
    import logging
    logger = logging.getLogger("JHRW1")
    logging.basicConfig(level=logging.INFO)

# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# ============================================================
__function_meta__ = {
    "JHRW1": {
        "title": "江湖任务 - Lua 层直读任务信息（网关，替代字模）",
        "args": {
            "target_location": "可选，期望地图名（如 '建邺城'），不匹配则视为失败",
            "target_coord": "可选，期望坐标 (x, y)，不匹配则视为失败",
            "gateway": "mhxy-mcp-gateway 地址（默认 http://127.0.0.1:18082）",
            "pid": "游戏进程 PID（仅记录）",
            "verbose": "是否打印过程日志",
        },
    },
}

try:
    from core.group_config import gateway_url
    DEFAULT_GATEWAY = gateway_url()  # ★2026-08-25 多组：组1=18082，组2=18083...
except Exception:
    # 2026-08-28 补丁3：最后兜底，仅 group_config 导入失败（独立 CLI 运行）时生效。
    DEFAULT_GATEWAY = "http://127.0.0.1:18082"


def _lua_call(gateway: str, code: str, timeout: float = 10.0) -> dict:
    """调网关 /api/lua 执行 Lua 代码，返回 {ok, value, error}。

    自愈（2026-08-24）：连接失败（10061）**或**网关内部 rpc 失败
    （script has been destroyed 等，HTTP 通但 frida 会话已随游戏重启失效）
    都触发 ensure_gateway 并重试一次，无需手动启动 mhxy-mcp-gateway。
    """
    req = urllib.request.Request(
        gateway.rstrip("/") + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    def _do():
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    try:
        d = _do()
    except Exception as e:
        d = None
        _err = e
    if d is None or not d.get("ok"):
        # 连接失败 或 网关内部失败（ok=false）→ 自动拉起网关 → 重试一次
        try:
            from core.gateway_guard import ensure_gateway
            ok, info = ensure_gateway(verbose=False)
        except Exception:
            ok, info = False, {}
        if not ok:
            err = d.get("error") if d is not None else _err
            return {
                "ok": False,
                "error": (
                    f"{err}（网关不可用且自动拉起失败：{info.get('error', '未知')}。"
                    f"请确认游戏已启动，或手动运行 E:/DS/mhxy-mcp-gateway/启动网关.bat）"
                ),
            }
        try:
            d = _do()
        except Exception as e2:
            return {
                "ok": False,
                "error": f"{e2}（网关自愈拉起后仍连接失败，检查 {gateway}）",
            }
    if d.get("ok"):
        return {"ok": True, "value": d.get("result", {}).get("value")}
    return {"ok": False, "error": d.get("error", "")}


# Lua 读取代码（GBK 由网关内部处理，此处写 UTF-8 源文件即可）
# 数据源优先级: 数据记录(结构化任务) > 介绍文本 > 计数
_LUA_READ = r'''
local out = {}
-- 1. 任务计数
out.count_main   = tostring(tp.队伍[1].主线 or 0)
out.count_branch = tostring(tp.队伍[1].支线 or 0)
out.count_jh     = tostring(tp.队伍[1].江湖次数 or 0)
out.count_sm     = tostring(tp.队伍[1].师门次数 or 0)
-- 2. 任务标识列表
local tl = {}
if type(tp.队伍[1].任务) == "table" then
  for i = 1, 5 do
    if tp.队伍[1].任务[i] then tl[#tl+1] = tostring(tp.队伍[1].任务[i]) end
  end
end
out.task_ids = table.concat(tl, ",")
-- 3. 追踪栏数据记录（结构化任务对象：名称/地图/坐标/进度）
--    字段实测: 名称 地图名称 地图编号 x y 江湖次数 类型 id 模型
local rec = {}
local rec_meta = {}
if type(tp.窗口.任务追踪栏.数据记录) == "table" then
  local n = 0
  for k, v in pairs(tp.窗口.任务追踪栏.数据记录) do
    n = n + 1
    if n <= 5 and type(v) == "table" then
      -- 优先选"有名称+地图+坐标"的活动任务记录
      if v.名称 and v.地图名称 and v.x then
        rec.name       = tostring(v.名称)
        rec.map_name   = tostring(v.地图名称)
        rec.map_id     = tostring(v.地图编号 or "")
        rec.x          = tostring(v.x)
        rec.y          = tostring(v.y)
        rec.progress   = tostring(v.江湖次数 or v.师门次数 or "")
        rec.type       = tostring(v.类型 or "")
        rec.model      = tostring(v.模型 or "")
        rec_meta.count = (rec_meta.count or 0) + 1
      end
    end
  end
end
out.rec_name   = rec.name or ""
out.rec_map    = rec.map_name or ""
out.rec_mapid  = rec.map_id or ""
out.rec_x      = rec.x or ""
out.rec_y      = rec.y or ""
out.rec_prog   = rec.progress or ""
out.rec_type   = rec.type or ""
out.rec_model  = rec.model or ""
-- 4. 介绍文本行数 + 文本行内容（兜底）
out.intro_lines = tostring(tp.窗口.任务追踪栏.介绍文本.行数量 or 0)
local txt = {}
if type(tp.窗口.任务追踪栏.介绍文本.文字) == "table" then
  local nn = 0
  for k, v in pairs(tp.窗口.任务追踪栏.介绍文本.文字) do
    nn = nn + 1
    if nn <= 30 and type(v) == "string" then txt[#txt+1] = v end
  end
end
out.intro_text = table.concat(txt, "|")
-- 5. 当前地图名
out.map_name = tostring(tp.窗口.小地图.地图名称 or "")
-- 6. 角色坐标（世界坐标，供参考）
out.world_x = tostring(tp.队伍[1].角色坐标 and tp.队伍[1].角色坐标.x or "")
out.world_y = tostring(tp.队伍[1].角色坐标 and tp.队伍[1].角色坐标.y or "")
_G.__out = ""
for k, v in pairs(out) do _G.__out = _G.__out .. k .. "=" .. v .. "\n" end
'''


def _parse_lua_output(text: str) -> dict:
    """解析 Lua 输出的 key=value 行。"""
    data = {}
    if not text:
        return data
    for line in text.splitlines():
        line = line.strip()
        if "=" in line:
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip()
    return data


def JHRW1(
    target_location: Optional[str] = None,
    target_coord: Optional[Tuple[int, int]] = None,
    gateway: str = DEFAULT_GATEWAY,
    pid: Optional[int] = None,
    verbose: bool = False,
):
    """
    江湖任务 Lua 层直读（替代字模指纹方案）。

    :param target_location: 可选期望地图名，匹配验证
    :param target_coord: 可选期望坐标 (x, y)，匹配验证
    :param gateway: 网关地址
    :param pid: 游戏 PID（仅记录）
    :param verbose: 是否打印详细日志
    :return: dict（结构兼容 JHRW 字模版）
    """
    t0 = time.time()
    r = _lua_call(gateway, _LUA_READ)
    if not r.get("ok"):
        return {
            "success": False,
            "pid": int(pid or 0),
            "quest_name": "",
            "target_location": "",
            "target_coord": None,
            "progress_text": "",
            "progress_num": 0,
            "description": f"网关读取失败: {r.get('error', '')}（网关是否运行？{gateway}）",
            "desc_addr": 0,
            "npc": "",
            "matched": False,
            "message": "任务信息查找失败（网关不可用）",
            "source": "lua_gateway",
            "stale": False,
            "quest_name_confidence": 0.0,
            "target_location_candidates": [],
            "quest_signatures": {},
        }
    d = _parse_lua_output(r.get("value") or "")

    # ---- 数据记录结构化字段（优先，任务激活时最全）----
    quest_name = ""
    target_location_out = ""
    target_coord_out = None
    progress_num = 0
    npc_name = ""
    data_rec_name = d.get("rec_name", "").strip()
    if data_rec_name:
        quest_name = data_rec_name
        if d.get("rec_map"):
            target_location_out = d["rec_map"].strip()
        rx, ry = d.get("rec_x", "").strip(), d.get("rec_y", "").strip()
        if rx and ry:
            try:
                target_coord_out = (int(float(rx)), int(float(ry)))
            except (TypeError, ValueError):
                pass
        if d.get("rec_prog"):
            try:
                progress_num = int(float(d["rec_prog"]))
            except (TypeError, ValueError):
                pass
        npc_name = d.get("rec_model", "").strip()

    # ---- 从介绍文本解析任务信息（数据记录无名称时的兜底）----
    intro_text = d.get("intro_text", "")
    if not quest_name and intro_text:
        # 过滤非文本行（字体资源路径等）
        _BAD = (".ttc", ".ttf", ".otf", "C:/", "C:\\")
        lines = [l for l in intro_text.split("|") if l.strip()
                 and not any(b in l for b in _BAD)]
        if lines:
            quest_name = lines[0].strip()
        import re
        for line in lines:
            m = re.search(r"\((\d+)\s*,\s*(\d+)\)", line)
            if m:
                target_coord_out = (int(m.group(1)), int(m.group(2)))
                # 坐标行前缀可能是地图名（黄通道语义）
                pre = line[:m.start()].strip().rstrip("(:：,")
                if pre:
                    target_location_out = pre
                break
        # 进度: "第N次" 或 纯数字
        for line in lines:
            m = re.search(r"第(\d+)次", line)
            if m:
                progress_num = int(m.group(1))
                break
        if not progress_num:
            for line in lines:
                m = re.search(r"^(\d+)$", line.strip())
                if m:
                    progress_num = int(m.group(1))
                    break

    # 地图名兜底：介绍文本没解析到时用小地图名
    if not target_location_out and d.get("map_name"):
        target_location_out = d.get("map_name", "")

    # ---- 任务计数整合 ----
    count_jh = int(d.get("count_jh") or 0)
    if not progress_num and count_jh:
        progress_num = count_jh

    ok = bool(quest_name or target_location_out or target_coord_out
              or d.get("task_ids"))

    # ---- 匹配验证（与 JHRW 语义一致）----
    has_expect = (target_location is not None) or (target_coord is not None)
    matched = True
    if target_location is not None and target_location_out:
        matched = matched and (str(target_location_out) == str(target_location))
    if target_coord is not None and target_coord_out is not None:
        try:
            matched = matched and (
                tuple(int(v) for v in target_coord_out)
                == tuple(int(v) for v in target_coord)
            )
        except (TypeError, ValueError):
            matched = False

    progress_text = f"当前第{progress_num}次" if progress_num else ""
    source_note = "lua_gateway"
    if not intro_text:
        source_note += "(无追踪文本,计数可用)"

    result = {
        "success": ok,
        "pid": int(pid or 0),
        "quest_name": quest_name,
        "target_location": target_location_out,
        "target_coord": target_coord_out,
        "progress_text": progress_text,
        "progress_num": progress_num,
        "description": intro_text or f"{quest_name} {target_location_out}"
                       or d.get("map_name", ""),
        "desc_addr": 0,
        "npc": npc_name,
        "matched": (matched if has_expect else ok),
        "message": "任务信息读取成功(Lua)" if ok else "任务信息读取失败",
        "source": source_note,
        "stale": False,
        "quest_name_confidence": 0.95 if quest_name else 0.0,
        "target_location_candidates": [target_location_out] if target_location_out else [],
        "quest_signatures": {
            "task_ids": d.get("task_ids", ""),
            "rec_raw": (f"{d.get('rec_name')}|{d.get('rec_map')}|"
                        f"{d.get('rec_mapid')}|{d.get('rec_x')},{d.get('rec_y')}"
                        f"|类型{d.get('rec_type')}|{d.get('rec_model')}"),
            "intro_lines": d.get("intro_lines", "0"),
            "counts": f"主线{d.get('count_main')}/支线{d.get('count_branch')}"
                      f"/江湖{d.get('count_jh')}/师门{d.get('count_sm')}",
            "world_xy": f"{d.get('world_x')},{d.get('world_y')}",
        },
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }

    if verbose:
        logger.info(f"[JHRW1 lua] {result}")
    return result


if __name__ == "__main__":
    import sys

    gw = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GATEWAY
    print(json.dumps(JHRW1(gateway=gw, verbose=True), ensure_ascii=False, indent=1))
