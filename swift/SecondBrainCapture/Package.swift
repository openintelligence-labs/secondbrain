// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecondBrainCapture",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "secondbrain-capture", targets: ["SecondBrainCapture"]),
        .executable(name: "secondbrain-ocr", targets: ["SecondBrainOcr"]),
        .executable(name: "secondbrain-auth", targets: ["SecondBrainAuth"]),
    ],
    targets: [
        .executableTarget(
            name: "SecondBrainCapture",
            path: "Sources/SecondBrainCapture"
        ),
        .executableTarget(
            name: "SecondBrainOcr",
            path: "Sources/SecondBrainOcr"
        ),
        .executableTarget(
            name: "SecondBrainAuth",
            path: "Sources/SecondBrainAuth"
        ),
    ]
)
