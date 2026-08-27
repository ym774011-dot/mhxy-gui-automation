# -*- coding: utf-8 -*-
"""诊断: 列出系统当前所有 GPU Engine / 专用显存 实例, 找出真正渲染的 PID.

用法: python gpu_diag.py
"""
import subprocess
import re

PS = (
    "powershell -NoProfile -Command \""
    "$e=(Get-Counter -ListSet 'GPU Engine').Paths | Sort-Object -Unique; "
    "Write-Output '===GPU Engine paths==='; $e; "
    "$m=(Get-Counter -ListSet 'GPU Process Memory').Paths | Sort-Object -Unique; "
    "Write-Output '===GPU Process Memory paths==='; $m\""
)

out = subprocess.run(PS, capture_output=True, text=True, timeout=25, shell=True)
print("STDOUT:")
print(out.stdout)
if out.stderr:
    print("\nSTDERR:", out.stderr[:2000])