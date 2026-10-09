# LLM watchdog · Desktop identity

## Direction
Warm paper (#F5F3EC), ink (#242620), vermilion (#BF421F). Editorial hierarchy with a quiet utility interface: large state-aware heading, model status strip, direct engine controls, and a connection/energy sidebar. System fonts keep Traditional Chinese crisp and work offline. Desktop scope only, as requested; checked at 1024, 1280 and 1440 px. At narrower desktop widths, the connection panel moves beneath the models.

The approved left-facing dog profile appears in the app icon, dashboard, and optically simplified macOS menu bar icon. Menu state uses shape, not color alone. Native SF Symbols provide menu commands; inline SVG provides web controls. No third-party frontend dependencies or remote font requests.

## Reference research
These are quality references, not a claim that this implementation has won an award or reproduces a winning site.
- Awwwards Sites of the Day: https://www.awwwards.com/websites/sites_of_the_day/ — reference gallery for composition and typography.
- Bézier, Webby 2025 Best Visual Design – Function: https://winners.webbyawards.com/2025/websites-and-mobile-sites/features-design/best-visual-design-function/324140/bzier — functional visual design benchmark.
- FWA, Rob Ford's curated projects: https://thefwa.com/FWA25/RobFWA.html — reference for distinctive identity and purposeful interaction.

## Files and rebuilding
- `../templates/dashboard.html`: self-contained dashboard and existing API integration.
- `../LLMMenuBar.swift`: native menu and template status artwork.
- `../assets/generate-icon.swift`: editable native vector master.
- `../assets/guardian.icns`: complete app icon.
- `../assets/guardian-1024.png`: full-size preview.

From the repository root:

```sh
swift watchdog/assets/generate-icon.swift /tmp/guardian.iconset
iconutil -c icns /tmp/guardian.iconset -o watchdog/assets/guardian.icns
swiftc -O watchdog/LLMMenuBar.swift -o watchdog/LLMMenuBar
```

The local app at `/Users/linjiade/LLM/LLM watchdog.app` uses `Contents/Resources/applet.icns`; the new ICNS is installed there. A copy of the previous icon is saved in `/tmp/guardian-original-applet.icns`. The launch script recompiles a newer Swift source automatically. Finder may retain its icon cache until the app is next opened.

## Verification
Swift compilation passed. Browser tests against an isolated mock API passed: wake, sleep, engine switch, sleep toggle, clipboard, exit dialog and Escape, stable model DOM across polling, desktop overflow, reduced motion, and disconnection recovery UI. Production model inference is outside this visual check. The preview uses illustrative model entries, not a live inventory.

Live verification: production `/status` loaded the new template and polled the real API without JavaScript errors. Captured `desktop-preview.png` from the live service. App icon registration now uses CFBundleIconFile, and the modified app was ad-hoc re-signed and verified. The menu bar binary was rebuilt and reloaded independently of the model service.

## Native menu redesign
The menu now has a fixed status panel with the current model, large `mm:ss` countdown and remaining-time bar, followed by a contextual wake/sleep command, checked auto-sleep option, model submenu, and concise utility commands. Destructive shutdown requires confirmation. Commands report failures and disable conflicting actions while pending.

A one-second timer runs in both common and event-tracking run-loop modes. A monotonic deadline is corrected from `/api/status` every two seconds. Network completions are delivered to both default and event-tracking modes. Open menus update existing views/items instead of rebuilding the menu under the pointer. Active inference, startup, sleep, always-on, zero countdown and disconnection have distinct presentations.

Regression test: concatenate `watchdog/LLMMenuBar.swift` before `// 主程式入口` with `tests/menubar-ui.swift`, compile with `swiftc`, and run in a macOS GUI session. It drives `.eventTracking`, verifies the countdown advances while item identities remain stable, tests backend deadline reset and all status presentations, and renders the panel in Aqua and Dark Aqua. Passed on 2026-10-06. Computer-use could not capture the live standalone menu; panel rendering and native run-loop tests were used for validation.

### Compact menu and K2 startup follow-up
The status panel is now 100 pt high with a 17 pt countdown (previously 27 pt). The current model name is a native submenu row directly under the status panel; selecting it exposes available models, replacing the separate switch-model row.

Startup regression: both status handlers and the background idle checker could stop a newly spawned process using the previous idle timestamp, before readiness was reached. All three now exclude startup. K2 has a 120-second readiness window; individual health probes are bounded to two seconds and timed-out processes are stopped before a retry. Added `tests/test_startup_idle.py`. All 16 Python tests and native UI regression tests passed. Live K2 startup with status polling succeeded (1.12 s backend readiness, 1.26 s observed request); restored K2 to its prior sleeping state afterward. This measures the current cached start, not a reboot-level cold-start benchmark.


Windows port and the renamed macOS app build are documented in [WINDOWS.md](WINDOWS.md).

### Left-facing dog expressions (2026-10-09)

Approved reference: `dog-profile-approved.png`. The dog closes its eye during sleep/disconnection, opens its eye while ready/loading, and opens its jaw only while `active_requests > 0` on a running model. Status text distinguishes loading from ready and disconnection from sleep. The jaw is static, so activity remains visible without continuous motion. Native macOS artwork is a transparent template, while tray/app assets retain a white face for contrast.

Verified: Swift optimized compilation; native menu regression including image changes on inference start/completion and stale-activity clearing on disconnect; existing tracking-mode countdown and menu identity tests; dashboard JavaScript syntax and seven state transitions; Windows presentation and icon-refresh tests with its native tray mocked on macOS. Actual Windows shell rendering still requires Windows. The generated preview includes 16/24/32 px samples on light and dark backgrounds.
