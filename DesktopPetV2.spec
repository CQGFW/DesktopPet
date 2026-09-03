# -*- mode: python ; coding: utf-8 -*-
"""DesktopPet V2 打包配置。

version_info.txt 在每次打包前依 desktoppet.APP_VERSION 重新生成，避免版本号
在源码 / 资源 / 安装包之间各写一份而漂移。"""
import os
import sys

sys.path.insert(0, os.path.abspath(SPECPATH))
from desktoppet import APP_VERSION

_quad = (tuple(int(part) for part in APP_VERSION.split(".")) + (0, 0, 0, 0))[:4]

with open(os.path.join(SPECPATH, 'version_info.txt'), 'w', encoding='utf-8') as _fh:
    _fh.write("""# UTF-8
# 本文件由 DesktopPetV2.spec 自动生成，请勿手工编辑；
# 版本号唯一来源是 desktoppet/__init__.py 的 APP_VERSION。
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(quad)s,
    prodvers=%(quad)s,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [
          StringStruct('CompanyName', 'DesktopPet'),
          StringStruct('FileDescription', 'DesktopPet desktop companion'),
          StringStruct('FileVersion', '%(ver)s'),
          StringStruct('InternalName', 'DesktopPetV2'),
          StringStruct('OriginalFilename', 'DesktopPetV2.exe'),
          StringStruct('ProductName', 'DesktopPet'),
          StringStruct('ProductVersion', '%(ver)s')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""" % {"quad": _quad, "ver": APP_VERSION})


a = Analysis(
    ['pet_v2.py'],
    pathex=[],
    binaries=[],
    datas=[('cat_soft.png', '.'), ('quotes.json', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DesktopPetV2',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
