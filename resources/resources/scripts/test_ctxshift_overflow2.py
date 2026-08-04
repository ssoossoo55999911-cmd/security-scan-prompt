#!/usr/bin/env python3
"""Test n_keep + n_discard signed int overflow (both INT32_MAX)."""
import json, time, urllib.request

BASE_URL = "http://localhost:9990"

def send(data, timeout=120):
    url = f"{BASE_URL}/completion"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return None, str(e)

# Prompt that fills ~7800 tokens of 8192 context
prefix = "The quick brown fox jumps over the lazy dog " * 780

print(f"Prompt: {len(prefix)} chars (~7800 tokens)")
print("Sending with n_keep=INT32_MAX, n_discard=INT32_MAX, n_predict=400...\n")

s, r = send({
    "prompt": prefix,
    "n_predict": 400,      # generate enough to trigger context shift
    "n_keep": 2147483647,  # INT32_MAX
    "n_discard": 2147483647,  # INT32_MAX
    "temperature": 0,
    "cache_prompt": False,
}, timeout=180)

print(f"Status: {s}")
if isinstance(r, dict):
    print(f"tokens_predicted: {r.get('tokens_predicted', 'N/A')}")
    print(f"truncated: {r.get('truncated', 'N/A')}")
    print(f"stop_type: {r.get('stop_type', 'N/A')}")
    tokens_eval = r.get("timings", {}).get("prompt_n", 0)
    print(f"prompt_n: {tokens_eval}")
else:
    print(f"Response: {str(r)[:500]}")

# Check health
time.sleep(1)
try:
    urllib.request.urlopen(f"{BASE_URL}/health", timeout=3)
    print("Server alive ✓")
except:
    print("SERVER DIED!")
