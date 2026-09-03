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
    guard.release()


def test_second_instance_is_refused_and_wakes_the_first(qapp):
    name = _name()
    guard = single_instance.acquire(name)
    spy = QSignalSpy(guard.activated)
    assert single_instance.acquire(name) is None
    _wait_for(qapp, spy)
    assert spy.count() == 1
    guard.release()


def test_stale_socket_name_is_reclaimed(qapp):
    name = _name()
    first = single_instance.acquire(name)
    first.release()               # 模拟退出：互斥体与服务端都释放
    second = single_instance.acquire(name)
    assert second is not None and second.server.isListening()
    second.release()


def test_mutex_alone_blocks_a_second_instance_even_without_a_listener(qapp, monkeypatch):
    """两实例同时启动、持有者尚未监听时，第二个也必须退出（Windows 命名管道
    允许重复监听，不能靠 listen 失败来判定）。"""
    name = _name()
    monkeypatch.setattr(single_instance, "NOTIFY_RETRIES", 1)
    monkeypatch.setattr(single_instance, "NOTIFY_RETRY_DELAY_S", 0)
    first = single_instance.acquire(name)
    first.server.close()          # 只保留互斥体，模拟"还没来得及监听"
    assert single_instance.acquire(name) is None
    first.release()


def test_main_exits_immediately_when_another_instance_runs(qapp):
    name = _name()
    guard = single_instance.acquire(name)
    spy = QSignalSpy(guard.activated)
    assert appmod.main([], instance_name=name) == 0
    _wait_for(qapp, spy)
    assert spy.count() == 1
    guard.release()


def test_wake_up_shows_and_greets(pet):
    pet.hide()
    pet.bubble.hide()
    pet.wake_up()
    assert pet.isVisible() and pet.bubble.isVisible()
