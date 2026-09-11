# Apple multipart comparison

This experiment stages the exact `RCTMultipartStreamReader` source into four variants. It changes no production file:

- `native`: the existing Foundation implementation, with KMP disabled.
- `optimized`: the same native framing and I/O, with a range-based Foundation header scanner that removes intermediate line arrays/substrings. Value trimming and dictionary key handling remain Foundation-owned.
- `cpp`: direct Objective-C++ calls to `MultipartCore.h`, with native UTF-16 units copied once for the header scanner. It adds no artificial Objective-C wrapper around the C++ core. Native buffers, delimiter searching, I/O, error handling and callbacks remain unchanged.
- `kmp`: the actual opt-in KMP adapter and an existing Release shared framework.

`AppleAdapters.py` requires every substitution to match exactly once. Preparation retains generated source, unified diffs, compiler commands, source hashes and symbol reports. A single benchmark-harness object is linked into four separate executables; only the KMP executable links the Kotlin archive. If the supplied archive contains other algorithms, its whole-module composition must be disclosed with any size result.

From this repository's root, first supply a previously built ARM64 simulator Release framework and a fresh output directory:

```sh
python3 packages/react-native/ReactShared/experiments/multipart-comparison/run-apple-comparison.py prepare \
  --framework packages/react-native/ReactShared/build/bin/iosSimulatorArm64/releaseFramework/ReactNativeShared.framework \
  --output "$APPLE_MULTIPART_COMPARISON_OUTPUT"
```

Preparation runs the actual seven RNTester XCTest methods for every variant, the existing 232 native/KMP adapter comparisons, and additional malformed/Unicode/fragmented/error/callback/many-part comparisons. It retains exact body, header and final-progress comparisons for all four timed inputs. Intermediate progress-event counts are clock-throttled and excluded from equality. It also compiles the C++ adapter for Catalyst and rejects Kotlin references in that object. These are standalone fixtures, not full RNTester or physical-device runs.

After preparation passes, reserve a window without other task builds or benchmarks:

```sh
python3 packages/react-native/ReactShared/experiments/multipart-comparison/run-apple-comparison.py measure \
  --output "$APPLE_MULTIPART_COMPARISON_OUTPUT"
```

The measurement phase checks source and executable hashes, then runs four fresh simulator processes per variant. Variant order follows a deterministic shuffled Latin schedule; each process uses five fixed warmups per case and 24 timed samples per case in balanced shuffled order. Workloads are a 1 KiB body, 2 MiB and 20 MiB bundles, and 64 progress JSON parts followed by a 2 MiB bundle. Input generation is excluded, while parser construction, native stream reads, scalar completion/progress callbacks, and autorelease-pool cleanup are timed. Raw samples, execution order, checksums, first-per-case observations and per-process medians are retained.

Fixed warmups do not prove convergence. Inspect the ordered raw samples for drift before interpreting a small difference; do not silently remove samples or call the results language-intrinsic. Initial observations showed material drift for the 1 KiB case, and some larger-process drift. This runner supplies no automatic performance acceptance threshold. First-per-case observations are not application startup measurements.

Both phases create and delete their own available Apple Silicon iOS simulator. They do not build the shared Gradle module, install an Intel runtime, run a full application, or establish network, physical-device, allocation, installed-size or product-performance results.
