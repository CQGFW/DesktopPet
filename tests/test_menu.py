# -*- coding: utf-8 -*-
"""右键菜单：版本标题、各开关、置顶联动气泡。"""
from PySide6.QtCore import Qt

from desktoppet import APP_VERSION


def test_menu_layout(pet):
    labels = [action.text() for action in pet.menu.actions() if action.text()]
    assert labels == ["DesktopPet %s" % APP_VERSION, "始终置顶", "自动走动",
                      "键盘互动", "输入跟随", "退出"]


def test_version_header_is_display_only(pet):
    assert not pet.menu.actions()[0].isEnabled()


class TestTopmostToggle:
    def test_defaults_to_on(self, pet):
        assert pet.act_topmost.isChecked()
        assert bool(pet.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_unchecking_drops_the_flag_on_pet_and_bubble(self, pet, qapp):
        pet.act_topmost.setChecked(False)
        qapp.processEvents()    # show 被延后到事件循环，先跑一轮
        assert not (pet.windowFlags() & Qt.WindowStaysOnTopHint)
        assert not (pet.bubble.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_rechecking_restores_the_flag(self, pet, qapp):
        pet.act_topmost.setChecked(False)
        qapp.processEvents()
        pet.act_topmost.setChecked(True)
        qapp.processEvents()
        assert pet.windowFlags() & Qt.WindowStaysOnTopHint
        assert pet.bubble.windowFlags() & Qt.WindowStaysOnTopHint

    def test_window_stays_visible_across_flag_changes(self, pet, qapp):
        """改窗口标志会销毁并重建原生窗口，处理不当宠物会消失。"""
        pet.act_topmost.setChecked(False)
        qapp.processEvents()
        assert pet.isVisible()
        pet.act_topmost.setChecked(True)
        qapp.processEvents()
        assert pet.isVisible()
