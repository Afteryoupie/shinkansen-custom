import Cocoa
import Foundation

class LLMMenuBarController: NSObject, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var menu: NSMenu!
    private var timer: Timer?
    private var isMenuOpen = false
    
    // 狀態緩存
    private var currentStatus: String = "sleeping"
    private var currentModel: String = "未知"
    private var currentModelId: String = ""
    private var idleRemaining: Int = 0
    private var idleTimeout: Int = 0
    private var isTranslation: Bool = false
    private var autoSleepEnabled: Bool = true
    private var availableModels: [[String: Any]] = []
    private var isConnected: Bool = false
    
    override init() {
        super.init()
        setupStatusItem()
        setupMenu()
        startPolling()
        fetchStatus()
    }
    
    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "⚪"
            button.toolTip = "LLM 本地服務中控台"
        }
    }
    
    private func setupMenu() {
        menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        renderMenu()
    }
    
    private func startPolling() {
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.fetchStatus()
        }
    }
    
    // ── HTTP API 通訊 ─────────────────────────────────────────
    
    private func fetchStatus() {
        guard let url = URL(string: "http://127.0.0.1:8080/api/status") else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.5
        
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }
            
            DispatchQueue.main.async {
                if error != nil {
                    self.isConnected = false
                    self.updateIcon(status: "disconnected")
                    if !self.isMenuOpen { self.renderMenu() }
                    return
                }
                
                guard let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] else {
                    self.isConnected = false
                    self.updateIcon(status: "disconnected")
                    if !self.isMenuOpen { self.renderMenu() }
                    return
                }
                
                self.isConnected = true
                self.currentStatus = json["status"] as? String ?? "sleeping"
                self.currentModel = json["current_model"] as? String ?? ""
                self.currentModelId = json["current_model_id"] as? String ?? ""
                self.isTranslation = json["is_translation"] as? Bool ?? false
                self.idleTimeout = json["idle_timeout"] as? Int ?? 0
                self.idleRemaining = json["idle_remaining"] as? Int ?? 0
                self.autoSleepEnabled = json["auto_sleep_enabled"] as? Bool ?? true
                self.availableModels = json["models"] as? [[String: Any]] ?? []
                
                self.updateIcon(status: self.currentStatus)
                if !self.isMenuOpen {
                    self.renderMenu()
                }
            }
        }.resume()
    }
    
    private func updateIcon(status: String) {
        guard let button = statusItem.button else { return }
        switch status {
        case "running":
            button.title = "🟢"
        case "starting":
            button.title = "🟡"
        case "sleeping":
            button.title = "⚪"
        default:
            button.title = "⚪"
        }
    }
    
    // ── 建立選單 ──────────────────────────────────────────────
    
    private func renderMenu() {
        menu.removeAllItems()
        
        if !isConnected {
            let item = NSMenuItem(title: "⚠️ 守護進程未連線 (:8080)", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
            menu.addItem(NSMenuItem.separator())
            menu.addItem(NSMenuItem(title: "🛑 退出", action: #selector(quitApp), keyEquivalent: "q"))
            return
        }
        
        // 1. 狀態標題
        var statusText = "⚪ 待命中 (0% 顯存佔用)"
        if currentStatus == "running" {
            statusText = "🟢 運行就緒"
        } else if currentStatus == "starting" {
            statusText = "🟡 模型啟動載入中..."
        }
        let statusItem = NSMenuItem(title: statusText, action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        menu.addItem(statusItem)
        
        // 2. 當前模型
        let modelItem = NSMenuItem(title: "模型: \(currentModel)", action: nil, keyEquivalent: "")
        modelItem.isEnabled = false
        menu.addItem(modelItem)
        
        // 3. 休眠倒數 / 常駐模式
        var modeText = ""
        if currentStatus == "running" {
            if autoSleepEnabled && idleTimeout > 0 {
                modeText = "⏱ 閒置倒數: \(idleRemaining) 秒 (\(max(1, idleTimeout / 60))分休眠)"
            } else {
                modeText = "⚡ 模式: 常駐不休眠 (隨時響應)"
            }
        } else {
            modeText = "💤 顯存狀態: 已釋放 (0 MB)"
        }
        let modeItem = NSMenuItem(title: modeText, action: nil, keyEquivalent: "")
        modeItem.isEnabled = false
        menu.addItem(modeItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 4. 切換模型 (Submenu)
        let switchSubmenu = NSMenu()
        for m in availableModels {
            guard let name = m["name"] as? String,
                  let mId = m["id"] as? String,
                  let mType = m["type"] as? String else { continue }
            
            let isCurrent = (mId == currentModelId || name == currentModel)
            let mTimeout = m["idle_timeout"] as? Int ?? 180
            let tag = mTimeout > 0 ? "[\(max(1, mTimeout / 60))m休眠]" : "[常駐通用]"
            let title = "[\(mType.uppercased())] \(name)  \(tag)"
            
            let subItem = NSMenuItem(title: title, action: #selector(modelSelected(_:)), keyEquivalent: "")
            subItem.target = self
            subItem.representedObject = mId
            subItem.state = isCurrent ? .on : .off
            switchSubmenu.addItem(subItem)
        }
        
        let switchItem = NSMenuItem(title: "🔄 切換模型 (點選即載入)", action: nil, keyEquivalent: "")
        switchItem.submenu = switchSubmenu
        menu.addItem(switchItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 5. 操作控制按鈕
        if currentStatus == "running" {
            let sleepItem = NSMenuItem(title: "💤 立即休眠 (釋放顯存)", action: #selector(sleepLLM), keyEquivalent: "")
            sleepItem.target = self
            menu.addItem(sleepItem)
        } else {
            let wakeItem = NSMenuItem(title: "⚡ 立即啟動模型", action: #selector(wakeLLM), keyEquivalent: "")
            wakeItem.target = self
            menu.addItem(wakeItem)
        }
        
        let autoSleepTitle = autoSleepEnabled ? "⏱️ 自動休眠: 開啟 (\(max(1, idleTimeout / 60))m)" : "♾️ 自動休眠: 關閉 (常駐)"
        let autoSleepItem = NSMenuItem(title: autoSleepTitle, action: #selector(toggleAutoSleep), keyEquivalent: "")
        autoSleepItem.target = self
        menu.addItem(autoSleepItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 6. 快捷工具
        let copyItem = NSMenuItem(title: "📋 複製 API 網址 (http://127.0.0.1:8080/v1)", action: #selector(copyApiUrl), keyEquivalent: "c")
        copyItem.target = self
        menu.addItem(copyItem)
        
        let webItem = NSMenuItem(title: "🌐 開啟控制儀表板", action: #selector(openWebDashboard), keyEquivalent: "d")
        webItem.target = self
        menu.addItem(webItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 7. 退出
        let quitItem = NSMenuItem(title: "🛑 退出守護與關閉服務", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
    }
    
    // ── NSMenuDelegate ───────────────────────────────────────
    
    func menuWillOpen(_ menu: NSMenu) {
        isMenuOpen = true
        renderMenu()
    }
    
    func menuDidClose(_ menu: NSMenu) {
        isMenuOpen = false
    }
    
    // ── Action Handlers ──────────────────────────────────────
    
    @objc private func modelSelected(_ sender: NSMenuItem) {
        guard let modelId = sender.representedObject as? String else { return }
        guard let escaped = modelId.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else { return }
        guard let url = URL(string: "http://127.0.0.1:8080/api/switch?model=\(escaped)") else { return }
        
        updateIcon(status: "starting")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self?.fetchStatus()
            }
        }.resume()
    }
    
    @objc private func wakeLLM() {
        guard let url = URL(string: "http://127.0.0.1:8080/api/wake") else { return }
        updateIcon(status: "starting")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self?.fetchStatus()
            }
        }.resume()
    }
    
    @objc private func sleepLLM() {
        guard let url = URL(string: "http://127.0.0.1:8080/api/sleep") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                self?.fetchStatus()
            }
        }.resume()
    }
    
    @objc private func toggleAutoSleep() {
        guard let url = URL(string: "http://127.0.0.1:8080/api/toggle_auto_sleep") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                self?.fetchStatus()
            }
        }.resume()
    }
    
    @objc private func copyApiUrl() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString("http://127.0.0.1:8080/v1", forType: .string)
    }
    
    @objc private func openWebDashboard() {
        if let url = URL(string: "http://127.0.0.1:8080/status") {
            NSWorkspace.shared.open(url)
        }
    }
    
    @objc private func quitApp() {
        // 先通知 watchdog 關閉
        if let url = URL(string: "http://127.0.0.1:8080/api/stop") {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            URLSession.shared.dataTask(with: req).resume()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            NSApplication.shared.terminate(nil)
        }
    }
}

// 主程式入口
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = LLMMenuBarController()
app.run()
