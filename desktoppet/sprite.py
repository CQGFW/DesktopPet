# -*- coding: utf-8 -*-
"""素材分层：把整张猫图拆成身体 / 头部 / 两只前脚三组图层。

只在启动时做一次；缩放时由 Pet 对各层按高度重采样。"""
from collections import namedtuple

from PySide6.QtGui import QPixmap, QPainter, QColor, QImage, QLinearGradient

from . import config

Layers = namedtuple(
    "Layers", "body head head_x_frac head_h_frac paw_srcs paw_fracs")


def build_layers(src_pixmap):
    """按原图分辨率把猫图拆成 body（头部核心区抠空）与 head（左 / 下边羽化）。
    0° 时 head 叠回 body 逐像素还原原图；转头时过渡带的原位皮毛垫底遮住接缝。
    只在启动时做一次，缩放时直接对两层按高度重采样。"""
    src = src_pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    w, h = src.width(), src.height()
    core_x = round(w * config.HEAD_CORE_X)
    core_y = round(h * config.HEAD_CORE_Y)
    band_x = round(w * config.HEAD_BAND_X)
    band_y = round(h * config.HEAD_BAND_Y)

    body = QImage(src)
    # 抠空蒙版：核心区内部全抠、左 / 下边缘按渐变过渡到不抠。
    # 转头让头层移开时，边缘处保留的静态皮毛垫底补位，避免露出直线接缝。
    mw, mh = w - core_x, core_y
    mx = round(w * config.ERASE_MX)
    my = round(h * config.ERASE_MY)
    mask = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
    mask.fill(0)
    p = QPainter(mask)
    gx = QLinearGradient(0, 0, mx, 0)
    gx.setColorAt(0.0, QColor(0, 0, 0, 0))
    gx.setColorAt(1.0, QColor(0, 0, 0, 255))
    p.fillRect(0, 0, mx, mh, gx)
    p.fillRect(mx, 0, mw - mx, mh, QColor(0, 0, 0, 255))
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    gy = QLinearGradient(0, mh - my, 0, mh)
    gy.setColorAt(0.0, QColor(0, 0, 0, 255))
    gy.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(0, mh - my, mw, my, gy)
    p.end()
    p = QPainter(body)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    p.drawImage(core_x, 0, mask)
    p.end()

    crop_x = core_x - band_x
    crop_h = core_y + band_y
    head = src.copy(crop_x, 0, w - crop_x, crop_h)
    p = QPainter(head)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    gx = QLinearGradient(0, 0, band_x, 0)
    gx.setColorAt(0.0, QColor(0, 0, 0, 0))
    gx.setColorAt(1.0, QColor(0, 0, 0, 255))
    p.fillRect(0, 0, band_x, crop_h, gx)
    gy = QLinearGradient(0, core_y, 0, crop_h)
    gy.setColorAt(0.0, QColor(0, 0, 0, 255))
    gy.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(0, core_y, head.width(), crop_h - core_y, gy)
    p.end()

    # 脚掌图层：从原图裁出两只前脚并羽化边缘。静止时原位叠回与原图
    # 逐像素重合（身体不抠空）；敲键时向下拉伸覆盖，不会露出空缺
    paw_srcs = []
    paw_fracs = []     # (x, y, w, h) 在整图中的比例
    py0 = round(h * config.PAW_TOP)
    fy = round(h * config.PAW_FEATHER_Y)
    fx = round(w * config.PAW_FEATHER_X)
    for x0, x1 in config.PAW_SPANS:
        rx0, rx1 = round(w * x0), round(w * x1)
        pw, ph = rx1 - rx0, h - py0
        paw = src.copy(rx0, py0, pw, ph)
        pp = QPainter(paw)
        pp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        gy = QLinearGradient(0, 0, 0, fy)
        gy.setColorAt(0.0, QColor(0, 0, 0, 0))
        gy.setColorAt(1.0, QColor(0, 0, 0, 255))
        pp.fillRect(0, 0, pw, fy, gy)
        gxl = QLinearGradient(0, 0, fx, 0)
        gxl.setColorAt(0.0, QColor(0, 0, 0, 0))
        gxl.setColorAt(1.0, QColor(0, 0, 0, 255))
        pp.fillRect(0, 0, fx, ph, gxl)
        gxr = QLinearGradient(pw - fx, 0, pw, 0)
        gxr.setColorAt(0.0, QColor(0, 0, 0, 255))
        gxr.setColorAt(1.0, QColor(0, 0, 0, 0))
        pp.fillRect(pw - fx, 0, fx, ph, gxr)
        pp.end()
        paw_srcs.append(QPixmap.fromImage(paw))
        paw_fracs.append((rx0 / w, py0 / h, pw / w, ph / h))

    return Layers(QPixmap.fromImage(body), QPixmap.fromImage(head),
                  crop_x / w,      # head 层在整图中的水平起点比例
                  crop_h / h,      # head 层高度占整图比例
                  paw_srcs, paw_fracs)
