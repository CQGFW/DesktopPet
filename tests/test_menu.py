# -*- coding: utf-8 -*-
"""右键菜单：版本标题、各开关、置顶联动气泡。"""
from PySide6.QtCore import Qt

from desktoppet import APP_VERSION


def test_menu_layout(pet):
    labels = [action.text() for action in pet.menu.actions() if action.text()]
    assert labels == ["DesktopPet %s" % APP_VERSION, "始终置顶", "自动走动",
                      "键盘互动", "输入跟随", "输入跟随大小", "退出"]


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


class TestFollowScaleSubmenu:
    def _actions(self, pet):
        return pet.follow_scale_menu.actions()

    def test_has_one_entry_per_choice(self, pet):
        from desktoppet import config
        labels = [a.text() for a in self._actions(pet)]
        assert labels == ["%d%%" % round(c * 100) for c in config.INPUT_SCALE_CHOICES]

    def test_entries_are_mutually_exclusive(self, pet):
        assert all(a.isCheckable() for a in self._actions(pet))
        assert sum(a.isChecked() for a in self._actions(pet)) == 1

    def test_current_choice_is_checked(self, pet):
        pet._set_input_follow_scale(0.30)
        checked = [a for a in self._actions(pet) if a.isChecked()]
        assert len(checked) == 1 and checked[0].text() == "30%"
        assert pet.input_follow_scale == 0.30

    def test_selecting_an_entry_updates_the_pet(self, pet):
        target = [a for a in self._actions(pet) if a.text() == "40%"][0]
        target.trigger()
        assert abs(pet.input_follow_scale - 0.40) < 1e-9

    def test_stays_enabled_when_input_follow_is_off(self, pet):
        """档位是独立的存储偏好，可以先设好大小再开启跟随。"""
        pet.act_input.setChecked(False)
        assert pet.follow_scale_menu.isEnabled()
        assert all(a.isEnabled() for a in self._actions(pet))


def test_submenu_survives_reading_it_back_through_the_action(pet):
    """PySide6 的 addMenu("标题") 会把子菜单所有权交给 Python，
    别处读一次 QAction.menu() 产生的临时包装被回收时会连带析构掉它。
    子菜单必须显式指定父对象，由 C++ 侧持有。"""
    import gc
    submenus = [a.menu() for a in pet.menu.actions() if a.menu()]
    assert submenus, "菜单里应当存在子菜单"
    del submenus
    gc.collect()
    assert len(pet.follow_scale_menu.actions()) == 4
    pet._set_input_follow_scale(0.30)        # 读回之后仍可正常切换档位
    assert pet.input_follow_scale == 0.30
