#!/usr/bin/env python3
"""Force context shift by filling context during generation with n_discard=INT32_MAX."""
import json, time, urllib.request, sys

BASE_URL = "http://localhost:9990"

def send(data, timeout=120):
    url = f"{BASE_URL}/completion"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return None, str(e)

# Fill context to ~8000 tokens
prefix = "The quick brown fox jumps over the lazy dog " * 800  # ~8000 tokens
print(f"Prompt: {len(prefix)} chars")
print("Sending completion with n_predict=9000 and n_discard=INT32_MAX...")
print("(This forces context shift when generation fills context)\n")

s, r = send({
    "prompt": prefix,
    "n_predict": 9000,  # Generate past context boundary
    "n_discard": 2147483647,  # INT32_MAX → overflow n_keep + n_discard
    "temperature": 0,
    "n_keep": 0,  # allow discarding
    "cache_prompt": False,
}, timeout=300)

print(f"Status: {s}")
if isinstance(r, dict):
    print(f"tokens_predicted: {r.get('tokens_predicted', 'N/A')}")
    print(f"truncated: {r.get('truncated', 'N/A')}")
    print(f"stop_type: {r.get('stop_type', 'N/A')}")
else:
    print(f"Response: {str(r)[:500]}")

# Check health
try:
    urllib.request.urlopen(f"{BASE_URL}/health", timeout=3)
    print("\nServer alive ✓")
except:
    print("\n*** SERVER DIED! ***")
