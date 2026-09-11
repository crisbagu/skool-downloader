from pathlib import Path
import plistlib
import subprocess
ROOT = Path(__file__).resolve().parent
APP = ROOT / 'build/Skool Downloader.app'
MAC = APP / 'Contents/MacOS'
MAC.mkdir(parents=True, exist_ok=True)
subprocess.run(['swiftc', '-parse-as-library', '-O', str(ROOT / 'App.swift'), '-o', str(MAC / 'SkoolDownloader')], check=True)
RES = APP / 'Contents/Resources'
RES.mkdir(parents=True, exist_ok=True)
icon = ROOT / 'assets/skool.icns'
plist = {'CFBundleExecutable':'SkoolDownloader','CFBundleIdentifier':'ai.celebro.skooldownloader','CFBundleName':'Skool Downloader','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'1.0.0','LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,'EngineRoot':str(ROOT)}
if icon.exists():
    import shutil; shutil.copy(icon, RES / 'skool.icns'); plist['CFBundleIconFile'] = 'skool'
with (APP / 'Contents/Info.plist').open('wb') as f:
    plistlib.dump(plist, f)
subprocess.run(['codesign','--force','--deep','--sign','-',str(APP)],check=True)
print(APP)
