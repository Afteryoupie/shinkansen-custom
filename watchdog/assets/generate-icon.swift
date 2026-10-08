// Resize the shared LLM watchdog identity into a macOS iconset.
// Redraw the master with generate_watchdog_icon.py; no separate artwork to drift.
import Cocoa
let output = URL(fileURLWithPath: CommandLine.arguments[1])
let master = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("guardian-1024.png")
guard let source = NSImage(contentsOf: master) else { fatalError("Missing LLM watchdog master icon") }
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
for size in [16,32,128,256,512] {
    for scale in [1,2] {
        let pixels = size * scale
        let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current?.imageInterpolation = .high
        source.draw(in: NSRect(x:0,y:0,width:pixels,height:pixels))
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
        try rep.representation(using:.png,properties:[:])!.write(to: output.appendingPathComponent(name))
    }
}
