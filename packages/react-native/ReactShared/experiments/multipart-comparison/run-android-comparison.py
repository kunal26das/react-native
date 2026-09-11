#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Generate real Android adapter controls, test them, or measure a prepared fixture.

The shared JAR must already exist. This runner never builds the shared project.
Benchmark mode launches fresh host JVMs, not Android ART or physical devices.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one adapter substitution: {old!r}")
    return text.replace(old, new, 1)


def header_control(source, helper):
    pattern = (
        r"  private fun parseHeaders\(data: Buffer\): Map<String, String> \{.*?\n  \}"
    )
    replacement = f"""  private fun parseHeaders(data: Buffer): Map<String, String> {{
    val headers: MutableMap<String, String> = TreeMap(String.CASE_INSENSITIVE_ORDER)
    {helper}(headers, data.readUtf8())
    return headers
  }}"""
    result, count = re.subn(pattern, replacement, source, flags=re.S)
    if count != 1:
        raise RuntimeError("Expected exactly one native header parser")
    return result


def rename(source, target):
    if source.count("internal class MultipartStreamReader(") != 1:
        raise RuntimeError("Unexpected adapter class")
    return re.sub(r"\bMultipartStreamReader\b", target, source)


def run(command, output, name, cwd):
    with (output / f"{name}.log").open("w") as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((output / f"{name}.log").read_text()[-10000:], file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, command)


