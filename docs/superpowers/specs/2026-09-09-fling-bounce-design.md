# 惯性抛掷与屏幕回弹设计

## 目标

拖拽宠物时如果松手前的拖动速度超过临界值，宠物沿拖动方向飞出，在当前屏幕可用区域内碰壁回弹，
受阻尼与重力逐渐减速，最终落在底部停下。慢速释放保持现状：宠物停在松手处。

## 范围与约束

- 只新增「松手后的飞行」这一段行为；拖拽本身、点击判定、气泡、菜单均不改语义。
- 飞行限定在起飞时所在屏幕的可用区域（任务栏以外），不跨屏幕。
- 任何直接互动（左键按下、右键菜单、滚轮、输入跟随触发）都立即接住宠物，飞行中止在当前位置。
- 服从系统「减少动态效果」：开启时不抛掷；飞行途中开启则原地停下。
- 物理计算是纯函数，不依赖 Qt，可在 offscreen 下完整单测。

## 方案

### 模块划分

| 文件 | 职责 |
| --- | --- |
| `desktoppet/fling.py` | 纯物理：`VelocityTracker`（释放速度采样）、`Body` / `Bounds` / `Params`、`step()`（单步积分与碰撞）、`settled()`（停止判定） |
| `desktoppet/fling_mixin.py` | `FlingMixin`：采样鼠标轨迹、起飞判定、16ms 定时器驱动、搬动窗口、翻转朝向、撞击动画、各种中止路径 |
| `desktoppet/config.py` | `FLING_*` 常量与撞击动画时长 / 幅度 |
| `desktoppet/animation_mixin.py` | 新增 `play_impact(side, strength)`：按撞击方向压扁再回弹 |
| `desktoppet/pet.py` | 装配 `FlingMixin`，在鼠标 / 菜单 / 滚轮事件里接入采样与中止 |
| `desktoppet/walk_mixin.py`、`input_follow_mixin.py` | 飞行中暂停走动；输入跟随进入前先接住宠物 |

沿用 `placement.py`（纯几何）+ `input_follow_mixin.py`（窗口侧）的拆分方式。

### 释放速度采样

拖拽期间每个 `mouseMoveEvent` 记录一条 `(t, x, y)`，`t` 取 `time.monotonic()`，坐标为鼠标全局坐标。
按下时先清空再记一条，样本超过 `窗口 + 停顿阈值` 的时长即丢弃，队列始终很短。

松手时：

1. 最近一条样本距松手超过 `FLING_HOLD_MS`（80ms）→ 视为「放下」，速度为 0。
2. 否则取窗口（`FLING_SAMPLE_WINDOW_MS`，120ms）内最早的样本到松手点的平均速度：
   `v = (p_release - p_first) / (t_release - t_first)`。分母包含松手前的停顿，
   停顿不足阈值时速度会随之衰减而不是硬切。
3. 时间跨度不足 20ms 的样本视为噪声，速度为 0（防止一次按下 / 松开之间没有真实移动却算出巨大速度）。

速度模长 `>= FLING_MIN_SPEED`（500 px/s）才起飞；超过 `FLING_MAX_SPEED`（3000 px/s）按比例缩到上限。

### 碰撞边界

以窗口左上角为坐标，边界让**可见的猫**贴到屏幕可用区域的边缘，四周透明留白允许探出屏幕；
底部与可用区域底边齐平（键盘区不出屏，与自动走动一致）：

```
x_min = screen.left()   - cat.left()                  # cat = _cat_rect()，cat.left() 即 side_pad
x_max = screen.right()  + 1 - (cat.left() + cat.width())   # 猫右缘贴屏幕右缘
y_min = screen.top()    - cat.top()                   # 猫头顶贴屏幕顶缘
y_max = screen.bottom() + 1 - height                  # 窗口底边齐平
```

边界在起飞时按 `_current_screen_rect()` 算一次，整段飞行沿用；区域比窗口还小的轴退化为一条线，该轴速度归零。

### 积分与回弹

定时器固定 `FLING_TICK_MS = 16`（约 60fps，`Qt.PreciseTimer`），每帧固定步长 `dt = 0.016s`，
与走动 / 互动动画一样按帧推进而不是按实际耗时，轨迹确定、可单测。每步：

1. 重力：`vy += g * dt`（`FLING_GRAVITY = 600`）。
2. 空气阻尼：`v *= exp(-μ * dt)`（`FLING_FRICTION = 0.8`）。与规格里的 `1 - μ·dt` 一阶等价，
   但对任意 `dt` 都不会翻号。
3. 位移：浮点累加，`move()` 时才取整。
4. 撞墙：越界则夹回边界，该轴速度反向乘弹性系数（左右 `FLING_RESTITUTION_X = 0.75`，
   上下 `FLING_RESTITUTION_Y = 0.70`）。同一帧撞角会同时报告两面墙。
