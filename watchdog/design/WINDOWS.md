# LLM watchdog

Windows and macOS share the local API and web dashboard. Windows uses a native right-click tray menu for status, sleep countdown, current model and model submenu, contextual wake/sleep, checked auto-sleep, clipboard action, reconnect and confirmed shutdown. It has no separate panel or left-click action. The countdown is refreshed when opening the menu; the web dashboard provides a continuously updating countdown.

Windows uses existing Pillow and pystray, without installing packages at runtime. The existing `windows/start-watchdog.ps1` launches the core Python module and tray script with hidden windows. Network operations run in worker threads. The native menu is refreshed immediately before a right-click opens it, so background polling does not destroy a menu under the pointer. If the backend process ends after a successful connection, the tray exits; temporary connection errors keep reconnection available.
The shared web dashboard and macOS native menu are named **LLM watchdog**. The macOS app can be rebuilt from this checkout with the actual project Python interpreter:

```sh
/path/to/project/.venv/bin/python3 mac/build_watchdog_app.py --output "$HOME/Applications/LLM watchdog.app"
```

The builder compiles the native Swift menu, installs the icon and bundle display name, and signs the app locally. The Finder launcher invokes `mac/launch_watchdog.py` directly using that same Python interpreter; it does not invoke `.command` files. Keep the checkout and interpreter at their build-time paths. Existing macOS app installations are not changed by a Windows checkout update; build and launch the new app on the Mac.

The previous Windows file and uncommitted changes are recoverable from the pre-update Git stash. The macOS build requires macOS and Xcode command-line tools; Swift compilation and Finder integration must be verified there.

## State icons

LLM watchdog uses a robot watchdog silhouette. Running: green, open eyes, play symbol. Sleeping: slate gray, closed eyes, pause symbol. Loading: amber hourglass. Disconnected: red cross. The Windows tray uses separate PNGs for each state; the macOS native menu uses the same dog silhouette with monochrome state glyphs. The icon source is watchdog/assets/generate_watchdog_icon.py. The 16/24/32 px preview is watchdog/assets/watchdog-states-preview.png. Mac menu compilation still requires macOS.
