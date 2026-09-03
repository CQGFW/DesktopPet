# -*- coding: utf-8 -*-
"""程序入口：组装 QApplication 与宠物窗口，并在退出时释放后台资源。"""
import sys

from PySide6.QtWidgets import QApplication

from . import single_instance, uia
from .pet import Pet


def main(argv=None, instance_name=None):
    # 复用已存在的实例：一个进程里只能有一个 QApplication，
    # 这样冒烟测试可以先建好 app 再调 main()。
    app = QApplication.instance() or QApplication(
        sys.argv if argv is None else argv)
    app.setQuitOnLastWindowClosed(True)
    guard = single_instance.acquire(instance_name)
    if guard is None:
        return 0        # 已有实例在跑，已通知它露面；本进程直接退出
    pet = Pet()
    guard.setParent(pet)
    guard.activated.connect(pet.wake_up)
    app.aboutToQuit.connect(pet.key_listener.stop)   # 退出时结束钩子线程
    app.aboutToQuit.connect(pet.save_settings)
    app.aboutToQuit.connect(uia.shutdown)            # 释放 UIA 客户端与 COM
    pet.show()
    return app.exec()
