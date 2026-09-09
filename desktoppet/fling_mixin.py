# -*- coding: utf-8 -*-
"""惯性抛掷 Mixin：快速拖拽后松手，宠物沿拖动方向飞出，在屏幕内碰壁回弹并逐渐停下。

物理计算在 fling 模块（纯函数）；本模块负责采样鼠标轨迹、起飞判定、定时器驱动、
搬动窗口、翻转朝向、撞击时播放压扁动画，以及被抓住 / 弹菜单 / 输入跟随时中止。"""
import math
import time

from PySide6.QtCore import Qt, QTimer

from . import config, fling


class FlingMixin:
    """抛掷回弹的状态机：拖拽采样 → 松手判定 → 逐帧积分 → 停止复位。

    依赖宿主提供：self.reduced_motion、self.facing、self.walk_enabled、
    self.walk_target、self._walk_pos、self._restart_walk_pause()、
    self._reset_idle_timer()、self._current_screen_rect()、self._cat_rect()、
    self.play_impact()、self.width()、self.height()、self.x()、self.y()、
    self.move()、self.update()。"""

    def _init_fling(self):
        self.fling_active = False
        self._fling_body = None        # fling.Body：飞行中的浮点位置与速度
        self._fling_bounds = None      # 起飞时所在屏幕的边界，整段飞行沿用
        self._fling_params = None
        self._fling_elapsed = 0.0      # 本次飞行累计时长（秒）
        self._fling_clock = time.monotonic   # 采样时钟，测试可替换
        self._fling_tracker = fling.VelocityTracker(
            config.FLING_SAMPLE_WINDOW_MS / 1000.0, config.FLING_HOLD_MS / 1000.0)
        self.fling_timer = QTimer(self)
        # 16ms 帧要精确定时器：Windows 上粗定时器的分辨率约 15.6ms，会抖到 30ms 一帧
        self.fling_timer.setTimerType(Qt.PreciseTimer)
        self.fling_timer.setInterval(config.FLING_TICK_MS)
        self.fling_timer.timeout.connect(self._fling_tick)

    # ---------- 拖拽轨迹采样 ----------
    def _fling_begin_drag(self, pos):
        """左键按下：清掉上一次拖拽的样本，从按下点开始记录。"""
        self._fling_tracker.reset()
        self._fling_track(pos)

    def _fling_track(self, pos):
        """拖拽期间记录一个鼠标全局坐标样本。"""
        self._fling_tracker.add(self._fling_clock(), pos.x(), pos.y())

    def _fling_release(self, pos):
        """松手：按采样速度决定是否抛掷。返回是否进入回弹。"""
        vx, vy = self._fling_tracker.velocity(self._fling_clock(), pos.x(), pos.y())
        self._fling_tracker.reset()
        if self.reduced_motion or math.hypot(vx, vy) < config.FLING_MIN_SPEED:
            return False
        self._start_fling(*fling.limit_speed(vx, vy, config.FLING_MAX_SPEED))
        return True

    # ---------- 飞行 ----------
    def _fling_bounds_now(self):
        """碰撞边界（窗口左上角坐标）：让可见的猫贴到屏幕可用区域的边缘，
        四周透明留白允许探出屏幕；底部与可用区域底边齐平（键盘区不出屏）。"""
        scr = self._current_screen_rect()
        cat = self._cat_rect()
        return fling.Bounds.normalized(
            scr.left() - cat.left(),
            scr.right() + 1 - (cat.left() + cat.width()),
            scr.top() - cat.top(),
            scr.bottom() + 1 - self.height())

    @staticmethod
    def _fling_params_now():
        return fling.Params(
            friction=config.FLING_FRICTION,
            ground_friction=config.FLING_GROUND_FRICTION,
            gravity=config.FLING_GRAVITY,
            restitution_x=config.FLING_RESTITUTION_X,
            restitution_y=config.FLING_RESTITUTION_Y,
            bounce_min_speed=config.FLING_BOUNCE_MIN_SPEED,
            stop_speed=config.FLING_STOP_SPEED)

    def _start_fling(self, vx, vy):
        """以给定初速度（像素/秒）从当前位置起飞。"""
        self._fling_bounds = self._fling_bounds_now()
        self._fling_params = self._fling_params_now()
        self._fling_body = fling.Body(float(self.x()), float(self.y()), vx, vy)
        self._fling_elapsed = 0.0
        self.fling_active = True
        self._fling_face(vx)
        self._reset_idle_timer()
        self.fling_timer.start()

    def _fling_tick(self):
        """每帧固定步长积分：搬窗口、转身、撞墙压扁；停下或超时则收尾。"""
        if not self.fling_active:
            return
        dt = config.FLING_TICK_MS / 1000.0
        body, hits = fling.step(self._fling_body, self._fling_bounds, dt,
                                self._fling_params)
        self._fling_body = body
        self._fling_elapsed += dt
        self.move(round(body.x), round(body.y))
        self._fling_face(body.vx)
        if hits:
            wall, speed = max(hits, key=lambda hit: hit[1])   # 撞角落只按更重的那一面压扁
            if speed >= config.FLING_IMPACT_MIN_SPEED:
                self.play_impact(wall, min(1.0, speed / config.FLING_IMPACT_FULL_SPEED))
        if fling.settled(body, self._fling_bounds, self._fling_params):
            self._stop_fling()
        elif self._fling_elapsed * 1000.0 >= config.FLING_MAX_DURATION_MS:
            # 超时兜底（超高屏幕上最后几下微弹可能撑过时限）：有重力就直接落到底边再收尾
            if self._fling_params.gravity > 0:
                self.move(round(body.x), round(self._fling_bounds.y_max))
            self._stop_fling()

    def _fling_face(self, vx):
        """朝向跟随水平速度：向右飞面向右，向左飞水平镜像；低速不翻，避免抖动。"""
        if abs(vx) < config.FLING_TURN_MIN_SPEED:
            return
        facing = 1 if vx > 0 else -1
        if facing != self.facing:
            self.facing = facing
            self.update()

    def _fling_refresh_geometry(self):
        """窗口尺寸重建后（缩放 / 键盘区增减）重算边界并同步位置。

        正常交互路径在重建前都已中止飞行，这里是兜底，保证不会带着旧边界飞出屏幕。"""
        if not self.fling_active:
            return
        self._fling_bounds = self._fling_bounds_now()
        x, y = self._fling_bounds.clamp(float(self.x()), float(self.y()))
        body = self._fling_body
        self._fling_body = fling.Body(x, y, body.vx, body.vy)
        self.move(round(x), round(y))

    # ---------- 停止 / 中止 ----------
    def _stop_fling(self):
        """结束飞行（自然停下或被抓住）：窗口留在当前位置，复位闲置与走动计时。"""
        if not self.fling_active:
            return
        self.fling_timer.stop()
        self.fling_active = False
        self._fling_body = None
        self._fling_bounds = None
        self._fling_params = None
        self._reset_idle_timer()
        if self.walk_enabled:
            # 落点可能远离原目标：丢弃旧目标，停留后按当前位置重选
            self.walk_target = None
            self._walk_pos = None
            self._restart_walk_pause()
