/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * This source code is licensed under the MIT license found in the LICENSE file in
 * the root directory of this source tree.
 */

#import <Foundation/Foundation.h>
#import <React/RCTMultipartStreamReader.h>
#import "AppleMultipartWorkloads.h"

@interface RCTMultipartStreamReader (HeaderProbe)
- (NSDictionary *)parseHeaders:(NSData *)data;
@end
@interface RCTMultipartStreamReaderBaseline : NSObject
- (instancetype)initWithInputStream:(NSInputStream *)stream boundary:(NSString *)boundary;
- (BOOL)readAllPartsWithCompletionCallback:(RCTMultipartCallback)callback
                          progressCallback:(RCTMultipartProgressCallback)progressCallback;
- (NSDictionary *)parseHeaders:(NSData *)data;
@end
@interface AppleProbeStream : NSInputStream
@property (nonatomic, readonly) NSUInteger reads;
@property (nonatomic, readonly) NSUInteger offset;
- (instancetype)initWithData:(NSData *)data size:(NSUInteger)size errorAfter:(NSInteger)errorAfter;
@end
@implementation AppleProbeStream {
  NSData *_data;
  NSUInteger _size;
  NSUInteger _reads;
  NSUInteger _offset;
  NSInteger _errorAfter;
  BOOL _failed;
}
- (instancetype)initWithData:(NSData *)data size:(NSUInteger)size errorAfter:(NSInteger)errorAfter
{
  if ((self = [super init])) {
    _data = data;
    _size = size;
    _errorAfter = errorAfter;
  }
  return self;
}
- (void)open
{
}
- (NSUInteger)reads
{
  return _reads;
}
- (NSUInteger)offset
{
  return _offset;
}
- (NSError *)streamError
{
  return _failed ? [NSError errorWithDomain:@"AppleProbe" code:7 userInfo:nil] : nil;
}
- (NSInteger)read:(uint8_t *)buffer maxLength:(NSUInteger)length
{
  if (_errorAfter >= 0 && _reads >= (NSUInteger)_errorAfter) {
    _failed = YES;
    _reads++;
    return -1;
  }
  const NSUInteger schedule[] = {1, 7, 2, 31, 4096, 3, 13};
  NSUInteger cap = _size ?: schedule[_reads % 7];
  _reads++;
  NSUInteger count = MIN(MIN(length, cap), _data.length - _offset);
  [_data getBytes:buffer range:NSMakeRange(_offset, count)];
  _offset += count;
  return count;
}
@end

