// SecondBrain Swift sidecar.
//
// Purpose: stream ScreenCaptureKit frames as NDJSON over stdout. The Python
// daemon (`secondbrain.daemon`) spawns this binary, reads NDJSON line-by-line,
// and feeds each frame into the cascade.
//
// NDJSON event types:
//   {"type":"ready", "displays":[{"id":..., "width":..., "height":...}]}
//   {"type":"frame", "ts":..., "monitor_index":..., "dirty_rect_fraction":...,
//    "width":..., "height":..., "png_b64":"..."}    // when --emit-png
//   {"type":"frame", "ts":..., "monitor_index":..., "dirty_rect_fraction":...,
//    "width":..., "height":..., "frame_path":"..."} // when --hevc-dir is set
//   {"type":"error", "msg":"..."}
//
// Pixel transport defaults:
//   - With `--emit-png`: small base64 PNGs inline (good for tests, ~20KB/frame).
//   - With `--hevc-dir <DIR>`: writes each persisted frame as a HEIC file via
//     VideoToolbox and emits the path in NDJSON.
//
// CLI:
//   secondbrain-capture [--display N]
//                       [--fps N]
//                       [--emit-png]
//                       [--hevc-dir <DIR>]
//                       [--max-frames N]
//                       [--use-picker]   # SCContentSharingPicker

import Foundation
import ScreenCaptureKit
import CoreImage
import CoreVideo
import CoreMedia
import AVFoundation
import AppKit
import ImageIO
import UniformTypeIdentifiers

// MARK: - NDJSON I/O

func emit(_ event: [String: Any]) {
    var dict = event
    if dict["ts"] == nil {
        dict["ts"] = Date().timeIntervalSince1970
    }
    guard let data = try? JSONSerialization.data(withJSONObject: dict, options: [.fragmentsAllowed]) else {
        return
    }
    if let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

func emitError(_ msg: String) {
    emit(["type": "error", "msg": msg])
}

// MARK: - CLI parsing

struct CLI {
    var displayIndex: Int = 0
    var fps: Int = 1
    var emitPNG: Bool = false
    var hevcDir: URL? = nil
    var maxFrames: Int = -1
    var usePicker: Bool = false
}

func parseArgs() -> CLI {
    var cli = CLI()
    let args = CommandLine.arguments.dropFirst()
    var it = args.makeIterator()
    while let a = it.next() {
        switch a {
        case "--display":
            if let v = it.next(), let n = Int(v) { cli.displayIndex = n }
        case "--fps":
            if let v = it.next(), let n = Int(v) { cli.fps = max(1, n) }
        case "--emit-png":
            cli.emitPNG = true
        case "--hevc-dir":
            if let v = it.next() { cli.hevcDir = URL(fileURLWithPath: v) }
        case "--max-frames":
            if let v = it.next(), let n = Int(v) { cli.maxFrames = n }
        case "--use-picker":
            cli.usePicker = true
        default:
            emitError("unknown arg: \(a)")
        }
    }
    return cli
}

// MARK: - Frame writer (PNG inline or HEIC on disk)

@MainActor
func encodeAsPNGBase64(_ buffer: CVPixelBuffer) -> (String, Int, Int)? {
    let ci = CIImage(cvPixelBuffer: buffer)
    let ctx = CIContext()
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let cgImage = ctx.createCGImage(ci, from: ci.extent, format: .RGBA8, colorSpace: cs) else {
        return nil
    }
    let mutableData = NSMutableData()
    guard let dest = CGImageDestinationCreateWithData(mutableData, UTType.png.identifier as CFString, 1, nil) else {
        return nil
    }
    CGImageDestinationAddImage(dest, cgImage, nil)
    if !CGImageDestinationFinalize(dest) {
        return nil
    }
    let b64 = (mutableData as Data).base64EncodedString()
    return (b64, cgImage.width, cgImage.height)
}

@MainActor
func encodeAsHEIC(_ buffer: CVPixelBuffer, into dir: URL, name: String) -> URL? {
    // VideoToolbox HEIC via CGImageDestination with HEIC type — patent-safe HW path.
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let ci = CIImage(cvPixelBuffer: buffer)
    let ctx = CIContext()
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let cgImage = ctx.createCGImage(ci, from: ci.extent, format: .RGBA8, colorSpace: cs) else {
        return nil
    }
    let url = dir.appendingPathComponent(name + ".heic")
    guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.heic.identifier as CFString, 1, nil) else {
        return nil
    }
    CGImageDestinationAddImage(dest, cgImage, [kCGImageDestinationLossyCompressionQuality: 0.7] as CFDictionary)
    if !CGImageDestinationFinalize(dest) {
        return nil
    }
    return url
}

// MARK: - Stream output handler

final class StreamOutput: NSObject, SCStreamOutput {
    let cli: CLI
    var framesEmitted: Int = 0
    var lastTimestamp: TimeInterval = 0
    var minIntervalSeconds: Double { 1.0 / Double(cli.fps) }

