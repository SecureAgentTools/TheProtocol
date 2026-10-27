# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the `tp` umbrella binary.

Build: pyinstaller tp.spec --clean --noconfirm
Output: dist/tp (linux/amd64 ELF; ~13-14 MB)
"""

block_cipher = None

a = Analysis(
    ["tp_cli.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tp_operator.umbrella",
        "tp_operator.main",
        "tp_operator.mcp_serve",
        "tp_operator.commands.status",
        "tp_operator.commands.health",
        "tp_operator.commands.logs",
        "tp_operator.commands.restart",
        "tp_operator.commands.license",
        "tp_operator.commands.peers",
        "tp_operator.commands.sync",
        "tp_operator.parent_call",
        "tp_operator.commands.validate_config",
        "tp_operator.commands.version",
        "tp_operator.commands.doctor",
        "tp_operator.commands.spire",
        "tp_operator.commands.backup",
        "tp_operator.commands.update",
        "tp_operator.commands.restore",
        "tp_operator.audit_remote",
        "mcp",
        "mcp.server",
        "mcp.server.stdio",
        "mcp.types",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="tp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
