import AppKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fputs("Usage: swift apply_app_icon.swift /path/to/icon.png /path/to/App.app\n", stderr)
    exit(1)
}

let iconPath = arguments[1]
let appPath = arguments[2]

if iconPath == "--clear" {
    guard NSWorkspace.shared.setIcon(nil, forFile: appPath, options: []) else {
        fputs("Could not clear registered application icon\n", stderr)
        exit(1)
    }
    exit(0)
}

guard let image = NSImage(contentsOfFile: iconPath) else {
    fputs("Could not read application icon\n", stderr)
    exit(1)
}

guard NSWorkspace.shared.setIcon(image, forFile: appPath, options: []) else {
    fputs("Could not register application icon\n", stderr)
    exit(1)
}