def prepare(args, experiment, shared, repo, output):
    adapter = (
        shared.parent
        / "ReactAndroid/src/main/java/com/facebook/react/devsupport/MultipartStreamReader.kt"
    )
    tests = (
        shared.parent
        / "ReactAndroid/src/test/java/com/facebook/react/devsupport/MultipartStreamReaderTest.kt"
    )
    baseline_ref = subprocess.check_output(
        ["git", "rev-parse", f"{args.baseline_ref}^{{commit}}"], cwd=repo, text=True
    ).strip()
    baseline = subprocess.check_output(
        ["git", "show", f"{baseline_ref}:{adapter.relative_to(repo)}"],
        cwd=repo,
        text=True,
    )
    if (
        "com.facebook.react.shared" in baseline
        or "indexOfMarker > chunkLength - marker.size()" not in baseline
    ):
        raise RuntimeError(
            "Baseline must be native with the corrected multipart header boundary"
        )
    actual = adapter.read_text()
    if actual.count("import com.facebook.react.shared.MultipartFraming\n") != 1:
        raise RuntimeError("Actual adapter no longer matches the KMP experiment")
    generated = {
        "AndroidNativeReader": rename(baseline, "AndroidNativeReader"),
        "AndroidOptimizedReader": rename(
            header_control(baseline, "scanNativeHeaders"), "AndroidOptimizedReader"
        ),
        "AndroidKmpReader": rename(actual, "AndroidKmpReader"),
    }
    cpp = replace_once(
        actual, "import com.facebook.react.shared.MultipartFraming\n", ""
    )
    cpp = replace_once(cpp, "import com.facebook.react.shared.MultipartHeaders\n", "")
    cpp = replace_once(
        cpp, "val framing = MultipartFraming(", "val framing = JniFraming("
    )
    cpp = header_control(cpp, "scanJniHeaders")
    cpp = replace_once(
        cpp,
        "    val framing = JniFraming(delimiter.size(), closeDelimiter.size())\n",
        "",
    )
    cpp = replace_once(
        cpp,
        "    while (true) {\n      val searchStart",
        "    val framing = JniFraming(delimiter.size(), closeDelimiter.size())\n    while (true) {\n      val searchStart",
    )
    cpp = replace_once(
        cpp,
        "    while (true) {\n      val searchStart",
        "    try {\n    while (true) {\n      val searchStart",
    )
    cpp = replace_once(
        cpp,
        "      bufferOffset += chunkEnd\n    }\n  }",
        "      bufferOffset += chunkEnd\n    }\n    } finally {\n      framing.close()\n    }\n  }",
    )
    generated["AndroidCppReader"] = rename(cpp, "AndroidCppReader")
    fixture = output / "fixture"
    fixture.mkdir(exist_ok=True)
    for name in ("main", "test"):
        directory = fixture / name
        directory.mkdir(exist_ok=True)
        for path in directory.glob("Android*.kt"):
            path.unlink()
    for name, source in generated.items():
        (fixture / "main" / f"{name}.kt").write_text(source)
        test_source = tests.read_text().replace("MultipartStreamReader", name)
        if f"class {name}Test" not in test_source:
            raise RuntimeError("Test rename did not produce the expected test class")
        (fixture / "test" / f"{name}Test.kt").write_text(test_source)
    for name in ("AndroidComparison.kt", "JniMultipart.kt"):
        shutil.copyfile(experiment / name, fixture / "main" / name)
    shutil.copyfile(
        experiment / "AndroidComparisonTest.kt",
        fixture / "test/AndroidComparisonTest.kt",
    )
    dispatch = """@file:Suppress("DEPRECATION_ERROR")
package com.facebook.react.devsupport
import okio.BufferedSource
internal fun dispatchReader(candidate: AndroidCandidate, source: BufferedSource, boundary: String, listener: AndroidListener): Boolean = when (candidate) {
"""
    for candidate, name in [
        ("NATIVE", "AndroidNativeReader"),
        ("OPTIMIZED_NATIVE", "AndroidOptimizedReader"),
        ("CPP_JNI", "AndroidCppReader"),
        ("KMP", "AndroidKmpReader"),
    ]:
        dispatch += f"""  AndroidCandidate.{candidate} -> {name}(source, boundary).readAllParts(object : {name}.ChunkListener {{
    override fun onChunkComplete(headers: Map<String, String>, body: BufferedSource, isLastChunk: Boolean) = listener.complete(headers, body, isLastChunk)
    override fun onChunkProgress(headers: Map<String, String>, loaded: Long, total: Long) = listener.progress(headers, loaded, total)
  }})
"""
    (fixture / "main/AndroidDispatch.kt").write_text(dispatch + "}\n")
    java_home = Path(os.environ["JAVA_HOME"])
    native = output / (
        "libmultipart.dylib" if sys.platform == "darwin" else "libmultipart.so"
    )
    native_command = [
        "clang++",
        "-std=c++17",
        "-O3",
        "-DNDEBUG",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-fPIC",
        "-dynamiclib" if sys.platform == "darwin" else "-shared",
        "-I" + str(java_home / "include"),
        "-I"
        + str(
            java_home / "include" / ("darwin" if sys.platform == "darwin" else "linux")
        ),
        str(experiment / "JniMultipart.cpp"),
        "-o",
        str(native),
    ]
    run(native_command, output, "compile-jni", repo)
    versions = tomllib.loads((shared.parent / "gradle/libs.versions.toml").read_text())[
        "versions"
    ]
    compiler = re.search(
        r'kotlin\("multiplatform"\) version "([^"]+)"',
        (shared / "build.gradle.kts").read_text(),
    )[1]
    language = ".".join(versions["kotlin"].split(".")[:2])
    (fixture / "settings.gradle.kts").write_text("""pluginManagement {
  resolutionStrategy { eachPlugin {
    if (requested.id.id == "org.jetbrains.kotlin.jvm") useModule("org.jetbrains.kotlin:kotlin-gradle-plugin:${requested.version}")
  } }
  repositories { mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement { repositories { mavenCentral() } }
rootProject.name = "multipart-four-way-comparison"
""")
    (fixture / "gradle.properties").write_text(
        "kotlin.stdlib.default.dependency=false\n"
    )
    (fixture / "build.gradle.kts").write_text(
        """import org.jetbrains.kotlin.gradle.dsl.KotlinVersion
plugins { kotlin("jvm") version %s }
kotlin {
  jvmToolchain(17)
  compilerOptions {
    languageVersion.set(KotlinVersion.fromVersion(%s))
    apiVersion.set(KotlinVersion.fromVersion(%s))
  }
}
sourceSets { main { kotlin.srcDir("main") }; test { kotlin.srcDir("test") } }
dependencies {
  implementation(files(%s))
  implementation("org.jetbrains.kotlin:kotlin-stdlib:%s")
  implementation("com.squareup.okio:okio:%s")
  testImplementation("junit:junit:%s")
  testImplementation("org.assertj:assertj-core:%s")
}
tasks.test {
  systemProperty("multipart.jni.library", %s)
  testLogging { events("passed", "failed", "skipped") }
}
tasks.register("exportRuntimeClasspath") {
  dependsOn("classes")
  doLast { file("runtime-classpath.txt").writeText(sourceSets.main.get().runtimeClasspath.asPath) }
}
"""
        % (
            json.dumps(compiler),
            json.dumps(language),
            json.dumps(language),
            json.dumps(str(args.shared_jar)),
            versions["kotlin"],
            versions["okio"],
            versions["junit"],
            versions["assertj"],
            json.dumps(str(native)),
        )
    )
    gradle_command = [
        str(shared / "gradlew"),
        "--console=plain",
        "--max-workers=2",
        "--offline",
        "-p",
        str(fixture),
        "test",
        "exportRuntimeClasspath",
    ]
    run(gradle_command, output, "gradle-test", repo)
    suites = [
        ET.parse(p).getroot()
        for p in (fixture / "build/test-results/test").glob("TEST-*.xml")
    ]
    counts = {
        key: sum(int(s.get(key, 0)) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] != 39 or any(
        counts[key] for key in ("failures", "errors", "skipped")
    ):
        raise RuntimeError(f"Unexpected correctness suite result: {counts}")
    inputs = [
        adapter,
        tests,
        args.shared_jar,
        shared.parent / "gradle/libs.versions.toml",
    ] + [
        p
        for p in experiment.iterdir()
        if p.is_file()
        and (
            p.name.startswith(("Android", "Jni", "run-android"))
            or p.name == "MultipartCore.h"
        )
    ]
    source_hashes = {str(p.relative_to(repo)): sha(p) for p in inputs}
    generated_hashes = {
        str(p.relative_to(output)): sha(p)
        for sub in ("main", "test")
        for p in (fixture / sub).glob("*.kt")
    }
    classpath = (fixture / "runtime-classpath.txt").read_text()
    artifact_hashes = {str(native): sha(native)}
    for entry in classpath.split(os.pathsep):
        p = Path(entry)
        if p.is_file():
            artifact_hashes[str(p)] = sha(p)
        elif p.is_dir():
            artifact_hashes.update({str(f): sha(f) for f in p.rglob("*.class")})
    provenance = {
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "baseline": baseline_ref,
        "baselineSourceSha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "sourceHashes": source_hashes,
        "generatedHashes": generated_hashes,
        "artifactHashes": artifact_hashes,
        "compiler": compiler,
        "languageApi": language,
        "runtimeDependencies": versions,
        "javaHome": str(java_home),
        "javaVersion": subprocess.check_output(
            [str(java_home / "bin/java"), "-version"],
            stderr=subprocess.STDOUT,
            text=True,
        ),
        "clangVersion": subprocess.check_output(["clang++", "--version"], text=True),
        "commands": [native_command, gradle_command],
        "tests": counts,
        "nativeLibrary": str(native),
        "classpath": classpath,
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(
        json.dumps({"phase": "prepare", "tests": counts, "output": str(output)}),
        flush=True,
    )


def benchmark(args, repo, output):
    provenance = json.loads((output / "provenance.json").read_text())
    selected_baseline = subprocess.check_output(
        ["git", "rev-parse", f"{args.baseline_ref}^{{commit}}"], cwd=repo, text=True
    ).strip()
    if selected_baseline != provenance["baseline"]:
        raise RuntimeError("Benchmark baseline differs from the prepared fixture")
    for filename, expected in provenance["generatedHashes"].items():
        if sha(output / filename) != expected:
            raise RuntimeError(f"Generated source changed after prepare: {filename}")
    for filename, expected in provenance["sourceHashes"].items():
        if sha(repo / filename) != expected:
            raise RuntimeError(f"Source changed after prepare: {filename}")
    for filename, expected in provenance["artifactHashes"].items():
        if sha(Path(filename)) != expected:
            raise RuntimeError(f"Runtime artifact changed after prepare: {filename}")
    if args.processes < 3:
        raise RuntimeError("At least three fresh processes are required")
    process_results = []
    commands = []
    for process in range(args.processes):
        command = [
            str(Path(provenance["javaHome"]) / "bin/java"),
            "-Xms512m",
            "-Xmx512m",
            "-Dmultipart.jni.library=" + provenance["nativeLibrary"],
            "-cp",
            provenance["classpath"],
            "com.facebook.react.devsupport.AndroidComparisonKt",
            str(47017 + process * 997),
        ]
        commands.append(command)
        raw = output / f"jvm-process-{process + 1}.jsonl"
        with raw.open("w") as stream, (
            output / f"jvm-process-{process + 1}.stderr"
        ).open("w") as errors:
            subprocess.run(command, stdout=stream, stderr=errors, check=True)
        rows = [json.loads(line) for line in raw.read_text().splitlines()]
        samples = [r for r in rows if r["kind"] == "sample"]
        if len(samples) != 800:
            raise RuntimeError(f"Expected 800 samples, got {len(samples)}")
        summaries = []
        for workload in dict.fromkeys(r["workload"] for r in samples):
            subset = [r for r in samples if r["workload"] == workload]
            medians = {}
            for candidate in ("NATIVE", "OPTIMIZED_NATIVE", "CPP_JNI", "KMP"):
                group = [r for r in subset if r["implementation"] == candidate]
                if len(group) != 40 or any(
                    sum(r["position"] == p for r in group) != 10 for p in range(4)
                ):
                    raise RuntimeError("Sample order is not position-balanced")
                medians[candidate] = {
                    key: statistics.median(r[key] for r in group)
                    for key in ("nsPerParse", "jvmBytesPerParse")
                }
            summaries.append(
                {
                    "workload": workload,
                    "medians": medians,
                    "latencyRatiosToNative": {
                        k: v["nsPerParse"] / medians["NATIVE"]["nsPerParse"]
                        for k, v in medians.items()
                    },
                    "latencyRatiosToOptimizedNative": {
                        k: v["nsPerParse"] / medians["OPTIMIZED_NATIVE"]["nsPerParse"]
                        for k, v in medians.items()
                    },
                }
            )
        process_results.append(
            {
                "process": process + 1,
                "environment": rows[0],
                "rawSha256": sha(raw),
                "workloads": summaries,
            }
        )
    summary = {
        "head": provenance["head"],
        "baseline": provenance["baseline"],
        "processes": process_results,
        "commands": commands,
        "limitations": [
            "Host JVM; no Android ART, physical device, network or frame-time measurement",
            "Current-thread JVM allocation counter excludes native C++ vector/state and any JNI string/array copies",
            "Buffers, UTF-8 decoding, callbacks, body reads and draining retained; source construction excluded",
            "Development host samples include normal system activity; no universal confidence or device claims",
        ],
    }
    (output / "benchmark-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {
                "phase": "benchmark",
                "processes": len(process_results),
                "samples": len(process_results) * 800,
                "output": str(output),
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--shared-jar", type=Path)
    parser.add_argument("--phase", choices=("prepare", "benchmark"), default="prepare")
    parser.add_argument("--processes", type=int, default=3)
    args = parser.parse_args()
    experiment = Path(__file__).resolve().parent
    shared = experiment.parents[1]
    repo = shared.parents[2]
    args.shared_jar = (
        args.shared_jar or shared / "build/android/react-native-shared.jar"
    ).resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "prepare":
        if not args.shared_jar.is_file():
            parser.error("Build/export the shared JAR before this independent fixture")
        prepare(args, experiment, shared, repo, output)
    else:
        benchmark(args, repo, output)


if __name__ == "__main__":
    main()
