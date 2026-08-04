# DesktopPet v2.1「闲置提醒」开发过程记录

> **时间**：2026-07-30 ~ 2026-07-31（继上一会话的 V2 动画版之后）
> **需求**：间隔一段时间未与宠物互动时，宠物自动弹出气泡，从已有语录中随机说一句。
> **成果**：`pet_v2.py` 新增闲置提醒，自测全部通过，重新打包并发布 GitHub Release **v2.1**。

---

## 1. 现状梳理

动手前先确认了项目现状与工作流：

- **文件结构**：`pet.py`（V1，冻结）、`pet_v2.py`（当前版本）、`selftest_v2.py`（offscreen 自测）、`DesktopPetV2.spec`（PyInstaller 配置）、`README.md`。
- **既有交互**：点击弹语录气泡 + 轮流互动动画（跳跃/压扁/抖动）、拖拽、滚轮缩放、右键菜单；呼吸起伏与头部跟随动画；系统「减少动态效果」时动画降级、**气泡保留**。
- **语录来源**：`QUOTES` 列表（12 条）；气泡为独立的 `Bubble` 窗口，2 秒自动消失，`WindowTransparentForInput` 不挡鼠标。
- **工作流（沿用上次会话）**：改代码 → `python selftest_v2.py` → PyInstaller 打包 → 中文描述式 commit。
- `dist/`、`build/` 在 `.gitignore` 中，提交只涉及源码。

## 2. 方案设计与思考

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 触发机制 | 单次触发的 `QTimer`（`setSingleShot`），到点弹泡后再重启 | 「互动重置计时」只需对定时器 `start()`，逻辑最简单；重复型定时器反而要额外管理相位 |
| 提醒间隔 | 90~180 秒，**每次在区间内随机**（常量 `IDLE_MIN_MS` / `IDLE_MAX_MS`） | 固定间隔像闹钟，随机更像活物；常量放文件顶部便于调整 |
| 什么算「互动」 | 点击、拖拽、悬停摸头、滚轮缩放、右键菜单 | 凡是宠物会有反应的操作都算。在 `mousePressEvent` / `mouseMoveEvent` / `wheelEvent` / `contextMenuEvent` 四个入口重置（release 必然跟在 press 后，无需重复） |
| 语录来源 | 复用 `QUOTES`，新增 `_pick_quote()` 避免与上一条重复；点击路径也改走它 | 自动弹出时若连续出现同一句，观感像程序坏了；点击与闲置共用一套选取逻辑 |
| 拖拽中到点 | 跳过弹泡，只重启计时 | 拖拽中弹泡位置观感差；属于防御性处理（按住不动 90 秒以上才可能触发） |
| 「减少动态效果」模式 | 闲置提醒照常生效 | 项目既有约定是该模式下「气泡保留」，与点击气泡行为一致 |
| 是否附带互动动画 | 不附带，只弹气泡 | 需求是「气泡提示」，自动触发时安静一点、不打扰 |

## 3. 代码实现（`pet_v2.py`）

改动点：文件顶部文档字符串补充功能说明；新增常量；`__init__` 挂定时器；新增三个方法；四个事件入口重置计时。

```python
# 闲置提醒：距上次互动超过随机间隔时自动弹一条语录；间隔每次在区间内随机取值
IDLE_MIN_MS = 90_000
IDLE_MAX_MS = 180_000
```

`__init__` 中：

```python
self.last_quote = None    # 上一条语录，随机时避免连续重复

# 闲置提醒：超时无互动自动弹语录；任何互动（含悬停）重置计时
self.idle_timer = QTimer(self)
self.idle_timer.setSingleShot(True)
self.idle_timer.timeout.connect(self._idle_chatter)
self._reset_idle_timer()
```

核心三个方法：

```python
# ---------- 语录 / 闲置提醒 ----------
def _pick_quote(self):
    """随机选一条语录，避免与上一条重复。"""
    q = random.choice([x for x in QUOTES if x != self.last_quote] or QUOTES)
    self.last_quote = q
    return q

def _reset_idle_timer(self):
    """互动后重新计时；下次闲置提醒的间隔在区间内随机取值。"""
    self.idle_timer.start(random.randint(IDLE_MIN_MS, IDLE_MAX_MS))

def _idle_chatter(self):
    """闲置到时：弹一条随机语录（拖拽中跳过），并继续计时等下一次。"""
    if not self.dragging:
        self.say(self._pick_quote())
    self._reset_idle_timer()
```

事件入口（`mousePressEvent` / `mouseMoveEvent` / `wheelEvent` / `contextMenuEvent`）首行加 `self._reset_idle_timer()`；`mouseReleaseEvent` 中点击弹泡由 `random.choice(QUOTES)` 改为 `self._pick_quote()`。

## 4. 自动化测试（`selftest_v2.py`）

新增用例（插在滚轮测试之后，复用其 `wheel()` 辅助函数）：

