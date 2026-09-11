# Separate Android ART correctness check

`run-android-art.py` consumes the frozen, previously prepared host fixture. It
verifies its runtime hashes, compiles the same JNI source for Android ARM64 at
API 24 with cached NDK tools, and converts the actual adapter/test classes to dex.
It neither downloads dependencies nor creates devices, installs an app, or runs a
benchmark. Its JVM allocation/timing entry point is never called on ART.

Example from the repository root, with JDK 17 in `JAVA_HOME`:

```sh
python3 packages/react-native/ReactShared/experiments/multipart-comparison/run-android-art.py \
  --host-output /absolute/path/to/evidence/android \
  --output /absolute/path/to/evidence/android/art \
  --sdk /absolute/path/to/Android/sdk \
  --ndk-version 28.2.13676358 \
  --build-tools-version 37.0.0 \
  --platform android-37.0 \
  --gradle-cache /absolute/path/to/.gradle/caches
```

The NDK compiler target is `aarch64-linux-android24`. C++ is optimized at `-O3`,
links libc++ statically, and requests 16 KiB ELF segment alignment. The original
host classes and dependencies remain unchanged. Expanded compiler commands and
all dex/native/input class hashes are recorded in ART `provenance.json`.

On an explicitly selected, task-owned ARM64 emulator, copy `dex/classes.dex` and
`libmultipart.so` to a unique directory under `/data/local/tmp`, make the dex
read-only, and execute:

```sh
adb -s EMULATOR_SERIAL shell \
  'CLASSPATH=/data/local/tmp/UNIQUE_DIR/classes.dex /system/bin/app_process /data/local/tmp/UNIQUE_DIR com.facebook.react.devsupport.AndroidArtMain /data/local/tmp/UNIQUE_DIR/libmultipart.so'
```

The default entry point executes all 39 tests: nine actual adapter tests for each
of four implementations, and three additional differential/error tests. It exits
unsuccessfully on any failure, skip or unexpected count.

The copied upstream tests depend on AssertJ 3.21. Its initialization references
`java.time.LocalDateTime`, unavailable on un-desugared API 24. The first complete
API 24 run therefore failed those 36 tests; its logs/artifacts must be retained as
that test-library compatibility failure, not relabeled as an adapter pass.
Appending `differential-only` to the command explicitly selects the three
additional JUnit-only tests without AssertJ. Those tests still exercise all four
actual adapters, 1,023 exact full-parser comparisons, final-progress values,
callback body draining and I/O/callback exception propagation. The entry point
requires exactly three passing tests in this mode.

For this evaluation, the explicit three-test mode passed on the cached API 24
ARM64 default image; the full 39-test mode passed on the cached API 37 ARM64 image.
Both runs produced 1,023 differential comparisons. They used `app_process` under
the emulator shell, not an application's Activity, R8 pipeline or networking.
They establish bounded ART parser parity, not ART speed, physical-device behavior
or whole-application integration. Exact device properties and commands are in the
separate ART evidence directory. Task-owned remote files and AVDs were removed
and emulators stopped after execution.
