# -*- coding: utf-8 -*-
"""应用级常量与素材路径。不含任何 Win32 / Qt 逻辑，可被任意模块安全导入。"""
import os
import sys


def resource_path(name):
    """定位随程序分发的素材。

    打包后素材被解包到 sys._MEIPASS；从源码运行时本模块位于 <项目根>/desktoppet/，
    而素材放在项目根，因此要向上取一级目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


BASE_H = 260          # 100% 缩放时的显示高度
MIN_SCALE, MAX_SCALE = 0.25, 1.50
ZOOM_STEP = 1.08      # 每格滚轮的平滑步进

# 输入光标跟随：输入时临时缩小并避开输入控件 / IME 候选区域
INPUT_IDLE_MS = 1000
INPUT_POLL_MS = 50
# 跟随时的大小档位（右键菜单可选）。这是**绝对**缩放比例，与平时大小无关：
# 若按平时大小的倍率算，平时调到 MIN_SCALE 时跟随会小到看不见。
# 档位允许低于 MIN_SCALE——跟随是独立的缩放域，不受平时缩放下限约束。
INPUT_SCALE_CHOICES = (0.20, 0.25, 0.30, 0.40)
INPUT_SCALE_DEFAULT = 0.20
INPUT_GAP = 12
INPUT_COMPACT_FOCUS_MAX_H = 96
INPUT_IME_FALLBACK_W = 420
INPUT_IME_FALLBACK_H = 120
INPUT_UNKNOWN_CANDIDATE_GAP = 66
INPUT_CANDIDATE_TTL = 0.2         # 候选框探测结果的复用时长（秒）
INPUT_CANDIDATE_CARET_TOL = 24    # 光标移动超过此距离时立即重新探测

# 互动动画：点击时按此顺序轮流触发；impact 不在轮换里，由抛掷撞墙触发
ANIM_KINDS = ("jump", "squash", "shake")
ANIM_DUR = {"jump": 620, "squash": 520, "shake": 700, "impact": 380}   # 毫秒
ANIM_TICK_MS = 15
ANIM_IMPACT_AMP = (0.15, 0.35)  # 撞击压扁幅度区间，按撞击速度插值

FRAME_MS = 33         # 呼吸 / 头部跟随的动画帧间隔（约 30fps）

# 呼吸：纵向 ±1.5%、横向反相 ±0.6%（近似保体积），周期 3.4s，脚底锚定
BREATH_PERIOD = 3.4
BREATH_AMP_Y = 0.015
BREATH_AMP_X = 0.006

# 头部跟随（比例均相对整张猫图的宽 / 高）
HEAD_MAX_DEG = 12.0             # 最大转角，避免过度旋转脱离身体
HEAD_GAIN = 0.5                 # 鼠标方位角 → 头部目标角的映射比例
HEAD_TAU = 0.12                 # 角度平滑时间常数（秒）
HEAD_PIVOT = (0.66, 0.34)       # 颈部转轴位置
HEAD_CORE_X, HEAD_CORE_Y = 0.44, 0.30   # 头部核心区边界（身体图在此区内抠空）
HEAD_BAND_X, HEAD_BAND_Y = 0.08, 0.08   # 左 / 下羽化过渡带宽度（原位皮毛垫底遮缝）
ERASE_MX, ERASE_MY = 0.07, 0.06         # 抠空区边缘的渐变余量：转头后由静态皮毛补位

# 脚掌图层（比例相对整张猫图）：从原图裁出两只前脚（边缘羽化），
# 静止时原位叠回与原图逐像素重合；敲键时顶端固定、向下拉伸压到键盘上
# （拉伸而非平移：身体不必抠空，也不会露出空缺）
PAW_TOP = 0.74                          # 脚部图层上边界（含小腿，摊薄拉伸比例）
PAW_SPANS = ((0.50, 0.69), (0.69, 0.86))    # 左 / 右脚的水平范围
PAW_FEATHER_Y = 0.10                    # 上边羽化带（拉伸后与身体无缝衔接）
PAW_FEATHER_X = 0.018                   # 左右羽化带
PAW_PRESS_FRAC = 0.45                   # 下压幅度（相对键盘高度）

# 气泡停留时长：短语录保底 2 秒，长语录按字数延长，上限 6 秒
BUBBLE_MIN_MS = 2_000
BUBBLE_MAX_MS = 6_000
BUBBLE_MS_PER_CHAR = 180

# 闲置提醒：距上次互动超过随机间隔时自动弹一条语录；间隔每次在区间内随机取值
IDLE_MIN_MS = 90_000
IDLE_MAX_MS = 180_000

# 自动走动：限定在当前屏幕可用区域的右下 1/4；匀速走向随机目标，到达后停留
WALK_TICK_MS = 33
WALK_TURN_MIN_PX = 4            # 目标横向距离超过该值才转身，避免垂直移动时来回翻
WALK_SPEED = 60                 # 像素/秒
WALK_PAUSE_MIN_MS = 2_000       # 到达目标后停留时长的随机区间
WALK_PAUSE_MAX_MS = 6_000

# 惯性抛掷：快速拖拽后松手，宠物沿拖动方向飞出，在当前屏幕内碰壁回弹并逐渐停下。
# 速度单位均为 像素/秒，加速度为 像素/秒²，阻尼系数为 1/秒（v *= exp(-μ·dt)）。
FLING_SAMPLE_WINDOW_MS = 120    # 释放速度 = 最近这段时间内的平均速度
FLING_HOLD_MS = 80              # 松手前停顿超过此时长视为「放下」，不抛掷
FLING_MIN_SPEED = 500           # 触发抛掷的最低释放速度
FLING_MAX_SPEED = 3000          # 初速度上限，避免一帧飞出视野
FLING_TICK_MS = 16              # 物理积分帧间隔（约 60fps）
FLING_FRICTION = 0.8            # 空气阻尼：1 秒后剩约 45% 速度
FLING_GROUND_FRICTION = 2.5     # 贴地滑行的额外阻尼
FLING_GRAVITY = 600             # 向下重力加速度，让宠物自然落回底部
FLING_RESTITUTION_X = 0.75      # 撞左右墙的弹性恢复系数
FLING_RESTITUTION_Y = 0.70      # 撞顶 / 撞底的弹性恢复系数
FLING_BOUNCE_MIN_SPEED = 60     # 撞底速度低于此值不再弹起（弹起已不足 2px），直接贴地
FLING_STOP_SPEED = 30           # 贴地且速度低于此值即停止
FLING_MAX_DURATION_MS = 10_000  # 单次飞行时限，超时强制停止
FLING_TURN_MIN_SPEED = 40       # 水平速度超过此值才按方向翻转朝向，避免低速抖动
FLING_IMPACT_MIN_SPEED = 200    # 撞击速度超过此值才播放压扁动画
FLING_IMPACT_FULL_SPEED = 1500  # 撞击速度达到此值时压扁幅度取上限
