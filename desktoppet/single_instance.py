# -*- coding: utf-8 -*-
"""多实例保护：同一用户会话内只允许一只宠物。

用 QLocalServer 占一个按用户名区分的本地套接字名；第二个实例连上后发一条
"show" 就退出，第一个实例收到后把宠物显示出来并打个招呼。开机自启动 + 手动
双击 exe 的场景下最容易出现两只猫，这样处理后用户只会看到已有的那只被唤醒。"""
import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import debuglog

CONNECT_TIMEOUT_MS = 500


def default_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = "default"
    return "DesktopPet-%s" % "".join(c if c.isalnum() else "_" for c in user)


def notify_existing(name):
    """有实例在跑就通知它并返回 True；没有则返回 False。"""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(CONNECT_TIMEOUT_MS):
        return False
    # 连接本身就是"露面"的信号；写一个字节只为让对端 readyRead 也能触发
    sock.write(b"show")
    sock.waitForBytesWritten(CONNECT_TIMEOUT_MS)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(CONNECT_TIMEOUT_MS)
    return True


class Guard(QObject):
    """持有本地服务端；另一实例试图启动时发出 activated。"""
    activated = Signal()

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)

    def listen(self):
        # 上次异常退出可能留下残留的套接字名；removeServer 后再监听
        QLocalServer.removeServer(self.name)
        ok = self.server.listen(self.name)
        if not ok:
            debuglog.log("single_instance: listen failed: %s" % self.server.errorString())
        return ok

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
    if notify_existing(name):
        debuglog.log("single_instance: another instance is running, handed over")
        return None
    guard = Guard(name)
    if not guard.listen():
        # 监听失败（极少见）：宁可放行也不要让用户什么都看不到
        return guard
    return guard
