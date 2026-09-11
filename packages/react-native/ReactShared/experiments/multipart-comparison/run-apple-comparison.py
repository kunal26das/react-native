#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# This source code is licensed under the MIT license found in the LICENSE file in
# the root directory of this source tree.
"""Prepare real-adapter parity first; run timings only in a separately reserved window."""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import plistlib
import random
import shutil
import statistics
import subprocess
import time

from AppleAdapters import generate

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent.parent
RN = SHARED.parent
REPO = RN.parent.parent
VARIANTS = ["native", "optimized", "cpp", "kmp"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, log, timeout=300):
    with log.open("w") as output:
        result = subprocess.run(
            [str(x) for x in args],
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    if result.returncode:
        raise RuntimeError(
            f"{log}: exit {result.returncode}\n"
            + "\n".join(log.read_text(errors="replace").splitlines()[-20:])
        )


def simulator():
    state = json.loads(
        subprocess.check_output(["xcrun", "simctl", "list", "--json"], text=True)
    )
    runtime = next(
        r
        for r in sorted(
            state["runtimes"],
            key=lambda x: tuple(map(int, x["version"].split("."))),
            reverse=True,
        )
        if r.get("isAvailable") and ".iOS-" in r["identifier"]
    )
    device = next(
        d["identifier"]
        for d in runtime["supportedDeviceTypes"]
        if d["name"].startswith("iPhone")
    )
    udid = subprocess.check_output(
        [
            "xcrun",
            "simctl",
            "create",
            "Apple multipart comparison",
            device,
            runtime["identifier"],
        ],
        text=True,
    ).strip()
    return udid, runtime["identifier"]


def cleanup(udid):
    subprocess.run(
        ["xcrun", "simctl", "shutdown", udid],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    subprocess.run(["xcrun", "simctl", "delete", udid], check=True)


def prepare(output, framework):
    output.mkdir(parents=True, exist_ok=False)
    include = output / "include"
    (include / "React").mkdir(parents=True)
    shutil.copy2(
        RN / "React/Base/RCTMultipartStreamReader.h",
        include / "React/RCTMultipartStreamReader.h",
    )
    shutil.copy2(HERE / "MultipartCore.h", include / "MultipartCore.h")
    framework_copy = output / "framework/ReactNativeShared.framework"
    shutil.copytree(framework, framework_copy)
    original = RN / "React/Base/RCTMultipartStreamReader.m"
    variants = generate(original.read_text(), output)
    source_paths = [
        original,
        RN / "React/Base/RCTMultipartStreamReader.h",
        HERE / "MultipartCore.h",
        HERE / "AppleAdapters.py",
        HERE / "AppleMultipartExtraParity.mm",
        HERE / "AppleMultipartBenchmark.mm",
        HERE / "AppleMultipartWorkloads.h",
        Path(__file__),
        SHARED / "tests/AppleMultipartParity.m",
        REPO / "packages/rn-tester/RNTesterUnitTests/RCTMultipartStreamReaderTests.m",
    ]
    provenance = {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "sourceHashes": {str(p.relative_to(REPO)): sha(p) for p in source_paths},
        "framework": {
            "source": str(framework),
            "sha256": sha(framework_copy / "ReactNativeShared"),
            "bytes": (framework_copy / "ReactNativeShared").stat().st_size,
            "scope": "Reused combined gradient + multipart + scroll Release framework; no additional shared Gradle build.",
        },
        "generatedAdapters": {},
        "compileCommands": [],
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    sdk = subprocess.check_output(
        ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True
    ).strip()
    developer = (
        Path(subprocess.check_output(["xcode-select", "-p"], text=True).strip())
        / "Platforms/iPhoneSimulator.platform/Developer"
    )
    common = [
        "-fobjc-arc",
        "-O2",
        "-target",
        "arm64-apple-ios15.1-simulator",
        "-isysroot",
        sdk,
        "-I",
        include,
        "-I",
        include / "React",
        "-F",
        output / "framework",
    ]
    libraries = [
        "-framework",
        "Foundation",
        "-framework",
        "QuartzCore",
        "-Wl,-dead_strip",
        "-ObjC",
    ]

    def compile(arguments, log):
        cmd = ["xcrun", "clang++", *common, *arguments]
        provenance["compileCommands"].append([str(x) for x in cmd])
        command(cmd, output / log)

    compile(
        [
            "-std=c++17",
            "-c",
            HERE / "AppleMultipartBenchmark.mm",
            "-o",
            output / "benchmark-harness.o",
        ],
        "benchmark-harness-build.log",
    )
    compile(
        [
            "-x",
            "objective-c++",
            "-std=c++17",
            "-DRCT_USE_KMP=0",
            "-DRCTMultipartStreamReader=RCTMultipartStreamReaderBaseline",
            "-c",
            original,
            "-o",
            output / "baseline.o",
        ],
        "baseline-build.log",
    )
    for variant in VARIANTS:
        source = output / f"AppleAdapter-{variant}.mm"
        (output / f"AppleAdapter-{variant}.patch").write_text(
            "".join(
                difflib.unified_diff(
                    original.read_text().splitlines(True),
                    variants[variant].splitlines(True),
                    fromfile="production/RCTMultipartStreamReader.m",
                    tofile=source.name,
                )
            )
        )
        provenance["generatedAdapters"][variant] = sha(source)
        obj = output / f"adapter-{variant}.o"
        compile(
            [
                "-std=c++17",
                f"-DRCT_USE_KMP={int(variant in ['kmp', 'cpp'])}",
                "-c",
                source,
                "-o",
                obj,
            ],
            f"adapter-{variant}-build.log",
        )
        references = subprocess.check_output(["xcrun", "nm", "-u", obj], text=True)
        (output / f"adapter-{variant}-undefined-symbols.txt").write_text(references)
        assert ("OBJC_CLASS_$_RNSMultipartFraming" in references) == (
            variant == "kmp"
        ), variant
        assert ("OBJC_CLASS_$_RNSMultipartHeaders" in references) == (
            variant == "kmp"
        ), variant
        extra = ["-framework", "ReactNativeShared"] if variant == "kmp" else []
        binary = output / f"benchmark-{variant}"
        compile(
            [output / "benchmark-harness.o", obj, *libraries, *extra, "-o", binary],
            f"benchmark-{variant}-build.log",
        )
        symbols = subprocess.check_output(["xcrun", "nm", "-gU", binary], text=True)
        assert ("_OBJC_CLASS_$_RNSBase" in symbols) == (variant == "kmp"), variant
        (output / f"benchmark-{variant}-defined-symbols.txt").write_text(symbols)
        for label, test in [
            ("existing-parity", SHARED / "tests/AppleMultipartParity.m"),
            ("extra-parity", HERE / "AppleMultipartExtraParity.mm"),
        ]:
            compile(
                [
                    *(
                        ["-x", "objective-c++", "-std=c++17"]
                        if test.suffix == ".mm"
                        else ["-x", "objective-c"]
                    ),
                    "-c",
                    test,
                    "-o",
                    output / f"{label}.o",
                ],
                f"{label}-{variant}-compile.log",
            )
            compile(
                [
                    output / f"{label}.o",
                    obj,
                    output / "baseline.o",
                    *libraries,
                    *extra,
                    "-o",
                    output / f"{label}-{variant}",
                ],
                f"{label}-{variant}-link.log",
            )
        bundle = output / f"Multipart-{variant}.xctest"
        bundle.mkdir()
        (bundle / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleExecutable": "MultipartTests",
                    "CFBundleIdentifier": "org.reactnative.experiment.multipart."
                    + variant,
                    "CFBundlePackageType": "BNDL",
                }
            )
        )
        test_source = (
            REPO
            / "packages/rn-tester/RNTesterUnitTests/RCTMultipartStreamReaderTests.m"
        )
        compile(
            [
                "-x",
                "objective-c",
                "-c",
                test_source,
                "-F",
                developer / "Library/Frameworks",
                "-o",
                output / "xctest.o",
            ],
            f"xctest-{variant}-compile.log",
        )
        compile(
            [
                "-bundle",
                output / "xctest.o",
                obj,
                *libraries,
                *extra,
                "-F",
                developer / "Library/Frameworks",
                "-framework",
                "XCTest",
                "-Wl,-rpath," + str(developer / "Library/Frameworks"),
                "-o",
                bundle / "MultipartTests",
            ],
            f"xctest-{variant}-link.log",
        )
    mac_sdk = subprocess.check_output(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
    ).strip()
    command(
        [
            "xcrun",
            "clang++",
            "-std=c++17",
            "-fobjc-arc",
            "-O2",
            "-target",
            "arm64-apple-ios15.1-macabi",
            "-isysroot",
            mac_sdk,
            "-isystem",
            mac_sdk + "/System/iOSSupport/usr/include",
            "-iframework",
            mac_sdk + "/System/iOSSupport/System/Library/Frameworks",
            "-I",
            include,
            "-I",
            include / "React",
            "-DRCT_USE_KMP=1",
            "-c",
            output / "AppleAdapter-cpp.mm",
            "-o",
            output / "cpp-catalyst.o",
        ],
        output / "cpp-catalyst-build.log",
    )
    assert "OBJC_CLASS_$_RNS" not in subprocess.check_output(
        ["xcrun", "nm", "-u", output / "cpp-catalyst.o"], text=True
    )
    udid, runtime = simulator()
    results = {
        "status": "running",
        "simulator": {"udid": udid, "runtime": runtime},
        "variants": {},
        "cppCatalystCompiledWithoutKotlin": True,
    }
    try:
        for variant in VARIANTS:
            print("Checking", variant, flush=True)
            command(
                [
                    "xcrun",
                    "simctl",
                    "spawn",
                    "--standalone",
                    udid,
                    developer / "Library/Xcode/Agents/xctest",
                    output / f"Multipart-{variant}.xctest",
                ],
                output / f"xctest-{variant}.log",
            )
            xctest = (output / f"xctest-{variant}.log").read_text()
            assert "Executed 7 tests, with 0 failures" in xctest, variant
            for label in ["existing-parity", "extra-parity"]:
                command(
                    [
                        "xcrun",
                        "simctl",
                        "spawn",
                        "--standalone",
                        udid,
                        output / f"{label}-{variant}",
                    ],
                    output / f"{label}-{variant}.log",
                )
            extra = json.loads(
                (output / f"extra-parity-{variant}.log")
                .read_text()
                .strip()
                .splitlines()[-1]
            )
            assert (
                "232 real Apple multipart adapter parity cases"
                in (output / f"existing-parity-{variant}.log").read_text()
            )
            results["variants"][variant] = {
                "xctestPasses": 7,
                "existingParityCases": 232,
                "extraParity": extra,
                "benchmarkBinaryBytes": (output / f"benchmark-{variant}")
                .stat()
                .st_size,
                "benchmarkBinarySha256": sha(output / f"benchmark-{variant}"),
            }
        results["status"] = "passed"
    finally:
        cleanup(udid)
        results["ownedSimulatorDeleted"] = True
        (output / "parity.json").write_text(json.dumps(results, indent=2) + "\n")
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print("READY FOR RESERVED TIMING WINDOW:", output, flush=True)


def measure(output):
    provenance = json.loads((output / "provenance.json").read_text())
    parity = json.loads((output / "parity.json").read_text())
    assert parity["status"] == "passed"
    for path, digest in provenance["sourceHashes"].items():
        assert sha(REPO / path) == digest, ("source changed after preparation", path)
    for variant in VARIANTS:
        assert (
            sha(output / f"benchmark-{variant}")
            == parity["variants"][variant]["benchmarkBinarySha256"]
        )
    timing = output / "measured"
    timing.mkdir(exist_ok=False)
    order = VARIANTS.copy()
    random.Random(58472).shuffle(order)
    schedule = [order[r:] + order[:r] for r in range(4)]
    report = {
        "sourceCommit": provenance["commit"],
        "processOrder": schedule,
        "processesPerVariant": 4,
        "runs": [],
        "scope": "Release ARM64 simulator full parser, separate otherwise-identical executables and shared harness object; no app, network, physical-device, or allocation claim",
        "frameworkComposition": provenance["framework"],
        "startedAt": time.time(),
        "loadAverageBefore": os.getloadavg(),
        "timingConditions": "Run only after coordinator reserves task-quiet window; unrelated system/user processes are not stopped.",
    }
    udid, runtime = simulator()
    report["simulator"] = {"udid": udid, "runtime": runtime}
    try:
        for repeat, variants in enumerate(schedule):
            for variant in variants:
                log = timing / f"{repeat + 1}-{variant}.log"
                command(
                    [
                        "xcrun",
                        "simctl",
                        "spawn",
                        "--standalone",
                        udid,
                        output / f"benchmark-{variant}",
                        variant,
                        str(1701 + repeat),
                    ],
                    log,
                )
                record = json.loads(log.read_text().strip().splitlines()[-1])
                record["repeat"] = repeat + 1
                report["runs"].append(record)
                print("Measured", repeat + 1, variant, flush=True)
        cases = sorted(
            {
                sample["case"]
                for run in report["runs"]
                for row in run["orderedSamples"]
                for sample in row
            }
        )
        report["cases"] = {}
        for case in cases:
            checksums = {
                sample["checksum"]
                for run in report["runs"]
                for row in run["orderedSamples"]
                for sample in row
                if sample["case"] == case
            }
            assert len(checksums) == 1, (case, checksums)
            medians = {
                v: [
                    statistics.median(
                        s["ms"]
                        for row in run["orderedSamples"]
                        for s in row
                        if s["case"] == case
                    )
                    for run in report["runs"]
                    if run["variant"] == v
                ]
                for v in VARIANTS
            }
            report["cases"][case] = {
                "checksum": next(iter(checksums)),
                "perProcessMediansMs": medians,
                "medianMs": {v: statistics.median(ms) for v, ms in medians.items()},
                "perRepeatRatiosToNative": {
                    v: [x / y for x, y in zip(medians[v], medians["native"])]
                    for v in VARIANTS
                },
            }
        report["binaryBytes"] = {
            v: parity["variants"][v]["benchmarkBinaryBytes"] for v in VARIANTS
        }
        report["status"] = "passed"
    finally:
        cleanup(udid)
        report.update(
            ownedSimulatorDeleted=True,
            finishedAt=time.time(),
            loadAverageAfter=os.getloadavg(),
        )
        (timing / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Evidence:", timing / "summary.json", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "measure"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--framework", type=Path)
    args = parser.parse_args()
    if args.phase == "prepare":
        assert args.framework and args.framework.name == "ReactNativeShared.framework"
        prepare(args.output.resolve(), args.framework.resolve())
    else:
        measure(args.output.resolve())
