/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <string_view>
#include <vector>

namespace rn_kmp_experiment {

struct Chunk {
  int64_t start;
  int64_t end;
  bool isPart;
  bool isLast;
};

// Experimental counterpart of MultipartFraming.kt. The caller keeps ownership
// of its buffer and searches for delimiters; this class only tracks offsets.
class Framing {
 public:
  Framing(int32_t delimiterLength, int32_t closeDelimiterLength) noexcept
      : delimiterLength_(delimiterLength),
        closeDelimiterLength_(closeDelimiterLength) {}

  int64_t searchStart(int64_t bufferOffset) const noexcept {
    return subtract(
        std::max(subtract(bytesSeen_, closeDelimiterLength_), chunkStart_),
        bufferOffset);
  }

  int64_t partStart(int64_t bufferOffset) const noexcept {
    return subtract(chunkStart_, bufferOffset);
  }

  std::optional<Chunk> nextChunk(
      int64_t bufferLength,
      int64_t bufferOffset,
      int64_t delimiterIndex,
      int64_t closeDelimiterIndex) noexcept {
    const bool isClosing = delimiterIndex < 0;
    const int64_t end = isClosing ? closeDelimiterIndex : delimiterIndex;
    if (end < 0) {
      bytesSeen_ = add(bufferOffset, bufferLength);
      return std::nullopt;
    }

    const Chunk chunk{partStart(bufferOffset), end, hasBoundary_, isClosing};
    if (!isClosing) {
      hasBoundary_ = true;
      chunkStart_ = add(add(bufferOffset, end), delimiterLength_);
      bytesSeen_ = chunkStart_;
    }
    return chunk;
  }

 private:
  // Kotlin Long arithmetic wraps. Use unsigned operations and an in-range
  // conversion so even extreme synthetic offsets do not invoke C++ signed UB.
  static int64_t signedValue(uint64_t value) noexcept {
    return value <= static_cast<uint64_t>(std::numeric_limits<int64_t>::max())
        ? static_cast<int64_t>(value)
        : -1 - static_cast<int64_t>(~value);
  }

  static int64_t add(int64_t left, int64_t right) noexcept {
    return signedValue(static_cast<uint64_t>(left) + static_cast<uint64_t>(right));
  }

  static int64_t subtract(int64_t left, int64_t right) noexcept {
    return signedValue(static_cast<uint64_t>(left) - static_cast<uint64_t>(right));
  }

  const int32_t delimiterLength_;
  const int32_t closeDelimiterLength_;
  int64_t chunkStart_ = 0;
  int64_t bytesSeen_ = 0;
  bool hasBoundary_ = false;
};

struct HeaderRange {
  size_t nameStart;
  size_t nameLength;
  size_t valueStart;
  size_t valueLength;
};

// Accept native UTF-16 units (jchar/unichar) without aliasing them as char16_t.
// Pointer and length avoid nonstandard std::char_traits<unsigned short>.
template <typename CharT>
std::vector<HeaderRange> parseHeaderUnits(const CharT* units, size_t length) {
  std::vector<HeaderRange> headers;
  size_t lineStart = 0;
  size_t colon = length;
  const auto append = [&](size_t lineEnd) {
    if (colon != length) {
      headers.push_back(
          {lineStart, colon - lineStart, colon + 1, lineEnd - colon - 1});
    }
  };
  for (size_t index = 0; index < length; ++index) {
    if (units[index] == static_cast<CharT>('\r') && index + 1 < length &&
        units[index + 1] == static_cast<CharT>('\n')) {
      append(index);
      lineStart = index + 2;
      colon = length;
      ++index;
    } else if (colon == length && units[index] == static_cast<CharT>(':')) {
      colon = index;
    }
  }
  append(length);
  return headers;
}

// Ranges refer to the original UTF-16 input, including unpaired surrogates.
// Keep whitespace, empty fields and duplicates as MultipartHeaders.parse does;
// the native adapter retains responsibility for trimming and dictionary policy.
inline std::vector<HeaderRange> parseHeaders(std::u16string_view text) {
  return parseHeaderUnits(text.data(), text.size());
}

} // namespace rn_kmp_experiment
