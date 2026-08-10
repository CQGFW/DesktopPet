# -*- coding: utf-8 -*-
"""键盘互动：左右分区选脚、自动重复忽略、按住 / 抬起、开关联动留白、钩子退出。"""
import time

from desktoppet import keyboard

LEFT_A, RIGHT_L = ord('A'), ord('L')
ENTER = 0x0D
SPACE = 0x20


class TestSideSplit:
    def test_left_hand_key_uses_the_left_paw(self, pet):
        pet._on_global_key(LEFT_A, 30)
        assert pet._held[30] == 0 and pet._paw_held[0] == 1

    def test_right_hand_key_uses_the_right_paw(self, pet):
        pet._on_global_key(RIGHT_L, 38)
        assert pet._held[38] == 1

    def test_unmapped_keys_alternate_paws(self, pet):
        sides = []
        for _ in range(2):
            pet._on_global_key(SPACE, 57)
            sides.append(pet._held[57])
            pet._on_global_key_up(SPACE, 57)
        assert sides[0] != sides[1]


class TestHoldAndLift:
    def test_auto_repeat_does_not_double_count(self, pet):
        pet._on_global_key(LEFT_A, 30)
        pet._on_global_key(LEFT_A, 30)      # 系统自动重复
        assert pet._paw_held[0] == 1

    def test_paw_stays_down_while_held(self, pet):
        pet._on_global_key(LEFT_A, 30)
        assert pet._paw_progress(0, time.monotonic()) == 1.0

    def test_paw_lifts_back_after_release(self, pet):
        pet._on_global_key(LEFT_A, 30)
        pet._on_global_key_up(LEFT_A, 30)
        assert pet._paw_held == [0, 0]
        assert pet._paw_progress(0, time.monotonic() + 1.0) == 0.0

    def test_unpaired_release_is_ignored(self, pet):
        """启动前就按住的键，松开时没有配对的按下记录。"""
        pet._on_global_key_up(ord('Q'), 16)
        assert pet._paw_held == [0, 0]

    def test_same_vk_on_two_physical_keys_both_count(self, pet):
        """主键盘与小键盘 Enter 共享 vkCode，靠 scanCode + 扩展位区分。"""
        pet._on_global_key(ENTER, 28)
        pet._on_global_key(ENTER, 28 | (1 << 16))
        assert pet._paw_held[1] == 2
        pet._on_global_key_up(ENTER, 28)
        pet._on_global_key_up(ENTER, 28 | (1 << 16))
        assert pet._paw_held == [0, 0]


def test_reduced_motion_suppresses_taps(pet):
    pet.reduced_motion = True
    pet._on_global_key(ord('B'), 48)
    assert pet._paw_held == [0, 0]


class TestToggle:
    def test_defaults_on_with_reserved_keyboard_area(self, pet):
        assert pet.kb_enabled and pet.act_kb.isChecked()
        assert pet.bottom_pad > 0

    def test_disabling_clears_state_and_padding_keeping_the_foot(self, pet):
        foot = (pet.x() + pet.width() // 2, pet.y() + pet.height())
        pet.act_kb.setChecked(False)
        assert pet.bottom_pad == 0
        assert not pet._held and pet._paw_held == [0, 0]
        assert (pet.x() + pet.width() // 2, pet.y() + pet.height()) == foot

    def test_no_response_while_disabled(self, pet):
        pet.act_kb.setChecked(False)
        pet._on_global_key(ord('C'), 46)
        assert pet._paw_held == [0, 0]

    def test_reenabling_restores_the_keyboard_area(self, pet):
        pet.act_kb.setChecked(False)
        pet.act_kb.setChecked(True)
        assert pet.bottom_pad > 0


class TestListenerLifecycle:
    def test_stop_ends_the_hook_thread(self, pet):
        pet.key_listener.stop()
        assert not pet.key_listener._thread.is_alive()

    def test_failure_disables_the_menu_entry(self, pet):
        """钩子装不上时菜单不能仍显示"已开启"却毫无反应。"""
        pet._on_kb_hook_failed()
        assert not pet.act_kb.isChecked()
        assert not pet.act_kb.isEnabled()
        assert "不可用" in pet.act_kb.text()


def test_left_and_right_key_sets_do_not_overlap():
    assert not (keyboard.LEFT_VKS & keyboard.RIGHT_VKS)
