# DesktopPet 桌面宠物

一只常驻桌面的小猫，基于 PySide6 实现。窗口透明、置顶、可拖拽，带呼吸与头部跟随动画。

![pet](cat_soft.png)

## 功能

- 透明无边框窗口，可拖到任意位置（支持多显示器）
- 始终置顶（默认开启，可在右键菜单切换）
- 自动走动（默认关闭，可在右键菜单开启）：宠物在当前屏幕右下 1/4 区域内随机游走，到达目标后停留数秒再走向下一处；拖拽或菜单打开时暂停
- 呼吸起伏与头部跟随鼠标的动画；系统开启“减少动态效果”时自动停止动画（含自动走动）
- 双击互动、右键菜单、滚轮缩放（仅纵向滚动生效）
- 气泡对话框，按宠物当前所在屏幕定位
- 闲置提醒：一段时间没有互动（约 1.5~3 分钟随机）时，宠物自动弹出一条随机语录

## 运行

```powershell
pip install PySide6
python pet_v2.py
```

`pet.py` 为第一版，`pet_v2.py` 为当前版本。

## 测试

```powershell
python selftest_v2.py
```

## 打包成 exe

```powershell
pip install pyinstaller
python -m PyInstaller DesktopPetV2.spec
```

产物在 `dist/DesktopPetV2.exe`，单文件、无控制台窗口。
