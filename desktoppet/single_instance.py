# -*- coding: utf-8 -*-
"""多实例保护：同一用户会话内只允许一只宠物。

判定"是否已有实例"用 Windows 命名互斥体：CreateMutexW 是原子的，两个实例同时
启动（开机自启动 + 手动双击）也只会有一个拿到。命名管道不能承担这个职责——
Windows 允许多个服务端监听同一个管道名，QLocalServer.listen 不会失败。

拿不到互斥体的实例通过 QLocalSocket 通知持有者"露面"后退出；持有者可能刚启动
还没开始监听，所以通知会短暂重试。非 Windows 平台没有互斥体，退化为只靠管道。"""
import ctypes
import getpass
import sys
import time

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import debuglog

CONNECT_TIMEOUT_MS = 500
NOTIFY_RETRIES = 8              # 持有者尚未监听时重试的次数
NOTIFY_RETRY_DELAY_S = 0.25
ERROR_ALREADY_EXISTS = 183


def default_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = "default"
    return "DesktopPet-%s" % "".join(c if c.isalnum() else "_" for c in user)


def _create_mutex(name):
    """返回 (handle, already_exists)；非 Windows 返回 (None, False)。"""
    if sys.platform != "win32":
        return None, False
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\" + name)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS or \
        kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    if not handle:
        return None, False
    return handle, already


def _close_handle(handle):
    if handle:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def notify_existing(name, retries=NOTIFY_RETRIES):
    """尝试连上已有实例并发一条 "show"；成功返回 True。"""
    for attempt in range(retries):
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(CONNECT_TIMEOUT_MS):
            sock.write(b"show")
            sock.waitForBytesWritten(CONNECT_TIMEOUT_MS)
            sock.disconnectFromServer()
            if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
                sock.waitForDisconnected(CONNECT_TIMEOUT_MS)
            _drain(sock)
            return True
        error = sock.errorString()
        _drain(sock)
        if attempt + 1 < retries:
            time.sleep(NOTIFY_RETRY_DELAY_S)
    debuglog.log("single_instance: could not reach existing instance on %r (%s)"
                 % (name, error))
    return False


def _drain(sock):
    """Windows 下 QLocalSocket 基于命名管道 + 重叠 IO；若进程从未跑过事件循环就
    直接进入解释器收尾，打包后的 exe 会卡在 Qt 的管道读线程清理上不退出。
    这里关闭套接字并把待处理事件跑空。"""
    sock.close()
    sock.deleteLater()
    for _ in range(3):
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)


class Guard(QObject):
    """持有互斥体与本地服务端；另一实例试图启动时发出 activated。"""
    activated = Signal()

    def __init__(self, name, mutex=None, parent=None):
        super().__init__(parent)
        self.name = name
        self._mutex = mutex
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)

    def listen(self):
        QLocalServer.removeServer(self.name)    # 清理 Unix 下可能残留的套接字文件
        ok = self.server.listen(self.name)
        if ok:
            debuglog.log("single_instance: listening on %r" % self.name)
        else:
            debuglog.log("single_instance: listen failed: %s" % self.server.errorString())
        return ok

    def release(self):
        """释放互斥体与监听；进程退出时系统也会自动回收，主要供测试使用。"""
        self.server.close()
        _close_handle(self._mutex)
        self._mutex = None

    def _on_connection(self):
        # 有人连上来就说明另一实例试图启动：不依赖读到内容，
        # 对端可能写完立刻断开，管道里的数据未必还在
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readAll()
            sock.disconnected.connect(sock.deleteLater)
            sock.close()
            self.activated.emit()


def acquire(name=None):
    """成功占位返回 Guard；已有实例则通知它并返回 None。"""
    name = name or default_name()
    mutex, already = _create_mutex(name)
    if already:
        _close_handle(mutex)
        notify_existing(name)
        debuglog.log("single_instance: another instance owns %r, handed over" % name)
        return None
    if mutex is None and notify_existing(name, retries=1):
        # 没有互斥体可用（非 Windows / 创建失败）：退回只看管道
        debuglog.log("single_instance: another instance is listening, handed over")
        return None
    guard = Guard(name, mutex)
    guard.listen()      # 失败（极少见）也放行：宁可少一层唤醒也不能让用户什么都看不到
    return guard
