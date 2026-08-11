# -*- coding: utf-8 -*-
"""开机自动启动：读写 HKCU 的 Run 注册表项。

状态以注册表本身为准，不经 QSettings 转存：启动项也可能被任务管理器等
外部工具改动，转存一份副本必然出现两边不一致、界面无法自解释的状态。"""
import os
import sys
import winreg

from . import debuglog

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DesktopPet"


def command():
    """本程序的开机启动命令行。

    打包后的 exe 直接指向自身；从源码运行时改用同目录的 pythonw.exe
    静默启动入口脚本（python.exe 会常驻一个控制台窗口）。"""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "pet_v2.py")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    return '"%s" "%s"' % (interpreter, script)


def is_enabled():
    """Run 项中是否已登记本程序。读失败一律视为未开启。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(on):
    """写入 / 删除 Run 项；返回是否成功。

    开启时总是重写命令行：程序可能被移动或换过打包方式，旧路径留着只会
    造成"勾着却启动不了"。失败只记日志，由调用方回退界面勾选状态。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass    # 本就不存在，视为删除成功
        return True
    except OSError:
        debuglog.exception("autostart.set_enabled")
        return False
