/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

/* Experimental comparison only; no production integration. */
package com.facebook.react.devsupport

internal object JniMultipart {
  init {
    System.load(requireNotNull(System.getProperty("multipart.jni.library")))
  }

  external fun create(delimiterLength: Int, closeDelimiterLength: Int): Long

  external fun destroy(handle: Long)

  external fun next(
    handle: Long,
    length: Long,
    offset: Long,
    delimiter: Long,
    close: Long,
    out: LongArray,
  ): Boolean

  external fun headers(text: String): IntArray
}

internal class JniFraming(delimiterLength: Int, closeDelimiterLength: Int) : AutoCloseable {
  private val output = LongArray(5)
  private var handle = JniMultipart.create(delimiterLength, closeDelimiterLength)

  fun searchStart(offset: Long): Long = output[0] - offset

  fun nextChunk(length: Long, offset: Long, delimiter: Long, close: Long): JniChunk? {
    check(handle != 0L)
    if (!JniMultipart.next(handle, length, offset, delimiter, close, output)) return null
    return JniChunk(output[1], output[2], output[3] != 0L, output[4] != 0L)
  }

  override fun close() {
    if (handle != 0L) {
      JniMultipart.destroy(handle)
      handle = 0L
    }
  }
}

internal class JniChunk(val start: Long, val end: Long, val isPart: Boolean, val isLast: Boolean)

internal fun putTrimmedHeader(
  headers: MutableMap<String, String>,
  text: String,
  nameStart: Int,
  nameEnd: Int,
  valueStart: Int,
  valueEnd: Int,
) {
  var ns = nameStart
  var ne = nameEnd
  var vs = valueStart
  var ve = valueEnd
  while (ns < ne && text[ns] <= ' ') ns++
  while (ne > ns && text[ne - 1] <= ' ') ne--
  while (vs < ve && text[vs] <= ' ') vs++
  while (ve > vs && text[ve - 1] <= ' ') ve--
  headers[text.substring(ns, ne)] = text.substring(vs, ve)
}

internal fun scanNativeHeaders(headers: MutableMap<String, String>, text: String) {
  var start = 0
  while (start <= text.length) {
    val found = text.indexOf("\r\n", start)
    val end = if (found < 0) text.length else found
    var colon = start
    while (colon < end && text[colon] != ':') colon++
    if (colon < end) putTrimmedHeader(headers, text, start, colon, colon + 1, end)
    if (found < 0) break
    start = found + 2
  }
}

internal fun scanJniHeaders(headers: MutableMap<String, String>, text: String) {
  val ranges = JniMultipart.headers(text)
  var i = 0
  while (i < ranges.size) {
    putTrimmedHeader(
      headers,
      text,
      ranges[i],
      ranges[i] + ranges[i + 1],
      ranges[i + 2],
      ranges[i + 2] + ranges[i + 3],
    )
    i += 4
  }
}
