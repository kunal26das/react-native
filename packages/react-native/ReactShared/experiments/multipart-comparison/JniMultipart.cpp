/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// Experimental JNI transport. Payload buffers never cross this interface.
#include <jni.h>
#include <cstdint>
#include <limits>
#include <new>
#include "MultipartCore.h"

using rn_kmp_experiment::Framing;

static void outOfMemory(JNIEnv* env) {
  auto cls = env->FindClass("java/lang/OutOfMemoryError");
  if (cls)
    env->ThrowNew(cls, "multipart comparison native allocation");
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_facebook_react_devsupport_JniMultipart_create(
    JNIEnv* env,
    jobject,
    jint delimiter,
    jint close) {
  auto* state = new (std::nothrow) Framing(delimiter, close);
  if (!state)
    outOfMemory(env);
  return reinterpret_cast<jlong>(state);
}

extern "C" JNIEXPORT void JNICALL
Java_com_facebook_react_devsupport_JniMultipart_destroy(
    JNIEnv*,
    jobject,
    jlong handle) {
  delete reinterpret_cast<Framing*>(handle);
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_facebook_react_devsupport_JniMultipart_next(
    JNIEnv* env,
    jobject,
    jlong handle,
    jlong length,
    jlong offset,
    jlong delimiter,
    jlong close,
    jlongArray output) {
  auto* state = reinterpret_cast<Framing*>(handle);
  // Private Kotlin wrapper supplies a live, exclusively owned state and array.
  if (!state || env->GetArrayLength(output) != 5) {
    auto cls = env->FindClass("java/lang/IllegalStateException");
    if (cls)
      env->ThrowNew(cls, "invalid multipart comparison state");
    return false;
  }
  const auto chunk = state->nextChunk(length, offset, delimiter, close);
  const jlong values[5] = {
      state->searchStart(0),
      chunk ? chunk->start : 0,
      chunk ? chunk->end : 0,
      chunk && chunk->isPart,
      chunk && chunk->isLast};
  env->SetLongArrayRegion(output, 0, 5, values);
  return chunk.has_value();
}

extern "C" JNIEXPORT jintArray JNICALL
Java_com_facebook_react_devsupport_JniMultipart_headers(
    JNIEnv* env,
    jobject,
    jstring text) {
  const jsize length = env->GetStringLength(text);
  const jchar* chars = env->GetStringChars(text, nullptr);
  if (!chars)
    return nullptr;
  // GetStringChars may copy this header only; no critical section spans
  // allocation.
  try {
    const auto ranges = rn_kmp_experiment::parseHeaderUnits(chars, length);
    env->ReleaseStringChars(text, chars);
    chars = nullptr;
    if (ranges.size() >
        static_cast<size_t>(std::numeric_limits<jsize>::max()) / 4) {
      outOfMemory(env);
      return nullptr;
    }
    auto result = env->NewIntArray(static_cast<jsize>(ranges.size() * 4));
    if (!result || ranges.empty())
      return result;
    auto* packed = env->GetIntArrayElements(result, nullptr);
    if (!packed)
      return nullptr;
    size_t i = 0;
    for (const auto& range : ranges) {
      packed[i++] = static_cast<jint>(range.nameStart);
      packed[i++] = static_cast<jint>(range.nameLength);
      packed[i++] = static_cast<jint>(range.valueStart);
      packed[i++] = static_cast<jint>(range.valueLength);
    }
    env->ReleaseIntArrayElements(result, packed, 0);
    return result;
  } catch (const std::bad_alloc&) {
    if (chars)
      env->ReleaseStringChars(text, chars);
    outOfMemory(env);
    return nullptr;
  }
}
