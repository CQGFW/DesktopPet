# -*- coding: utf-8 -*-
"""pytest 公共装置。

必须在导入任何 Qt 模块之前设定 offscreen 平台，否则测试机上会真的弹窗。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import desktoppet.pet as petmod


@pytest.fixture(scope="session", autouse=True)
def isolate_settings(tmp_path_factory):
    """把 QSettings 重定向到临时目录。

    否则跑一次测试就会污染开发机上真实保存的偏好（Windows 下是注册表）。"""
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                      str(tmp_path_factory.mktemp("settings")))


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def pet(qapp):
    """每个用例一只全新的宠物：互不继承状态，也不读写真实偏好。

    reduced_motion 显式置 False——测试机的系统"减少动态效果"设置不该左右用例。"""
    widget = petmod.Pet(persist=False)
    widget.show()
    widget.reduced_motion = False
    yield widget
    widget.key_listener.stop()
    widget.idle_timer.stop()
    widget.frame_timer.stop()
    widget.rm_timer.stop()
    widget.bubble.hide()
    widget.hide()
