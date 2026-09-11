# Results: equivalent multipart readers

The comparison establishes tested behavior parity and workable KMP and C++ shared
boundaries. It does **not** establish a performance reason to add KMP to React
Native core. Optimizing the existing native header parser is a credible control;
C++ can also share the framing/header implementation and tests.

Measurements were collected on an ARM64 macOS development host on 11 September
2026. The production inputs are frozen at
`fec597ba9fb51628b04206fb215ff9156084f535`; the corrected Android native baseline
is `b150c6f7dd718c5b4a320fdecb06f2049b87b5c0`. Exact source, generated adapter,
runtime, and benchmark binary hashes accompany the [evidence](results/README.md).
No production source or published PR head was changed for this comparison.

## Correctness before timing

| Layer | Executed checks | Outcome |
| --- | --- | --- |
| Shared C++ core | 65,536 transitions and 131,072 state queries against the actual Kotlin implementation; 10,009 header cases; 462 fragmented retained/sliding-buffer cases; nine independent large-offset/precedence assertions | Passed with address and undefined-behavior sanitizers |
| UTF-16 representation | 10,009 comparisons of actual native UTF-16 units and `char16_t` header ranges | Passed without aliasing casts |
| Actual Android readers | Nine existing adapter tests against each of four variants, plus three differential/error tests: 39 JUnit tests; 1,023 full-parser differential comparisons | Zero failures, errors, or skips |
| Android ART emulators | API 24: three differential/error tests; API 37: all 39 tests. Each includes the same 1,023 differential comparisons | Passed in those scopes; API 24's full-suite attempt hit an assertion-library limitation described below |
| Actual Apple readers | Per variant: seven existing XCTest tests, 232 existing adapter parity cases, 131 header cases, and 2,255 additional stream comparisons including all four measured workloads | Zero failures or observed differences across all four variants |
| C++ Apple fallback feasibility | Catalyst object compilation with no Kotlin symbol references | Passed; compilation only |

Full-parser comparisons include exact bodies, headers, completion/last-part
behavior, error paths, and final progress values per completed part. Intermediate
progress event counts and timestamps are excluded because production throttling
uses wall-clock time. The malformed, Unicode, fragmented, callback-exception,
and partial-input cases are described in the reproducible runners. These finite
checks are not a proof of equivalence for all inputs.

The supplementary ART run used cached ARM64 API 24 and API 37 emulators and a
separate correctness entry point. The initial full API 24 attempt ran 39 tests:
the three differential/error tests passed, while the 36 existing adapter test
copies failed because AssertJ 3.21.0 initializes `java.time.LocalDateTime`, which
is unavailable on that API. A separate differential-only run then passed all
three tests; all 39 passed on API 37. The original failure log and both successful
run logs are retained. This does not claim full-suite API 24 coverage, ART
performance, or application integration. Both owned emulators and their files
were removed after the check. See [ART reproduction and scope](AndroidART.md).

## Android adapter on the host JVM

Three fresh JDK 17 processes, 24 fixed warmup rounds and 40 sampled rounds per
implementation/workload, produced **2,400 raw samples**. Deterministically
randomized rotations balance implementation positions. Every parse retains
Okio buffering, body reads, and draining; input/source construction is outside
the timer. C++ crosses the actual JNI boundary.

Times below are microseconds per parse. Ranges span the **three process medians**;
ratio ranges use the corresponding process medians. They are not confidence
intervals.

| Workload | Native | Optimized native | C++/JNI | KMP | KMP / optimized native |
| --- | ---: | ---: | ---: | ---: | ---: |
| One 1 KiB part, eight headers | 3.08–3.56 | 2.11–2.15 | 2.69–2.79 | 2.49–2.61 | 1.158–1.227 |
| One 2 MiB bundle | 2,139.69–2,155.85 | 2,120.31–2,148.77 | 2,134.17–2,165.58 | 2,127.06–2,135.98 | 0.994–1.003 |
| One 20 MiB bundle | 21,236.25–21,321.10 | 21,245.42–21,286.10 | 21,321.33–21,417.58 | 21,253.40–21,303.10 | 1.000–1.001 |
| 128 × 1 KiB parts | 193.57–203.40 | 153.51–154.80 | 211.46–212.40 | 166.71–168.97 | 1.086–1.095 |
| 128 × 128-byte parts + 2 MiB bundle | 2,163.23–2,165.56 | 2,142.52–2,149.56 | 2,204.52–2,212.12 | 2,150.85–2,157.15 | 1.002–1.004 |

KMP improved on the original regex parser for small and many-part inputs in these
runs, but the optimized native control was faster there. Large-input medians were
close; this is not a statistical equivalence result. The last workload is a
synthetic sequence of binary progress-sized payloads followed by a bundle; it
does not parse Metro JSON or measure the complete downloader.

