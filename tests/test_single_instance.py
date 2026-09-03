# -*- coding: utf-8 -*-
"""多实例保护：第二个实例把第一个唤醒后自行退出。"""
import uuid

from PySide6.QtTest import QSignalSpy

from desktoppet import app as appmod
from desktoppet import single_instance


def _name():
    return "DesktopPet-test-%s" % uuid.uuid4().hex[:8]


def _wait_for(qapp, spy):
    for _ in range(100):
        qapp.processEvents()
        if spy.count():
            return
        qapp.thread().msleep(5)


def test_first_instance_acquires(qapp):
    guard = single_instance.acquire(_name())
    assert guard is not None and guard.server.isListening()
    guard.server.close()


def test_second_instance_is_refused_and_wakes_the_first(qapp):
    name = _name()
    guard = single_instance.acquire(name)
    spy = QSignalSpy(guard.activated)
    assert single_instance.acquire(name) is None
    _wait_for(qapp, spy)
    assert spy.count() == 1
    guard.server.close()


def test_stale_socket_name_is_reclaimed(qapp):
    name = _name()
    first = single_instance.acquire(name)
    first.server.close()          # 模拟异常退出：服务端消失但名字可能残留
    second = single_instance.acquire(name)
    assert second is not None and second.server.isListening()
    second.server.close()


def test_main_exits_immediately_when_another_instance_runs(qapp):
    name = _name()
    guard = single_instance.acquire(name)
    spy = QSignalSpy(guard.activated)
    assert appmod.main([], instance_name=name) == 0
    _wait_for(qapp, spy)
    assert spy.count() == 1
    guard.server.close()


def test_wake_up_shows_and_greets(pet):
    pet.hide()
    pet.bubble.hide()
    pet.wake_up()
    assert pet.isVisible() and pet.bubble.isVisible()
