// secondbrain-auth — biometric gate for destructive operations.
//
// Usage: `secondbrain-auth "reason shown to the user"`
// Exit 0 on success, 1 on auth failure, 2 on policy unavailable.
//
// Used by the MCP/HTTP `memory.forget` flow when
// SECONDBRAIN_REQUIRE_BIOMETRIC=1. Off by default — opt-in for paranoid
// users who want every cascading delete gated by Touch ID / Apple Watch.

import Foundation
import LocalAuthentication

let reason = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : "Confirm destructive memory operation"

let ctx = LAContext()
var error: NSError?

guard ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
    let msg = error?.localizedDescription ?? "biometrics unavailable"
    FileHandle.standardError.write("\(msg)\n".data(using: .utf8) ?? Data())
    exit(2)
}

let semaphore = DispatchSemaphore(value: 0)
var success = false
var authError: Error?

ctx.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason) { ok, err in
    success = ok
    authError = err
    semaphore.signal()
}

semaphore.wait()

if !success {
    let msg = authError?.localizedDescription ?? "auth denied"
    FileHandle.standardError.write("\(msg)\n".data(using: .utf8) ?? Data())
    exit(1)
}

exit(0)
