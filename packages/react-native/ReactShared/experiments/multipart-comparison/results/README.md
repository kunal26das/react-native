# Published evidence

These are selected results from the 11 September 2026 comparison. The
[main report](../RESULTS.md) explains what they establish and their limits;
[reproduction commands](../README.md#reproduce) generate fresh evidence.

| Files | Contents |
| --- | --- |
| [Android summary](android/benchmark-summary.json) | Three process medians, ratios, exact JVM invocations, and raw sample hashes |
| `android/jvm-process-{1,2,3}.jsonl` | All 2,400 fixed-warmup host-JVM samples, order, elapsed time, allocation counts |
| [Android spread](android/sample-spread.json) | Minimum, median, p95, and maximum by process/workload/implementation |
| [Android provenance](android/provenance.json), `android/junit/` | Source/runtime/generated fixture hashes, toolchains, commands, and 39 passing test results |
| `android/art/` | Separate API 24 differential-only and API 37 full-suite ART checks; the original API 24 AssertJ failure, commands, hashes, and emulator cleanup |
| [Apple summary](apple/measured/summary.json) | All 1,536 samples, process order, medians, per-round ratios, sizes, and simulator cleanup |
| `apple/measured/{1,2,3,4}-{native,optimized,cpp,kmp}.log` | Original process output, retaining every sample |
| [Apple stability](apple/sample-stability.json) | Fixed-warmup drift and raw sample spread |
| [Apple parity](apple/parity.json), `apple/parity-logs/` | Existing XCTest, header/stream parity, and exact benchmark workload parity results |
| [Apple provenance](apple/provenance.json), [binary evidence](apple/binary-evidence.json) | Compile commands, source/framework/binary hashes, and absence of Kotlin runtime symbols in native/C++ controls |
| [Core results](core/results.json), [differential digests](core/differential-digests.json) | Sanitized C++/Kotlin oracle checks, deterministic corpus/output hashes, and fragmented-stream checks |
| [Manifest](manifest.json) | SHA-256 and byte length for every selected result; normalization status and original file hashes |
| [Independent review](read-only-review.json) | Recomputed table values, sample counts, provenance checks, and resolved findings |

`measurement-host.json` on each platform records post-measurement environment
observations and their scope. Post-measurement checks verify that the prepared
inputs stayed unchanged. These records do not imply a controlled laboratory or
converged steady state.

Local checkout, evidence, workspace, Gradle-cache, Android-SDK, and home directory
paths in selected text files are replaced with descriptive placeholders. Numeric
samples, orders, versions, source hashes, and benchmark artifact hashes are
preserved. The manifest distinguishes original and published file checksums; raw
sample logs with no local paths remain byte-for-byte unchanged. Commands containing
`<REPO>` or `<EVIDENCE>` placeholders describe the original run; use the portable
commands in the reproduction guide for a new run.

Compiled binaries, dependency caches, generated build directories, and the large
deterministic core corpus are omitted. The checked-in runners regenerate them;
the core corpus and output digests allow comparison without committing tens of
megabytes of duplicate generated text. No new whole-application, ART performance,
or physical-device measurements are contained in these host/simulator samples.
