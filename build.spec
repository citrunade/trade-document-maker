# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件。
用法：pyinstaller build.spec
生成的单文件 EXE 位于 dist/ 外贸制单工具.exe
"""
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# pandas 在读取 Excel 时会通过 importlib.metadata 检查 openpyxl/xlrd 的版本号，
# 用以确认版本满足最低要求。PyInstaller 默认不会打包这些库的 dist-info 元数据，
# 导致打包后版本号读取为 "unknown"，进而在 packaging.version.Version("unknown")
# 处抛出 "Invalid version: 'unknown'" 报错（AI导入/Excel批量导入功能均会触发）。
# 显式复制这些包的元数据即可解决。
datas = []
for pkg in ("openpyxl", "xlrd", "pandas", "python-docx", "reportlab", "Pillow"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'reportlab.pdfbase._fontdata_enc_winansi',
        'reportlab.pdfbase._fontdata_enc_macroman',
        'reportlab.pdfbase._fontdata_enc_standard',
        'reportlab.pdfbase._fontdata_enc_symbol',
        'reportlab.pdfbase._fontdata_enc_zapfdingbats',
        'reportlab.pdfbase._fontdata_widths_helvetica',
        'reportlab.pdfbase._fontdata_widths_helveticabold',
        'reportlab.pdfbase._fontdata_widths_helveticaoblique',
        'reportlab.pdfbase._fontdata_widths_helveticaboldoblique',
        'reportlab.pdfbase._fontdata_widths_timesroman',
        'reportlab.pdfbase._fontdata_widths_timesbold',
        'reportlab.pdfbase._fontdata_widths_timesitalic',
        'reportlab.pdfbase._fontdata_widths_timesbolditalic',
        'reportlab.pdfbase._fontdata_widths_courier',
        'reportlab.pdfbase._fontdata_widths_courierbold',
        'reportlab.pdfbase._fontdata_widths_courieroblique',
        'reportlab.pdfbase._fontdata_widths_courierboldoblique',
        'reportlab.pdfbase._fontdata_widths_symbol',
        'reportlab.pdfbase._fontdata_widths_zapfdingbats',
        'PyQt6.sip',
        'fitz',
        'tabulate',
        'docx',
        'openpyxl',
        'xlrd',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='外贸制单工具',
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
    icon=None,
)
