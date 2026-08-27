# -*- coding: utf-8 -*-
"""监控游戏进程 GPU：3D 引擎利用率 + 进程专用显存，定位"放技能特效卡"。

两种根因判据：
    1) 粒子量瞬时爆炸 -> 放技能瞬间 GPU_3D/专用显存 出现高峰但对回落到基线
    2) D3D 资源泄漏   -> 每次放技能后 专用显存/GPU 一步步抬高、不回落到基线

实现：通过 powershell `Get-Counter` 读取该 PID 对应实例的性能计数器
     GPU 利用率:  \\GPU Engine(pid...)\\Utilization Percentage  （多个引擎累加）
     进程专用显存: \\GPU Process Memory(pid...)\\Dedicated Usage

用法（powershell应从$PATH可调用；管理员非必需）：
    python gpu_monitor.py PID [间隔秒=2] [时长秒=600]
"""
import sys
import time
import re
import csv
import io
import subprocess


def _typeperf(counter_pattern, timeout=15):
    """typeperf 一次采样指定计数器（通配模式），返回数值列表。失败返回 []."""
    # typeperf 百分比计数器第一次采样无值，须 -sc 2（第1次blank，第2次有值）
    cmd = 'typeperf "%s" -sc 2 -si 1 -y' % counter_pattern
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout,
                             shell=True)
        text = out.stdout.decode('utf-8', errors='replace')
        rows = list(csv.reader(io.StringIO(text)))
        if not rows or len(rows) < 3:
            return []
        # 数据行: 首列时间戳，其余是要读的计数器值（取最后一行，即第2次采样）
        data = rows[-1]
        vals = []
        for cell in data[1:]:
            cell = cell.strip()
            if cell == '':
                continue
            try:
                vals.append(float(cell))
            except ValueError:
                continue
        return vals
    except Exception:
        return []


def gpu_3d_pct(pid):
    """该进程所有 GPU 3D 引擎利用率之和（%）。失败返回 None."""
    vals = _typeperf(r"\GPU Engine(pid_%s*engtype_3D)\Utilization Percentage" % pid)
    return sum(vals) if vals else None


def gpu_mem_mb(pid):
    """该进程专用(显存)GPU 内存，单位 MB。失败返回 None."""
    vals = _typeperf(r"\GPU Process Memory(pid_%s*)\Dedicated Usage" % pid)
    if not vals:
        return None
    # 值为字节
    return max(vals) / 1024.0 / 1024.0


def process_mem_mb(pid):
    try:
        import psutil
        return psutil.Process(pid).memory_info().rss / 1024 / 1024
    except Exception:
        return None


def main():
    if len(sys.argv) < 2:
        print("用法: python gpu_monitor.py PID [间隔秒=2] [时长秒=600]")
        return
    pid = int(sys.argv[1])
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 600.0

    print("请切换到游戏窗口并准备放技能...")
    for i in range(3, 0, -1):
        print(i, end=' ', flush=True); time.sleep(1)
    print("\n开始监控\n")

    gpu_peaks = []
    gm_series = []
    peak_gpu = 0.0
    peak_gmem = 0.0
    start = time.time()

    while time.time() - start < duration:
        g = gpu_3d_pct(pid)
        gm = gpu_mem_mb(pid)
        mem = process_mem_mb(pid)
        if g is not None:
            gpu_peaks.append(g)
            peak_gpu = max(peak_gpu, g)
        if gm is not None:
            gm_series.append(gm)
            peak_gmem = max(peak_gmem, gm)
        ts = time.asctime()[-8:]
        print("%s  GPU_3D=%6.1f%%  GPU显存=%7.1fMB  系统内存=%6.0fMB"
              % (ts, g if g is not None else -1,
                 gm if gm is not None else -1, mem or -1))
        time.sleep(interval)

    print("\n=== 结束汇总 ===")
    if gpu_peaks:
        print("GPU_3D 利用率: 峰值=%.1f%%  均值=%.1f%%" %
              (peak_gpu, sum(gpu_peaks) / len(gpu_peaks)))
    if gm_series and len(gm_series) >= 4:
        first = sum(gm_series[:2]) / 2
        last = sum(gm_series[-2:]) / 2
        print("进程专用显存: 开头≈%.0fMB -> 末尾≈%.0fMB (%+.0fMB)" %
              (first, last, last - first))
        print("  显存单调抬升不清零 -> D3D泄漏; 只在放技能时瞬时涨且回落 -> 粒子量过大")
    print("脚本结束。")


if __name__ == "__main__":
    main()