# -*- coding: utf-8 -*-
"""语录分池：内置文件、时段池、用户覆盖与惰性重载。"""
import json
import os

import pytest

from desktoppet import quotes


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    quotes.reset_cache()
    yield tmp_path
    quotes.reset_cache()


def test_builtin_file_has_every_pool():
    pools = quotes._builtin_pools()
    for key in quotes.CONTEXTS + quotes.TIME_POOLS:
        assert pools.get(key), key


@pytest.mark.parametrize("hour, pool", [
    (5, "morning"), (10, "morning"), (11, "noon"), (13, "noon"),
    (14, "afternoon"), (17, "afternoon"), (18, "evening"), (22, "evening"),
    (23, "night"), (0, "night"), (4, "night")])
def test_time_pool_boundaries(hour, pool):
    assert quotes.time_pool(hour) == pool


def test_candidates_combine_context_and_time_pool(user_dir):
    pools = quotes.pools()
    items = quotes.candidates("click", hour=9)
    assert set(items) == set(pools["click"]) | set(pools["morning"])
    assert not set(items) & set(pools["idle"])


def test_pick_avoids_repeating_the_last_quote(user_dir):
    last = quotes.pick("idle", hour=15)
    for _ in range(30):
        q = quotes.pick("idle", last, hour=15)
        assert q != last and q in quotes.candidates("idle", 15)
        last = q


def test_user_file_overrides_only_the_pools_it_defines(user_dir):
    path = quotes.user_path()
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"click": ["自定义点击"], "_说明": ["忽略"]}, fh, ensure_ascii=False)
    assert quotes.candidates("click", hour=2) == ["自定义点击"] + quotes._builtin_pools()["night"]
    assert quotes.candidates("idle", hour=2)[0] in quotes._builtin_pools()["idle"]


def test_user_file_reloads_when_modified(user_dir):
    path = quotes.ensure_user_file()
    assert path and os.path.exists(path)
    assert quotes.candidates("click", hour=15)[0] in quotes._builtin_pools()["click"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"click": ["改过了"]}, fh, ensure_ascii=False)
    os.utime(path, (os.stat(path).st_atime, os.stat(path).st_mtime + 10))
    assert quotes.candidates("click", hour=15)[0] == "改过了"


def test_broken_user_file_falls_back_to_builtin(user_dir):
    path = quotes.user_path()
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert quotes.candidates("click", hour=15)[0] in quotes._builtin_pools()["click"]


def test_ensure_user_file_copies_builtin_once(user_dir):
    first = quotes.ensure_user_file()
    with open(first, encoding="utf-8") as fh:
        assert json.load(fh)["click"] == quotes._builtin_pools()["click"]
    with open(first, "a", encoding="utf-8") as fh:
        fh.write("\n")
    assert quotes.ensure_user_file() == first     # 已存在则不覆盖


def test_pet_click_and_idle_use_their_own_pools(pet, user_dir, monkeypatch):
    monkeypatch.setattr(quotes.time, "localtime", lambda: type("T", (), {"tm_hour": 15})())
    pools = quotes.pools()
    seen_click = {pet._pick_quote("click") for _ in range(40)}
    seen_idle = {pet._pick_quote("idle") for _ in range(40)}
    assert seen_click <= set(pools["click"]) | set(pools["afternoon"])
    assert seen_idle <= set(pools["idle"]) | set(pools["afternoon"])


def test_edit_quotes_menu_creates_the_user_file(pet, user_dir):
    pet._edit_quotes()      # persist=False：只建文件不真的打开编辑器
    assert os.path.exists(quotes.user_path())
    assert pet.bubble.isVisible()
