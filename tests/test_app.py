# -*- coding: utf-8 -*-
"""入口冒烟：main() 能建窗、装好退出钩子并正常返回。"""
from PySide6.QtCore import QTimer

from desktoppet import app as appmod


def test_main_starts_and_quits_cleanly(qapp):
    QTimer.singleShot(0, qapp.quit)
    assert appmod.main([]) == 0