    init(cli: CLI) {
        self.cli = cli
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sampleBuffer.isValid else { return }

        let now = Date().timeIntervalSince1970
        if now - lastTimestamp < minIntervalSeconds { return }
        lastTimestamp = now

        guard let attachmentsArray = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let attachments = attachmentsArray.first,
              let statusRaw = attachments[.status] as? Int,
              let status = SCFrameStatus(rawValue: statusRaw),
              status == .complete
        else {
            return
        }

        // Dirty rectangles (SCStreamFrameInfo.dirtyRects on Sonoma+)
        let dirtyArea: Double
        if let rectArray = attachments[.dirtyRects] as? [[String: Any]] {
            var area: Double = 0
            for r in rectArray {
                if let w = r["Width"] as? Double, let h = r["Height"] as? Double {
                    area += w * h
                }
            }
            dirtyArea = area
        } else {
            dirtyArea = -1
        }

        guard let pixelBuffer = sampleBuffer.imageBuffer else { return }
        let totalArea = Double(CVPixelBufferGetWidth(pixelBuffer) * CVPixelBufferGetHeight(pixelBuffer))
        let dirtyFraction = totalArea > 0 && dirtyArea > 0 ? dirtyArea / totalArea : -1.0

        var event: [String: Any] = [
            "type": "frame",
            "ts": now,
            "monitor_index": cli.displayIndex,
            "dirty_rect_fraction": dirtyFraction,
            "width": CVPixelBufferGetWidth(pixelBuffer),
            "height": CVPixelBufferGetHeight(pixelBuffer),
        ]

        if cli.emitPNG {
            if let (b64, w, h) = encodeAsPNGBase64Sync(pixelBuffer) {
                event["png_b64"] = b64
                event["width"] = w
                event["height"] = h
            }
        } else if let dir = cli.hevcDir {
            let name = String(format: "%.6f", now)
            if let url = encodeAsHEICSync(pixelBuffer, into: dir, name: name) {
                event["frame_path"] = url.path
            }
        }

        emit(event)
        framesEmitted += 1
        if cli.maxFrames > 0 && framesEmitted >= cli.maxFrames {
            exit(0)
        }
    }
}

// Synchronous wrappers — main thread is the SCStream output queue, no async needed.
func encodeAsPNGBase64Sync(_ buffer: CVPixelBuffer) -> (String, Int, Int)? {
    let ci = CIImage(cvPixelBuffer: buffer)
    let ctx = CIContext()
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let cgImage = ctx.createCGImage(ci, from: ci.extent, format: .RGBA8, colorSpace: cs) else {
        return nil
    }
    let mutableData = NSMutableData()
    guard let dest = CGImageDestinationCreateWithData(mutableData, UTType.png.identifier as CFString, 1, nil) else {
        return nil
    }
    CGImageDestinationAddImage(dest, cgImage, nil)
    if !CGImageDestinationFinalize(dest) { return nil }
    return ((mutableData as Data).base64EncodedString(), cgImage.width, cgImage.height)
}

func encodeAsHEICSync(_ buffer: CVPixelBuffer, into dir: URL, name: String) -> URL? {
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let ci = CIImage(cvPixelBuffer: buffer)
    let ctx = CIContext()
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let cgImage = ctx.createCGImage(ci, from: ci.extent, format: .RGBA8, colorSpace: cs) else { return nil }
    let url = dir.appendingPathComponent(name + ".heic")
    guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.heic.identifier as CFString, 1, nil) else { return nil }
    CGImageDestinationAddImage(dest, cgImage, [kCGImageDestinationLossyCompressionQuality: 0.7] as CFDictionary)
    if !CGImageDestinationFinalize(dest) { return nil }
    return url
}

// MARK: - Main: discover content + start stream

let cli = parseArgs()

let semaphore = DispatchSemaphore(value: 0)
var stream: SCStream?
var output: StreamOutput?

Task {
    do {
        let content = try await SCShareableContent.current
        guard !content.displays.isEmpty else {
            emitError("no displays available — accept Screen Recording permission and retry")
            exit(2)
        }
        let displayIdx = max(0, min(cli.displayIndex, content.displays.count - 1))
        let display = content.displays[displayIdx]

        emit([
            "type": "ready",
            "displays": content.displays.map { d -> [String: Any] in
                ["id": d.displayID, "width": d.width, "height": d.height]
            },
        ])

        // Filter: capture the chosen display, exclude SecondBrain itself if running.
        let excluded = content.applications.filter { $0.bundleIdentifier == Bundle.main.bundleIdentifier }
        let filter = SCContentFilter(display: display, excludingApplications: excluded, exceptingWindows: [])

        let config = SCStreamConfiguration()
        config.width = display.width
        config.height = display.height
        config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(cli.fps))
        config.queueDepth = 5
        config.showsCursor = true
        // Request dirtyRects metadata.
        config.capturesAudio = false

        let s = SCStream(filter: filter, configuration: config, delegate: nil)
        let o = StreamOutput(cli: cli)
        try s.addStreamOutput(o, type: .screen, sampleHandlerQueue: .main)
        try await s.startCapture()
        stream = s
        output = o
    } catch {
        emitError("setup failed: \(error.localizedDescription)")
        exit(3)
    }
}

// Block forever until --max-frames triggers exit(0) inside output.
signal(SIGINT) { _ in
    Task {
        try? await stream?.stopCapture()
        exit(0)
    }
}
signal(SIGTERM) { _ in
    Task {
        try? await stream?.stopCapture()
        exit(0)
    }
}

dispatchMain()
