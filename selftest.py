# -*- coding: utf-8 -*-
"""offscreen 自测：图片加载、缩放锚点、气泡逻辑、互动动画"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from PySide6.QtWidgets import QApplication
import pet as m

app = QApplication(sys.argv)
p = m.Pet()
p.show()
assert not p.src.isNull(), "cat_soft.png load failed"
print("sprite:", p.src.width(), "x", p.src.height(), "| display:", p.pix.width(), "x", p.pix.height())
assert p.pix.hasAlphaChannel()

for target in (0.25, 1.5):
    foot = (p.x() + p.width() // 2, p.y() + p.height())
    p._set_scale(target)
    foot2 = (p.x() + p.width() // 2, p.y() + p.height())
    assert abs(foot[0] - foot2[0]) <= 1 and foot[1] == foot2[1], (foot, foot2)
    print(f"scale {target}: size {p.pix.width()}x{p.pix.height()}, foot fixed OK")
p._set_scale(1.0)

p.say("测试一条比较长的语录，看看自动换行和居中效果如何。")
b = p.bubble
assert b.isVisible() and b.timer.isActive()
print("bubble:", b.geometry(), "tail", "down(above cat)" if b.tail_down else "up(below cat)")

# 把猫头贴到屏幕顶（窗口顶含 top_pad 预留空间，需再上移）
p.move(p.x(), p.screen_rect.top() - p.top_pad)
p.say("顶部测试")
assert not p.bubble.tail_down, "near-top should flip below"
print("near-top bubble flips below OK")

# ---------- 互动动画 ----------
# 轮流触发顺序
kinds = []
for _ in range(4):
    p.play_anim()
    kinds.append(p.anim_kind)
    p.anim_kind = None; p.anim_timer.stop()
assert kinds == ["jump", "squash", "shake", "jump"], kinds
print("anim rotation jump->squash->shake->jump OK")

def offsets_at(kind, t):
    p.anim_kind, p.anim_t = kind, t
    return p._anim_offsets()

# 跳跃：抛物线，t=0.5 最高，起落归零
dx, dy, sx, sy = offsets_at("jump", 0.5)
peak = p.pix.height() * 0.30
assert abs(dy - peak) < 1 and dx == 0 and sx == sy == 1.0, (dx, dy, sx, sy)
assert offsets_at("jump", 0.0)[1] == 0 and offsets_at("jump", 1.0)[1] == 0
assert offsets_at("jump", 0.2)[1] < offsets_at("jump", 0.4)[1] < dy
assert peak + 6 <= p.top_pad + 3, "jump must fit inside top padding"
print(f"jump: peak {dy:.1f}px (parabola, fits headroom {p.top_pad}px) OK")

# 压扁回弹：压到 0.62 变宽近似保体积，结束回到 1，中途轻微过冲
dx, dy, sx, sy = offsets_at("squash", 0.35)
assert abs(sy - 0.62) < 0.01 and abs(sx - 1.228) < 0.01, (sx, sy)
overshoot = max(offsets_at("squash", t / 100)[3] for t in range(36, 100))
assert 1.0 < overshoot < 1.06, overshoot
assert abs(offsets_at("squash", 1.0)[3] - 1.0) < 0.01
assert p.pix.width() * 1.228 <= p.pix.width() + 2 * p.side_pad, "squash widening must fit side padding"
print(f"squash: min sy 0.62 / max sx 1.228, rebound overshoot {overshoot:.3f} OK")

# 左右抖动：衰减正弦，前段幅度 > 后段幅度，收尾近零
first = max(abs(offsets_at("shake", t / 100)[0]) for t in range(0, 34))
last = max(abs(offsets_at("shake", t / 100)[0]) for t in range(67, 101))
assert first > last * 3, (first, last)
assert first <= p.side_pad, "shake must fit side padding"
print(f"shake: amplitude {first:.1f}px -> {last:.1f}px decaying OK")

# 动画计时器推进到结束后自动复位
p.play_anim()  # squash（接着上面的轮换）
for _ in range(200):
    p._anim_tick()
    if p.anim_kind is None:
        break
assert p.anim_kind is None and not p.anim_timer.isActive()
assert p._anim_offsets() == (0.0, 0.0, 1.0, 1.0)
print("anim finishes and resets to neutral OK")

print("ALL PASS")
