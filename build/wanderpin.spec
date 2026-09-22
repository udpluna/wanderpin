# PyInstaller spec - builds dist\WanderPin\WanderPin.exe  (run build\build_windows.bat)
import json, os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
product = json.load(open(os.path.join(ROOT, 'product.json'), encoding='utf-8'))
NAME = product.get('app_name', 'WanderPin')

datas = [
    (os.path.join(ROOT, 'static'), 'static'),
    (os.path.join(ROOT, 'product.json'), '.'),
    (os.path.join(ROOT, 'LICENSE'), '.'),
    (os.path.join(ROOT, 'EULA.txt'), '.'),
    (os.path.join(ROOT, 'THIRD_PARTY_NOTICES.md'), '.'),
]
binaries, hiddenimports = [], []
for pkg in ['pymobiledevice3', 'developer_disk_image', 'pmd_pytcp', 'pmd_net_addr', 'pmd_net_proto',
            'pytun_pmd3', 'ipsw_parser', 'pykdebugparser', 'pycrashreport', 'construct', 'bpylist2',
            'opack2', 'srptools', 'qh3', 'gpxpy', 'hyperframe', 'wsproto', 'uvicorn', 'webview',
            'sslpsk_pmd3', 'asn1', 'cryptography', 'ifaddr', 'packaging']:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print('skip', pkg, e)
hiddenimports += ['core.server', 'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
                  'uvicorn.lifespan.on']

a = Analysis([os.path.join(ROOT, 'wanderpin.py')], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=['tkinter', 'matplotlib', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False,
          icon=os.path.join(ROOT, 'static', 'img', 'icon.ico'), version=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
