# Copyright (c) Meta Platforms, Inc. and affiliates.
# This source code is licensed under the MIT license found in the LICENSE file in
# the root directory of this source tree.

"""Stage auditable variants of the exact production Apple multipart adapter."""

from pathlib import Path


def once(source, old, new):
    assert source.count(old) == 1, ("substitution count", source.count(old), old[:100])
    return source.replace(old, new)


def generate(source: str, output: Path):
    # The optimized control only removes intermediate line arrays/substrings. NSData decoding,
    # Foundation value trimming, dictionary key semantics, and all I/O remain unchanged.
    native_headers = """  NSArray<NSString *> *lines = [text componentsSeparatedByString:CRLF];
  for (NSString *line in lines) {
    NSUInteger location = [line rangeOfString:@":"].location;
    if (location == NSNotFound) {
      continue;
    }
    NSString *key = [line substringToIndex:location];
    NSString *value = [[line substringFromIndex:location + 1]
        stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    [headers setValue:value forKey:key];
  }"""
    optimized_headers = """  NSUInteger start = 0;
  NSUInteger length = text.length;
  while (start < length) {
    NSRange separator = [text rangeOfString:CRLF options:0 range:NSMakeRange(start, length - start)];
    NSUInteger end = separator.location == NSNotFound ? length : separator.location;
    NSRange colon = [text rangeOfString:@":" options:0 range:NSMakeRange(start, end - start)];
    if (colon.location != NSNotFound) {
      NSString *key = [text substringWithRange:NSMakeRange(start, colon.location - start)];
      NSString *value = [[text substringWithRange:NSMakeRange(colon.location + 1, end - colon.location - 1)]
          stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
      [headers setValue:value forKey:key];
    }
    if (separator.location == NSNotFound) break;
    start = end + 2;
  }"""
    optimized = once(source, native_headers, optimized_headers)
    cpp = once(
        source,
        "#import <ReactNativeShared/ReactNativeShared.h>",
        '#include "MultipartCore.h"\n#include <string>',
    )
    cpp = once(
        cpp,
        "#if RCT_USE_KMP && TARGET_OS_IOS && !TARGET_OS_MACCATALYST",
        "#if 1 // Experimental C++ core also compiles for Catalyst.",
    )
    cpp = once(
        cpp,
        """  for (RNSMultipartHeader *header in [RNSMultipartHeaders.shared parseText:text ?: @""]) {
    NSString *value = [header.value stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    [headers setValue:value forKey:header.name];
  }""",
        """  std::vector<unichar> units(text.length);
  if (text.length) [text getCharacters:units.data() range:NSMakeRange(0, text.length)];
  for (const auto &header : rn_kmp_experiment::parseHeaderUnits(units.data(), units.size())) {
    NSString *key = [text substringWithRange:NSMakeRange(header.nameStart, header.nameLength)];
    NSString *value = [[text substringWithRange:NSMakeRange(header.valueStart, header.valueLength)]
        stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    [headers setValue:value forKey:key];
  }""",
    )
    cpp = once(
        cpp,
        """  RNSMultipartFraming *framing = [[RNSMultipartFraming alloc] initWithDelimiterLength:(int32_t)delimiter.length
                                                                 closeDelimiterLength:(int32_t)closeDelimiter.length];""",
        """  rn_kmp_experiment::Framing framing((int32_t)delimiter.length, (int32_t)closeDelimiter.length);""",
    )
    cpp = once(
        cpp,
        """    NSInteger searchStart = [framing searchStartBufferOffset:0];
    NSInteger chunkStart = [framing partStartBufferOffset:0];""",
        """    NSInteger searchStart = framing.searchStart(0);
    NSInteger chunkStart = framing.partStart(0);""",
    )
    cpp = once(
        cpp,
        """    RNSMultipartChunk *chunk = [framing nextChunkBufferLength:content.length
                                                 bufferOffset:0
                                               delimiterIndex:isCloseDelimiter ? -1 : index
                                          closeDelimiterIndex:isCloseDelimiter ? index : -1];""",
        """    auto chunk = framing.nextChunk(content.length, 0, isCloseDelimiter ? -1 : index, isCloseDelimiter ? index : -1);""",
    )
    cpp = once(
        cpp,
        """    NSInteger chunkEnd = chunk.end;
    BOOL isPart = chunk.isPart;
    isCloseDelimiter = chunk.isLast;""",
        """    NSInteger chunkEnd = chunk->end;
    BOOL isPart = chunk->isPart;
    isCloseDelimiter = chunk->isLast;""",
    )
    variants = {"native": source, "optimized": optimized, "cpp": cpp, "kmp": source}
    for variant, text in variants.items():
        (output / ("AppleAdapter-" + variant + ".mm")).write_text(text)
    return variants
