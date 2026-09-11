# Multipart sharing comparison

This is an isolated experiment supporting [architectural discussion #1020](https://github.com/react-native-community/discussions-and-proposals/issues/1020). It is not wired into React Native's production build. It compares the existing native implementation, a native header-scanning optimization, the current KMP implementation, and a shared C++ implementation with the same responsibility boundary.

## Questions defined before measurement

1. Do all implementations preserve the actual platform reader's completion, body, header, error, and final-progress behavior across fragmented input and malformed/Unicode headers?
2. What does sharing framing and header decisions cost on the host JVM and Apple simulator when the native buffer search, I/O, payload ownership, and callback paths remain equivalent?
3. Does KMP improve on an optimized native control or a reasonably implemented shared C++ control, rather than only an unoptimized original?
4. What additional integration and maintenance obligations exist for each approach, including costs outside a timing sample?

Correctness is a prerequisite for interpreting a timing result. Differences must be fixed or reported before presenting comparative performance. A KMP-favorable result is not required for this experiment to succeed.

## Scope and controls

The production input is frozen at `fec597ba9fb51628b04206fb215ff9156084f535`, the top of the native fork stack. The corrected native Android implementation is selected from `b150c6f7dd718c5b4a320fdecb06f2049b87b5c0`; the Apple source includes its existing native fallback. Experimental readers are generated from these real adapters using checked transformations. No production adapter is edited.

All variants retain their platform's buffer searches and sizes, input streams, body-draining behavior, header trimming/case rules, and progress policy. The C++ core shares delimiter state and header ranges; native adapters retain strings and body ownership. Android exercises an actual JNI path. Apple can call the same C++ core directly from Objective-C++. Avoiding JNI is a possible Kotlin convenience on Android, not proof that KMP has lower total integration cost.

The optimized native control is a specific header-scanning improvement. It is not a claim that the original native implementation has been exhaustively optimized. The C++ variant is a comparison implementation, not an approved React Native binding/distribution design.

The representation differs deliberately: the C++ header scanner returns UTF-16 ranges, while the existing KMP API returns header objects and strings. The optimized Android controls can trim before constructing substrings; the original KMP adapter trims returned strings. These are comparisons of concrete implementations and their interfaces, not an isolated language/compiler speed contest. An optimized KMP range interface could be evaluated separately before attributing a difference to an unavoidable property of Kotlin.

The call sites principally support JavaScript bundle loading: Android's `devsupport/BundleDownloader` consumes multipart progress messages and the final bundle; Apple's non-file URL path in `RCTJavaScriptLoader` uses `RCTMultipartDataTask`. Local file bundles take a separate Apple path. These parser measurements do not demonstrate faster rendering, network throughput, Metro bundling, or application startup.

## Measurement discipline

- Generate deterministic input before the measured parse; include small bodies, 2 MiB and 20 MiB bodies, and a progress-message sequence followed by a bundle.
- Establish exact callback/body/header parity before timing. Test fragmented input, incomplete bodies and delimiters, near matches, and each platform's Unicode/header policies separately.
- Warm each variant, alternate or deterministically shuffle execution order, retain all raw samples, and repeat in at least three fresh processes. Report per-process results and spread rather than treating samples from one warmed process as independent deployments.
- Serialize platform timing runs. Build and correctness-test work may run in parallel; final measurements should run without other task-owned builds or benchmark processes competing for resources.
- Measure Release code on Apple. JVM results remain host-JVM results unless an Android ART run is explicitly identified. Simulator results remain simulator results; physical-device execution is not inferred.
- JVM thread-allocation counters exclude native C++ allocations and whole-process memory. They must not be used to claim a total-memory advantage over C++.
- Binary comparisons need separate executables so the native/C++ baselines do not accidentally include the Kotlin runtime. If a shared KMP archive contains the other experiments, disclose that scope; do not call its cost multipart-only.
- Build timing must identify warm dependencies, compiler daemons, cache settings, and whether it measures a component or a full application. A successful cached build is not a cold-CI benchmark.

## Decision limits

Passing this experiment can support a narrower claim about parity, a measured workload, or the cost of one shared boundary. It cannot establish that KMP is React Native's future or justify core adoption on its own. C++ also centralizes an implementation and tests, so code deduplication is not a KMP-exclusive benefit.

A credible adoption proposal still needs an agreed problem worth solving, representative physical-device/application evidence, a supported release/distribution contract, internal build validation, a toolchain owner, and a rollback path. A library or fork that demonstrates value without imposing a new core dependency is a possible next stage if maintainers consider further evaluation useful.
