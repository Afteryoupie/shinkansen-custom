"""Build the renamed native macOS app: python mac/build_watchdog_app.py --output '/path/LLM watchdog.app'."""
import argparse
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Build this app on macOS (requires the Swift compiler).')
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path.home() / 'Applications/LLM watchdog.app')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    app = args.output.resolve()
    if app.name != 'LLM watchdog.app':
        parser.error('Output must be named LLM watchdog.app')
    macos, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    binary = resources / 'LLMMenuBar'
    subprocess.run(['swiftc', '-O', str(repo / 'watchdog/LLMMenuBar.swift'), '-o', str(binary)], check=True)
    shutil.copy2(repo / 'watchdog/assets/guardian.icns', resources / 'guardian.icns')
    launcher = macos / 'llm-watchdog'
    command = [sys.executable, str(repo / 'mac/launch_watchdog.py'), str(repo), str(binary)]
    launcher.write_text('#!/bin/sh\nexec ' + shlex.join(command) + '\n', encoding='utf-8')
    launcher.chmod(0o755)
    with (app / 'Contents/Info.plist').open('wb') as stream:
        plistlib.dump(dict(CFBundleName='LLM watchdog', CFBundleDisplayName='LLM watchdog',
                          CFBundleIdentifier='local.llm.watchdog', CFBundleExecutable='llm-watchdog',
                          CFBundleIconFile='guardian.icns', CFBundlePackageType='APPL',
                          CFBundleVersion='1', LSUIElement=True, NSHighResolutionCapable=True), stream)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    print(app)


if __name__ == '__main__':
    main()
