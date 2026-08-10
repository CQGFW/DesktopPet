# -*- coding: utf-8 -*-
"""Win32 层：进程名缓存的 TTL 与容量上限。"""
import time

import pytest

from desktoppet import winapi


@pytest.fixture(autouse=True)
def clean_cache():
    winapi._WINDOW_PROCESS_NAMES.clear()
    yield
    winapi._WINDOW_PROCESS_NAMES.clear()


class FakeKernel32:
    """只实现 process_name 用到的四个调用。"""

    def __init__(self, name="probe.exe"):
        self.name = name
        self.opens = 0

    def OpenProcess(self, _access, _inherit, _pid):
        self.opens += 1
        return 1234

    def QueryFullProcessImageNameW(self, _handle, _flags, buffer, _size):
        buffer.value = "C:\\Windows\\%s" % self.name
        return 1

    def CloseHandle(self, _handle):
        return 1


@pytest.fixture
def kernel32(monkeypatch):
    fake = FakeKernel32()
    monkeypatch.setattr(winapi.ctypes.windll, "kernel32", fake)
    return fake


def test_resolves_and_lowercases_the_exe_name(kernel32):
    assert winapi.process_name(4242) == "probe.exe"


def test_repeated_lookups_hit_the_cache(kernel32):
    for _ in range(10):
        winapi.process_name(4242)
    assert kernel32.opens == 1


def test_expired_entries_are_re_resolved(kernel32, monkeypatch):
    """Windows 会复用 PID：永久缓存会把新进程认成已退出的旧进程
    （例如误判成输入法宿主）。TTL 到期后必须重新解析。"""
    winapi.process_name(4242)
    assert kernel32.opens == 1
    name, deadline = winapi._WINDOW_PROCESS_NAMES[4242]
    winapi._WINDOW_PROCESS_NAMES[4242] = (name, time.monotonic() - 1.0)
    kernel32.name = "recycled.exe"
    assert winapi.process_name(4242) == "recycled.exe"
    assert kernel32.opens == 2


def test_cache_is_bounded(kernel32, monkeypatch):
    """长时间运行不能让字典无界增长。"""
    monkeypatch.setattr(winapi, "PROCESS_NAME_CACHE_MAX", 16)
    for pid in range(200):
        winapi.process_name(pid)
    assert len(winapi._WINDOW_PROCESS_NAMES) <= 16


def test_pruning_drops_expired_before_clearing(kernel32, monkeypatch):
    monkeypatch.setattr(winapi, "PROCESS_NAME_CACHE_MAX", 4)
    stale = time.monotonic() - 1.0
    for pid in range(3):
        winapi._WINDOW_PROCESS_NAMES[pid] = ("old.exe", stale)
    fresh_deadline = time.monotonic() + winapi.PROCESS_NAME_TTL
    winapi._WINDOW_PROCESS_NAMES[99] = ("keep.exe", fresh_deadline)
    winapi._prune_process_names(time.monotonic())
    assert 99 in winapi._WINDOW_PROCESS_NAMES
    assert not any(pid in winapi._WINDOW_PROCESS_NAMES for pid in range(3))


def test_failed_open_returns_none_without_caching(monkeypatch):
    class NoOpen(FakeKernel32):
        def OpenProcess(self, *a):
            return 0

    monkeypatch.setattr(winapi.ctypes.windll, "kernel32", NoOpen())
    assert winapi.process_name(777) is None
    assert 777 not in winapi._WINDOW_PROCESS_NAMES
