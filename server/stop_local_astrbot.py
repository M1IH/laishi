# -*- coding: utf-8 -*-
"""停本机 AstrBot（决定②：扫码前本机必须让号，避免双端抢登录态）。

防呆：逐个 PID 断言命令行确属 astrbot_launcher，不匹配就跳过并报错退出；
绝不用任务名/窗口标题批量杀。NapCat 侧本机已因窗口截断问题不在跑（6199 无
ESTABLISHED），这里顺带核实 6199/4100 是否已释放。
"""
import psutil
import sys
import time

TARGETS = (20996, 20812)

killed = []
for pid in TARGETS:
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        print(f"{pid} 已不在")
        continue
    cmd = " ".join(p.cmdline())
    # 只要求路径确属 astrbot_launcher（我们的会话宿主是 DeepSeek Harness.exe、
    # OTTO 的日常 QQ 是 D:\QQ\QQ.exe，都不会带这个路径），不满足就中止
    if "astrbot_launcher" not in cmd:
        print(f"[ABORT] {pid} 命令行不符合预期，拒绝杀: {cmd[:120]}")
        sys.exit(2)
    p.terminate()
    killed.append(pid)
    print(f"terminate -> {pid}")

time.sleep(3)
for pid in killed:
    try:
        psutil.Process(pid).kill()
        print(f"kill(兜底) -> {pid}")
    except psutil.NoSuchProcess:
        print(f"{pid} 已干净退出")
