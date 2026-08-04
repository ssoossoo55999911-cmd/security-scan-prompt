#!/usr/bin/env python3
"""Test server with crafted audio/image files for overflow bugs"""

import json
import base64
import struct
import zlib
import subprocess
import requests
import time
import sys
import random

SERVER_URL = "http://localhost:9990"

def make_wav(claimed_samples):
    """Create a WAV header that claims huge number of samples but has minimal data"""
    sample_rate = 16000
    bits_per_sample = 16
    channels = 1
    
    data_size = min(claimed_samples * channels * bits_per_sample // 8, 0xFFFFFFF0)
    
    # RIFF header
    riff = b'RIFF'
    file_size = 36 + data_size
    wave = b'WAVE'
    
    # fmt chunk
    fmt = b'fmt '
    fmt_size = 16
    audio_format = 1  # PCM
    
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    
    fmt_data = struct.pack('<HHIIHH', 
        audio_format, channels, sample_rate,
        byte_rate, block_align, bits_per_sample)
    
    # data chunk header
    data_hdr = b'data'
    
    # Build header parts manually (to avoid overflow in struct.pack)
    header = b''.join([
        riff,
        struct.pack('<I', file_size & 0xFFFFFFFF),
        wave,
        fmt,
        struct.pack('<I', fmt_size),
        fmt_data,
        data_hdr,
        struct.pack('<I', data_size),
    ])
    
    # Add minimal audio data (just 1 byte)
    return header + b'\x00' * min(100, data_size)

def make_wav_big(samples):
    """Create WAV with large sample count but small actual data"""
    sample_rate = 16000
    bits_per_sample = 16
    channels = 1
    data_size = samples * channels * bits_per_sample // 8
    
    header = struct.pack('<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, channels, sample_rate,
        sample_rate * channels * bits_per_sample // 8,
        channels * bits_per_sample // 8, bits_per_sample,
        b'data', data_size)
    
    return header + b'\x00' * 100  # minimal data

def make_png_with_dim(width, height):
    """Create a valid PNG with given dimensions"""
    
    def make_chunk(chunk_type, data):
        crc = struct.pack('>I', 0)  # placeholder, most decoders don't check
        return struct.pack('>I', len(data)) + chunk_type + data + crc
    
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'
    
    # IHDR chunk with huge dimensions but 1-bit depth (tiny data)
    ihdr_data = struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0)
    ihdr = make_chunk(b'IHDR', ihdr_data)
    
    # IDAT chunk with minimal data (single transparent pixel)
    raw_data = b'\x00'  # filter byte + empty data (1-bit format)
    compressed = zlib.compress(raw_data)
    idat = make_chunk(b'IDAT', compressed)
    
    # IEND chunk
    iend = make_chunk(b'IEND', b'')
    
    return sig + ihdr + idat + iend

