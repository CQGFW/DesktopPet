# -*- coding: utf-8 -*-
"""偏好持久化：往返、默认值、损坏值兜底，以及 Pet 的读写接线。"""
import pytest

from desktoppet import config, settings


class TestRoundTrip:
    def test_saved_flags_and_scale_come_back(self, qapp):
        settings.save({"topmost": False, "walk": True,
                       "keyboard": False, "input_follow": False}, 0.75,
                      config.INPUT_SCALE_DEFAULT)
        flags, scale, _ = settings.load()
        assert flags == {"topmost": False, "walk": True,
                         "keyboard": False, "input_follow": False}
        assert abs(scale - 0.75) < 1e-9

    def test_booleans_survive_as_booleans(self, qapp):
        """QSettings 在 INI / 注册表里存的是字符串，读回来必须仍是 bool，
        否则 "false" 这种真值字符串会把开关默默打开。"""
        settings.save(dict(settings.DEFAULTS, topmost=False), 1.0,
                      config.INPUT_SCALE_DEFAULT)
        flags, _, _ = settings.load()
        assert flags["topmost"] is False


class TestDefaults:
    def test_missing_keys_fall_back(self, qapp, monkeypatch):
        monkeypatch.setattr(settings, "APPLICATION", "DesktopPet-Unwritten")
        flags, scale, _ = settings.load()
        assert flags == settings.DEFAULTS
        assert scale == settings.DEFAULT_SCALE

    def test_out_of_range_scale_is_rejected(self, qapp):
        for bogus in (0.0, -1.0, 99.0):
            settings.save(dict(settings.DEFAULTS), bogus,
                          config.INPUT_SCALE_DEFAULT)
            _, scale, _ = settings.load()
            assert config.MIN_SCALE <= scale <= config.MAX_SCALE
            assert scale == settings.DEFAULT_SCALE


class TestPetWiring:
    def test_non_persisting_pet_never_writes(self, pet, monkeypatch):
        """测试与临时实例不该污染用户已保存的偏好。"""
        written = []
        monkeypatch.setattr(settings, "save",
                            lambda *a: written.append(a))
        pet.act_walk.setChecked(True)
        pet.save_settings()
        assert written == []

    def test_current_flags_track_the_menu(self, pet):
        pet.act_topmost.setChecked(False)
        pet.act_walk.setChecked(True)
        pet.act_kb.setChecked(False)
        pet.act_input.setChecked(False)
        assert pet._current_flags() == {"topmost": False, "walk": True,
                                        "keyboard": False, "input_follow": False}

    def test_persisted_scale_ignores_the_input_follow_shrink(self, pet, monkeypatch):
        """输入跟随期间 self.scale 是临时缩小值，存进去会越存越小。"""
        from desktoppet import input_follow
        from PySide6.QtCore import QRect
        monkeypatch.setattr(input_follow, "query_input_context",
                            lambda: input_follow.InputContext(
                                QRect(300, 200, 2, 20), None, None,
                                QRect(0, 0, 1280, 720)))
        pet._set_scale(0.8)
        pet._input_on_key()
        assert pet.input_follow_active and pet.scale < 0.8
        assert abs(pet._persistable_scale() - 0.8) < 1e-9


class TestFollowScalePersistence:
    """跟随档位是离散值，校验比连续的 scale 更严。"""

    def test_round_trip(self, qapp):
        settings.save(dict(settings.DEFAULTS), 1.0, 0.40)
        _, _, input_scale = settings.load()
        assert abs(input_scale - 0.40) < 1e-9

    def test_missing_key_falls_back_to_the_default(self, qapp, monkeypatch):
        monkeypatch.setattr(settings, "APPLICATION", "DesktopPet-NoFollowScale")
        _, _, input_scale = settings.load()
        assert input_scale == config.INPUT_SCALE_DEFAULT

    def test_value_outside_the_choices_is_rejected(self, qapp):
        """不在档位集合内的值会让菜单没有任何一项处于选中态，必须挡掉。"""
        for bogus in (0.0, 0.23, 0.99, -1.0):
            settings.save(dict(settings.DEFAULTS), 1.0, bogus)
            _, _, input_scale = settings.load()
            assert input_scale in config.INPUT_SCALE_CHOICES
            assert input_scale == config.INPUT_SCALE_DEFAULT

    def test_pet_persists_the_selected_choice(self, pet, monkeypatch):
        written = []
        monkeypatch.setattr(pet, "persist", True)
        monkeypatch.setattr(settings, "save", lambda *a: written.append(a))
        pet._set_input_follow_scale(0.30)
        pet.save_settings()
        assert written and abs(written[-1][2] - 0.30) < 1e-9


@pytest.mark.parametrize("choice", config.INPUT_SCALE_CHOICES)
def test_every_choice_survives_a_round_trip(qapp, choice):
    """QSettings 的 float 走 C++ 单精度往返（0.40 -> 0.4000000059604645），
    用它做档位的精确比对会让「选了 40%，重启变回 20%」。档位以整数百分比存盘。"""
    settings.save(dict(settings.DEFAULTS), 1.0, choice)
    _, _, restored = settings.load()
    assert restored == choice
