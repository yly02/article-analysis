import Foundation
import ImageIO
import Vision

struct OCRLine: Codable {
    let text: String
    let confidence: Float
}

struct OCRResult: Codable {
    let text: String
    let confidence: Float
    let engine: String
    let lines: [OCRLine]
}

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("usage: chart_ocr.swift IMAGE_PATH\n".utf8))
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    FileHandle.standardError.write(Data("cannot decode image\n".utf8))
    exit(3)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: image, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("Vision OCR failed: \(error)\n".utf8))
    exit(4)
}

let observations = request.results ?? []
let lines = observations.compactMap { observation -> OCRLine? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    return OCRLine(text: candidate.string, confidence: candidate.confidence)
}
let confidence = lines.isEmpty ? 0 : lines.reduce(0) { $0 + $1.confidence } / Float(lines.count)
let result = OCRResult(
    text: lines.map(\.text).joined(separator: "\n"),
    confidence: confidence,
    engine: "apple-vision",
    lines: lines
)
let encoder = JSONEncoder()
let data = try encoder.encode(result)
FileHandle.standardOutput.write(data)
