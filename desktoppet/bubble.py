# -*- coding: utf-8 -*-
"""对话气泡窗口：圆角白底 + 小尾巴，逐像素透明，自动消失。"""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPainterPath
from PySide6.QtWidgets import QWidget

from . import config


class Bubble(QWidget):
    """对话气泡：圆角白底 + 小尾巴，逐像素透明，按文字长度自动消失。"""
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

    @staticmethod
    def duration_ms(text):
        """按字数估算停留时长：短语录仍保底 2 秒，长语录留出读完的时间。"""
        return min(config.BUBBLE_MAX_MS,
                   max(config.BUBBLE_MIN_MS, len(text) * config.BUBBLE_MS_PER_CHAR))

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
        # 纵向同样收进屏幕：贴近上 / 下边缘时宁可尾巴对不准，也不要整条跑出屏幕
        y = max(screen.top() + 4, min(y, screen.bottom() - h - 4))
        self.setGeometry(x, y, w, h)
        self.show()
        self.update()
        self.timer.start(self.duration_ms(text))

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
