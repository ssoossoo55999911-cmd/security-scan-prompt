#!/usr/bin/env python3
"""
Craft a GGUF with 0 tokens in the vocabulary by copying an existing model
and replacing the tokenizer.ggml.tokens array with an empty one.
"""

import sys
import os
import struct
from pathlib import Path

gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
if gguf_path.exists():
    sys.path.insert(0, str(gguf_path))

import gguf

VT = gguf.GGUFValueType

def main():
    input_file = Path("models/LFM2-Audio-1.5B-Q8_0.gguf")
    output = Path("models/crafted/vocab_empty_tokens.gguf")
    output.parent.mkdir(parents=True, exist_ok=True)

    reader = gguf.GGUFReader(str(input_file))

    if os.path.exists(str(output)):
        os.remove(str(output))
    writer = gguf.GGUFWriter(str(output), "lfm2")

    for field in reader.fields.values():
        name = field.name
        # Skip tokens, scores, token_type — we'll add empty versions
        if name in ("tokenizer.ggml.tokens", "tokenizer.ggml.scores", "tokenizer.ggml.token_type"):
            continue
        # Skip general.architecture — writer already added it
        if name == "general.architecture":
            continue

        if len(field.parts) == 0:
            continue

        vtype = field.types[0]

        try:
            if vtype == VT.STRING:
                val = str(bytes(field.parts[-1]), 'utf-8', errors='replace')
                writer.add_string(name, val)
            elif vtype == VT.UINT32:
                val = int(field.parts[-1][0])
                writer.add_uint32(name, val)
            elif vtype == VT.INT32:
                val = int(field.parts[-1][0])
                writer.add_int32(name, val)
            elif vtype == VT.FLOAT32:
                val = float(field.parts[-1][0])
                writer.add_float32(name, val)
            elif vtype == VT.BOOL:
                val = bool(field.parts[-1][0])
                writer.add_bool(name, val)
            elif vtype == VT.UINT64:
                val = int(field.parts[-1][0])
                writer.add_uint64(name, val)
            elif vtype == VT.ARRAY:
                # Skip arrays (tokens, merges, etc.)
                pass
        except Exception as e:
            print(f"  Skipping {name} (type={vtype}): {e}")

    # Add empty token arrays — this creates n_vocab = 0
    writer.add_array("tokenizer.ggml.tokens", [])
    writer.add_array("tokenizer.ggml.scores", [])
    writer.add_array("tokenizer.ggml.token_type", [])

    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()

    print(f"Written: {output}")

if __name__ == "__main__":
    main()