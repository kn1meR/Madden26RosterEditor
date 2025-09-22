# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/mrepAPI.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config', 'config'), 
        ('roster_io.js', '.'),
        ('node', 'node'),
        ('node_modules', 'node_modules')
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # --- FIX #1: Add the exclusions to prevent huge file size ---
    excludes=['venv', 'build', 'dist'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# --- FIX #2: Use the correct, complete PYZ definition ---
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='MREP',
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
          entitlements_file=None)