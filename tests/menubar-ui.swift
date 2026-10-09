// Append to LLMMenuBar.swift with its entry point removed, then compile with swiftc.
// Uses a synthetic snapshot: no model starts, API mutations, or network requests.
extension LLMMenuBarController {
    func verifyMenuUI() {
        isConnected = true
        currentStatus = "running"
        currentModel = "Apple Foundation Models"
        currentModelId = "apple"
        availableModels = [["id": "apple", "name": currentModel, "type": "apple-api"]]
        idleTimeout = 180
        idleDeadline = ProcessInfo.processInfo.systemUptime + 125
        rebuildModels()
        refreshPresentation()
        assert(panel.countdown.stringValue == "02:05")
        assert(primaryItem.title == "立即休眠")
        assert(modelsItem.title == currentModel && modelsItem.submenu === modelsMenu)
        assert(panel.countdown.font!.pointSize == 17)
        assert(autoItem.state == .on)
        decisionSnapshot = ["status": "sleeping", "models": [["id": "laya-multilingual"]], "runtime_available": true]
        refreshPresentation()
        assert(decisionItem.isEnabled && decisionToggle.title == "啟動決策模型")
        assert(decisionToggle.isEnabled)
        decisionSnapshot["status"] = "running"
        decisionSnapshot["device"] = "mps"
        decisionSnapshot["active_requests"] = 1
        refreshPresentation()
        assert(decisionToggle.title == "決策模型休眠" && !decisionToggle.isEnabled)
        decisionSnapshot = [:]
        refreshPresentation()
        let readyArtwork = statusItem.button!.image!.tiffRepresentation!
        assert(statusItem.button!.toolTip!.contains("準備就緒"))
        activeRequests = 1; refreshPresentation()
        let workingArtwork = statusItem.button!.image!.tiffRepresentation!
        assert(readyArtwork != workingArtwork, "Inference must open the jaw")
        assert(statusItem.button!.toolTip!.contains("處理請求"))
        activeRequests = 0; refreshPresentation()
        assert(statusItem.button!.image!.tiffRepresentation! == readyArtwork, "Completed inference must close the jaw")
        currentStatus = "sleeping"; refreshPresentation()
        let sleepingArtwork = statusItem.button!.image!.tiffRepresentation!
        assert(sleepingArtwork != readyArtwork, "Sleep must close the eye")
        for (name, artwork) in [("ready", readyArtwork), ("working", workingArtwork), ("sleeping", sleepingArtwork)] {
            let rep = NSBitmapImageRep(data: artwork)!
            try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "/tmp/watchdog-native-\(name).png"))
        }
        isConnected = false; activeRequests = 1; refreshPresentation()
        assert(statusItem.button!.image!.tiffRepresentation! == sleepingArtwork, "Disconnection must clear stale activity")
        isConnected = true; currentStatus = "running"; activeRequests = 0; refreshPresentation()
        let identity = menu.items.map { ObjectIdentifier($0) }
        isMenuOpen = true
        nextPoll = .greatestFiniteMagnitude
        startPolling()
        let before = panel.countdown.stringValue
        // Regression: drive the same run-loop mode used by an open native menu.
        let end = Date().addingTimeInterval(2.2)
        while Date() < end { RunLoop.main.run(mode: .eventTracking, before: end) }
        assert(panel.countdown.stringValue != before, "Countdown froze in menu tracking mode")
        assert(identity == menu.items.map { ObjectIdentifier($0) }, "Open menu items were rebuilt")
        timer?.invalidate()
        // Backend reset and state transitions.
        idleDeadline = ProcessInfo.processInfo.systemUptime + 180
        refreshPresentation()
        assert(panel.countdown.stringValue == "03:00")
        activeRequests = 1; refreshPresentation()
        assert(panel.countdown.stringValue == "處理中" && panel.progress.isHidden)
        activeRequests = 0; autoSleepEnabled = false; refreshPresentation()
        assert(panel.countdown.stringValue == "保持喚醒")
        autoSleepEnabled = true; idleDeadline = 0; refreshPresentation()
        assert(panel.countdown.stringValue == "00:00")
        assert(panel.detail.stringValue == "等待服務進入休眠")
        currentStatus = "starting"; refreshPresentation()
        assert(!primaryItem.isEnabled && !modelsItem.isEnabled)
        currentStatus = "sleeping"; refreshPresentation()
        assert(panel.countdown.stringValue == "休眠中" && primaryItem.title == "啟動模型")
        isConnected = false; refreshPresentation()
        assert(panel.countdown.stringValue == "尚未連線" && !primaryItem.isEnabled)
        assert(!refreshItem.isHidden)
        isConnected = true; currentStatus = "running"; idleDeadline = ProcessInfo.processInfo.systemUptime + 125
        refreshPresentation()
        for (name, appearance) in [("light", NSAppearance.Name.aqua), ("dark", NSAppearance.Name.darkAqua)] {
            panel.appearance = NSAppearance(named: appearance)
            panel.appearance!.performAsCurrentDrawingAppearance {
                let rep = panel.bitmapImageRepForCachingDisplay(in: panel.bounds)!
                panel.cacheDisplay(in: panel.bounds, to: rep)
                try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "/tmp/guardian-menu-\(name).png"))
            }
        }
        print("PASS: tracking-mode countdown, stable menu identity, deadline reset, active requests, auto-sleep off, zero, starting, sleeping, disconnected; light/dark panel rendered")
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = LLMMenuBarController(connect: false)
controller.verifyMenuUI()
