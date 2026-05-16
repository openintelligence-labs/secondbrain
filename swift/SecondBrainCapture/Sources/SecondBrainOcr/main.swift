// SecondBrain Apple Vision OCR sidecar.
//
// Reads an image path from argv[1], emits the extracted text on stdout. Used
// only when the AX-tree path produced no text. Apple Vision RecognizeTextRequest
// is ANE-accelerated and ships with macOS.
//
// Usage:
//   secondbrain-ocr <path-to-image>     # one-shot
//   secondbrain-ocr --version
//
// Output (stdout):
//   {"type":"ocr","text":"...","confidence_avg":0.93,"lang":"en"}
//   {"type":"error","msg":"..."}

import Foundation
import Vision
import AppKit

func emit(_ event: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: event, options: [.fragmentsAllowed]),
       let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

let args = CommandLine.arguments
if args.count < 2 || args[1] == "--help" {
    emit(["type": "error", "msg": "usage: secondbrain-ocr <path-to-image>"])
    exit(2)
}
if args[1] == "--version" {
    emit(["type": "version", "vision": "macos26"])
    exit(0)
}

let path = args[1]
guard let nsimage = NSImage(contentsOfFile: path),
      let cgImage = nsimage.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    emit(["type": "error", "msg": "cannot read image: \(path)"])
    exit(3)
}

let request = VNRecognizeTextRequest { req, err in
    if let err = err {
        emit(["type": "error", "msg": "vision: \(err.localizedDescription)"])
        exit(4)
    }
    var pieces: [String] = []
    var confs: [Float] = []
    if let observations = req.results as? [VNRecognizedTextObservation] {
        for obs in observations {
            if let candidate = obs.topCandidates(1).first {
                pieces.append(candidate.string)
                confs.append(candidate.confidence)
            }
        }
    }
    let avg: Double = confs.isEmpty ? 0.0 : Double(confs.reduce(0, +)) / Double(confs.count)
    emit([
        "type": "ocr",
        "text": pieces.joined(separator: "\n"),
        "confidence_avg": avg,
        "n_lines": pieces.count,
    ])
    exit(0)
}
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    emit(["type": "error", "msg": "perform: \(error.localizedDescription)"])
    exit(5)
}

dispatchMain()
