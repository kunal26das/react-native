# Android multipart comparison

This experiment compares four complete `MultipartStreamReader` adapters. It does
not change production sources or the PR series. The Android callsite is
`devsupport/BundleDownloader`: Metro progress responses and downloaded JavaScript
bundles motivate the workloads, rather than rendering or frame time.

## Controls and preserved work

- **NATIVE** is the actual native Kotlin adapter extracted from an explicit Git
  revision. Use `b150c6f7dd718c5b4a320fdecb06f2049b87b5c0`, which includes the native
  header-boundary correction. The runner rejects a shared-code baseline or one
  without that correction.
- **OPTIMIZED_NATIVE** uses that adapter's framing unchanged. Its only algorithm
  change replaces regex/split/line allocations with a bounded CRLF and first-colon
  scanner; it trims range endpoints before allocating final key/value substrings.
- **KMP** is the actual working-tree adapter and separately built shared JVM JAR.
  Only the reader class is renamed to let the four adapters coexist.
- **CPP_JNI** retains the KMP adapter's native buffer loop, replacing shared framing
  and header calls with `MultipartCore.h` through a private JNI wrapper. The
  generator adds `try/finally` cleanup of the exclusively owned native framing
  state on success, EOF, I/O errors and callback exceptions.

All four retain Okio buffers, UTF-8 decoding, case-insensitive `TreeMap` behavior,
first-colon separation, trimming only characters at or below ASCII space,
last-duplicate-wins policy, native progress throttling, callback body ownership,
fixed-length sources and best-effort draining. No body bytes cross JNI and no
whole-body copies are added. Generated adapters use checked substitutions; their
hashes, original adapter hashes and the baseline commit are recorded.

This compares concrete designs, not only languages. KMP returns raw header
strings which the adapter then trims; the optimized native and C++ controls return
or work with ranges and allocate only trimmed strings. A range-returning KMP API
is a possible separate optimization, not measured here.

## JNI transport

There is one framing JNI call per loop iteration, plus one creation and one
release per parse. The call returns an optional chunk and the next absolute search
start in a reused five-element `LongArray`. Kotlin rebases that cached start using
its wrapping `Long` subtraction, avoiding a redundant JNI getter. The optional
chunk still has a JVM object, as in the actual KMP adapter.

Header parsing crosses JNI once per parse of a header block. `GetStringChars`
provides UTF-16 units (the VM may copy); the C++ scanner reads their actual `jchar`
type without aliasing casts and returns ranges. The string is released before
allocating a packed JNI `IntArray`, which Kotlin consumes with native trimming and
map insertion. Native vectors/state and optional JNI string/array copies are
**excluded** from the JVM allocation counter. C++ allocation failure becomes
`OutOfMemoryError`; there is no JNI critical region or retained borrowed pointer.

## Reproduction

Set `JAVA_HOME` to JDK 17 and build/export the shared JAR separately. The runner
uses the checkout's Kotlin compiler, language/API level and exact ReactAndroid
runtime dependency versions. Dependencies must already be cached; fixture Gradle
runs offline, with at most two workers. From the repository root:

```sh
python3 packages/react-native/ReactShared/experiments/multipart-comparison/run-android-comparison.py \
  --output /absolute/path/to/evidence/android \
  --baseline-ref b150c6f7dd718c5b4a320fdecb06f2049b87b5c0 \
  --phase prepare
```

This compiles the host JNI library at `-O3 -DNDEBUG`, copies the actual nine adapter
JUnit tests for each implementation, adds full-parser differential/error tests,
and records compiler/runtime/artifact hashes. No shared-project or application
build is started. The additional comparisons cover malformed UTF-8, Unicode and
case/whitespace/duplicate header policy, byte-fragmented delimiters, final progress
values, partial framing and exceptions. Progress comparison retains the last
value before each completed part; intermediate callback count and timing are
intentionally not compared because they use wall-clock throttling.

After preparation, reserve a measurement window without other task-owned builds
or benchmarks:

```sh
python3 packages/react-native/ReactShared/experiments/multipart-comparison/run-android-comparison.py \
  --output /absolute/path/to/evidence/android \
  --baseline-ref b150c6f7dd718c5b4a320fdecb06f2049b87b5c0 \
  --phase benchmark --processes 3
```

The benchmark verifies prepared source and runtime hashes and launches three
fresh JDK 17 JVMs with the same 512 MiB heap settings. Each workload has 24 warmup
rounds and 40 sampled rounds per implementation. Deterministically randomized
four-rotation blocks put every implementation in every position equally often.
Raw samples record order, seed, elapsed time and current-thread JVM allocation
bytes. Report per-process medians and ratios, preserving all raw samples.

Workloads are one 1 KiB part with eight headers, one 2 MiB bundle, one 20 MiB bundle,
128 1 KiB parts, and 128 small progress parts followed by a 2 MiB bundle. Input and
source construction are outside the measured region; parsing, callbacks, body
reads and draining are inside. A result digest from every parse is checked outside
the timer. Exact body contents are checked in the correctness tests.

These are warmed host-JVM parser measurements with normal development-host
activity. They do not measure ART, physical devices, networking, whole-app memory,
GC pauses, energy, release artifact size or user-visible loading time. Allocation
numbers must not be treated as total cross-language allocation costs.
