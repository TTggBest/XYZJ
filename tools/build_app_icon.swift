import AppKit
import CoreGraphics
import Foundation

let args = CommandLine.arguments
guard args.count >= 2 else {
    fputs("Usage: swift build_app_icon.swift /path/to/output.png\n", stderr)
    exit(1)
}

let outputURL = URL(fileURLWithPath: args[1])
let size = CGSize(width: 1024, height: 1024)
let image = NSImage(size: size)

func roundedRect(_ rect: CGRect, radius: CGFloat) -> NSBezierPath {
    return NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
}

func linearGradient(_ colors: [NSColor], angle: CGFloat = 90) -> NSGradient {
    return NSGradient(colors: colors) ?? NSGradient(starting: colors.first ?? .black, ending: colors.last ?? .black)!
}

image.lockFocus()
guard let context = NSGraphicsContext.current?.cgContext else {
    fputs("Could not create graphics context\n", stderr)
    exit(1)
}

context.setShouldAntialias(true)
context.setAllowsAntialiasing(true)

let canvas = CGRect(origin: .zero, size: size)
NSColor.clear.setFill()
canvas.fill()

let outer = canvas.insetBy(dx: 58, dy: 58)
let outerPath = roundedRect(outer, radius: 206)
linearGradient([
    NSColor(calibratedRed: 0.03, green: 0.18, blue: 0.15, alpha: 1),
    NSColor(calibratedRed: 0.08, green: 0.47, blue: 0.39, alpha: 1),
    NSColor(calibratedRed: 0.02, green: 0.25, blue: 0.22, alpha: 1),
]).draw(in: outerPath, angle: 120)

NSColor(calibratedWhite: 0, alpha: 0.22).setFill()
roundedRect(outer.offsetBy(dx: 0, dy: -18).insetBy(dx: 18, dy: 18), radius: 184).fill()

let inner = outer.insetBy(dx: 76, dy: 76)
let innerPath = roundedRect(inner, radius: 142)
NSColor(calibratedRed: 0.92, green: 0.98, blue: 0.94, alpha: 0.96).setFill()
innerPath.fill()

let markRect = CGRect(x: 238, y: 252, width: 436, height: 462)
let font = NSFont(name: "STHeitiSC-Medium", size: 315) ?? NSFont.boldSystemFont(ofSize: 315)
let paragraph = NSMutableParagraphStyle()
paragraph.alignment = .center
let textAttributes: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor(calibratedRed: 0.02, green: 0.21, blue: 0.18, alpha: 1),
    .paragraphStyle: paragraph,
    .kern: -12,
]
("短" as NSString).draw(in: markRect, withAttributes: textAttributes)

let play = NSBezierPath()
play.move(to: CGPoint(x: 646, y: 390))
play.line(to: CGPoint(x: 646, y: 622))
play.line(to: CGPoint(x: 826, y: 506))
play.close()
NSColor(calibratedRed: 0.96, green: 0.34, blue: 0.20, alpha: 1).setFill()
play.fill()

let lineColor = NSColor(calibratedRed: 0.02, green: 0.21, blue: 0.18, alpha: 0.72)
lineColor.setStroke()
context.setLineWidth(22)
context.setLineCap(.round)
let path = NSBezierPath()
path.move(to: CGPoint(x: 300, y: 226))
path.line(to: CGPoint(x: 300, y: 172))
path.line(to: CGPoint(x: 724, y: 172))
path.line(to: CGPoint(x: 724, y: 226))
path.stroke()

for point in [CGPoint(x: 300, y: 172), CGPoint(x: 512, y: 172), CGPoint(x: 724, y: 172)] {
    let circle = CGRect(x: point.x - 25, y: point.y - 25, width: 50, height: 50)
    NSColor(calibratedRed: 0.96, green: 0.34, blue: 0.20, alpha: 1).setFill()
    NSBezierPath(ovalIn: circle).fill()
    NSColor(calibratedWhite: 1, alpha: 0.72).setStroke()
    NSBezierPath(ovalIn: circle.insetBy(dx: 8, dy: 8)).stroke()
}

let shine = roundedRect(CGRect(x: 170, y: 674, width: 660, height: 92), radius: 46)
linearGradient([
    NSColor(calibratedWhite: 1, alpha: 0.20),
    NSColor(calibratedWhite: 1, alpha: 0.02),
]).draw(in: shine, angle: 0)

image.unlockFocus()

guard let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Could not render PNG\n", stderr)
    exit(1)
}

try png.write(to: outputURL)
print(outputURL.path)
