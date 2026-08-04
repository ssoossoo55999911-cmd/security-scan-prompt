#!/usr/bin/env python3
"""Test server image/audio input with crafted data"""

import json
import base64
import struct
import subprocess
import requests
import time
import sys

SERVER_URL = "http://localhost:9990"

def test_image():
    """Test various image attack vectors"""
    
    # Test 1: Send a crafted JPEG with extreme dimensions
    # We create a minimal JPEG header that claims 65535x65535 pixels
    # (the maximum JPEG can represent)
    print("=== Test 1: JPEG with max dimensions (65535x65535) ===")
    
    # Create a minimal valid JPEG with maximum dimensions
    # SOI marker: FF D8
    # APP0 marker: FF E0 00 10 4A 46 49 46 00 01 01 00 00 01 00 01 00 00
    # Then a tiny 1x1 MCU (Minimum Coded Unit) encoded
    img_data = bytes([
        0xFF, 0xD8,  # SOI
        # APP0
        0xFF, 0xE0, 0x00, 0x10,  
        0x4A, 0x46, 0x49, 0x46, 0x00,  # "JFIF\0"
        0x01, 0x01,  # version 1.01
        0x00,  # no density units
        # DQT marker - define quantization table
        0xFF, 0xDB, 0x00, 0x43, 0x00,
        *([0x01]*64),  # Q table (all 1s = no compression)
        # SOF0 - Start of Frame (baseline DCT)
        0xFF, 0xC0, 0x00, 0x0B,  # length = 11
        0x08,  # precision = 8
        0x00, 0x01,  # height = 1 (we'll use 1 to avoid OOM, but stash width for later)
        0x00, 0x01,  # width = 1
        0x01,  # num components = 1
        0x01, 0x11, 0x00,  # component 1: Y, 4:2:0, no table
        # DHT - Huffman table
        0xFF, 0xC4, 0x00, 0x1F, 0x00,
        *([0x00]*16),  # DC codes
        *([0x00]*12),  # AC codes
        # SOS - Start of Scan
        0xFF, 0xDA, 0x00, 0x08,
        0x01,  # num components = 1
        0x01, 0x00,  # component 1 uses table 0
        0x00, 0x3F, 0x00,  # entropy coded segment
        # Actual data: a tiny 1x1 MCU
        0x00, 0x00,  # just zeros = black pixel
        # EOI
        0xFF, 0xD9,  # End of Image
    ])
    
    b64 = base64.b64encode(img_data).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What do you see?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }
        ],
        "max_tokens": 10,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            print(f"  Response: {r.json().get('choices', [{}])[0].get('message', {}).get('content', '')[:100]}")
        else:
            print(f"  Error: {r.text[:200]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 2: EXTREMELY LARGE base64 (crafted header with huge dimensions)
    print("\n=== Test 2: Crafted JPEG claiming INT32_MAX pixels ===")
    # We craft a JPEG header that claims width=65535, height=65535
    # but with only 1 MCU (so actual data is tiny, but header says huge)
    # The image decoders like stb_image should handle this - they don't actually
    # *decode* the whole image, they just read dimensions. But if the decoder
    # tries to allocate width*height*channels, it could OOM.
    
    # Actually let's test with a REAL huge image: create a tiny valid PNG 
    # but with huge IHDR dimensions
    
    import struct
    
    def make_png(width, height):
        """Create a minimal valid PNG with given dimensions"""
        def make_chunk(chunk_type, data):
            chunk_len = struct.pack('>I', len(data))
            chunk_crc = struct.pack('>I', 0)  # we'll compute CRC later
            return chunk_len + chunk_type + data + chunk_crc
        
        # PNG signature
        sig = b'\x89PNG\r\n\x1a\n'
        
        # IHDR chunk
        ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)  # 8bpp RGB
        import zlib
        # IDAT: single black pixel
        raw_data = b'\x00\x00\x00\x00'  # filter byte + RGB black
        idat_data = zlib.compress(raw_data)
        
        # End chunk
        iend_data = b''
        
        return sig + make_chunk(b'IHDR', ihdr_data) + make_chunk(b'IDAT', idat_data) + make_chunk(b'IEND', iend_data)
    
    # PNG with huge dimensions but tiny data
    huge_png = make_png(65535, 65535)  # 65K x 65K
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
        if r.status_code == 200:
            print(f"  Response: {r.json().get('choices', [{}])[0].get('message', {}).get('content', '')[:100]}")
        else:
            print(f"  Error: {r.text[:200]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 3: Binary garbage (malformed image)
    print("\n=== Test 3: Malformed image (random bytes) ===")
    import random
    garbage = bytes([random.randint(0, 255) for _ in range(10000)])
    b64 = base64.b64encode(garbage).decode()
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Parse this image"},
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
        if r.status_code == 200:
            print(f"  Response: {r.json().get('choices', [{}])[0].get('message', {}).get('content', '')[:100]}")
        else:
            print(f"  Error: {r.text[:200]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 4: Base64 overflow (massive string)
    print("\n=== Test 4: Massive base64 payload ===")
    huge_b64 = "A" * 10 * 1024 * 1024  # 10MB of base64
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Process this"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{huge_b64}"}}
                ]
            }
        ],
        "max_tokens": 5,
        "stream": False,
    }
    
    try:
        r = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload, timeout=30)
        print(f"  Status: {r.status_code}")
        print(f"  Error: {r.text[:200]}")
    except requests.exceptions.ConnectionError:
        print("  Server crashed or refused connection!")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 5: Crafted WAV with extreme sample count
    print("\n=== Test 5: Crafted WAV with huge sample count ===")
    # WAV format: 44 bytes header + data
    # We craft a WAV that claims to have max uint32 samples
    def make_wav(num_samples):
        sample_rate = 16000
        bits_per_sample = 16
        channels = 1
        data_size = num_samples * channels * bits_per_sample // 8
        
        # RIFF header
        riff = b'RIFF'
        file_size = 36 + data_size
        wave = b'WAVE'
        
        # fmt chunk
        fmt = b'fmt '
        fmt_size = 16
        audio_format = 1  # PCM
        fmt_data = struct.pack('<IHHIIHH', 
            fmt_size, audio_format, channels, sample_rate,
            sample_rate * channels * bits_per_sample // 8,
            channels * bits_per_sample // 8,
            bits_per_sample)
        
        # data chunk
        data_chunk = b'data'
        
        # Build header
        header = struct.pack('<4sI4s4sIHHIIHH4sI',
            riff, file_size, wave,
            fmt, fmt_size, audio_format, channels,
            sample_rate, sample_rate * channels * bits_per_sample // 8,
            channels * bits_per_sample // 8, bits_per_sample,
            data_chunk, data_size)
        
        # Add 1 byte of actual audio data (to make it valid with minimum data)
        return header + b'\x00'  # single silent sample
    
    wav_data = make_wav(0xFFFFFFFF)  # 4GB of samples claimed
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
            print(f"  Response: {r.json().get('choices', [{}])[0].get('message', {}).get('content', '')[:100]}")
        else:
            print(f"  Error: {r.text[:200]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test 6: Audio with negative sample count
    print("\n=== Test 6: WAV with negative sample count ===")
    # Craft a WAV with INT32_MIN as sample count (interpreted as unsigned)
    # This will try to allocate 4GB of memory for the audio buffer
    def make_wav_signed(num_samples):
        """Create WAV with signed sample count (wraps to huge unsigned)"""
        sample_rate = 16000
        bits_per_sample = 16
        channels = 1
        # Use struct.pack with signed int for data_size
        data_size = num_samples * channels * bits_per_sample // 8
        
        # RIFF header
        riff = b'RIFF'
        file_size = 36 + data_size
        wave = b'WAVE'
        
        # fmt chunk
        fmt = b'fmt '
        fmt_size = 16
        audio_format = 1  # PCM
        fmt_data = struct.pack('<IHHIIHH',
            fmt_size, audio_format, channels, sample_rate,
            sample_rate * channels * bits_per_sample // 8,
            channels * bits_per_sample // 8,
            bits_per_sample)
        
        # data chunk
        data_chunk = b'data'
        
        header = struct.pack('<4sI4s4sIHHIIHH4si',
            riff, file_size, wave,
            fmt, fmt_size, audio_format, channels,
            sample_rate, int(sample_rate * channels * bits_per_sample // 8),
            channels * bits_per_sample // 8, bits_per_sample,
            data_chunk, data_size)
        
        return header + b'\x00' * 1  # minimal data
    
    # INT32_MIN / 4 (because each sample is 4 bytes for 16-bit stereo)
    # Actually use INT32_MAX / 2 + 1 which wraps to negative in signed int
    wav_data = make_wav_signed(2147483648)  # > INT32_MAX
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
            print(f"  Response: {r.json().get('choices', [{}])[0].get('message', {}).get('content', '')[:100]}")
        else:
            print(f"  Error: {r.text[:200]}")
    except Exception as e:
        print(f"  Exception: {e}")

    print("\n=== ALL TESTS DONE ===")

if __name__ == "__main__":
    test_image()
