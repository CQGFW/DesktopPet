# -*- coding: utf-8 -*-
"""pet_v2 offscreen 自测：分层还原、无待机平移、呼吸、头部跟随、减少动态效果、V1 回归"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import math
import sys
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
import pet_v2 as m

app = QApplication(sys.argv)
p = m.Pet()
p.show()
p.reduced_motion = False   # 测试机的系统设置不应影响用例
assert not p.src.isNull(), "cat_soft.png load failed"
print("sprite:", p.src.width(), "x", p.src.height(), "| display:", p.pix.width(), "x", p.pix.height())

# ---------- 待机不再左右平移 ----------
assert not hasattr(p, "vx") and not hasattr(p, "behave"), "walk logic should be removed"
pos0 = (p.x(), p.y())
for _ in range(200):
    p._frame()
assert (p.x(), p.y()) == pos0, "idle must not move the window"
print("idle: no horizontal walk, window position fixed OK")

# ---------- 呼吸：幅度、连续性、脚底/中心锚定 ----------
t0 = p.t0
vals = [p._breath_scales(t0 + i * 0.033) for i in range(240)]   # 约 2.3 个周期
bys = [by for _, by in vals]
assert max(bys) <= 1 + m.BREATH_AMP_Y + 1e-9 and min(bys) >= 1 - m.BREATH_AMP_Y - 1e-9
assert max(bys) > 1 + m.BREATH_AMP_Y * 0.95 and min(bys) < 1 - m.BREATH_AMP_Y * 0.95
for a, b in zip(bys, bys[1:]):
    assert abs(b - a) < 0.002, "breathing must be continuous (no frame jump)"
for i in range(0, 240, 17):
    r = p._layout(t0 + i * 0.033)
    assert abs(r.bottom() - (p.height() - 3)) < 1e-6, "feet must stay anchored"
    assert abs(r.center().x() - p.width() / 2) < 1e-6, "no horizontal drift"
amp_px = p.pix.height() * m.BREATH_AMP_Y
print(f"breath: ±{m.BREATH_AMP_Y*100:.1f}% (~{amp_px:.1f}px), continuous, foot/center anchored OK")

# ---------- 头部跟随：方向、限幅、平滑、复位 ----------
r = p._cat_rect()
def hover(fx, fy):
    p.hover_pos = QPoint(round(r.x() + r.width() * fx), round(r.y() + r.height() * fy))
    p._update_head_target()
    return p.head_target

assert hover(0.90, 0.10) > 2, "mouse right of pivot -> head turns right"
assert hover(0.10, 0.10) < -2, "mouse left of pivot -> head turns left"
assert hover(0.99, 0.95) == m.HEAD_MAX_DEG, "far corner clamps to +max"
assert hover(0.01, 0.95) == -m.HEAD_MAX_DEG, "far corner clamps to -max"
assert abs(hover(0.66, 0.05)) < 1.5, "above pivot -> nearly straight"

p.hover_pos = QPoint(round(r.x() + r.width() * 0.9), round(r.y() + r.height() * 0.2))
angles = []
for _ in range(120):
    p._frame()
    angles.append(p.head_angle)
target = p.head_target
assert abs(angles[-1] - target) < 0.05, (angles[-1], target)
assert all(b >= a - 1e-9 for a, b in zip(angles, angles[1:])), "approach must be monotonic"
step_max = max(abs(b - a) for a, b in zip(angles, angles[1:]))
assert step_max < target * 0.35, "no snapping, smooth approach"
p.hover_pos = None          # 鼠标移出 → 平滑回正
for _ in range(150):
    p._frame()
assert abs(p.head_angle) < 0.05, p.head_angle
print(f"head: direction/clamp(±{m.HEAD_MAX_DEG}°)/smooth(max step {step_max:.2f}°)/reset OK")

# 窗口内但在猫身外（留白区）不应触发；拖拽中不跟随
assert hover(-0.04, 0.5) == 0.0 if r.x() > 0 else True
p.hover_pos = QPoint(2, 2); p._update_head_target()
assert p.head_target == 0.0, "padding area must not trigger head turn"
p.dragging = True; hover(0.9, 0.2); assert p.head_target == 0.0, "no head turn while dragging"
p.dragging = False

# ---------- 减少动态效果：呼吸/头部/点击动画降级，气泡保留 ----------
p.reduced_motion = True
assert p._breath_scales(t0 + 1.7) == (1.0, 1.0)
assert hover(0.9, 0.2) == 0.0
p.play_anim()
assert p.anim_kind is None and not p.anim_timer.isActive(), "click anim skipped"
p.say("降级模式也要说话")
assert p.bubble.isVisible(), "bubble must survive reduced motion"

# 开启时头部必须立即归零（不能只清 target 后继续平滑旋转）
p.head_angle = 7.5
p._frame()
assert p.head_angle == 0.0, "reduced motion must zero head_angle immediately"
# 系统开关轮询路径同样立即归零
p.reduced_motion = False
p.head_angle = 5.0
_orig_qrm = m.query_reduced_motion
m.query_reduced_motion = lambda: True
p._poll_reduced_motion()
m.query_reduced_motion = _orig_qrm
assert p.reduced_motion and p.head_angle == 0.0 and p.head_target == 0.0, \
    "poll path must zero head_angle immediately"
p.reduced_motion = False
print("reduced-motion: breath/head/click-anim off, head snaps to 0, bubble kept OK")

# ---------- 0° 头身分层应还原原图 ----------
p.anim_kind = None
p.reduced_motion = True     # 冻结呼吸，布局为整数矩形
img = QImage(p.size(), QImage.Format_ARGB32)
img.fill(0)
p.render(img)
ref = p.pix.toImage().convertToFormat(QImage.Format_ARGB32)
ox, oy = p.side_pad, p.height() - p.pix.height() - 3
total = bad = 0
for j in range(0, ref.height(), 5):
    for i in range(0, ref.width(), 5):
        pa = ref.pixelColor(i, j)
        pb = img.pixelColor(ox + i, oy + j)
        if pa.alpha() < 8 and pb.alpha() < 8:
            continue
        total += 1
        if (abs(pa.alpha() - pb.alpha()) > 40 or abs(pa.red() - pb.red()) > 45
                or abs(pa.green() - pb.green()) > 45 or abs(pa.blue() - pb.blue()) > 45):
            bad += 1
assert total > 800, total
assert bad / total < 0.02, f"composite mismatch {bad}/{total}"
print(f"split layers reconstruct original at 0°: {bad}/{total} outliers OK")
p.reduced_motion = False

# ---------- V1 回归：缩放锚点 / 气泡 / 互动动画 ----------
for target in (0.25, 1.5):
    foot = (p.x() + p.width() // 2, p.y() + p.height())
    p._set_scale(target)
    foot2 = (p.x() + p.width() // 2, p.y() + p.height())
    assert abs(foot[0] - foot2[0]) <= 1 and foot[1] == foot2[1], (foot, foot2)
p._set_scale(1.0)
print("zoom keeps foot anchor OK")

# ---------- 滚轮：纵向缩放，纯横向事件忽略 ----------
from PySide6.QtCore import QPointF
from PySide6.QtGui import QWheelEvent

def wheel(ax, ay):
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(ax, ay),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    p.wheelEvent(ev)

s0 = p.scale
wheel(120, 0)
assert p.scale == s0, "horizontal-only wheel must not change scale"
wheel(-120, 0)
assert p.scale == s0, "horizontal-only wheel must not change scale"
wheel(0, 120)
assert p.scale > s0, "wheel up should zoom in"
wheel(0, -120)
assert abs(p.scale - s0) < 1e-9, "wheel down should zoom out"
print("wheel: vertical zooms, horizontal-only ignored OK")

# ---------- 气泡按宠物当前所在屏幕定位 ----------
from PySide6.QtCore import QRect
p.screen_rect = QRect(-9999, -9999, 10, 10)   # 污染缓存，模拟启动后被拖去别的屏幕
p.say("屏幕定位测试")
assert p.screen_rect == p.screen().availableGeometry(), \
    "say() must refresh from the pet's current screen, not a startup cache"
print("bubble uses current screen geometry OK")

p.say("测试一条比较长的语录，看看自动换行和居中效果如何。")
assert p.bubble.isVisible() and p.bubble.timer.isActive()
p.move(p.x(), p.screen_rect.top() - p.top_pad)
p.say("顶部测试")
assert not p.bubble.tail_down, "near-top should flip below"
print("bubble + near-top flip OK")

kinds = []
for _ in range(4):
    p.play_anim()
    kinds.append(p.anim_kind)
    p.anim_kind = None; p.anim_timer.stop()
assert kinds == ["jump", "squash", "shake", "jump"], kinds

def offsets_at(kind, t):
    p.anim_kind, p.anim_t = kind, t
    return p._anim_offsets()

dx, dy, sx, sy = offsets_at("jump", 0.5)
assert abs(dy - p.pix.height() * 0.30) < 1 and dx == 0 and sx == sy == 1.0
dx, dy, sx, sy = offsets_at("squash", 0.35)
assert abs(sy - 0.62) < 0.01 and abs(sx - 1.228) < 0.01
assert p.pix.width() * 1.228 <= p.pix.width() + 2 * p.side_pad
first = max(abs(offsets_at("shake", t / 100)[0]) for t in range(0, 34))
assert first <= p.side_pad
p.anim_kind = None
p.play_anim()
for _ in range(200):
    p._anim_tick()
    if p.anim_kind is None:
        break
assert p.anim_kind is None and not p.anim_timer.isActive()
assert p._anim_offsets() == (0.0, 0.0, 1.0, 1.0)
print("click anims (jump/squash/shake) regression OK")

# 转头极限时也不越出窗口（头层四角绕轴旋转后仍在窗口内）
rr = p._layout(p.t0)
pxv = rr.x() + rr.width() * m.HEAD_PIVOT[0]
pyv = rr.y() + rr.height() * m.HEAD_PIVOT[1]
hx0 = rr.x() + rr.width() * p.head_x_frac
corners = [(hx0, rr.y()), (rr.right(), rr.y()),
           (hx0, rr.y() + rr.height() * p.head_h_frac), (rr.right(), rr.y() + rr.height() * p.head_h_frac)]
for deg in (m.HEAD_MAX_DEG, -m.HEAD_MAX_DEG):
    a = math.radians(deg)
    for cx, cy in corners:
        x = pxv + (cx - pxv) * math.cos(a) - (cy - pyv) * math.sin(a)
        y = pyv + (cx - pxv) * math.sin(a) + (cy - pyv) * math.cos(a)
        assert -1 <= x <= p.width() + 1 and -1 <= y <= p.height() + 1, (deg, x, y)
print("rotated head stays inside window at ±max angle OK")

print("ALL PASS")
