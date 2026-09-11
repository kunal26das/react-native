/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

@file:Suppress("DEPRECATION_ERROR")

package com.facebook.react.devsupport

import java.lang.management.ManagementFactory
import java.util.Random
import okio.Buffer
import okio.BufferedSource

internal enum class AndroidCandidate {
  NATIVE,
  OPTIMIZED_NATIVE,
  CPP_JNI,
  KMP,
}

internal interface AndroidListener {
  fun complete(headers: Map<String, String>, body: BufferedSource, last: Boolean)

  fun progress(headers: Map<String, String>, loaded: Long, total: Long) = Unit
}

internal fun response(parts: Int, bodySize: Int, headers: Int = 2, bundleSize: Int = 0): ByteArray {
  val b = Buffer().writeUtf8("preamble")
  fun part(size: Int, index: Int) {
    b.writeUtf8(
      "\r\n--sample\r\nContent-Length: $size\r\nContent-Type: application/octet-stream\r\n"
    )
    repeat(headers - 2) { b.writeUtf8("X-Header-$it: value:$it\r\n") }
    b.writeUtf8("\r\n")
    b.write(ByteArray(size) { ((it + index) % 251).toByte() })
  }
  repeat(parts) { part(bodySize, it) }
  if (bundleSize > 0) part(bundleSize, parts)
  return b.writeUtf8("\r\n--sample--\r\nepilogue").readByteArray()
}

private fun consume(candidate: AndroidCandidate, source: BufferedSource): Long {
  var digest = 0L
  val scratch = Buffer()
  check(
    dispatchReader(
      candidate,
      source,
      "sample",
      object : AndroidListener {
        override fun complete(headers: Map<String, String>, body: BufferedSource, last: Boolean) {
          digest = digest * 31 + headers.hashCode()
          digest = digest * 31 + if (last) 1 else 0
          while (true) {
            val read = body.read(scratch, 8192)
            if (read == -1L) break
            digest += read
            scratch.clear()
          }
        }
      },
    )
  )
  return digest
}

private data class Workload(val name: String, val input: ByteArray, val batch: Int)

fun main(args: Array<String>) {
  val seed = args.firstOrNull()?.toLong() ?: 47017L
  val bean = ManagementFactory.getThreadMXBean() as com.sun.management.ThreadMXBean
  check(bean.isThreadAllocatedMemorySupported)
  bean.isThreadAllocatedMemoryEnabled = true
  val threadId = Thread.currentThread().id
  val candidates = AndroidCandidate.values().toList()
  val random = Random(seed)
  val workloads =
    listOf(
      Workload("small-1KiB", response(1, 1024, 8), 64),
      Workload("bundle-2MiB", response(1, 2 * 1024 * 1024), 1),
      Workload("bundle-20MiB", response(1, 20 * 1024 * 1024), 1),
      Workload("many-128x1KiB", response(128, 1024, 8), 2),
      Workload("progress-128x128B-plus-2MiB", response(128, 128, 4, 2 * 1024 * 1024), 1),
    )
  println(
    """{"kind":"environment","seed":$seed,"javaVersion":"${System.getProperty("java.version")}","vm":"${System.getProperty("java.vm.name")}","warmupRounds":24,"sampleRounds":40,"allocations":"JVM current-thread allocations; excludes all native/JNI allocations"}"""
  )
  for (workload in workloads) {
    val expected = consume(AndroidCandidate.NATIVE, Buffer().write(workload.input))
    fun measure(candidate: AndroidCandidate): Pair<Double, Double> {
      // Fixture input and source construction are deliberately outside the timer/counter.
      val sources = Array(workload.batch) { Buffer().write(workload.input) }
      val digests = LongArray(workload.batch)
      val allocated = bean.getThreadAllocatedBytes(threadId)
      val start = System.nanoTime()
      for (i in sources.indices) digests[i] = consume(candidate, sources[i])
      val elapsed = System.nanoTime() - start
      val bytes = bean.getThreadAllocatedBytes(threadId) - allocated
      check(digests.all { it == expected })
      return elapsed.toDouble() / workload.batch to bytes.toDouble() / workload.batch
    }
    // Four randomized rotations per block balance every implementation in every position.
    fun orders(rounds: Int): List<List<AndroidCandidate>> = buildList {
      repeat(rounds / 4) {
        val shuffled = candidates.shuffled(random)
        val rotations = (0..3).shuffled(random)
        for (shift in rotations) add(List(4) { shuffled[(it + shift) % 4] })
      }
    }
    for (order in orders(24)) for (candidate in order) measure(candidate)
    for ((round, order) in orders(40).withIndex()) {
      for ((position, candidate) in order.withIndex()) {
        val (ns, bytes) = measure(candidate)
        println(
          """{"kind":"sample","workload":"${workload.name}","inputBytes":${workload.input.size},"batch":${workload.batch},"round":$round,"position":$position,"implementation":"$candidate","nsPerParse":$ns,"jvmBytesPerParse":$bytes}"""
        )
      }
    }
  }
}
