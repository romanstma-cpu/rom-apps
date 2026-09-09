# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.utils.hooks import collect_all

datas = []
hiddenimports = ['db', 'scanner', 'trader', 'polymarket_api', 'polymarket_auth', 'categorize', 'config', 'webhook', 'crypto15m', 'crypto15m_trader', 'crypto15m_record', 'backtest', 'indicators', 'clob_ws', 'rules', 'copy_trader', 'spot_ws', 'rtds_ws', 'replay', 'parlay_generator', 'ws_ssl', 'script_sandbox', 'script_engine', 'script_backtest', 'script_docs', 'script_audit', 'statistics', 'activity_ws', 'us_market_stream']
hiddenimports += collect_submodules('cryptography')
hiddenimports += collect_submodules('httpx')
hiddenimports += collect_submodules('cytoolz')
hiddenimports += collect_submodules('toolz')
hiddenimports += collect_submodules('parsimonious')
hiddenimports += collect_submodules('bitarray')
# Real-time CLOB market-data WebSocket feed (clob_ws.py).
hiddenimports += collect_submodules('websockets')
# certifi CA bundle: ws_ssl.py verifies every wss:// handshake against it
# (frozen macOS Python has no usable OpenSSL default verify paths). httpx
# already pulls certifi in, but collect it explicitly so the .pem can never
# silently drop out of the bundle.
hiddenimports += ['certifi']
datas += collect_data_files('certifi')

# Polymarket deposit-wallet (POLY_1271) order signing is delegated to the
# official py_clob_client_v2. It's lazy-imported, so PyInstaller's static
# analysis would miss it — collect each package (submodules + data + binaries)
# in full so the frozen backend can sign deposit-wallet orders.
binaries = []
for _pkg in ('py_clob_client_v2', 'poly_eip712_structs', 'py_order_utils', 'Crypto'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

# OS keychain for at-rest credential encryption on macOS/Linux (polymarket_auth
# stores a Fernet master key there). keyring resolves its backends via package
# metadata + entry points, so collect it in full and copy its metadata; the
# Linux Secret Service backend also needs secretstorage + jeepney (absent on the
# Windows build box — the except just skips them there). All optional at runtime:
# a missing/unusable backend falls back to plaintext, so a collect miss here can
# never break the build or the signer.
for _pkg in ('keyring', 'secretstorage', 'jeepney'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass
try:
    datas += copy_metadata('keyring')
except Exception:
    pass


a = Analysis(
    ['service.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Pillow (~13MB) is pulled in transitively but NOTHING on the runtime/signer
    # path imports it (verified: our code + py_clob_client_v2 / poly_eip712_structs
    # / py_order_utils are all PIL-free). The `--selftest` build gate signs a
    # POLY_1271 order, so if this exclude were ever wrong the build aborts before
    # shipping. Drops it from the installer.
    excludes=['PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='rom-polybot-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX disabled: UPX-packed unsigned exes are a common AV/EDR false-positive
    # heuristic and get quarantined on user machines. Ship unpacked.
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,  # see EXE(): avoid AV false-positive/quarantine of the unsigned exe
    upx_exclude=[],
    name='rom-polybot-backend',
)
