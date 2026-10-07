import Cocoa
import Foundation

/// A non-interactive status panel above native, keyboard-accessible menu commands.
final class GuardianStatusView: NSView {
    let status = NSTextField(labelWithString: "正在連線")
    let countdown = NSTextField(labelWithString: "—")
    let detail = NSTextField(labelWithString: "")
    let progress = NSProgressIndicator()

    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: 300, height: 100))
        let title = NSTextField(labelWithString: "翻譯守護")
        title.font = .systemFont(ofSize: 13, weight: .semibold)
        title.frame = NSRect(x: 18, y: 72, width: 110, height: 22)
        status.font = .systemFont(ofSize: 11, weight: .medium)
        status.alignment = .right
        status.frame = NSRect(x: 130, y: 73, width: 152, height: 20)
        countdown.font = .monospacedDigitSystemFont(ofSize: 17, weight: .medium)
        countdown.frame = NSRect(x: 18, y: 43, width: 264, height: 25)
        detail.font = .systemFont(ofSize: 11)
        detail.textColor = .secondaryLabelColor
        detail.frame = NSRect(x: 18, y: 24, width: 264, height: 18)
        progress.isIndeterminate = false
        progress.minValue = 0; progress.maxValue = 1
        progress.style = .bar
        progress.frame = NSRect(x: 18, y: 10, width: 264, height: 5)
        for view in [title, status, countdown, detail, progress] { addSubview(view) }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

