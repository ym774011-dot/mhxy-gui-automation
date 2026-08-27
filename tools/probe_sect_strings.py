# -*- coding: utf-8 -*-
"""深扫所有表: 找含『传送』+门派名的 desc 条目 / 门派传送配置"""
import json, urllib.request

GW = "http://127.0.0.1:18083"
SECTS = ["大唐官府","方寸山","女儿村","神木林","化生寺","盘丝洞",
         "阴曹地府","无底洞","魔王寨","狮驼岭","天宫","普陀山",
         "凌波城","五庄观","龙宫","花果山","九黎城"]


def jget(gw, path, data=None, timeout=30):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"

# 深扫 tp 和 _G 下所有字符串, 找 含门派名的 传送desc
sect = SECTS[14]  # 龙宫 做样本
code = r'''
local target = "TGT"
local res = {}
local seen = {}
local scanid = 0
local function scan(t, path, depth)
  if depth > 4 then return end
  if type(t) ~= "table" then return end
  for k, v in pairs(t) do
    scanid = scanid + 1
    if scanid > 4000 then return end
    if type(v) == "string" then
      if string.find(v, target) then
        local kk = tostring(k)
        if not seen[kk] then seen[kk] = true end
        if #res < 60 then res[#res+1] = path .. "." .. kk .. " = " .. v end
      end
    elseif type(v) == "table" then
      scan(v, path .. "." .. tostring(k), depth + 1)
    end
    if #res >= 60 then return end
  end
end
scan(tp, "tp", 0)
scan(_G, "_G", 0)
_G.__out = table.concat(res, "\n")'''.replace("TGT", sect)
print(f"=== 深扫含『{sect}』的字符串 ===")
print(lua(code))