def test():
    """Test various attack vectors"""
    
    # Test 1: Crafted WAV with contradictory header (claims 4GB but has minimal data)
    print("=== Test 1: WAV with max data_size (claims 4GB samples) ===")
    
    wav_data = make_wav(0xFFFFFFFF)  # ~4GB
    b64 = base64.b64encode(wav_data).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this audio"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=15)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            print(f"  Response: {r.json().get('choices', [{}])[0].get('message', {}).get('content', '')[:200]}")
        else:
            print(f"  Error: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        print("  CONNECTION REFUSED - server may have crashed!")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 2: real image with 65535x65535 dimensions (should return reasonable tokens)
    print("\n=== Test 2: Real image max dimensions ===")
    
    huge_png = make_png_with_dim(65535, 65535)
    print(f"  PNG size: {len(huge_png)} bytes")
    b64 = base64.b64encode(huge_png).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What do you see in this image?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "max_tokens": 50,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            content = resp.get('choices', [{}])[0].get('message', {}).get('content', '')
            print(f"  Response: {content[:200]}")
            usage = resp.get('usage', {})
            print(f"  Tokens: prompt={usage.get('prompt_tokens', '?')}, completion={usage.get('completion_tokens', '?')}")
        else:
            print(f"  Error: {r.text[:300]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 3: Huge image that causes OOM
    print("\n=== Test 3: Image with 1000000x1000000 dimensions ===")
    huge_png = make_png_with_dim(1000000, 1000000)
    print(f"  PNG size: {len(huge_png)} bytes")
    b64 = base64.b64encode(huge_png).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        print(f"  Error: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        print("  CONNECTION REFUSED - server may have crashed!")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 4: Image preprocessing overflow (crafted dimensions)
    print("\n=== Test 4: Image with INT32_MAX x 1 dimensions ===")
    huge_png = make_png_with_dim(2147483647, 1)  # INT32_MAX x 1
    b64 = base64.b64encode(huge_png).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        print(f"  Error: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        print("  CONNECTION REFUSED - server may have crashed!")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 5: Audio with large sample count
    print("\n=== Test 5: WAV with large sample count ===")
    wav_data = make_wav_big(1000000000)  # ~1 billion samples (~2GB)
    print(f"  WAV size on disk: {len(wav_data)} bytes")
    print(f"  Claimed data_size: {2147483647 * 2} bytes = ~4GB")
    b64 = base64.b64encode(wav_data).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this audio"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            print(f"  Response: {resp.get('choices', [{}])[0].get('message', {}).get('content', '')[:200]}")
        else:
            print(f"  Error: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        print("  CONNECTION REFUSED - server may have crashed!")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 6: Audio file with minimal WAV header (no data chunk)
    print("\n=== Test 6: Malformed WAV header ===")
    
    header = b'RIFF' + struct.pack('<I', 36) + b'WAVE'
    b64 = base64.b64encode(header).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        print(f"  Error: {r.text[:300]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 7: MP3 with garbage header
    print("\n=== Test 7: MP3 format with minimal data ===")
    mp3_header = b'\xFF\xE0\x00\x00\x00\x00'  # MPEG sync, bitrate 0
    b64 = base64.b64encode(mp3_header).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            print(f"  Response: {resp.get('choices', [{}])[0].get('message', {}).get('content', '')[:200]}")
        else:
            print(f"  Error: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        print("  CONNECTION REFUSED - server may have crashed!")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 8: FLAC with minimal header
    print("\n=== Test 8: FLAC format ===")
    flac_data = b'fLaC\x00\x00\x22'  # minimal FLAC stream marker
    b64 = base64.b64encode(flac_data).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "flac"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            print(f"  Response: {resp.get('choices', [{}])[0].get('message', {}).get('content', '')[:200]}")
        else:
            print(f"  Error: {r.text[:300]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 9: Audio with zero sample rate
    print("\n=== Test 9: WAV with 0 sample rate ===")
    
    def make_wav_zero(claimed_samples):
        sample_rate = 0  # zero sample rate
        bits_per_sample = 16
        channels = 1
        data_size = min(claimed_samples * channels * bits_per_sample // 8, 0xFFFFFFF0)
        
        riff = b'RIFF'
        wave = b'WAVE'
        fmt = b'fmt '
        fmt_size = 16
        audio_format = 1  # PCM
        
        fmt_data = struct.pack('<HHIIHH', 
            audio_format, channels, sample_rate,
            0, 0, bits_per_sample)
        
        data_hdr = b'data'
        
        header = b''.join([
            riff,
            struct.pack('<I', 36 + data_size),
            wave,
            fmt,
            struct.pack('<I', fmt_size),
            fmt_data,
            data_hdr,
            struct.pack('<I', data_size),
        ])
        
        return header + b'\x00' * min(100, data_size)
    
    wav_data = make_wav_zero(1000)
    b64 = base64.b64encode(wav_data).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            print(f"  Response: {resp.get('choices', [{}])[0].get('message', {}).get('content', '')[:200]}")
        else:
            print(f"  Error: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        print("  CONNECTION REFUSED - server may have crashed!")
    except Exception as e:
        print(f"  Exception: {e}")

    print("\n=== ALL TESTS DONE ===")

if __name__ == "__main__":
    test()
