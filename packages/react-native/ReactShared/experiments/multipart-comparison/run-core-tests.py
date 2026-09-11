#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Compare the C++ experiment with the actual Kotlin core and known stream results.

Build ReactShared's exportAndroidJar first. This runner uses that JAR and an
existing Kotlin stdlib JAR; it never downloads dependencies or runs Gradle.
The C++ executable runs with AddressSanitizer and UndefinedBehaviorSanitizer.
"""

import argparse
import hashlib
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import tempfile


CPP = r'''
#include "MultipartCore.h"
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
using namespace rn_kmp_experiment;

std::u16string decode(const std::string& value) {
  std::u16string result;
  if (value == "-") return result;
  if (value.size() % 4) throw std::runtime_error("Invalid UTF-16 fixture");
  for (size_t i = 0; i < value.size(); i += 4)
    result.push_back(static_cast<char16_t>(std::stoul(value.substr(i, 4), nullptr, 16)));
  return result;
}
std::string encode(std::u16string_view value) {
  if (value.empty()) return "-";
  std::string result;
  for (char16_t unit : value)
    for (int shift = 12; shift >= 0; shift -= 4)
      result.push_back("0123456789abcdef"[(unit >> shift) & 15]);
  return result;
}
void stream(std::istringstream& args) {
  size_t readSize;
  bool discard;
  std::string boundaryHex, inputHex;
  args >> readSize >> discard >> boundaryHex >> inputHex;
  const auto input = decode(inputHex);
  const auto boundary = decode(boundaryHex);
  const auto delimiter = u"\r\n--" + boundary + u"\r\n";
  const auto close = u"\r\n--" + boundary + u"--\r\n";
  Framing framing(static_cast<int32_t>(delimiter.size()), static_cast<int32_t>(close.size()));
  std::u16string buffer;
  size_t read = 0;
  int64_t offset = 0;
  bool complete = false;
  std::vector<std::u16string> parts;
  for (size_t step = 0; ; ++step) {
    if (!readSize || step > input.size() * 4 + 64) throw std::runtime_error("Stream did not terminate");
    const auto start = framing.searchStart(offset);
    if (start < 0) throw std::runtime_error("Negative search position in valid stream");
    const auto normal = buffer.find(delimiter, static_cast<size_t>(start));
    const auto closing = normal == std::u16string::npos
        ? buffer.find(close, static_cast<size_t>(start)) : std::u16string::npos;
    const auto chunk = framing.nextChunk(static_cast<int64_t>(buffer.size()), offset,
        normal == std::u16string::npos ? -1 : static_cast<int64_t>(normal),
        closing == std::u16string::npos ? -1 : static_cast<int64_t>(closing));
    if (!chunk) {
      if (read == input.size()) break;
      const auto count = std::min(readSize, input.size() - read);
      buffer.append(input, read, count);
      read += count;
    } else {
      if (chunk->start < 0 || chunk->end < chunk->start ||
          static_cast<uint64_t>(chunk->end) > buffer.size())
        throw std::runtime_error("Invalid chunk bounds in valid stream");
      if (chunk->isPart)
        parts.push_back(buffer.substr(static_cast<size_t>(chunk->start),
            static_cast<size_t>(chunk->end - chunk->start)));
      if (chunk->isLast) { complete = true; break; }
      if (discard) {
        buffer.erase(0, static_cast<size_t>(chunk->end));
        offset += chunk->end;
      }
    }
  }
  std::cout << "P " << complete << ' ' << parts.size();
  for (const auto& part : parts) std::cout << ' ' << encode(part);
  std::cout << '\n';
}
int main() {
  const auto unicode = parseHeaders(u"\U0001f642:v\r\né:x");
  if (unicode.size() != 2 || unicode[0].nameStart != 0 || unicode[0].nameLength != 2 ||
      unicode[0].valueStart != 3 || unicode[0].valueLength != 1 || unicode[1].nameStart != 6 ||
      unicode[1].nameLength != 1 || unicode[1].valueStart != 8 || unicode[1].valueLength != 1)
    throw std::runtime_error("Header positions must count UTF-16 code units");
  std::optional<Framing> framing;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream args(line);
    char operation;
    args >> operation;
    if (operation == 'F') {
      int32_t normal, close;
      args >> normal >> close;
      framing.emplace(normal, close);
    } else if (operation == 'S') {
      int64_t offset;
      args >> offset;
      std::cout << "S " << framing->searchStart(offset) << ' ' << framing->partStart(offset) << '\n';
    } else if (operation == 'C') {
      int64_t length, offset, normal, close;
      args >> length >> offset >> normal >> close;
      const auto chunk = framing->nextChunk(length, offset, normal, close);
      if (!chunk) std::cout << "C -\n";
      else std::cout << "C " << chunk->start << ' ' << chunk->end << ' '
          << chunk->isPart << ' ' << chunk->isLast << '\n';
    } else if (operation == 'H') {
      std::string hex;
      args >> hex;
      const auto text = decode(hex);
      const auto headers = parseHeaders(text);
      const std::vector<uint16_t> nativeUnits(text.begin(), text.end());
      const auto nativeHeaders = parseHeaderUnits(nativeUnits.data(), nativeUnits.size());
      if (nativeHeaders.size() != headers.size()) throw std::runtime_error("Native UTF-16 units differ");
      for (size_t i = 0; i < headers.size(); ++i)
        if (nativeHeaders[i].nameStart != headers[i].nameStart ||
            nativeHeaders[i].nameLength != headers[i].nameLength ||
            nativeHeaders[i].valueStart != headers[i].valueStart ||
            nativeHeaders[i].valueLength != headers[i].valueLength)
          throw std::runtime_error("Native UTF-16 ranges differ");
      std::cout << "H " << headers.size();
      for (const auto& header : headers) {
        if (header.nameStart > text.size() || header.nameLength > text.size() - header.nameStart ||
            header.valueStart > text.size() || header.valueLength > text.size() - header.valueStart)
          throw std::runtime_error("Header range out of bounds");
        std::cout << ' ' << encode(std::u16string_view(text).substr(header.nameStart, header.nameLength))
            << ':' << encode(std::u16string_view(text).substr(header.valueStart, header.valueLength));
      }
      std::cout << '\n';
    } else if (operation == 'P') stream(args);
    else throw std::runtime_error("Unknown fixture operation");
  }
}
'''


JAVA = r'''
import com.facebook.react.shared.MultipartChunk;
import com.facebook.react.shared.MultipartFraming;
import com.facebook.react.shared.MultipartHeader;
import com.facebook.react.shared.MultipartHeaders;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.List;

public class KotlinOracle {
  static String decode(String value) {
    if (value.equals("-")) return "";
    char[] result = new char[value.length() / 4];
    for (int i = 0; i < result.length; ++i)
      result[i] = (char) Integer.parseInt(value.substring(i * 4, i * 4 + 4), 16);
    return new String(result);
  }
  static String encode(String value) {
    if (value.isEmpty()) return "-";
    StringBuilder result = new StringBuilder();
    for (int i = 0; i < value.length(); ++i)
      for (int shift = 12; shift >= 0; shift -= 4)
        result.append("0123456789abcdef".charAt((value.charAt(i) >> shift) & 15));
    return result.toString();
  }
  public static void main(String[] ignored) throws Exception {
    BufferedReader input = new BufferedReader(new InputStreamReader(System.in));
    MultipartFraming framing = null;
    for (String line; (line = input.readLine()) != null;) {
      String[] args = line.split(" ");
      switch (args[0]) {
        case "F": framing = new MultipartFraming(Integer.parseInt(args[1]), Integer.parseInt(args[2])); break;
        case "S": {
          long offset = Long.parseLong(args[1]);
          System.out.println("S " + framing.searchStart(offset) + " " + framing.partStart(offset));
          break;
        }
        case "C": {
          MultipartChunk chunk = framing.nextChunk(Long.parseLong(args[1]), Long.parseLong(args[2]),
              Long.parseLong(args[3]), Long.parseLong(args[4]));
          System.out.println(chunk == null ? "C -" : "C " + chunk.getStart() + " " + chunk.getEnd()
              + " " + (chunk.isPart() ? 1 : 0) + " " + (chunk.isLast() ? 1 : 0));
          break;
        }
        case "H": {
          List<MultipartHeader> headers = MultipartHeaders.INSTANCE.parse(decode(args[1]));
          StringBuilder result = new StringBuilder("H " + headers.size());
          for (MultipartHeader header : headers)
            result.append(' ').append(encode(header.getName())).append(':').append(encode(header.getValue()));
          System.out.println(result);
          break;
        }
        default: throw new IllegalArgumentException(line);
      }
    }
  }
}
'''


def utf16(text):
    return text.encode("utf-16-be", "surrogatepass").hex() or "-"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-jar", type=pathlib.Path)
    parser.add_argument("--stdlib-jar", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    directory = pathlib.Path(__file__).resolve().parent
    shared = directory.parents[1]
    shared_jar = (args.shared_jar or shared / "build/android/react-native-shared.jar").resolve()
    if not shared_jar.is_file():
        parser.error("Build ReactShared exportAndroidJar first, or provide --shared-jar")
    stdlib = args.stdlib_jar
    if stdlib is None:
        kotlin_version = re.search(r'kotlin\("multiplatform"\) version "([^"]+)"',
                                   (shared / "build.gradle.kts").read_text()).group(1)
        candidates = list((pathlib.Path(os.environ.get("GRADLE_USER_HOME", pathlib.Path.home() / ".gradle"))
                           / "caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib" / kotlin_version)
                          .glob(f"*/kotlin-stdlib-{kotlin_version}.jar"))
        if not candidates:
            parser.error("Provide --stdlib-jar; no cached Kotlin stdlib found")
        stdlib = max(candidates, key=lambda path: path.stat().st_mtime)
    if not stdlib.is_file():
        parser.error("Kotlin stdlib JAR does not exist")
    output = (args.output or pathlib.Path(tempfile.mkdtemp(prefix="multipart-core-test-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cpp = output / "core-test.cpp"
    cpp.write_text(CPP)
    java = output / "KotlinOracle.java"
    java.write_text(JAVA)
    cxx = os.environ.get("CXX", "clang++")
    compile_command = [cxx, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-I", str(directory), str(cpp), "-o", str(output / "core-test")]
    subprocess.run(compile_command, check=True)
    java_home = pathlib.Path(os.environ["JAVA_HOME"]) / "bin" if "JAVA_HOME" in os.environ else None
    javac = str(java_home / "javac") if java_home else shutil.which("javac")
    java_bin = str(java_home / "java") if java_home else shutil.which("java")
    if not javac or not java_bin:
        parser.error("A JDK is required for the actual Kotlin oracle")
    classpath = os.pathsep.join(map(str, [shared_jar, stdlib.resolve(), output]))
    subprocess.run([javac, "-cp", classpath, str(java)], check=True)

    rng = random.Random(0x4D50415254)
    long_edges = [-(1 << 63), -(1 << 63) + 1, -(1 << 31), -2, -1, 0, 1, 7, 31,
                  (1 << 31) - 1, (1 << 31) + 100, (1 << 63) - 2, (1 << 63) - 1]
    lengths = [-(1 << 31), -1, 0, 1, 7, 9, (1 << 31) - 1]
    commands = []
    for case in range(4096):
        normal, close = (7, 9) if case % 2 else (rng.choice(lengths), rng.choice(lengths))
        commands.append(f"F {normal} {close}")
        for _ in range(16):
            offset = rng.choice(long_edges) if rng.randrange(2) else rng.randrange(-(1 << 63), 1 << 63)
            length, normal_index, close_index = (rng.choice(long_edges) for _ in range(3))
            commands.extend([f"S {offset}", f"C {length} {offset} {normal_index} {close_index}", f"S {offset}"])

    headers = ["", ":", "\r\n", "x:\r\n", "x:1:2", "a\nb:c\rd", "\r\nx:1\r\n\r\n",
               " Content-Type : text/plain:extra \r\ninvalid\r\nx:1\r\nX:2\r\n:empty\r\n",
               "🙂:e\u0301\r\n\ud800:\udfff\r\n\u0000:x"]
    alphabet = ["x", " ", "\t", ":", "\r", "\n", "\r\n", "é", "🙂", "\ud800", "\udfff", "\u0000"]
    headers += ["".join(rng.choice(alphabet) for _ in range(rng.randrange(100))) for _ in range(10000)]
    commands += ["H " + utf16(value) for value in headers]
    corpus = "\n".join(commands) + "\n"
    (output / "differential-input.txt").write_text(corpus)
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"

    def execute(command, text, label):
        result = subprocess.run(command, input=text, text=True, capture_output=True, env=environment)
        (output / (label + ".stdout")).write_text(result.stdout)
        (output / (label + ".stderr")).write_text(result.stderr)
        result.check_returncode()
        return result.stdout.splitlines()

    actual = execute([str(output / "core-test")], corpus, "cpp")
    oracle = execute([java_bin, "-Xmx512m", "-cp", classpath, "KotlinOracle"], corpus, "kotlin")
    expected_results = 4096 * 16 * 3 + len(headers)
    if len(actual) != expected_results or len(oracle) != expected_results:
        raise AssertionError(f"Expected {expected_results} results, got C++={len(actual)}, Kotlin={len(oracle)}")
    if actual != oracle:
        for index, (left, right) in enumerate(zip(actual, oracle)):
            if left != right:
                raise AssertionError(f"Differential result {index}: C++={left!r}, Kotlin={right!r}; corpus retained at {output}")
        raise AssertionError(f"Result count differs: C++={len(actual)}, Kotlin={len(oracle)}")

    # Independent expected states: >2 GB offset rebasing, overlap, unchanged
    # closing state, and a normal delimiter later than the closing delimiter.
    offset = (1 << 31) + 100
    known_commands = ["F 7 9", "S 0", f"C {offset + 7} 0 {offset} -1", f"S {offset}",
                      f"C 30 {offset} -1 -1", f"S {offset}", f"C 40 {offset} -1 31", f"S {offset}",
                      "F 7 9", "C 40 0 20 5", "S 0"]
    known_expected = ["S 0 0", f"C 0 {offset} 0 0", "S 7 7", "C -", "S 21 7", "C 7 31 1 1",
                      "S 21 7", "C 0 20 0 0", "S 27 27"]
    known = "\n".join(known_commands) + "\n"
    known_actual = execute([str(output / "core-test")], known, "known-states")
    known_oracle = execute([java_bin, "-cp", classpath, "KotlinOracle"], known, "known-kotlin-states")
    if known_actual != known_expected or known_oracle != known_expected:
        raise AssertionError("Known offset/precedence/closing states differ; results retained")

    body = "binary\u0000\r\n--samplX\r\n\r\n--sample-\r\n"
    samples = [
        ("preamble\r\n--sample\r\nA: b\r\n\r\none\r\n--sample\r\ntwo\r\n--sample--\r\nepilogue", ["A: b\r\n\r\none", "two"], True),
        ("\r\n--sample\r\n" + body + "\r\n--sample--\r\n", [body], True),
        ("preamble\r\n--sample--\r\n", [], True),
        ("no delimiter", [], False),
        ("\r\n--sample\r\nfirst\r\n--sample\r\nincomplete", ["first"], False),
        ("\r\n--sample\r\n\r\n--sample--\r\n", [""], True),
    ]
    stream_commands, stream_expected = [], []
    for text, parts, complete in samples:
        for read_size in range(1, len(text) + 2):
            for discard in [0, 1]:
                stream_commands.append(f"P {read_size} {discard} {utf16('sample')} {utf16(text)}")
                stream_expected.append(f"P {int(complete)} {len(parts)}" + "".join(" " + utf16(part) for part in parts))
    stream_corpus = "\n".join(stream_commands) + "\n"
    (output / "stream-input.txt").write_text(stream_corpus)
    stream_actual = execute([str(output / "core-test")], stream_corpus, "stream")
    if stream_actual != stream_expected:
        raise AssertionError("Known multipart parts/completion differ; stream corpus and results retained")

    source = shared / "src/commonMain/kotlin/com/facebook/react/shared/MultipartFraming.kt"
    report = {
        "validation": "passed", "framingStateMachines": 4096,
        "framingTransitions": 4096 * 16, "stateQueries": 4096 * 16 * 2,
        "headerCases": len(headers), "streamFragmentationAndRetentionCases": len(stream_commands),
        "uint16AndChar16RangeEquivalenceCases": len(headers),
        "independentExpectedStateQueriesAndChunks": len(known_expected),
        "sanitizers": ["address", "undefined"], "compilerCommand": compile_command,
        "coreHeaderSha256": hashlib.sha256((directory / "MultipartCore.h").read_bytes()).hexdigest(),
        "kotlinSourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sharedJar": str(shared_jar), "sharedJarSha256": hashlib.sha256(shared_jar.read_bytes()).hexdigest(),
        "stdlibJar": str(stdlib.resolve()), "output": str(output),
        "scope": "Core behavior only: no JNI, Objective-C interop, I/O, trimming, dictionary policy or performance claims.",
    }
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
