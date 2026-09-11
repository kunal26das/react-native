/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * This source code is licensed under the MIT license found in the LICENSE file in
 * the root directory of this source tree.
 */

#pragma once

#import <Foundation/Foundation.h>

static NSData *AppleComparisonText(NSString *s)
{
  return [s dataUsingEncoding:NSUTF8StringEncoding];
}
static NSData *AppleComparisonResponse(NSUInteger bytes, NSUInteger progressParts)
{
  NSMutableData *data = [AppleComparisonText(@"preamble") mutableCopy];
  for (NSUInteger i = 0; i < progressParts; i++) {
    NSString *progress =
        [NSString stringWithFormat:@"{\"done\":%lu,\"total\":64,\"status\":\"Bundling\"}", (unsigned long)i];
    NSData *body = AppleComparisonText(progress);
    [data
        appendData:
            AppleComparisonText([NSString
                stringWithFormat:
                    @"\r\n--sample\r\nContent-Type: application/json\r\nContent-Length: %lu\r\nX-Progress: %lu\r\n\r\n",
                    (unsigned long)body.length,
                    (unsigned long)i])];
    [data appendData:body];
  }
  [data
      appendData:
          AppleComparisonText([NSString
              stringWithFormat:
                  @"\r\n--sample\r\nContent-Type: application/javascript\r\nContent-Length: %lu\r\nX-Metro-Files-Changed-Count: 17\r\nX-Test: one:two\r\n\r\n",
                  (unsigned long)bytes])];
  NSMutableData *body = [NSMutableData dataWithLength:bytes];
  uint8_t *buffer = (uint8_t *)body.mutableBytes;
  for (NSUInteger i = 0; i < bytes; i++)
    buffer[i] = (uint8_t)(i % 251);
  [data appendData:body];
  [data appendData:AppleComparisonText(@"\r\n--sample--\r\nepilogue")];
  return data;
}
