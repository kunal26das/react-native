/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * This source code is licensed under the MIT license found in the LICENSE file in
 * the root directory of this source tree.
 */

#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#import <React/RCTMultipartStreamReader.h>
#include <algorithm>
#include <array>
#include <cstdint>
#import "AppleMultipartWorkloads.h"

static void Require(BOOL ok)
{
  if (!ok) {
    fputs("benchmark correctness failure\n", stderr);
    exit(1);
  }
}
static uint64_t Parse(NSData *data, NSUInteger expectedParts, NSUInteger expectedFinalSize)
{
  NSInputStream *stream = [NSInputStream inputStreamWithData:data];
  RCTMultipartStreamReader *reader = [[RCTMultipartStreamReader alloc] initWithInputStream:stream boundary:@"sample"];
  __block NSUInteger count = 0;
  __block BOOL last = NO;
  __block uint64_t checksum = 0;
  __block NSUInteger loaded = 0;
  BOOL success = [reader
      readAllPartsWithCompletionCallback:^(NSDictionary *headers, NSData *body, BOOL done) {
        count++;
        last = done;
        checksum += body.length + headers.count + loaded;
        if (body.length)
          checksum += ((const uint8_t *)body.bytes)[0] + ((const uint8_t *)body.bytes)[body.length - 1];
        if (done)
          Require(body.length == expectedFinalSize);
        loaded = 0;
      }
      progressCallback:^(__unused NSDictionary *headers, __unused NSNumber *total, NSNumber *bytes) {
        loaded = bytes.unsignedIntegerValue;
      }];
  Require(success && last && count == expectedParts);
  return checksum;
}
static double Measure(NSData *data, NSUInteger count, NSUInteger size, uint64_t *checksum)
{
  CFTimeInterval start = CACurrentMediaTime();
  @autoreleasepool {
    *checksum = Parse(data, count, size);
  }
  return (CACurrentMediaTime() - start) * 1000.0;
}
static uint32_t Next(uint32_t &state)
{
  state = state * 1664525u + 1013904223u;
  return state;
}
static std::array<unsigned, 4> Shuffle(uint32_t &seed)
{
  std::array<unsigned, 4> order = {0, 1, 2, 3};
  for (unsigned i = 3; i > 0; i--)
    std::swap(order[i], order[Next(seed) % (i + 1)]);
  return order;
}
int main(int argc, const char **argv)
{
  @autoreleasepool {
    Require(argc == 3);
    NSString *variant = [NSString stringWithUTF8String:argv[1]];
    uint32_t seed = (uint32_t)strtoul(argv[2], nullptr, 10);
    uint32_t initialSeed = seed;
    NSArray *names = @[ @"small-1KiB", @"bundle-2MiB", @"bundle-20MiB", @"64-progress-parts-and-2MiB-bundle" ];
    const NSUInteger sizes[] = {1024, 2 * 1024 * 1024, 20 * 1024 * 1024, 2 * 1024 * 1024};
    const NSUInteger counts[] = {1, 1, 1, 65};
    NSArray<NSData *> *inputs = @[
      AppleComparisonResponse(sizes[0], 0),
      AppleComparisonResponse(sizes[1], 0),
      AppleComparisonResponse(sizes[2], 0),
      AppleComparisonResponse(sizes[3], 64)
    ];
    NSMutableArray *samples = [NSMutableArray new];
    NSMutableArray *first = [NSMutableArray new];
    uint64_t expected[4] = {};
    auto firstOrder = Shuffle(seed);
    for (unsigned c : firstOrder) {
      uint64_t checksum = 0;
      double ms = Measure(inputs[c], counts[c], sizes[c], &checksum);
      expected[c] = checksum;
      [first addObject:@{@"case" : names[c], @"ms" : @(ms), @"checksum" : @(checksum)}];
    }
    for (unsigned warm = 0; warm < 5; warm++) {
      auto order = Shuffle(seed);
      for (unsigned c : order) {
        uint64_t checksum = 0;
        Measure(inputs[c], counts[c], sizes[c], &checksum);
        Require(checksum == expected[c]);
      }
    }
    // Six shuffled Latin cycles: each case occurs six times in every timing position.
    for (unsigned cycle = 0; cycle < 6; cycle++) {
      auto base = Shuffle(seed);
      for (unsigned rotation = 0; rotation < 4; rotation++) {
        NSMutableArray *row = [NSMutableArray new];
        for (unsigned position = 0; position < 4; position++) {
          unsigned c = base[(position + rotation) % 4];
          uint64_t checksum = 0;
          double ms = Measure(inputs[c], counts[c], sizes[c], &checksum);
          Require(checksum == expected[c]);
          [row addObject:@{@"case" : names[c], @"ms" : @(ms), @"checksum" : @(checksum)}];
        }
        [samples addObject:row];
      }
    }
    NSDictionary *result = @{
      @"variant" : variant,
      @"seed" : @(initialSeed),
      @"warmupsPerCase" : @5,
      @"samplesPerCase" : @24,
      @"firstPerCase" : first,
      @"orderedSamples" : samples,
      @"scope" :
          @"full parser with scalar completion/progress callbacks; input construction excluded; firstPerCase order recorded, then warm steady samples"
    };
    puts([[NSString alloc] initWithData:[NSJSONSerialization dataWithJSONObject:result options:0 error:nil]
                               encoding:NSUTF8StringEncoding]
             .UTF8String);
  }
}