class LLMMenuBarController: NSObject, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private let panel = GuardianStatusView()
    private let modelsMenu = NSMenu()
    private var primaryItem: NSMenuItem!
    private var autoItem: NSMenuItem!
    private var modelsItem: NSMenuItem!
    private var quitItem: NSMenuItem!
    private var refreshItem: NSMenuItem!
    private var timer: Timer?
    private var nextPoll: TimeInterval = 0
    private var polling = false
    private var isMenuOpen = false
    private var busy = false
    private var feedback: String?
    private var currentStatus = "sleeping"
    private var currentModel = "尚未取得模型"
    private var currentModelId = ""
    private var idleDeadline: TimeInterval = 0
    private var idleTimeout = 0
    private var activeRequests = 0
    private var autoSleepEnabled = true
    private var availableModels: [[String: Any]] = []
    private var isConnected = false

    init(connect: Bool = true) {
        super.init()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.menu = menu
        menu.delegate = self
        menu.autoenablesItems = false
        modelsMenu.autoenablesItems = false
        buildMenu()
        refreshPresentation()
        if connect {
            startPolling()
            fetchStatus()
        }
    }

    @discardableResult
    private func item(_ title: String, _ symbol: String, _ action: Selector, key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        item.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
        menu.addItem(item)
        return item
    }

    private func buildMenu() {
        let header = NSMenuItem()
        header.view = panel
        menu.addItem(header)
        modelsItem = NSMenuItem(title: "切換模型", action: nil, keyEquivalent: "")
        modelsItem.image = NSImage(systemSymbolName: "square.stack.3d.up", accessibilityDescription: nil)
        modelsItem.submenu = modelsMenu
        menu.addItem(modelsItem)
        menu.addItem(.separator())
        primaryItem = item("啟動模型", "power", #selector(toggleEngine))
        autoItem = item("閒置時自動休眠", "timer", #selector(toggleAutoSleep))
        menu.addItem(.separator())
        item("開啟控制台", "rectangle.grid.2x2", #selector(openWebDashboard), key: "d")
        item("複製 API 網址", "doc.on.doc", #selector(copyApiUrl), key: "c")
        refreshItem = item("重新連線", "arrow.clockwise", #selector(reconnect))
        menu.addItem(.separator())
        quitItem = item("結束守護與模型服務…", "power", #selector(quitApp), key: "q")
    }

    private func startPolling() {
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.refreshPresentation()
            if ProcessInfo.processInfo.systemUptime >= self.nextPoll {
                self.nextPoll = ProcessInfo.processInfo.systemUptime + 2
                self.fetchStatus()
            }
        }
        self.timer = timer
        // Explicit tracking mode keeps ticking inside an open NSMenu/submenu.
        RunLoop.main.add(timer, forMode: .common)
        RunLoop.main.add(timer, forMode: .eventTracking)
    }

    private func fetchStatus() {
        guard !polling else { return }
        polling = true
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8080/api/status")!)
        request.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            // Dispatch onto the modes used by both the ordinary and menu loops.
            RunLoop.main.perform(inModes: [.default, .eventTracking]) {
                guard let self = self else { return }
                self.polling = false
                guard error == nil, (response as? HTTPURLResponse)?.statusCode == 200,
                      let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let status = json["status"] as? String else {
                    self.isConnected = false
                    self.refreshPresentation()
                    return
                }
                self.isConnected = true
                self.currentStatus = status
                self.currentModel = json["current_model"] as? String ?? "尚未選擇模型"
                self.currentModelId = json["current_model_id"] as? String ?? ""
                self.idleTimeout = json["idle_timeout"] as? Int ?? 0
                self.idleDeadline = ProcessInfo.processInfo.systemUptime + Double(json["idle_remaining"] as? Int ?? 0)
                self.activeRequests = json["active_requests"] as? Int ?? 0
                self.autoSleepEnabled = json["auto_sleep_enabled"] as? Bool ?? true
                self.availableModels = json["models"] as? [[String: Any]] ?? []
                if !self.isMenuOpen { self.rebuildModels() }
                self.refreshPresentation()
            }
        }.resume()
    }

    private func refreshPresentation() {
        let running = currentStatus == "running"
        let starting = currentStatus == "starting"
        let remaining = max(0, Int(ceil(idleDeadline - ProcessInfo.processInfo.systemUptime)))
        modelsItem.title = currentModel
        modelsItem.toolTip = "點選切換模型"
        panel.status.stringValue = !isConnected ? "未連線" : starting ? "正在載入" : running ? "運行中" : "休眠待命"
        panel.status.textColor = isConnected && running ? .systemGreen : .secondaryLabelColor
        panel.progress.isHidden = true
        if !isConnected {
            panel.countdown.stringValue = "尚未連線"
            panel.detail.stringValue = "正在重試；請確認守護程式已啟動"
        } else if busy || starting {
            panel.countdown.stringValue = starting ? "載入中" : "處理中"
            panel.detail.stringValue = "操作完成後會自動更新"
        } else if !running {
            panel.countdown.stringValue = "休眠中"
            panel.detail.stringValue = "需要時自動喚醒，或按下啟動模型"
        } else if activeRequests > 0 {
            panel.countdown.stringValue = "處理中"
            panel.detail.stringValue = "目前有 \(activeRequests) 個請求，暫不休眠"
        } else if !autoSleepEnabled || idleTimeout <= 0 {
            panel.countdown.stringValue = "保持喚醒"
            panel.detail.stringValue = "模型常駐，隨時回應請求"
        } else {
            panel.countdown.stringValue = String(format: "%02d:%02d", remaining / 60, remaining % 60)
            panel.detail.stringValue = remaining == 0 ? "等待服務進入休眠" : "後自動休眠 · 新請求會重設倒數"
            panel.progress.isHidden = false
            panel.progress.doubleValue = min(1, Double(remaining) / Double(idleTimeout))
        }
        if let feedback = feedback { panel.detail.stringValue = feedback }
        primaryItem.title = busy ? "正在處理…" : starting ? "模型載入中…" : running ? "立即休眠" : "啟動模型"
        primaryItem.image = NSImage(systemSymbolName: running ? "moon" : "power", accessibilityDescription: nil)
        primaryItem.isEnabled = isConnected && !busy && !starting
        autoItem.title = idleTimeout > 0 ? "閒置 \(idleTimeout / 60) 分鐘後自動休眠" : "此模型保持常駐"
        autoItem.state = autoSleepEnabled && idleTimeout > 0 ? .on : .off
        autoItem.isEnabled = isConnected && !busy && idleTimeout > 0
        modelsItem.isEnabled = isConnected && !busy && !starting
        for item in modelsMenu.items {
            let selected = item.representedObject as? String == currentModelId
            item.state = selected ? .on : .off
            item.isEnabled = isConnected && !busy && !starting && !(selected && running) && item.action != nil
        }
        refreshItem.isHidden = isConnected
        quitItem.isEnabled = !busy
        updateIcon(status: isConnected ? currentStatus : "disconnected")
    }

    private func rebuildModels() {
        modelsMenu.removeAllItems()
        for model in availableModels {
            guard let name = model["name"] as? String, let id = model["id"] as? String else { continue }
            let item = NSMenuItem(title: name, action: #selector(modelSelected(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = id
            item.toolTip = "點選即載入 · \(String(describing: model["type"] ?? "local").uppercased())"
            modelsMenu.addItem(item)
        }
        if modelsMenu.items.isEmpty {
            let empty = NSMenuItem(title: "尚無可用模型", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            modelsMenu.addItem(empty)
        }
    }

    // Template artwork follows the system menu bar appearance; the state glyph
    // remains legible in monochrome and does not depend on color perception.
    private func guardianIcon(status: String) -> NSImage {
        let image = NSImage(size: NSSize(width: 28, height: 18), flipped: false) { _ in
            NSColor.black.setFill()
            let upper = NSBezierPath(roundedRect: NSRect(x: 1, y: 8, width: 13, height: 9), xRadius: 2, yRadius: 2)
            upper.fill()
            let tail = NSBezierPath()
            tail.move(to: NSPoint(x: 3, y: 9)); tail.line(to: NSPoint(x: 3, y: 5)); tail.line(to: NSPoint(x: 8, y: 9)); tail.close(); tail.fill()
            let lower = NSBezierPath(roundedRect: NSRect(x: 7, y: 1, width: 12, height: 6), xRadius: 2, yRadius: 2)
            lower.fill()
            let state = NSBezierPath()
            state.lineWidth = 1.5
            state.lineCapStyle = .round
            NSColor.black.setStroke()
            switch status {
            case "running":
                state.move(to: NSPoint(x: 22, y: 8)); state.line(to: NSPoint(x: 24, y: 6)); state.line(to: NSPoint(x: 27, y: 11)); state.stroke()
            case "starting":
                NSBezierPath(ovalIn: NSRect(x: 22, y: 7, width: 5, height: 5)).stroke()
            case "sleeping":
                state.move(to: NSPoint(x: 23, y: 6)); state.line(to: NSPoint(x: 23, y: 11)); state.move(to: NSPoint(x: 26, y: 6)); state.line(to: NSPoint(x: 26, y: 11)); state.stroke()
            default:
                state.move(to: NSPoint(x: 23, y: 6)); state.line(to: NSPoint(x: 27, y: 10)); state.move(to: NSPoint(x: 23, y: 10)); state.line(to: NSPoint(x: 27, y: 6)); state.stroke()
            }
            return true
        }
        image.isTemplate = true
        return image
    }

    private func updateIcon(status: String) {
        guard let button = statusItem.button else { return }
        button.title = ""
        button.image = guardianIcon(status: status)
        let labels = ["running": "運行就緒", "starting": "正在載入", "sleeping": "休眠待命", "disconnected": "尚未連線"]
        let label = "翻譯守護 · \(labels[status] ?? "狀態未知") · \(currentModel)"
        button.toolTip = label
        button.setAccessibilityLabel(label)
    }


    func menuWillOpen(_ menu: NSMenu) {
        rebuildModels()
        isMenuOpen = true
        refreshPresentation()
        fetchStatus()
    }
    func menuDidClose(_ menu: NSMenu) { isMenuOpen = false }

    private func perform(_ path: String, query: [URLQueryItem] = [], completion: (() -> Void)? = nil) {
        guard !busy else { return }
        busy = true; feedback = nil
        refreshPresentation()
        var components = URLComponents(string: "http://127.0.0.1:8080/api/" + path)!
        if !query.isEmpty { components.queryItems = query }
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.timeoutInterval = 180
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            RunLoop.main.perform(inModes: [.default, .eventTracking]) {
                guard let self = self else { return }
                self.busy = false
                let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                let status = json?["status"] as? String
                if error == nil, (response as? HTTPURLResponse)?.statusCode == 200, status == "ok" || status == "stopped" {
                    completion?()
                } else {
                    self.feedback = "操作未完成：" + (json?["message"] as? String ?? error?.localizedDescription ?? "請稍後重試")
                }
                self.refreshPresentation()
                self.fetchStatus()
            }
        }.resume()
    }
    @objc private func modelSelected(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        perform("switch", query: [URLQueryItem(name: "model", value: id)])
    }
    @objc private func toggleEngine() { perform(currentStatus == "running" ? "sleep" : "wake") }
    @objc private func toggleAutoSleep() { perform("toggle_auto_sleep") }
    @objc private func reconnect() { feedback = nil; fetchStatus() }
    @objc private func copyApiUrl() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString("http://127.0.0.1:8080/v1", forType: .string)
        feedback = "API 網址已複製"
        refreshPresentation()
    }
    @objc private func openWebDashboard() {
        NSWorkspace.shared.open(URL(string: "http://127.0.0.1:8080/status")!)
    }
    @objc private func quitApp() {
        let alert = NSAlert()
        alert.messageText = "結束翻譯守護？"
        alert.informativeText = "將停止模型與本機 API 服務。需要時可重新開啟翻譯守護 app。"
        alert.addButton(withTitle: "取消")
        alert.addButton(withTitle: "結束守護")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        if !isConnected { NSApp.terminate(nil); return }
        perform("stop") { NSApp.terminate(nil) }
    }
}

// 主程式入口
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = LLMMenuBarController()
app.run()
