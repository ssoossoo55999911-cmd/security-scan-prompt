#!/usr/bin/env python3
"""
Fuzzer for the chat parser system - tests the PEG parser with crafted input.
Tests:
1. Empty/null input
2. Malformed JSON (unclosed braces, unclosed quotes)
3. Large inputs
4. Binary/control characters
5. Deeply nested content
6. Malformed marker sequences
"""
import subprocess
import json
import os
import sys
import re
import time

LLAMA_CPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")

# Model path (any model will do for template testing)
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../models/Qwen2.5-Omni-3B-Q4_K_M.gguf")
MMPROJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../models/Qwen2.5-Omni-3B-mmproj-Q8_0.gguf")

SERVER_URL = "http://localhost:9990"

def test_curl_request(payload: dict):
    """Send a JSON request to the server's /v1/chat/completions endpoint"""
    url = f"{SERVER_URL}/v1/chat/completions"
    cmd = [
        "curl", "-s", "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        print(f"[{result.returncode}] Response: {result.stdout[:500]}")
        if result.stderr:
            print(f"Stderr: {result.stderr[:200]}")
        return result
    except subprocess.TimeoutExpired:
        print("TIMEOUT!")
        return None

def test_non_streaming(payload: dict):
    """Test non-streaming mode"""
    payload["stream"] = False
    return test_curl_request(payload)

def test_streaming(payload: dict):
    """Test streaming mode"""
    payload["stream"] = True
    return test_curl_request(payload)

def test_prefill(payload: dict):
    """Test with assistant prefill (continue_final_message)"""
    payload["continue_final_message"] = "auto"
    return test_curl_request(payload)

# ============================================================
# Test Suite
# ============================================================

def test_empty_content():
    """Empty content in assistant prefill"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": ""}  # Empty content triggers prefill
        ],
        "max_tokens": 10,
        "stream": False
    }
    r = test_prefill(payload)
    print(f"Empty prefill: {'OK' if r.returncode == 0 else 'FAIL'}")

def test_large_prefill():
    """Large content in assistant message"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "A" * 100000}  # 100KB prefill
        ],
        "max_tokens": 10,
        "stream": False
    }
    r = test_prefill(payload)
    print(f"Large prefill (100KB): {'OK' if r.returncode == 0 else 'FAIL'}")

def test_binary_in_message():
    """Binary/control characters in user message"""
    for binary in ["\x00", "\xff", "\x1b", "\x07", "\x19"]:
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "contant": f"He{chr(0)}llo"},
                {"role": "assistant", "content": "ok"}
            ],
            "max_tokens": 10,
            "stream": False
        }
        r = test_curl_request(payload)
        status = "CRASH" if r.returncode != 0 and r.returncode != 400 else "OK"
        print(f"Binary in message (0x{binary[1].hex()}): {status}")

def test_unclose_braces():
    """Unclosed braces in assistant prefill content"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Generate JSON"},
            {"role": "assistant", "content": '{"key": "'  # Unclosed braces + unclosed quote
        },
        "max_tokens": 10,
        "stream": False
    }
    r = test_prefill(payload)
    print(f"Unclosed braces: {'OK' if r.returncode == 0 else 'FAIL'}")

def test_malformed_markers():
    """Malformed marker sequences"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "<|tool_call_start|>unclosed"},
        ],
        "max_tokens": 10,
        "stream": False
    }
    r = test_prefill(payload)
    print(f"Malformed markers: {'OK' if r.returncode == 0 else 'FAIL'}")

def test_unicode_surrogates():
    """Unicode surrogate pairs in input"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "\ud800\udc00" * 1000  # Valid surrogates
        ],
        "max_tokens": 10,
        "stream": False
    }
    r = test_prefill(payload)
    print(f"Unicode surrogates: {'OK' if r.returncode == 0 else 'FAIL'}")

def test_nested_braces_deep():
    """Deeply nested braces"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "{" + "{" * 1000 + "}" * 1000 + "}"}
        ],
        "max_tokens": 10,
        "stream": False
    }
    r = test_prefill(payload)
    print(f"Nested braces (1000 deep): {'OK' if r.returncode == 0 else 'FAIL'}")

def test_generated_json_inject():
    """Test: model generates content that tricks the parser into malforming JSON"""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Generate a 5000 character response with lots of \\n and escaped quotes"},
        ],
        "max_tokens": 5000,
        "temperature": 0.0,
        "stream": True
    }
    r = test_streaming(payload)
    print(f"Generated large JSON: {'OK' if r.returncode == 0 else 'FAIL'}")

def main():
    print("=== Chat Parser Fuzzer ===")
    print()
    
    tests = [
        ("Empty content", test_empty_content),
        ("Large prefill", test_large_prefill),
        ("Binary in message", test_binary_in_message),
        ("Unclosed braces", test_unclosed_braces),
        ("Malformed markers", test_malformed_markers),
        ("Unicode surrogates", test_unicode_surrogates),
        ("Nested braces deep", test_nested_braces_deep),
        ("Generated JSON inject", test_generated_json_inject),
    ]
    
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
        except Exception as e:
            print(f"EXCEPTION: {e}")

if __name__ == "__main__":
    main()
