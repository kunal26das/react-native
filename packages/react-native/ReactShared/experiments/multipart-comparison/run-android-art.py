#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Prepare ART parity files from frozen host fixture; no devices/install/downloads.

Run resulting dex through app_process with AndroidArtMain and libmultipart.so.
This is a correctness runner, not an ART performance measurement.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--ndk-version", required=True)
    parser.add_argument("--build-tools-version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--gradle-cache", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    host = args.host_output.resolve()
    provenance = json.loads((host / "provenance.json").read_text())
    for filename, expected in provenance["artifactHashes"].items():
        if digest(Path(filename)) != expected:
            raise RuntimeError(f"Frozen host artifact changed: {filename}")
    experiment = Path(__file__).resolve().parent
    native = output / "libmultipart.so"
    compiler = (
        args.sdk
        / "ndk"
        / args.ndk_version
        / "toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++"
    )
    commands = []

    def run(command, name):
        commands.append([str(x) for x in command])
        with (output / f"{name}.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)

    run(
        [
            compiler,
            "-std=c++17",
            "-O3",
            "-DNDEBUG",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-fPIC",
            "-shared",
            "-static-libstdc++",
            "-Wl,-z,max-page-size=16384",
            experiment / "JniMultipart.cpp",
            "-o",
            native,
        ],
        "compile-jni",
    )
    jars = [
        Path(x) for x in provenance["classpath"].split(os.pathsep) if Path(x).is_file()
    ]
    for group, name, version in [
        ("junit", "junit", "4.13.2"),
        ("org.hamcrest", "hamcrest-core", "1.3"),
        ("org.assertj", "assertj-core", "3.21.0"),
    ]:
        matches = list(
            (args.gradle_cache / "modules-2/files-2.1" / group / name / version).glob(
                f"*/{name}-{version}.jar"
            )
        )
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one cached runtime JAR: {group}:{name}:{version}"
            )
        jars += matches
    android_jar = args.sdk / "platforms" / args.platform / "android.jar"
    classes = output / "classes"
    classes.mkdir(exist_ok=True)
    host_classes = [
        host / "fixture/build/classes/kotlin/main",
        host / "fixture/build/classes/kotlin/test",
    ]
    classpath = os.pathsep.join(map(str, jars + host_classes + [android_jar]))
    java_home = Path(provenance["javaHome"])
    run(
        [
            java_home / "bin/javac",
            "-source",
            "8",
            "-target",
            "8",
            "-cp",
            classpath,
            "-d",
            classes,
            experiment / "AndroidArtMain.java",
        ],
        "compile-main",
    )
    packed = output / "fixture-classes.jar"
    input_hashes = {}
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        for root in host_classes + [classes]:
            for file in sorted(root.rglob("*.class")):
                archive.write(file, file.relative_to(root))
                input_hashes[str(file)] = digest(file)
    dex = output / "dex"
    dex.mkdir(exist_ok=True)
    run(
        [
            args.sdk / "build-tools" / args.build_tools_version / "d8",
            "--release",
            "--min-api",
            "24",
            "--lib",
            android_jar,
            "--output",
            dex,
            packed,
        ]
        + jars,
        "dex",
    )
    files = (
        [
            native,
            packed,
            experiment / "AndroidArtMain.java",
            experiment / "run-android-art.py",
            experiment / "JniMultipart.cpp",
            experiment / "MultipartCore.h",
        ]
        + list(dex.glob("*.dex"))
        + jars
    )
    (output / "provenance.json").write_text(
        json.dumps(
            {
                "hostHead": provenance["head"],
                "hostBaseline": provenance["baseline"],
                "hostProvenanceSha256": digest(host / "provenance.json"),
                "commands": commands,
                "inputClassHashes": input_hashes,
                "artifacts": {str(p): digest(p) for p in files},
                "scope": "Four actual adapter variants, 39 JUnit tests and 1023 differential comparisons on ART; no benchmark or application integration",
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"phase": "ART prepare", "output": str(output)}))


if __name__ == "__main__":
    main()
