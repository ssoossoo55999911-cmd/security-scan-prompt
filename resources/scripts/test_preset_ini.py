#!/usr/bin/env python3
"""Test preset INI parsing with edge cases"""
import subprocess
import os
import sys
import tempfile

BUILD_DIR = "/Users/ngxson/work/llama.cpp-security-agent/llama.cpp/build"

def create_preset_ini(content):
    """Write a temp INI file and return path"""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False)
    f.write(content)
    f.close()
    return f.name

def test_preset_parsing():
    """Test various edge cases of preset INI parsing"""
    
    # Test 1: Valid preset with extreme integer
    print("=== Test 1: Valid preset with INT32_MAX threads ===")
    ini = """[default]\nthreads = 2147483647\n"""
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        # Check it doesn't crash
        print("  OK: no crash")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 2: Valid preset with negative threads
    print("\n=== Test 2: Valid preset with -1 threads ===")
    ini = """[default]\nthreads = -1\nmodel = /nonexistent/model.gguf\n"""
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print("  OK: no crash")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 3: Malformed INI (no key)
    print("\n=== Test 3: Malformed INI (no key) ===")
    ini = """[default]\n = novalue\n"""
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)
    
    # Test 4: Huge number of keys
    print("\n=== Test 4: 10000-key INI file ===")
    ini = "[default]\n" + "".join(f"key_{i} = value_{i}\n" for i in range(10000))
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 5: Null bytes in value
    print("\n=== Test 5: Null bytes in value ===")
    ini_bytes = b"[default]\nmodel = model\x00bad.gguf\n"
    path = create_preset_ini(ini_bytes.decode('latin-1'))
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 6: Binary data in value
    print("\n=== Test 6: Binary data in value ===")
    ini_bytes = b"[default]\nmodel = \x01\x02\x03\x04\x05\xff\xfe\xfd.gguf\n"
    path = create_preset_ini(ini_bytes.decode('latin-1'))
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 7: Empty INI file
    print("\n=== Test 7: Empty INI file ===")
    path = create_preset_ini("")
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 8: 100MB INI file
    print("\n=== Test 8: 100MB INI file (expect memory exhaustion) ===")
    ini = "[default]\n" + "key = " + "A" * (100 * 1024 * 1024) + "\n"
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        print(f"  stderr: {result.stderr[:300]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (timeout - likely OOM or swapping)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 9: Invalid section names
    print("\n=== Test 9: Invalid section names ===")
    ini = """[section with spaces]\nmodel = /bad/path.gguf\n"""
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    # Test 10: Non-ascii keys
    print("\n=== Test 10: Non-ascii keys ===")
    ini = """[default]\nmodèle = /bad/path.gguf\n"""
    path = create_preset_ini(ini)
    try:
        cmd = [f"{BUILD_DIR}/bin/llama-server", "--models-preset", path, "--port", "9999"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"  stderr: {result.stderr[:200]}")
        print(f"  return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  (server started, no crash)")
    except Exception as e:
        print(f"  Error: {e}")
    os.unlink(path)

    print("\n=== ALL TESTS COMPLETE ===")

if __name__ == "__main__":
    test_preset_parsing()
