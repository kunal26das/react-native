# Multipart sharing: KMP, C++, and native controls

This isolated experiment supplies an equivalent multipart-reader comparison for
[React Native architectural discussion #1020](https://github.com/react-native-community/discussions-and-proposals/issues/1020).
It adds no production integration and makes no core adoption request.

The four implementations are the actual platform reader, a native header-scanning
optimization, the existing KMP prototype, and a shared C++ framing/header core.
All keep the platform's buffers, stream I/O, body ownership, and callback policy.
C++ uses real JNI on Android and a direct Objective-C++ call on Apple.

- [Results and limits](RESULTS.md): parity, repeated measurements, and binary scope.
- [Method](METHOD.md): questions and comparison controls defined before timing.
- [Adoption requirements](ADOPTION.md): Kotlin-specific value, downstream gaps,
  and an external-library route with decision points.
- [Android adapter details](AndroidREADME.md): generated readers, JNI ownership,
  buffering, header representations, and JVM measurement scope.
- [Apple adapter details](AppleREADME.md): separate executables, exact workload
  parity, simulator lifecycle, and sample stability.
- [Supplementary Android ART checks](AndroidART.md): runtime correctness and the
  API 24 assertion-library limitation, separate from performance measurements.
- [Published evidence](results/README.md): raw samples, provenance, and checksums.

## Reproduce

Use an Apple Silicon Mac with Xcode and an installed ARM64 iOS simulator runtime,
Python 3, JDK 17, and the Gradle dependencies for this experimental checkout.
The runners use cached dependencies; they do not download simulator runtimes.
Record the compiler, OS, and simulator versions in each new result. A new machine
is not expected to produce identical timings or binary hashes.

Run these commands from the repository root. Set `JAVA_HOME` to your JDK 17 home
and choose an absolute, disposable evidence directory outside the checkout:

```sh
export MULTIPART_EVIDENCE=/absolute/path/to/new-multipart-evidence
export MULTIPART_EXPERIMENT=packages/react-native/ReactShared/experiments/multipart-comparison

# Fetch the independently corrected native Android baseline if it is absent.
git fetch https://github.com/kunal26das/react-native.git codex/multipart-header-bounds

# Build inputs before either platform's measurement window.
packages/react-native/ReactShared/gradlew \
  -p packages/react-native/ReactShared \
  exportAndroidJar linkReleaseFrameworkIosSimulatorArm64 \
  --offline --max-workers=2 --console=plain

python3 "$MULTIPART_EXPERIMENT/run-core-tests.py" \
  --output "$MULTIPART_EVIDENCE/core"

python3 "$MULTIPART_EXPERIMENT/run-android-comparison.py" \
  --output "$MULTIPART_EVIDENCE/android" \
  --baseline-ref b150c6f7dd718c5b4a320fdecb06f2049b87b5c0 \
  --phase prepare

python3 "$MULTIPART_EXPERIMENT/run-apple-comparison.py" prepare \
  --output "$MULTIPART_EVIDENCE/apple" \
  --framework packages/react-native/ReactShared/build/bin/iosSimulatorArm64/releaseFramework/ReactNativeShared.framework

# Reserve a window without other task-owned builds or benchmarks.
# Run these sequentially, after all preparation finishes.
python3 "$MULTIPART_EXPERIMENT/run-android-comparison.py" \
  --output "$MULTIPART_EVIDENCE/android" \
  --baseline-ref b150c6f7dd718c5b4a320fdecb06f2049b87b5c0 \
  --phase benchmark --processes 3

python3 "$MULTIPART_EXPERIMENT/run-apple-comparison.py" measure \
  --output "$MULTIPART_EVIDENCE/apple"
```

Apple preparation and measurement create their own temporary simulator and remove
it afterward. Preparation requires a new output directory. Reusing an existing
directory is intentionally rejected; retain each run rather than overwriting it.
Android benchmark mode checks the prepared sources and runtime artifact hashes.
Apple measurement checks source and executable hashes. Neither timing phase
rebuilds the shared module.

The native baseline commit and production source hashes are pinned in the
published evidence. Experimental source hashes identify the exact inputs used
before this experiment was committed. The framework contains the existing three
KMP candidates; its measured executable cost is not a multipart-only cost.

## Scope

Multipart readers support JavaScript bundle loading and progress responses. This
experiment does not measure rendering, networking, whole-app startup, physical
devices, or Meta's internal build system. KMP and C++ both permit a shared core and
shared tests. Any proposal to add a new runtime needs a benefit beyond that common
property and an acceptable distribution, upgrade, and maintenance contract.
