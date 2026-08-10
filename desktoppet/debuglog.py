# -*- coding: utf-8 -*-
"""可选调试日志。

程序大量试探 Win32 / COM 接口，失败路径几乎都以"返回 None 然后降级"收场。
默认保持静默（打包后没有控制台，写日志反而会拖慢热路径），但排查线上问题时
可以用环境变量打开：

    set DESKTOPPET_DEBUG=1            输出到 stderr
    set DESKTOPPET_LOG=C:\\pet.log     追加到文件（同时隐含开启）
"""
import os
import sys
import time
import traceback

_LOG_PATH = os.environ.get("DESKTOPPET_LOG", "").strip()
_ENABLED = bool(_LOG_PATH) or os.environ.get(
    "DESKTOPPET_DEBUG", "").strip() not in ("", "0", "false", "False")


def enabled():
    return _ENABLED


def _emit(text):
    line = "%s %s" % (time.strftime("%H:%M:%S"), text)
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return
        except OSError:
            pass    # 日志本身失败时退回 stderr，不能反过来影响主流程
    stream = sys.stderr
    if stream is not None:      # 无控制台的打包进程里 stderr 可能是 None
        try:
            stream.write(line + "\n")
            stream.flush()
        except Exception:
            pass


def log(message):
    if _ENABLED:
        _emit(message)


def exception(context):
    """在 except 分支里记录当前异常；未开启调试时是空操作。

    调用方仍然自行决定返回值 / 降级行为，本函数只负责让失败可见。"""
    if not _ENABLED:
        return
    _emit("%s failed: %s" % (context, traceback.format_exc().strip()))
