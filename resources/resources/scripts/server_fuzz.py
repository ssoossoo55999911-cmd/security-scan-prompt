#!/usr/bin/env python3
"""
Systematic fuzz tests for llama-server endpoints.
Tests extreme values for int/float/string parameters looking for crashes.
"""

import json
import time
import urllib.request
import struct
import sys
import os

BASE_URL = "http://localhost:9990"
ENDPOINTS = ["/completion", "/v1/completions"]

VERBOSE = os.environ.get("VERBOSE", "0") == "1"

def test(name, endpoint, data, timeout=5):
    """Send a request and check for crash or abnormal response."""
    if not endpoint.startswith("http"):
        url = BASE_URL + endpoint
    else:
        url = endpoint
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        start = time.time()
        resp = urllib.request.urlopen(req, timeout=timeout)
        elapsed = time.time() - start
        result = json.loads(resp.read().decode())
        status = resp.status

        if status == 200:
            return ("OK", f"status={status} time={elapsed:.2f}s")
        else:
            err = result.get("error", {}).get("message", "unknown")
            return ("ERROR", f"status={status} msg={err[:100]}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {}).get("message", "")
            return ("HTTP", f"HTTP {e.code}: {err[:100]}")
        except:
            return ("HTTP", f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        return ("CRASH", f"Connection refused/error: {e.reason}")
    except Exception as e:
        return ("UNKNOWN", str(e)[:100])

def check_server():
    """Verify server is alive."""
    try:
        urllib.request.urlopen(f"{BASE_URL}/health", timeout=2)
        return True
    except:
        return False

def run_tests():
    if not check_server():
        print("ERROR: Server is not running on port 9990")
        return False

    tests = []

    # === INT32 overflow tests ===
    INT32_MAX = 2147483647

    for endpoint in ENDPOINTS:
        # n_discard overflow (context shift)
        tests.append((
            f"n_discard=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_discard": INT32_MAX}
        ))

        # n_keep extreme
        tests.append((
            f"n_keep=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_keep": INT32_MAX}
        ))

        # n_predict large
        tests.append((
            f"n_predict=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": INT32_MAX}
        ))

        # negative n_predict
        tests.append((
            f"n_predict=-2@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": -2}
        ))

        # negative n_keep
        tests.append((
            f"n_keep=-2@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_keep": -2}
        ))

        # negative n_keep=-1 (special: use context size)
        tests.append((
            f"n_keep=-1@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_keep": -1}
        ))

        # n_probs=INT32_MAX
        tests.append((
            f"n_probs=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_probs": INT32_MAX}
        ))

        # min_keep=INT32_MAX
        tests.append((
            f"min_keep=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "min_keep": INT32_MAX}
        ))

        # n_indent=INT32_MAX
        tests.append((
            f"n_indent=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_indent": INT32_MAX}
        ))

        # n_cache_reuse=INT32_MAX
        tests.append((
            f"n_cache_reuse=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "n_cache_reuse": INT32_MAX}
        ))

        # seed=INT32_MAX (stored as uint32_t internally)
        tests.append((
            f"seed=INT32_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "seed": INT32_MAX}
        ))

        # seed=negative (also valid)
        tests.append((
            f"seed=-1@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "seed": -1}
        ))

        # t_max_predict_ms extreme
        tests.append((
            f"t_max_predict_ms=INT64_MAX@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "t_max_predict_ms": 9223372036854775807}
        ))

    # === Float extreme tests ===
    for endpoint in ENDPOINTS:
        # temperature extremes
        for temp in [1e38, -1e38, 0.0, 2.0]:
            tests.append((
                f"temperature={temp}@{endpoint}",
                endpoint,
                {"prompt": "hi", "n_predict": 1, "temperature": temp}
            ))

        # repeat_penalty extremes
        for rp in [1e38, -1e38, 0.0]:
            tests.append((
                f"repeat_penalty={rp}@{endpoint}",
                endpoint,
                {"prompt": "hi", "n_predict": 1, "repeat_penalty": rp}
            ))

        # dynatemp extreme (no limits)
        for dr in [1e38, -1e38]:
            tests.append((
                f"dynatemp_range={dr}@{endpoint}",
                endpoint,
                {"prompt": "hi", "n_predict": 1, "dynatemp_range": dr}
            ))

        # dry_multiplier extreme (no limits)
        for dm in [1e38, -1e38]:
            tests.append((
                f"dry_multiplier={dm}@{endpoint}",
                endpoint,
                {"prompt": "hi", "n_predict": 1, "dry_multiplier": dm}
            ))

        # top_p=0.0
        tests.append((
            f"top_p=0.0@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "top_p": 0.0}
        ))

        # mirostat extreme
        for miro in [-1, 3, 100]:
            tests.append((
                f"mirostat={miro}@{endpoint}",
                endpoint,
                {"prompt": "hi", "n_predict": 1, "mirostat": miro}
            ))

    # === Large payload tests ===
    for endpoint in ENDPOINTS:
        # Large logit_bias array
        tests.append((
            f"logit_bias=50k@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "logit_bias": [[i, 1.0] for i in range(50000)]}
        ))

        # Large stop array
        tests.append((
            f"stop=10k_strings@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "stop": ["word" + str(i) for i in range(10000)]}
        ))

    # === Type confusion tests ===
    for endpoint in ENDPOINTS:
        # String where int expected
        tests.append((
            f"temperature=string@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "temperature": "hello"}
        ))

        # Object where array expected
        tests.append((
            f"stop=object@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "stop": {"key": "value"}}
        ))

        # Int where bool expected
        tests.append((
            f"stream=42@{endpoint}",
            endpoint,
            {"prompt": "hi", "n_predict": 1, "stream": 42}
        ))

    # === Prompt-specific tests ===
    # Empty prompt
    tests.append(("empty_prompt", "/completion", {"prompt": "", "n_predict": 1}))

    # Very long prompt
    tests.append(("long_prompt_100k", "/completion",
                  {"prompt": "hi " * 50000, "n_predict": 1}))

    # Mixed token array prompt
    tests.append(("mixed_token_prompt", "/completion",
                  {"prompt": ["hi", 42, "there", 99]}))

    # Null prompt
    tests.append(("null_prompt", "/completion",
                  {"prompt": None, "n_predict": 1}))

    # === Negative slot test ===
    tests.append(("neg_id_slot", "/completion",
                  {"prompt": "hi", "n_predict": 1, "id_slot": -100}))

    # === RUN ALL TESTS ===
    passed = 0
    errors = 0
    crashes = 0
    unknown = 0

    for name, endpoint, data in tests:
        result, msg = test(name, endpoint, data, timeout=8)

        if VERBOSE or result in ("CRASH", "UNKNOWN"):
            print(f"[{result:7s}] {name:<55s} | {msg}")
        else:
            if result == "OK":
                print(f"[{result:7s}] {name:<55s}", end="\r", flush=True)

        if result == "OK":
            passed += 1
        elif result in ("ERROR", "HTTP"):
            errors += 1
        elif result == "CRASH":
            crashes += 1
            print(f"\n*** CRASH: {name}")
        else:
            unknown += 1
            print(f"\n??? UNKNOWN: {name}: {msg}")

        time.sleep(0.05)  # Don't flood

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {errors} errors, {crashes} crashes, {unknown} unknown")
    print(f"{'=' * 60}")

    return crashes == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
