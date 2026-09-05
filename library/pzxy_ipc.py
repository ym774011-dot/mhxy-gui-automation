# -*- coding: utf-8 -*-
"""pzxy_ipc.py — 方案② 文件通道客户端（Python 侧）。

与游戏内常驻 worker（pzxy_worker.lua）通过 3 个文件通信，全程零 frida：
    pzxy_cmd.txt  Python -> Lua  "--WB:<id>\\n<lua 源码>"（GBK，tmp+replace 原子写）
    pzxy_out.txt  Lua -> Python  "<id>|ok|<ret>" / "<id>|err|<msg>" / "TICKERR|..."
    pzxy_hb.txt   心跳           "<frame>|<os.time()>"

用法:
    from library.pzxy_ipc import PzxyWorker
    w = PzxyWorker()
    if not w.is_alive():
        raise RuntimeError('worker 心跳停止，需在登录界面重新播种')
    ok, val = w.cmd('local m=tp and tp.地图; return m and m.地图名称')
    # ok=True, val='乌鸡国副本'

⚠ 编码铁律：游戏 Lua 的中文标识符/字符串全是 GBK 字节。
  命令源码必须 GBK 写入；结果按 GBK 解码。UTF-8 的中文标识符在游戏里是
  另一个不存在的标识符（表现为返回 nil，不报错）——极易踩坑。
"""
import os
import time


class PzxyWorker(object):
    def __init__(self, tmp_dir=r'E:\DS\tmp', timeout=3.0):
        self.tmp_dir = tmp_dir
        self.cmd_path = os.path.join(tmp_dir, 'pzxy_cmd.txt')
        self.out_path = os.path.join(tmp_dir, 'pzxy_out.txt')
        self.hb_path = os.path.join(tmp_dir, 'pzxy_hb.txt')
        self.timeout = timeout
        self.seq = 0

    # ---- 心跳 ----
    def heartbeat(self):
        """返回 (frame:int|None, epoch:int|None)，文件缺失/坏帧返回 (None, None)。"""
        try:
            with open(self.hb_path, 'rb') as f:
                raw = f.read().decode('gbk', 'replace').strip()
            fr, _, ts = raw.partition('|')
            return int(fr), int(ts)
        except (IOError, OSError, ValueError):
            return None, None

    def is_alive(self, max_age=5.0):
        fr, ts = self.heartbeat()
        if ts is None:
            return False
        return abs(time.time() - ts) <= max_age

    # ---- 命令 ----
    def cmd(self, lua_src, timeout=None):
        """发送 Lua 源码（GBK），阻塞等结果。

        lua_src 内可写中文标识符/字符串（如 tp.地图.地图名称）——本方法
        统一按 GBK 落盘。源码建议以 return 结尾给出结果值。
        返回 (ok:bool, value:str)。value 为 ret1 的 tostring 形式或错误消息。
        """
        timeout = self.timeout if timeout is None else timeout
        self.seq += 1
        cid = str(self.seq)
        payload = ('--WB:%s\n%s' % (cid, lua_src)).encode('gbk', 'replace')
        tmp = self.cmd_path + '.tmp'
        # ★2026-09-05 不再删除 out 文件：结果按 <cid>| 前缀匹配，跨命令不会串；
        # 且频繁 os.remove 会触发沙箱批量删除守卫（SAFE_DELETE）杀进程。
        with open(tmp, 'wb') as f:
            f.write(payload)
        os.replace(tmp, self.cmd_path)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with open(self.out_path, 'rb') as f:
                    raw = f.read().decode('gbk', 'replace')
            except (IOError, OSError):
                raw = ''
            for line in raw.splitlines():
                if line.startswith(cid + '|'):
                    parts = line.split('|', 2)
                    return parts[1] == 'ok', parts[2] if len(parts) > 2 else ''
            time.sleep(0.04)
        return False, '(timeout %.1fs)' % timeout

    def shutdown(self):
        """停机：worker 还原原始 更新函数/渲染函数 并停止消费。"""
        return self.cmd('return 1', ) if False else self._shutdown()

    def _shutdown(self):
        try:
            os.remove(self.out_path)
        except OSError:
            pass
        with open(self.cmd_path + '.tmp', 'wb') as f:
            f.write(b'--WB:SHUTDOWN')
        os.replace(self.cmd_path + '.tmp', self.cmd_path)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                raw = open(self.out_path, 'rb').read().decode('gbk', 'replace')
            except (IOError, OSError):
                raw = ''
            if raw.startswith('SHUTDOWN|'):
                return True
            time.sleep(0.05)
        return False


if __name__ == '__main__':
    w = PzxyWorker()
    fr, ts = w.heartbeat()
    print('heartbeat: frame=%s epoch=%s alive=%s' % (fr, ts, w.is_alive()))
    if w.is_alive():
        ok, val = w.cmd('local m=tp and tp.地图; return m and m.地图名称')
        print('map read : ok=%s value=%r' % (ok, val))
