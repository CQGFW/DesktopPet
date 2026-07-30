# -*- coding: utf-8 -*-
"""桌面宠物（PySide6 版）：真实照片猫咪，逐像素羽化半透明边缘。
功能：随机散步/发呆、走路起伏、拖拽、点击弹出对话气泡并轮流触发互动动画
（跳跃 → 压扁回弹 → 左右抖动）、滚轮缩放(25%~150%，脚底不动)、右键菜单退出。"""
import math
import os
import sys
import random

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF
from PySide6.QtGui import QPixmap, QPainter, QTransform, QColor, QFont, QFontMetrics, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget, QMenu

BASE_H = 260          # 100% 缩放时的显示高度
MIN_SCALE, MAX_SCALE = 0.25, 1.50
ZOOM_STEP = 1.08      # 每格滚轮的平滑步进

# 互动动画：点击时按此顺序轮流触发
ANIM_KINDS = ("jump", "squash", "shake")
ANIM_DUR = {"jump": 620, "squash": 520, "shake": 700}   # 毫秒
ANIM_TICK_MS = 15

QUOTES = [
    "喵~ 今天也要加油鸭！",
    "本喵盯着你工作呢，别摸鱼！",
    "铲屎官，罐罐时间到了吗？",
    "刚睡醒，梦见一条大鱼……",
    "摸我可以，但要付猫粮。",
    "你的代码有 bug 的味道。",
    "晒太阳的日子最舒服啦~",
    "陪本喵玩一会儿嘛！",
    "喵生苦短，及时打盹。",
    "今天的你也很好看哦~",
    "工作再忙，也要记得喝水！",
    "本喵才是这台电脑的主人。",
]


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class Bubble(QWidget):
    """对话气泡：圆角白底 + 小尾巴，逐像素透明，2 秒自动消失。"""
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text = ""
        self.tail_down = True   # 尾巴朝下（气泡在猫上方）
        self.tail_x = 0.5       # 尾巴水平位置（0~1）
        self.font = QFont("Microsoft YaHei", 11)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    PAD_X, PAD_Y, TAIL = 14, 9, 10

    def popup(self, text, anchor_x, anchor_y, above, screen):
        """anchor 为尾巴尖端应指向的点；above=True 表示气泡显示在锚点上方。"""
        self.text = text
        fm = QFontMetrics(self.font)
        tw = min(fm.horizontalAdvance(text), 260)
        rect = fm.boundingRect(0, 0, tw, 1000, Qt.TextWordWrap, text)
        w = rect.width() + self.PAD_X * 2
        h = rect.height() + self.PAD_Y * 2 + self.TAIL
        self.tail_down = above
        x = anchor_x - w // 2
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        self.tail_x = min(0.9, max(0.1, (anchor_x - x) / w))
        y = anchor_y - h if above else anchor_y
        self.setGeometry(x, y, w, h)
        self.show()
        self.update()
        self.timer.start(2000)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, t = self.width(), self.height(), self.TAIL
        body = QRectF(0, 0 if self.tail_down else t, w, h - t)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        # 小尾巴三角
        tx = self.tail_x * w
        if self.tail_down:
            path.moveTo(tx - 8, body.bottom()); path.lineTo(tx, h); path.lineTo(tx + 8, body.bottom())
        else:
            path.moveTo(tx - 8, body.top()); path.lineTo(tx, 0); path.lineTo(tx + 8, body.top())
        path.closeSubpath()
        p.setPen(QColor(180, 150, 120))
        p.setBrush(QColor(255, 252, 245, 242))
        p.drawPath(path)
        p.setPen(QColor(80, 60, 45))
        p.setFont(self.font)
        p.drawText(body.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y),
                   Qt.AlignCenter | Qt.TextWordWrap, self.text)


