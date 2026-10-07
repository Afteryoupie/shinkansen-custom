// Run: swift generate-icon.swift <output.iconset>
// Native vector source; no external packages required.
import Cocoa
let output = CommandLine.arguments[1]
try FileManager.default.createDirectory(atPath: output, withIntermediateDirectories: true)
func polygon(_ points: [(CGFloat, CGFloat)]) {
    let path = NSBezierPath(); path.move(to: NSPoint(x: points[0].0, y: points[0].1))
    for p in points.dropFirst() { path.line(to: NSPoint(x:p.0,y:p.1)) }; path.close(); path.fill()
}
for size in [16,32,128,256,512] {
    for scale in [1,2] {
        let pixels=size*scale
        let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:rep)
        let transform=NSAffineTransform(); transform.scale(by:CGFloat(pixels)/1024); transform.concat()
        NSColor(calibratedRed:0.75,green:0.26,blue:0.12,alpha:1).setFill()
        NSBezierPath(roundedRect:NSRect(x:64,y:64,width:896,height:896),xRadius:202,yRadius:202).fill()
        NSColor(calibratedRed:1,green:0.97,blue:0.89,alpha:1).setFill()
        NSBezierPath(roundedRect:NSRect(x:236,y:478,width:482,height:302),xRadius:75,yRadius:75).fill()
        polygon([(284,516),(284,364),(460,516)])
        NSBezierPath(roundedRect:NSRect(x:326,y:244,width:462,height:166),xRadius:55,yRadius:55).fill()
        polygon([(650,376),(740,474),(740,376)])
        NSGraphicsContext.restoreGraphicsState()
        let name="icon_\(size)x\(size)\(scale==2 ? "@2x" : "").png"
        try rep.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:output).appendingPathComponent(name))
    }
}
