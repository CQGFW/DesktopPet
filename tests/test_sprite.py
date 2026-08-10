# -*- coding: utf-8 -*-
"""头 / 身 / 脚分层：0° 时三层叠回去应当逐像素还原原图。"""
from PySide6.QtGui import QImage


def test_sprite_asset_loads(pet):
    """打包后素材路径会变（sys._MEIPASS），加载失败必须立刻暴露。"""
    assert not pet.src.isNull(), "cat_soft.png load failed"
    assert pet.pix.height() > 0 and pet.pix.width() > 0


def test_layers_reconstruct_the_original_sprite(pet):
    """身体抠空了头部核心区、脚掌是单独裁出的图层，转头角为 0 时
    这些层叠回来必须与原图重合，否则会看到接缝或错位。"""
    pet.anim_kind = None
    pet.reduced_motion = True       # 冻结呼吸，布局退化成整数矩形
    pet.act_kb.setChecked(False)    # 键盘画在猫脚前，先关掉再逐像素比对

    shot = QImage(pet.size(), QImage.Format_ARGB32)
    shot.fill(0)
    pet.render(shot)
    reference = pet.pix.toImage().convertToFormat(QImage.Format_ARGB32)

    ox = pet.side_pad
    oy = pet.height() - pet.bottom_pad - pet.pix.height() - 3
    total = bad = 0
    for j in range(0, reference.height(), 5):
        for i in range(0, reference.width(), 5):
            want = reference.pixelColor(i, j)
            got = shot.pixelColor(ox + i, oy + j)
            if want.alpha() < 8 and got.alpha() < 8:
                continue
            total += 1
            if (abs(want.alpha() - got.alpha()) > 40
                    or abs(want.red() - got.red()) > 45
                    or abs(want.green() - got.green()) > 45
                    or abs(want.blue() - got.blue()) > 45):
                bad += 1

    assert total > 800, "sampling grid must actually cover the sprite"
    assert bad / total < 0.02, "composite mismatch %d/%d" % (bad, total)
