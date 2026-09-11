# What would make a KMP proposal more persuasive?

The case should start with a valuable problem and a measured advantage, not a prediction about which language is the future. The maintainer's [discussion-first direction](https://github.com/react/react-native/pull/58472#issuecomment-5632212313) and React Native's existing C++/JavaScript strategy are the starting constraints. This experiment supplies a missing comparison; it does not change that direction.

## What is specific to Kotlin, and what is not?

Both KMP and C++ can centralize framing decisions and shared tests. Deduplication, a single bug fix, and cross-platform fixtures are therefore not exclusive arguments for KMP. The current native implementations also need different buffering, progress, string, and header-map policies, which neither shared core removes.

KMP offers direct reuse of Kotlin source and libraries on Android, without writing a JNI adapter for each utility. For a larger existing Kotlin subsystem, the avoided rewrite and developer workflow may be meaningful. That advantage must be demonstrated on a real subsystem and compared with React Native's existing C++ integration machinery. The 79-line multipart common source alone is a weak proxy for such a benefit.

There is a concrete ecosystem reason to investigate that library-level route: [Google officially supports KMP for sharing Android/iOS business logic](https://developer.android.com/kotlin/multiplatform) and provides multiplatform Jetpack libraries including Room and DataStore. Reusing an established Kotlin library, with coarse operations that amortize interop, is a more specific hypothesis than replacing tiny native calculations. This does not establish a benefit for React Native core or require adopting Compose.

C++ has a direct Objective-C++ path on Apple and matches the core's established shared-code strategy. An Android JNI adapter adds implementation work in this particular Kotlin reader, but a standalone experiment's JNI wrapper is not an estimate of every possible production C++ binding. Kotlin/Native adds runtime ownership, toolchain, packaging, and upgrade obligations that an algorithm line count misses.

For these readers, a JavaScript alternative also needs a bootstrap/availability design because they participate in loading the JavaScript bundle. A Node-only algorithm timing would not resolve that integration question, so no such timing is presented as a production JS alternative here.

## Concrete downstream requirements

| Area | Current experiment | Evidence needed before a core adoption proposal |
| --- | --- | --- |
| Real user benefit | Multipart primarily handles development/remote bundle loading and progress messages. | A correctness or maintenance problem worth the ecosystem cost; representative bundle loading or another agreed workload. |
| Android consumer | Common JVM classes are embedded in the existing ReactAndroid AAR, and source builds invoke an included Gradle build. | Version/support policy, reproducible artifact provenance, shrinking compatibility, clean/offline builds, and impact on downstream variants. |
| Apple source consumer | `RCT_USE_KMP=1` selects a core source build and invokes Kotlin tooling for the native archive. | A complete distribution route that does not unexpectedly turn ordinary binary consumers into full core source builds or require an unmanaged extra toolchain. |
| Apple binary/SPM consumer | Separate XCFramework/SPM feasibility was exercised previously; complete core prebuilt/SPM integration remains guarded. | End-to-end supported core artifacts, linkage, licenses, signing/distribution policy, and consumer builds without relying on this checkout's caches. |
| Additional Kotlin libraries | Prior coexistence fixtures use the same compiler and primitive API values. | An explicit mixed-version support contract and runtime/thread/exception/lifecycle tests, or a documented version restriction. |
| Platforms | JVM and ARM64 iOS simulator comparisons; existing Intel iOS frameworks compile. Catalyst retains the native path in the KMP prototype. | Agreed coverage for physical devices, Intel simulator execution, out-of-tree platforms, and the maintained fallback policy. |
| Internal build/release | No Meta internal build or release validation is available. | A maintainer-backed integration design and internal validation; public local tests cannot substitute for it. |
| Cost and ownership | Isolated local timings and binaries, with explicit scope. | Physical-device application startup/memory/size and clean/incremental CI budgets, a named maintainer/toolchain owner, and rollback criteria. |

The Apple source-build behavior is visible in `scripts/react_native_pods.rb`; the Android embedding is in `ReactAndroid/build.gradle.kts`. The reader call sites are `ReactAndroid/.../devsupport/BundleDownloader.kt`, `React/Base/RCTJavaScriptLoader.mm`, and `React/Base/RCTMultipartDataTask.m`. These are observations about the frozen experimental source, not promises of supported downstream behavior.

## A staged path with decision points

1. **Complete an equivalent comparison.** Use actual readers, malformed/fragmented-input parity, optimized native and C++ controls, raw repeated measurements, and clearly scoped costs. Do not broaden adoption based on a favorable microbenchmark alone.
2. **Select an external pilot with a concrete benefit.** If maintainers and library authors see value, an independently maintained React Native library can consume existing Kotlin business logic without changing core's architecture. Demonstrate what functionality or maintenance work it saves, preserve native UI ownership, and publish reproducible releases. This is a proposed next stage, not completed work or a request for core adoption.
3. **Validate ordinary consumers.** Show clean builds and prebuilt consumption, multiple independent libraries, upgrades, failures, rollback, and physical-device workloads. Agree on budgets before comparing results; do not invent a maintainer-approved performance threshold.
4. **Earn a narrower RFC.** Only if the external result establishes a useful advantage and an acceptable support burden should an RFC propose an explicit core boundary. It should include an optimized C++ alternative, an ownership plan, and a costed downstream migration. If the evidence favors C++ or native code for core, retain the Kotlin library experiment outside core.

Popularity or stability of KMP as a platform does not demonstrate compatibility with every React Native consumer. The current [Kotlin platform support documentation](https://kotlinlang.org/docs/multiplatform/supported-platforms.html) and [runtime documentation](https://kotlinlang.org/docs/native-memory-manager.html) are useful inputs to a support plan, not replacements for the integration evidence above.
