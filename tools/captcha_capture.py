# -*- coding: utf-8 -*-
"""防脚本(防外挂)验证码弹窗现场抓取（2026-08-25）

后台轮询网关(18083)，当 tp.窗口.防脚本.可视=true 时，一次性 dump：
  - 分割验证（目标字符序列）
  - 每个随机组[i] 的字符 + 所有可坐标字段（坐标/验证坐标/选中判断/x/y/按下…）
  - 验证按钮 全字段 + 按钮子表
把原始 JSON 写到 E:\\DS\\mhxy-gui-automation\\tools\\captcha_capture.json 供分析。

用法: E:\\py\\python.exe tools\\captcha_capture.py [秒数，默认180]
"""
import json
import sys
import time
import urllib.request

GATEWAY = "http://127.0.0.1:18083/api/lua"
OUT = r"E:\DS\mhxy-gui-automation\tools\captcha_capture.json"

DUMP = r"""
local F = '|::|'
local w = tp.窗口.防脚本
local out = {}
out[#out+1] = '可视' .. '=' .. tostring(w.可视)
out[#out+1] = '验证码' .. '=' .. tostring(w.验证码 or '')
out[#out+1] = '超时' .. '=' .. tostring(w.超时 or '')
local rg = w.随机组
local rgd = {}
if type(rg) == 'table' then
  for i = 1, #rg do
    local item = rg[i]
    local it = {}
    if type(item) == 'table' then
      for k, v in pairs(item) do
        local vt = type(v)
        if vt == 'table' then
          it[#it+1] = k .. '=T[' .. tostring(#v) .. ']'
        elseif vt == 'function' then
          it[#it+1] = k .. '=fn'
        else
          it[#it+1] = k .. '=' .. tostring(v)
        end
      end
      rgd[#rgd+1] = '[' .. i .. ']' .. table.concat(it, ',')
    else
      rgd[#rgd+1] = '[' .. i .. ']' .. tostring(item)
    end
  end
end
out[#out+1] = '随机组' .. '=' .. table.concat(rgd, ' , ')
local sv = w.分割验证
local svd = {}
if type(sv) == 'table' then for i = 1, #sv do svd[#svd+1] = tostring(sv[i]) end end
out[#out+1] = '分割验证' .. '=' .. table.concat(svd, ',')
local function flat(t)
  local r = {}
  if type(t) ~= 'table' then return tostring(t) end
  for k, v in pairs(t) do
    local vt = type(v)
    if vt == 'table' then r[#r+1] = k .. '=T[' .. tostring(#v) .. ']'
    elseif vt == 'function' then r[#r+1] = k .. '=fn'
    else r[#r+1] = k .. '=' .. tostring(v) end
  end
  return '{' .. table.concat(r, ',') .. '}'
end
out[#out+1] = '验证坐标' .. '=' .. flat(w.验证坐标)
out[#out+1] = '验证按钮' .. '=' .. flat(w.验证按钮)
_G.__out = table.concat(out, F)
"""


def call_script():
    req = urllib.request.Request(GATEWAY, data=json.dumps({"code": DUMP}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    return d.get("result", {}).get("value") or ""


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    deadline = time.time() + total
    last = None
    while time.time() < deadline:
        try:
            raw = call_script()
        except Exception as e:
            print(f"[{int(time.time())}] 网关异常: {e}", flush=True)
            time.sleep(1)
            continue
        try:
            parsed = json.loads(raw)
            vis = parsed.get("可视") == "true"
        except Exception:
            vis = False
        print(f"[{int(time.time())}] 防脚本.可视={parsed.get('可视') if parsed else '?'}", flush=True)
        if vis and raw != last:
            last = raw
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            print("=== 抓到防脚本弹窗，已写入 " + OUT + " ===", flush=True)
            print(raw, flush=True)
            break
        time.sleep(0.5)
    else:
        print(f"等待 {total}s 内未出现防脚本弹窗（可视始终 false）", flush=True)


if __name__ == "__main__":
    main()