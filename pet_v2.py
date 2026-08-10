# -*- coding: utf-8 -*-
"""桌面宠物 V2 启动入口。

实现已拆分到 desktoppet 包（见 desktoppet/pet.py 等）；本文件保留为入口，
README、DesktopPetV2.spec 与既有快捷方式都指向它。"""
import sys

from desktoppet.app import main

if __name__ == "__main__":
    sys.exit(main())
