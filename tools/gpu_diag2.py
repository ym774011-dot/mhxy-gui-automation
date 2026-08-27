# -*- coding: utf-8 -*-
"""诊断2: 用 typeperf 展开 GPU Engine/专用显存 真实实例, 找出渲染 PID.

用法: python gpu_diag2.py
"""
import subprocess

def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=30, shell=True)
        return out.stdout + "\n" + out.stderr
    except Exception as e:
        return "ERR:" + str(e)

print("=== GPU Engine 利用率 (typeperf 采样1次) ===")
print(run('typeperf "\\GPU Engine(*)\\Utilization Percentage" -sc 1 -o "E:\\DS\\mhxy-gui-automation\\tools\\gpu_counts.csv"'))
print("\n=== GPU Process Memory 专用显存 (采样1次) ===")
print(run('typeperf "\\GPU Process Memory(*)\\Dedicated Usage" -sc 1 -o "E:\\DS\\mhxy-gui-automation\\tools\\gpu_mem.csv"'))