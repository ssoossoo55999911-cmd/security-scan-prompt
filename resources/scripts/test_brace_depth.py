#!/usr/bin/env python3
"""Quick test: malformed JSON in assistant prefill with lots of closing braces"""
import subprocess, json, sys

SERVER = 'http://localhost:9990/v1/chat/completions'

payload = {
    'model': 'gpt-3.5-turbo',
    'messages': [
        {'role': 'user', 'content': 'Test'},
        {'role': 'assistant', 'content': '{}' + '}' * 1000  # Lots of closing braces
    ],
    'stream': False,
    'max_tokens': 1,
}
r = subprocess.run(['curl', '-s', '-X', 'POST', SERVER,
                     '-H', 'Content-Type: application/json',
                     '-d', json.dumps(payload)], capture_output=True, text=True, timeout=15)
print('rc=' + str(r.returncode))
print('body=' + r.stdout[:500])
if r.stderr: print('stderr=' + r.stderr[:200])