static void Require(BOOL condition, NSString *message)
{
  if (!condition) {
    fprintf(stderr, "FAIL: %s\n", message.UTF8String);
    exit(1);
  }
}
static NSDictionary *
Read(Class type, NSData *data, NSString *boundary, NSUInteger size, NSInteger errorAfter, BOOL throwCallback)
{
  AppleProbeStream *stream = [[AppleProbeStream alloc] initWithData:data size:size errorAfter:errorAfter];
  RCTMultipartStreamReader *reader = [[type alloc] initWithInputStream:stream boundary:boundary];
  NSMutableArray *parts = [NSMutableArray new];
  NSMutableArray *completedProgress = [NSMutableArray new];
  __block NSArray *progress;
  BOOL success = NO;
  NSArray *exception = @[];
  @try {
    success = [reader
        readAllPartsWithCompletionCallback:^(NSDictionary *headers, NSData *body, BOOL done) {
          [parts addObject:@[ headers ?: @{}, body, @(done) ]];
          [completedProgress addObject:progress ?: @[]];
          progress = nil;
          if (throwCallback)
            @throw [NSException exceptionWithName:@"ProbeCallback" reason:@"injected callback exception" userInfo:nil];
        }
        progressCallback:^(NSDictionary *headers, NSNumber *total, NSNumber *loaded) {
          progress = @[ headers, total, loaded ];
        }];
  } @catch (NSException *error) {
    exception = @[ error.name, error.reason ?: @"" ];
  }
  return @{
    @"success" : @(success),
    @"parts" : parts,
    @"finalProgress" : completedProgress,
    @"reads" : @(stream.reads),
    @"offset" : @(stream.offset),
    @"exception" : exception,
    @"streamError" : @(stream.streamError != nil)
  };
}
static NSData *Text(NSString *s)
{
  return [s dataUsingEncoding:NSUTF8StringEncoding];
}
static NSData *ManyParts(NSUInteger count)
{
  NSMutableData *data = [NSMutableData new];
  for (NSUInteger i = 0; i < count; i++) {
    [data
        appendData:
            Text([NSString
                stringWithFormat:
                    @"\r\n--sample\r\nContent-Type: application/json\r\nX-Progress: %lu\r\nContent-Length: 2\r\n\r\n{}",
                    (unsigned long)i])];
  }
  [data appendData:Text(@"\r\n--sample--\r\n")];
  return data;
}
int main(void)
{
  @autoreleasepool {
    Class baseline = RCTMultipartStreamReaderBaseline.class, selected = RCTMultipartStreamReader.class;
    NSArray<NSData *> *headers = @[
      Text(@""),
      Text(@"\r\n"),
      Text(@":"),
      Text(@"a:b:c\r\nA: d\r\na: final\r\n"),
      Text(@" 名😀 :\u00a0 value\u2003\r\nempty:\r\n: unnamed\r\nbad\r\nNUL:\0x"),
      Text(@"é:v\r\ne\u0301: w\r\nline\nbreak:x\r lone: yes\r\n"),
      [NSData dataWithBytes:"x:\xff\xfe\r\n" length:6]
    ];
    NSUInteger headerCases = 0, streamCases = 0;
    for (NSData *data in headers) {
      for (NSUInteger length = 0; length <= data.length; length++) {
        NSData *prefix = [data subdataWithRange:NSMakeRange(0, length)];
        id a = [[baseline alloc] initWithInputStream:[NSInputStream inputStreamWithData:[NSData data]]
                                            boundary:@"sample"];
        id b = [[selected alloc] initWithInputStream:[NSInputStream inputStreamWithData:[NSData data]]
                                            boundary:@"sample"];
        Require(
            [[a parseHeaders:prefix] isEqual:[b parseHeaders:prefix]],
            [NSString stringWithFormat:@"header %lu", (unsigned long)headerCases++]);
      }
    }
    NSMutableArray<NSData *> *inputs = [NSMutableArray arrayWithArray:@[
      Text(@""),
      Text(@"Yolo"),
      Text(@"\r\n--sample--\r\n"),
      Text(
          @"\r\n--sample\r\nContent-Length: -1\r\nContent-Length: 9999999999999999999999999999\r\n名😀: \u00a0value\u2003\r\n\r\nbody\r\n--sample--\r\n"),
      Text(
          @"\r\n--sample\r\nX: one\r\nx: two\r\n: blank\r\nX: three:four\r\n\r\n\0binary\r\n--samplX\r\n--sample--\r\n"),
      Text(@"pre\r\n--sample\r\nfirst\r\n--sample\r\nunfinished"),
      Text(@"\r\n--sample\r\nX: v\r\n\r\n\r\n--sample--\r\n")
    ]];
    NSMutableData *invalid = [Text(@"\r\n--sample\r\nX: ") mutableCopy];
    const uint8_t bytes[] = {0xff, 0xfe};
    [invalid appendBytes:bytes length:2];
    [invalid appendData:Text(@"\r\n\r\nbody\r\n--sample--\r\n")];
    [inputs addObject:invalid];
    for (NSData *data in inputs) {
      for (NSUInteger size = 0; size <= MAX((NSUInteger)1, data.length); size++) {
        for (NSNumber *error in @[ @-1, @0, @2 ]) {
          for (NSNumber *throws in @[ @NO, @YES ]) {
            NSDictionary *a = Read(baseline, data, @"sample", size, error.integerValue, throws.boolValue);
            NSDictionary *b = Read(selected, data, @"sample", size, error.integerValue, throws.boolValue);
            Require(
                [a isEqual:b],
                [NSString stringWithFormat:@"stream %lu size %lu error %@ throw %@\n%@\n%@",
                                           (unsigned long)streamCases++,
                                           (unsigned long)size,
                                           error,
                                           throws,
                                           a,
                                           b]);
          }
        }
      }
    }
    for (NSString *boundary in @[ @"", @"名😀", @"two words", @"colon:boundary" ]) {
      NSData *data =
          Text([NSString stringWithFormat:@"\r\n--%@\r\nX: v\r\n\r\nbody\r\n--%@--\r\n", boundary, boundary]);
      for (NSUInteger size = 0; size <= data.length; size++) {
        Require(
            [Read(baseline, data, boundary, size, -1, NO) isEqual:Read(selected, data, boundary, size, -1, NO)],
            @"boundary parity");
        streamCases++;
      }
    }
    NSData *many = ManyParts(64);
    for (NSNumber *size in @[ @0, @1, @7, @31, @4095, @4096, @4097 ]) {
      Require(
          [Read(baseline, many, @"sample", size.unsignedIntegerValue, -1, NO)
              isEqual:Read(selected, many, @"sample", size.unsignedIntegerValue, -1, NO)],
          @"many-part exact parity");
      streamCases++;
    }
    // Verify the exact four inputs subsequently used for timing, retaining all body bytes.
    for (NSArray<NSNumber *> *spec in
         @[ @[ @1024, @0 ], @[ @(2 * 1024 * 1024), @0 ], @[ @(20 * 1024 * 1024), @0 ], @[ @(2 * 1024 * 1024), @64 ] ]) {
      @autoreleasepool {
        NSData *data = AppleComparisonResponse(spec[0].unsignedIntegerValue, spec[1].unsignedIntegerValue);
        NSDictionary *a = Read(baseline, data, @"sample", 4096, -1, NO);
        NSDictionary *b = Read(selected, data, @"sample", 4096, -1, NO);
        Require([a[@"success"] boolValue], @"benchmark workload completion");
        Require([a[@"parts"] count] == spec[1].unsignedIntegerValue + 1, @"benchmark workload part count");
        Require([a isEqual:b], @"exact timed workload parity");
        streamCases++;
      }
    }
    printf(
        "{\"headerCases\":%lu,\"streamCases\":%lu,\"failures\":0,\"progressScope\":\"final progress per completed part; wall-clock-throttled intermediate event counts excluded\"}\n",
        (unsigned long)headerCases,
        (unsigned long)streamCases);
  }
  return 0;
}