5. 撞底速度低于 `FLING_BOUNCE_MIN_SPEED`（60 px/s，约 3px 弹跳高度）不再弹起，直接贴地，避免无限微弹。
6. 贴地时额外施加地面阻尼 `FLING_GROUND_FRICTION = 2.5`，模拟滑行减速。

停止判定：速度低于 `FLING_STOP_SPEED`（30 px/s）且（有重力时）已贴地；或飞行超过
`FLING_MAX_DURATION_MS`（10s）强制停止——超时时若仍在空中（超高屏幕上最后几下微弹可能撑过时限），
有重力就直接落到底边，不悬在半空。停止后：定时器停、状态清空、闲置提醒重新计时、
自动走动丢弃旧目标并重新排期停留。

### 动画与朝向

- 朝向：`|vx| > FLING_TURN_MIN_SPEED`（40 px/s）时按水平速度方向翻转，落地后保持最后朝向。
- 撞击形变：撞击速度 `>= FLING_IMPACT_MIN_SPEED`（200 px/s）时播放 `impact` 动画，
  幅度随撞击速度在 `ANIM_IMPACT_AMP`（0.15 ~ 0.35）间插值，`FLING_IMPACT_FULL_SPEED`（1500 px/s）达上限；
  同一帧撞角落时只按撞得更重的那一面压扁。
  形变沿撞击方向压扁、另一方向近似保体积地变宽 / 变高，撞墙侧的边缘固定不动
  （左右墙用水平偏移抵消、镜像时偏移随 `facing` 取反；撞顶时用抬升量把头顶钉住）。
  压扁 → 带过冲的回弹曲线与现有 `squash` 共用，只是压下去更快（20% 处到底）。

### 中止路径

| 触发 | 处理 |
| --- | --- |
| 左键按下 | `_stop_fling()` 后照常进入拖拽，位置就是被抓住那一帧 |
| 右键菜单 | `_stop_fling()` 再弹菜单 |
| 滚轮 | `_stop_fling()` 再缩放 |
| 输入跟随进入 | `_input_on_key` 里先 `_stop_fling()`，再记录脚底锚点 |
| 减少动态效果开启 | `_poll_reduced_motion` 里 `_stop_fling()` |
| 另一实例唤醒（`wake_up`） | `_stop_fling()` 再打招呼，气泡才会贴着停下的位置 |
| 自动走动 | `_walk_paused()` 加入 `fling_active`；停止后按拖拽释放同样处理 |
| 闲置提醒 | 飞行中不弹语录，起飞与停止都重新计时 |
| 窗口尺寸重建 | `_rebuild_geometry` 调 `_fling_refresh_geometry()` 重算边界并同步位置（安全网，正常路径已先中止） |

## 测试

`tests/test_fling.py`，全部 offscreen：

- 采样器：慢速不起飞、快速给出正确速度向量、停顿超过阈值归零、停顿不足按比例衰减、只看最近窗口、
  跨度不足视为噪声、样本队列有界。
- 积分：自由飞行受阻尼与重力、四面墙各自夹紧 + 反向 + 衰减、角落同帧双报、随机初速度长跑不越界、
  必然在时限内贴地停止、微弹被吸附、退化边界、无重力原地停、速度上限。
- Mixin：慢放不起飞、快甩起飞、点击不起飞、悬停后松手不起飞、减少动态效果不起飞、
  边界贴合可见猫、飞行推进窗口并停下、停下后闲置 / 走动计时复位、走动飞行中暂停、
  按下 / 右键 / 滚轮 / 输入跟随 / 减少动态效果各自中止、朝向随速度翻转、撞墙触发撞击动画、
  飞行中闲置提醒静默、尺寸重建后仍在边界内。
- 动画：撞击形变四个方向各自钉住撞墙侧边缘，幅度不越出留白。

## 参数调优指南

| 常量 | 默认 | 调大的效果 |
| --- | --- | --- |
| `FLING_MIN_SPEED` | 500 | 更难触发，防误甩 |
| `FLING_MAX_SPEED` | 3000 | 飞得更快更远 |
| `FLING_FRICTION` | 0.8 | 空中减速更快、飞行更短 |
| `FLING_GRAVITY` | 600 | 下坠更重、抛物线更陡 |
| `FLING_RESTITUTION_X/Y` | 0.75 / 0.70 | 反弹更「弹」，回弹次数更多 |
| `FLING_GROUND_FRICTION` | 2.5 | 落地后滑行更短 |
| `FLING_BOUNCE_MIN_SPEED` | 60 | 更早停止微弹，落地更干脆 |
| `FLING_STOP_SPEED` | 30 | 更早判停 |
| `FLING_SAMPLE_WINDOW_MS` | 120 | 速度更平滑但对方向突变更迟钝 |
| `FLING_HOLD_MS` | 80 | 允许松手前停顿更久仍算甩出 |