Fixed warmup did **not** establish steady state: small-input timings and
allocations still drifted. For example, in process 2, the first-ten/last-ten
sample medians fell from 3,531.6 to 2,848.6 ns for native and 3,295.6 to 2,413.1 ns
for KMP. No sample was discarded; the largest small-input sample was 4.61× its
process median for KMP and 3.41× for native. These results should not be used to
assign an intrinsic cost to a language or predict ART performance.

Current-thread JVM allocation medians for KMP versus optimized native were
approximately 3,633/2,217 bytes for the small case, 413,196/230,636 bytes for
128 × 1 KiB parts, and 250,256/145,488 bytes for progress-sized parts plus a bundle.
They exclude native C++ allocations and possible JNI copies. The optimized
native/C++ designs trim ranges before allocating strings; the existing KMP API
returns strings that the adapter then trims. An optimized KMP range interface
could be evaluated separately. This measures concrete interfaces and adapters,
not only language/compiler choices.

## Apple ARM64 simulator

Four fresh processes per implementation used separate Release executables linked
to the same benchmark harness object. Implementation order rotates across four
rounds; each process records 24 samples per workload after five fixed warmups. All
**1,536 raw samples** are retained. Only the KMP executable links the Kotlin
archive/runtime. The simulator runtime was iOS 26.5.

Times below are microseconds per parse. Ranges span the **four process medians**;
ratio ranges compare processes from the corresponding round.

| Workload | Native | Optimized native | C++ | KMP | KMP / optimized native |
| --- | ---: | ---: | ---: | ---: | ---: |
| One 1 KiB part | 15.021–15.417 | 12.833–13.792 | 12.687–13.417 | 14.667–17.125 | 1.143–1.292 |
| One 2 MiB bundle | 1,424.229–1,452.396 | 1,421.562–1,451.208 | 1,427.021–1,445.354 | 1,456.542–1,482.292 | 1.011–1.030 |
| One 20 MiB bundle | 13,839.812–14,259.146 | 13,834.333–14,442.375 | 13,924.604–14,281.646 | 14,094.000–14,344.271 | 0.978–1.019 |
| 64 progress JSON parts + 2 MiB bundle | 1,571.875–1,589.000 | 1,539.292–1,569.542 | 1,513.854–1,560.813 | 1,614.292–1,634.354 | 1.038–1.050 |

For 2 MiB and progress-plus-bundle inputs, KMP/native ratios were 1.017–1.028 and
1.019–1.029 respectively. The small and 20 MiB ratios crossed 1 across repeats;
there is no universal slowdown or speedup claim. Small-input optimized native
and C++ medians were lower than KMP in every round. Apple and Android use
different platform buffers and workloads, so their absolute times are not a
cross-platform speed comparison.

Apple samples also did not establish steady state. Across small-input processes,
last-eight/first-eight sample median ratios ranged from 0.702 to 1.149 after the
fixed warmup. The first C++ process's larger cases also shifted by approximately
8–10%. All samples and the stability analysis are retained. These descriptive
process comparisons do not establish an intrinsic implementation ranking or a
production device budget.

| Separate executable | Bytes | Difference from native |
| --- | ---: | ---: |
| Native | 73,824 | — |
| Optimized native | 57,072 | −16,752 |
| C++ | 75,248 | +1,424 |
| KMP | 906,160 | +832,336 |

The KMP archive contains **gradients, multipart, scroll selection, and the Kotlin
runtime**. Its difference is neither multipart's marginal cost nor installed-app
size. Link flags, framework hash, binary hashes, and symbol checks are published.
No Apple allocation, process-memory, startup, energy, or device result is inferred
from the executable size or warmed parser samples.

## What this changes about the adoption case

The missing C++ comparison now exists and has been exercised through both real
platform adapters. It demonstrates that sharing the algorithm/tests is possible
within React Native's established C++ direction too. KMP's direct Android calls
avoid this experiment's JNI wrapper, but its Apple runtime/distribution cost and
the native optimization results still need justification.

The best next hypothesis is **reuse of substantial existing Kotlin business
logic in an external React Native library**, where avoided reimplementation can
be measured. The [adoption requirements](ADOPTION.md) spell out a staged pilot,
ordinary prebuilt consumers, mixed-library upgrades, physical-device budgets,
ownership, and rollback before any narrower core RFC. That external pilot has
not been implemented by this experiment, and no maintainer acceptance is implied.

The timing windows excluded other task-owned builds/benchmarks. Normal system
activity remained uncontrolled. No physical device, network, full-app cost,
cold-CI build, or Meta internal build validation was performed here. Intel iOS
simulator execution remains deferred as previously requested. The existing
upstream KMP consumers remain drafts and the foundation closure is respected.
