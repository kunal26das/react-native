/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

package com.facebook.react.devsupport;

import org.junit.runner.JUnitCore;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Separate ART correctness entry point; never calls the host JVM benchmark. */
public final class AndroidArtMain {
  public static void main(String[] args) {
    System.setProperty("multipart.jni.library", args[0]);
    boolean differentialOnly = args.length > 1 && args[1].equals("differential-only");
    Result result = differentialOnly
        ? JUnitCore.runClasses(AndroidComparisonTest.class)
        : JUnitCore.runClasses(
        AndroidNativeReaderTest.class,
        AndroidOptimizedReaderTest.class,
        AndroidCppReaderTest.class,
        AndroidKmpReaderTest.class,
        AndroidComparisonTest.class);
    for (Failure failure : result.getFailures()) {
      System.out.println(failure.getTrace());
    }
    System.out.println("ANDROID_ART_PARITY api=" + android.os.Build.VERSION.SDK_INT
        + " abi=" + android.os.Build.SUPPORTED_ABIS[0]
        + " mode=" + (differentialOnly ? "differential-only" : "full")
        + " tests=" + result.getRunCount()
        + " failures=" + result.getFailureCount()
        + " skipped=" + result.getIgnoreCount());
    if (!result.wasSuccessful() || result.getRunCount() != (differentialOnly ? 3 : 39) || result.getIgnoreCount() != 0) {
      System.exit(1);
    }
  }
}