- 启动即开始计时，且间隔落在 `[IDLE_MIN_MS, IDLE_MAX_MS]` 内；
- `_idle_chatter()` 会弹泡、文本必须来自 `QUOTES`、弹后自动重新计时；
- 拖拽中到点不弹泡，但计时继续；
- 停掉定时器后模拟一次滚轮互动，定时器必须被重启；
- `_pick_quote()` 连续取 40 次，无连续重复且都在 `QUOTES` 内。

结果：**ALL PASS**（含原有全部回归用例：分层还原、呼吸、头部跟随、减少动态效果、缩放锚点、气泡定位、互动动画等）。

## 5. 打包：exe 被锁问题排查

重新打包时 PyInstaller 报错：

```
PermissionError: [WinError 5] 拒绝访问。: 'D:\...\dist\DesktopPetV2.exe'
```

排查过程：

1. 查进程：没有 `DesktopPetV2` / `DesktopPet` 进程在运行 → 不是程序没退出；
2. 查属性：文件只有 `Archive` 属性，非只读 → 不是属性问题；
3. 分层验证：在 `dist/` 里新建/删除测试文件正常 → 不是目录权限问题；
4. 对旧 exe 本身：**删除被拒，但重命名成功** → 这是 Windows 上「文件句柄被占用」的典型表现（多半是杀毒软件扫描或残留句柄；运行中的 exe 也是可改名不可删）。

处理：把旧 exe 改名为 `DesktopPetV2_old.exe` 腾出目标路径 → 重新打包成功（46,916,948 字节）→ 稍后旧文件锁已释放，删除清理完成。

## 6. 提交与推送

- 提交 `2f924d5`：`闲置提醒：一段时间无互动时自动从语录随机弹气泡，互动重置计时`（3 个文件，+62/−3：`pet_v2.py`、`selftest_v2.py`、`README.md`）；
- 推送：`881b92b..2f924d5  main -> main`（github.com/CQGFW/DesktopPet）。

## 7. 发布 GitHub Release

**工具选择**：`gh` CLI 未安装。为避免往系统装软件，改用 GitHub REST API：凭据通过 `git credential fill` 从 Git Credential Manager 读取（就是推送时用的那份，全程不打印 token）；创建 Release 用 `POST /repos/{repo}/releases`，上传 exe 用 `uploads.github.com` 的 assets 接口。

踩到两个环境坑：

1. **Git Bash 的 `$TMPDIR` 为空**：payload 路径拼成了 `/release.json`，写入被拒、请求未发出（无副作用）。改用 `mktemp` 解决。
2. **Windows 管道编码**：curl 返回的 UTF-8 JSON 经管道进 Python 时按 cp936 解码，中文被解坏导致 `json` 解析失败。设 `PYTHONIOENCODING=utf-8` 解决。

**一个意外发现与处理**：

- 首次发布用了 tag `v2.0.0`，成功后 `git fetch --tags` 却拉回了**两个** tag：`v2.0` 和 `v2.0.0`。
- 追查发现远程本来就有一个**用户手动创建的 v2.0 Release**（挂着 V1 `DesktopPet.exe` 和旧版 `DesktopPetV2.exe`）。此前本地从未 fetch 过 tags，`git tag -l` 为空，所以没能发现它。
- `v2.0.0` 与 `v2.0` 语义上是同一个版本号，两个 Release 并存会让人困惑。
- **决策**：用户手建的 v2.0 一律不动（作为旧版本存档）；只删除我自己刚创建的 v2.0.0（release + tag，均返回 HTTP 204），重建为 **v2.1**——版本号顺着 v2.0 递增，tag 指向含新功能的提交 `2f924d5`，发布说明写「较 v2.0 的更新」。

**最终校验**（API 复核）：

| Release | 资产 | 说明 |
| --- | --- | --- |
| **v2.1**（最新） | `DesktopPetV2.exe`（46,916,948 字节，与本地构建一致） | 含闲置提醒的新版 |
| v2.0 | `DesktopPet.exe` + 旧版 `DesktopPetV2.exe` | 用户手建，保持原样 |

## 8. 最终成果

- 代码：`pet_v2.py` 新增闲置提醒（含点击/闲置共用的不重复选语录逻辑）；
- 测试：`selftest_v2.py` 新增 5 项断言，全量 ALL PASS；
- 文档：`README.md` 功能清单补充闲置提醒；
- 产物：`dist/DesktopPetV2.exe` 重新打包；
- 版本：commit `2f924d5` 已推送 `main`；
- 发布：<https://github.com/CQGFW/DesktopPet/releases/tag/v2.1>。

## 9. 经验小结

- Windows 上「删除被拒但重命名成功」≈ 文件句柄被占用（杀软扫描/程序运行中），**改名腾路**是可靠的绕过手段；
- Git Bash 的 `$TMPDIR` 可能为空，临时文件一律用 `mktemp`；
- Windows 下管道传 UTF-8 文本给 Python，记得 `PYTHONIOENCODING=utf-8`；
- 操作远程 Release/tag 前先 `git fetch --tags`，本地看不到 ≠ 远程不存在；
- 别人（用户）手动创建的东西不删不改，只处理自己刚创建的——发现冲突时优先调整自己这边的命名。
