# -*- coding: utf-8 -*-
"""开机自动启动：注册表 Run 项读写与菜单联动。

真实注册表绝不能在测试里碰——用内存版 winreg 替身跑完整读写路径。"""
import os
import sys

import pytest

from desktoppet import autostart


class FakeWinreg:
    """内存版 winreg：只实现 autostart 用到的接口，行为对齐真实模块
    （查询 / 删除不存在的值抛 FileNotFoundError，它是 OSError 的子类）。"""
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1

    def __init__(self):
        self.values = {}          # 值名 -> 命令行；模拟 Run 键的内容
        self.open_fails = False   # 模拟注册表被策略锁定

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=None):
        assert root is self.HKEY_CURRENT_USER
        assert path == autostart.RUN_KEY
        if self.open_fails:
            raise PermissionError("locked")
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture
def fake_reg(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(autostart, "winreg", fake)
    return fake


class TestRegistryRoundTrip:
    def test_defaults_to_disabled(self, fake_reg):
        assert not autostart.is_enabled()

    def test_enable_then_query(self, fake_reg):
        assert autostart.set_enabled(True)
        assert autostart.is_enabled()
        assert fake_reg.values[autostart.VALUE_NAME] == autostart.command()

    def test_disable_removes_the_value(self, fake_reg):
        autostart.set_enabled(True)
        assert autostart.set_enabled(False)
        assert not autostart.is_enabled()
        assert autostart.VALUE_NAME not in fake_reg.values

    def test_disabling_when_absent_is_success(self, fake_reg):
        """值本就不存在时删除应视为成功，不能让菜单勾选回弹。"""
        assert autostart.set_enabled(False)

    def test_reenabling_rewrites_the_command(self, fake_reg):
        """程序可能被移动过：再次开启要重写命令行，而不是保留旧路径。"""
        fake_reg.values[autostart.VALUE_NAME] = '"C:\\old\\gone.exe"'
        autostart.set_enabled(True)
        assert fake_reg.values[autostart.VALUE_NAME] == autostart.command()

    def test_locked_registry_reports_failure(self, fake_reg):
        fake_reg.open_fails = True
        assert not autostart.set_enabled(True)
        assert not autostart.is_enabled()   # 读失败视为未开启，而非抛异常


class TestCommand:
    def test_frozen_points_at_the_exe(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", "windows_exe", raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\Apps\DesktopPet.exe")
        assert autostart.command() == r'"C:\Apps\DesktopPet.exe"'

    def test_source_runs_the_entry_script(self):
        cmd = autostart.command()
        assert cmd.endswith('pet_v2.py"')
        script = cmd.rsplit('" "', 1)[1].rstrip('"')
        assert os.path.exists(script)

    def test_source_prefers_pythonw(self, tmp_path, monkeypatch):
        """源码模式用 pythonw 静默启动，python.exe 会常驻控制台窗口。"""
        pythonw = tmp_path / "pythonw.exe"
        pythonw.write_bytes(b"")
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
        assert autostart.command().startswith('"%s"' % pythonw)


class TestMenuIntegration:
    def test_action_is_checkable_and_defaults_off(self, pet):
        assert pet.act_autostart.isCheckable()
        assert not pet.act_autostart.isChecked()

    def test_persist_off_never_touches_the_registry(self, pet, monkeypatch):
        def boom(_on):
            raise AssertionError("测试模式不应写注册表")
        monkeypatch.setattr(autostart, "set_enabled", boom)
        pet.act_autostart.setChecked(True)    # persist=False 时应短路返回

    def test_write_failure_reverts_the_checkbox(self, pet, monkeypatch):
        pet.persist = True
        monkeypatch.setattr(autostart, "set_enabled", lambda on: False)
        pet.act_autostart.setChecked(True)
        assert not pet.act_autostart.isChecked()

    def test_successful_write_keeps_the_checkbox(self, pet, monkeypatch):
        calls = []
        pet.persist = True
        monkeypatch.setattr(autostart, "set_enabled",
                            lambda on: calls.append(on) or True)
        pet.act_autostart.setChecked(True)
        assert calls == [True]
        assert pet.act_autostart.isChecked()

    def test_menu_show_syncs_from_registry(self, pet, monkeypatch):
        """外部工具改过启动项后，弹出的菜单要反映注册表现状。"""
        monkeypatch.setattr(autostart, "is_enabled", lambda: True)
        pet._sync_autostart()
        assert pet.act_autostart.isChecked()
        # 对账走 blockSignals，不应触发一次真实的注册表写入
        monkeypatch.setattr(autostart, "is_enabled", lambda: False)
        pet.persist = True
        writes = []
        monkeypatch.setattr(autostart, "set_enabled",
                            lambda on: writes.append(on) or True)
        pet._sync_autostart()
        assert not pet.act_autostart.isChecked()
        assert writes == []