class Pet(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.src = QPixmap(resource_path("cat_soft.png"))   # 高清羽化素材
        self.scale = 1.0
        self.facing = 1
        self.vx = 0
        self.frame = 0
        self.dragging = False
        self.drag_offset = QPoint()
        self._press_pos = None

        # 互动动画状态
        self.anim_kind = None
        self.anim_t = 0.0
        self.anim_index = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(ANIM_TICK_MS)
        self.anim_timer.timeout.connect(self._anim_tick)

        self._rebuild_pixmap()

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = scr
        self._apply_geometry(scr.center().x(), scr.bottom() + 1)

        self.bubble = Bubble()

        self.menu = QMenu()
        self.menu.addAction("退出", QApplication.quit)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.behave()

    # ---------- 素材缩放与窗口几何 ----------
    def _rebuild_pixmap(self):
        h = round(BASE_H * self.scale)
        self.pix = self.src.scaledToHeight(h, Qt.SmoothTransformation)
        self.pix_flip = self.pix.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)
        # 窗口内为动画预留的空间：头顶留跳跃高度，左右留抖动/压扁变宽的余量
        self.top_pad = round(self.pix.height() * 0.32)
        self.side_pad = round(self.pix.width() * 0.13)

    def _apply_geometry(self, foot_x, foot_y):
        """按当前素材重设窗口尺寸，并保持脚底中心位于 (foot_x, foot_y)。"""
        w = self.pix.width() + 2 * self.side_pad
        h = self.pix.height() + self.top_pad + 6
        self.resize(w, h)
        self.move(foot_x - w // 2, foot_y - h)

    def _set_scale(self, new_scale):
        foot_x = self.x() + self.width() // 2
        foot_y = self.y() + self.height()
        self.scale = new_scale
        self._rebuild_pixmap()
        self._apply_geometry(foot_x, foot_y)

    # ---------- 行为 ----------
    def behave(self):
        if not self.dragging and self.anim_kind is None:
            if random.random() < 0.45:
                self.vx = 0
            else:
                self.vx = random.choice([-2, 2])
                self.facing = 1 if self.vx > 0 else -1
        QTimer.singleShot(random.randint(2000, 5000), self.behave)

    def tick(self):
        self.frame += 1
        if not self.dragging and self.vx and self.anim_kind is None:
            x = self.x() + self.vx
            scr = self.screen_rect
            if x < scr.left():
                x = scr.left(); self.vx = 2; self.facing = 1
            elif x > scr.right() - self.width():
                x = scr.right() - self.width(); self.vx = -2; self.facing = -1
            self.move(x, self.y())
        self.update()

    # ---------- 互动动画 ----------
    def play_anim(self):
        """点击时轮流触发：跳跃 → 压扁回弹 → 左右抖动。"""
        self.anim_kind = ANIM_KINDS[self.anim_index % len(ANIM_KINDS)]
        self.anim_index += 1
        self.anim_t = 0.0
        self.anim_timer.start()

    def _anim_tick(self):
        self.anim_t += ANIM_TICK_MS / ANIM_DUR[self.anim_kind]
        if self.anim_t >= 1.0:
            self.anim_kind = None
            self.anim_timer.stop()
        self.update()

    def _anim_offsets(self):
        """当前动画帧的绘制参数：(水平偏移, 抬升高度, 宽度系数, 高度系数)。"""
        k, t = self.anim_kind, self.anim_t
        if k == "jump":
            # 抛物线：t=0.5 时到达最高点
            return 0.0, self.pix.height() * 0.30 * 4 * t * (1 - t), 1.0, 1.0
        if k == "squash":
            if t < 0.35:            # 压下去
                sy = 1 - 0.38 * math.sin(t / 0.35 * math.pi / 2)
            else:                   # 弹回来，带轻微过冲
                u = (t - 0.35) / 0.65
                sy = 1 - 0.38 * math.exp(-4 * u) * math.cos(u * 1.5 * math.pi)
            return 0.0, 0.0, 1 + (1 - sy) * 0.6, sy   # 压扁时变宽，近似保体积
        if k == "shake":
            # 衰减正弦：3 个来回，幅度递减
            amp = self.pix.width() * 0.055
            return amp * math.exp(-3 * t) * math.sin(t * 6 * math.pi), 0.0, 1.0, 1.0
        return 0.0, 0.0, 1.0, 1.0

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        bob = 3 if (self.vx and self.anim_kind is None and self.frame // 4 % 2 == 0) else 0
        img = self.pix if self.facing == 1 else self.pix_flip
        dx, dy, sx, sy = self._anim_offsets()
        w = round(img.width() * sx)
        h = round(img.height() * sy)
        x = (self.width() - w) // 2 + round(dx)
        y = self.height() - h - 3 + bob - round(dy)
        p.drawPixmap(QRect(x, y, w, h), img)

    # ---------- 互动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self._press_pos = e.globalPosition().toPoint()
            self.drag_offset = self._press_pos - self.pos()

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.move(e.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = False
            # 位移很小视为点击 → 弹气泡 + 轮流触发互动动画
            if self._press_pos is not None and \
               (e.globalPosition().toPoint() - self._press_pos).manhattanLength() < 6:
                self.say(random.choice(QUOTES))
                self.play_anim()
            self._press_pos = None

    def contextMenuEvent(self, e):
        self.menu.exec(e.globalPos())

    def say(self, text):
        head_y = self.y() + self.height() - self.pix.height()   # 猫头顶
        anchor_x = self.x() + self.width() // 2
        # 窗口顶部距屏幕顶部太近时改到下方（用窗口位置而非猫头顶，
        # 因为 top_pad 留白会让猫头顶始终距屏幕顶有 ~89px，导致贴顶时阈值不触发）
        above = self.y() - 80 > self.screen_rect.top()
        anchor_y = head_y - 6 if above else self.y() + self.height() + 6
        self.bubble.popup(text, anchor_x, anchor_y, above, self.screen_rect)

    # ---------- 滚轮缩放：脚底位置不动 ----------
    def wheelEvent(self, e):
        factor = ZOOM_STEP if e.angleDelta().y() > 0 else 1 / ZOOM_STEP
        new_scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        if abs(new_scale - self.scale) < 1e-4:
            return
        self._set_scale(new_scale)
        self.update()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = Pet()
    pet.show()
    sys.exit(app.exec())
