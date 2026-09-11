/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

@file:Suppress("DEPRECATION_ERROR")

package com.facebook.react.devsupport

import java.io.IOException
import java.util.Random
import okio.Buffer
import okio.BufferedSource
import okio.ByteString
import okio.ForwardingSource
import okio.Okio
import org.junit.Assert.*
import org.junit.Test

class AndroidComparisonTest {
  private data class Progress(val headers: Map<String, String>, val loaded: Long, val total: Long)

  private data class Part(
    val headers: Map<String, String>,
    val body: ByteString,
    val last: Boolean,
    val finalProgress: Progress?,
  )

  private data class Result(val success: Boolean, val parts: List<Part>, val error: String?)

  private fun capture(candidate: AndroidCandidate, bytes: ByteArray, fragment: Long): Result {
    val source =
      Okio.buffer(
        object : ForwardingSource(Buffer().write(bytes)) {
          override fun read(sink: Buffer, byteCount: Long): Long =
            super.read(sink, minOf(fragment, byteCount))
        }
      )
    val parts = mutableListOf<Part>()
    var latestProgress: Progress? = null
    try {
      return Result(
        dispatchReader(
          candidate,
          source,
          "sample",
          object : AndroidListener {
            override fun complete(
              headers: Map<String, String>,
              body: BufferedSource,
              last: Boolean,
            ) {
              parts += Part(headers.toMap(), body.readByteString(), last, latestProgress)
              latestProgress = null
            }

            override fun progress(headers: Map<String, String>, loaded: Long, total: Long) {
              latestProgress = Progress(headers.toMap(), loaded, total)
            }
          },
        ),
        parts,
        null,
      )
    } catch (error: Exception) {
      return Result(false, parts, error.javaClass.name + ":" + error.message)
    }
  }

  @Test
  fun fullParserDifferentialAcrossFragmentsAndMalformedUtf8() {
    val random = Random(84151)
    val inputs = mutableListOf<ByteArray>()
    inputs += response(1, 0)
    inputs += response(5, 731, 8)
    inputs += response(128, 128, 4, 2 * 1024 * 1024)
    inputs += "none".toByteArray()
    inputs +=
      "\r\n--sample\r\nContent-Length: nope\r\n\r\n${"x".repeat(32768)}\r\n--sample--\r\n"
        .toByteArray()
    repeat(80) {
      val headers = buildString {
        append("content-length: 4\r\n")
        repeat(1 + random.nextInt(12)) {
          val chars = listOf("plain", "ß", "İ", "\u00a0", "\t ", "🙂", "", "a:b")
          append(chars[random.nextInt(chars.size)])
          if (random.nextInt(5) != 0) append(':')
          append(chars[random.nextInt(chars.size)])
          append("\r\n")
        }
      }
      val b = Buffer().writeUtf8("\r\n--sample\r\n$headers\r\nbody\r\n--sample--\r\n")
      inputs += b.readByteArray()
    }
    inputs +=
      Buffer()
        .writeUtf8("\r\n--sample\r\nX-")
        .write(byteArrayOf(0xc3.toByte(), 0x28))
        .writeUtf8(": value\r\n\r\nbody\r\n--sample--\r\n")
        .readByteArray()
    var comparisons = 0
    for (input in inputs) for (fragment in listOf(1L, 3L, 17L, 16384L)) {
      // Keep the very large fixture bounded; byte-by-byte paths are exercised by small cases.
      if (input.size > 100_000 && fragment < 16384) continue
      val expected = capture(AndroidCandidate.NATIVE, input, fragment)
      for (candidate in AndroidCandidate.values().drop(1)) {
        assertEquals(
          "$candidate fragment=$fragment input=${input.size}",
          expected,
          capture(candidate, input, fragment),
        )
        comparisons++
      }
    }
    println("ANDROID_DIFFERENTIAL_COMPARISONS=$comparisons")
  }

  @Test
  fun callbackExceptionDrainsBodyWithoutClosingSource() {
    for (candidate in AndroidCandidate.values()) {
      var closed = false
      var borrowed: BufferedSource? = null
      val source =
        Okio.buffer(
          object : ForwardingSource(Buffer().write(response(2, 31))) {
            override fun close() {
              closed = true
              super.close()
            }
          }
        )
      val expected = IOException("callback sentinel")
      try {
        dispatchReader(
          candidate,
          source,
          "sample",
          object : AndroidListener {
            override fun complete(
              headers: Map<String, String>,
              body: BufferedSource,
              last: Boolean,
            ) {
              borrowed = body
              body.readByte()
              throw expected
            }
          },
        )
        fail("callback exception not propagated")
      } catch (actual: IOException) {
        assertSame(expected, actual)
      }
      assertNotNull(borrowed)
      assertTrue(borrowed!!.exhausted())
      assertFalse(closed)
    }
  }

  @Test
  fun ioExceptionAndProgressCallbackExceptionPropagate() {
    for (candidate in AndroidCandidate.values()) {
      val expected = IOException("I/O sentinel")
      val source =
        Okio.buffer(
          object : ForwardingSource(Buffer().write(response(1, 65536))) {
            var calls = 0

            override fun read(sink: Buffer, byteCount: Long): Long {
              if (++calls == 2) throw expected
              return super.read(sink, minOf(1024, byteCount))
            }
          }
        )
      try {
        dispatchReader(
          candidate,
          source,
          "sample",
          object : AndroidListener {
            override fun complete(
              headers: Map<String, String>,
              body: BufferedSource,
              last: Boolean,
            ) {
              body.skip(Long.MAX_VALUE)
            }
          },
        )
        fail("I/O exception not propagated")
      } catch (actual: IOException) {
        assertSame(expected, actual)
      }
      val progressFailure = IllegalStateException("progress sentinel")
      try {
        dispatchReader(
          candidate,
          Buffer().write(response(1, 65536)),
          "sample",
          object : AndroidListener {
            override fun complete(
              headers: Map<String, String>,
              body: BufferedSource,
              last: Boolean,
            ) = Unit

            override fun progress(headers: Map<String, String>, loaded: Long, total: Long) {
              throw progressFailure
            }
          },
        )
        fail("progress exception not propagated")
      } catch (actual: IllegalStateException) {
        assertSame(progressFailure, actual)
      }
    }
  }
}
