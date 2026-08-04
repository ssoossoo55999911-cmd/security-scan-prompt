#!/usr/bin/env python3
"""
Craft malicious GGUF files by modifying/adding metadata and tensor info.
Targets deep vulnerabilities in llama.cpp model loader, clip, mtmd.

Usage:
  # Modify existing metadata key in-place
  python3 gguf_craft.py set <input.gguf> <key> <value>
  
  # Copy GGUF with multiple metadata changes (inc. adding new keys)
  python3 gguf_craft.py batch <input.gguf> --set key1=val1 --add key2=val2:uint32 --output <out.gguf>
  
  # Dump metadata
  python3 gguf_craft.py dump <input.gguf>
  
  # Dump tensor info
  python3 gguf_craft.py tensors <input.gguf>
"""

import sys
import os
import argparse
from pathlib import Path

# Load local gguf package
gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
if gguf_path.exists():
    sys.path.insert(0, str(gguf_path))

import gguf
import numpy as np


# ---- Type conversion helpers ----

TYPE_MAP = {
    'uint8':   (gguf.GGUFValueType.UINT8,   lambda v: int(v)),
    'int8':    (gguf.GGUFValueType.INT8,    lambda v: int(v)),
    'uint16':  (gguf.GGUFValueType.UINT16,  lambda v: int(v)),
    'int16':   (gguf.GGUFValueType.INT16,   lambda v: int(v)),
    'uint32':  (gguf.GGUFValueType.UINT32,  lambda v: int(v)),
    'int32':   (gguf.GGUFValueType.INT32,   lambda v: int(v)),
    'float32': (gguf.GGUFValueType.FLOAT32, lambda v: float(v)),
    'float64': (gguf.GGUFValueType.FLOAT64, lambda v: float(v)),
    'bool':    (gguf.GGUFValueType.BOOL,    lambda v: v.lower() in ('true', '1', 'yes')),
    'string':  (gguf.GGUFValueType.STRING,  lambda v: str(v)),
    'uint64':  (gguf.GGUFValueType.UINT64,  lambda v: int(v)),
    'int64':   (gguf.GGUFValueType.INT64,   lambda v: int(v)),
}


def _convert_type(val_type, type_str, raw_value):
    """Convert a raw value string to the right GGUF type.
    Returns (val_type, sub_type, converted_value).
    If type_str is 'auto', use the existing val_type.
    """
    if type_str == 'auto':
        # Keep existing type, just convert the value
        if val_type is None:
            raise ValueError("Cannot auto-detect type for a new key; specify type explicitly")
        converter = TYPE_MAP_REVERSE.get(val_type)
        if converter is None:
            raise ValueError(f"Cannot auto-convert type {val_type}")
        new_val = converter(raw_value)
        return val_type, None, new_val
    if type_str not in TYPE_MAP:
        raise ValueError(f"Unknown type: {type_str}, known: {list(TYPE_MAP.keys())}")
    new_val_type, converter = TYPE_MAP[type_str]
    new_val = converter(raw_value)
    return new_val_type, None, new_val


TYPE_MAP_REVERSE = {
    gguf.GGUFValueType.UINT8:   lambda v: int(v),
    gguf.GGUFValueType.INT8:    lambda v: int(v),
    gguf.GGUFValueType.UINT16:  lambda v: int(v),
    gguf.GGUFValueType.INT16:   lambda v: int(v),
    gguf.GGUFValueType.UINT32:  lambda v: int(v),
    gguf.GGUFValueType.INT32:   lambda v: int(v),
    gguf.GGUFValueType.FLOAT32: lambda v: float(v),
    gguf.GGUFValueType.FLOAT64: lambda v: float(v),
    gguf.GGUFValueType.BOOL:    lambda v: v.lower() in ('true', '1', 'yes'),
    gguf.GGUFValueType.STRING:  lambda v: str(v),
    gguf.GGUFValueType.UINT64:  lambda v: int(v),
    gguf.GGUFValueType.INT64:   lambda v: int(v),
}


# ---- Dump metadata ----

def dump_metadata(input_path):
    """Dump all metadata from a GGUF file."""
    reader = gguf.GGUFReader(input_path, 'r')
    for key, field in reader.fields.items():
        if key.startswith('GGUF.'):
            continue
        val = field.contents()
        if isinstance(val, list) and len(val) > 10:
            print(f"  {key}: [{field.types}] len={len(val)}, first={val[0]}")
        else:
            print(f"  {key}: {val}  [{field.types}]")


# ---- Dump tensors ----

def dump_tensors(input_path):
    """Dump all tensor info from a GGUF file."""
    reader = gguf.GGUFReader(input_path, 'r')
    total_bytes = 0
    print(f"{'Name':<50s} {'Shape':<25s} {'Type':<10s} {'Bytes':>10s}")
    print("-" * 100)
    for tensor in reader.tensors:
        shape_str = "x".join(str(d) for d in tensor.data.shape)
        total_bytes += tensor.n_bytes
        print(f"{tensor.name:<50s} {shape_str:<25s} {str(tensor.data.dtype):<10s} {tensor.n_bytes:>10,d}")
    print("-" * 100)
    print(f"  Total: {len(reader.tensors)} tensors, {total_bytes / 1024 / 1024:.1f} MiB")


# ---- Copy-with-modifications ----

def set_metadata(input_path, output_path, modifications, additions=None):
    """
    Copy input GGUF to output with modified and added metadata values.
    modifications: dict of key -> (value, type_str)  - changes existing keys
    additions: dict of key -> (value, type_str)      - adds NEW keys
    """
    reader = gguf.GGUFReader(input_path, 'r')
    
    arch_field = reader.get_field('general.architecture')
    if arch_field is None:
        raise ValueError("No general.architecture found")
    arch = arch_field.contents()
    
    writer = gguf.GGUFWriter(output_path, arch=arch, endianess=reader.endianess)
    
    written_keys = set()
    
    for key, field in reader.fields.items():
        if key.startswith('GGUF.'):
            continue
        if key == 'general.architecture':
            continue
        
        written_keys.add(key)
        val_type = field.types[0]
        sub_type = field.types[-1] if val_type == gguf.GGUFValueType.ARRAY else None
        
        if key in modifications:
            new_val, type_str = modifications[key]
            val_type, sub_type, new_val = _convert_type(val_type, type_str, new_val)
            print(f"  MODIFY: {key} = {new_val} (was: {field.contents()})")
            writer.add_key_value(key, new_val, val_type, sub_type=sub_type)
        else:
            old_val = field.contents()
            if old_val is not None:
                writer.add_key_value(key, old_val, val_type, sub_type=sub_type)
    
    # Add new keys
    if additions:
        for key, (value, type_str) in additions.items():
            if key in written_keys:
                print(f"  WARNING: key '{key}' already exists, skipping add")
                continue
            val_type, sub_type, new_val = _convert_type(None, type_str, value)
            print(f"  ADD: {key} = {new_val} [{type_str}]")
            writer.add_key_value(key, new_val, val_type, sub_type=sub_type)
    
    # Copy tensors
    total_bytes = 0
    for tensor in reader.tensors:
        total_bytes += tensor.n_bytes
        writer.add_tensor_info(tensor.name, tensor.data.shape, tensor.data.dtype, tensor.data.nbytes, tensor.tensor_type)
    
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    
    for tensor in reader.tensors:
        writer.write_tensor_data(tensor.data, tensor_endianess=reader.endianess)
    
    writer.close()
    print(f"  Written: {output_path} ({total_bytes / 1024 / 1024:.1f} MiB tensor data)")


# ---- In-place metadata set ----

def set_metadata_inplace(input_path, key, value, type_str='auto'):
    """Modify a single metadata key in-place using GGUFReader r+ mode."""
    reader = gguf.GGUFReader(input_path, 'r+')
    field = reader.get_field(key)
    if field is None:
        print(f"ERROR: Key '{key}' not found in GGUF metadata")
        print("Available keys:")
        for k in reader.fields:
            if not k.startswith('GGUF.'):
                print(f"  {k}")
        sys.exit(1)
    
    if type_str == 'auto':
        type_str = {
            gguf.GGUFValueType.UINT32: 'uint32',
            gguf.GGUFValueType.INT32: 'int32',
            gguf.GGUFValueType.FLOAT32: 'float32',
            gguf.GGUFValueType.STRING: 'string',
            gguf.GGUFValueType.BOOL: 'bool',
            gguf.GGUFValueType.UINT64: 'uint64',
            gguf.GGUFValueType.INT64: 'int64',
        }.get(field.types[0], 'unknown')
    
    handler = reader.gguf_scalar_to_np.get(field.types[0]) if field.types else None
    if handler is None and type_str != 'string':
        print(f"ERROR: Cannot modify key '{key}' with type {field.types}")
        sys.exit(1)
    
    old_val = field.contents()
    if handler:
        new_val = handler(value)
        field.parts[field.data[0]][0] = new_val
        print(f"  SET: {key} = {value} (was: {old_val})")
    else:
        print(f"ERROR: In-place modification not supported for type {type_str}")
        sys.exit(1)


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(description='Craft malicious GGUF files for vulnerability research')
    subparsers = parser.add_subparsers(dest='command')
    
    dump_parser = subparsers.add_parser('dump', help='Dump GGUF metadata')
    dump_parser.add_argument('input', type=Path)
    
    tensors_parser = subparsers.add_parser('tensors', help='Dump GGUF tensor info')
    tensors_parser.add_argument('input', type=Path)
    
    set_parser = subparsers.add_parser('set', help='Set a metadata key in-place')
    set_parser.add_argument('input', type=Path)
    set_parser.add_argument('key', type=str)
    set_parser.add_argument('value', type=str)
    
    batch_parser = subparsers.add_parser('batch', help='Copy GGUF with multiple metadata changes & additions')
    batch_parser.add_argument('input', type=Path)
    batch_parser.add_argument('--output', type=Path, required=True)
    batch_parser.add_argument('--set', action='append', dest='modifications', metavar='KEY=VALUE', default=[],
                              help='Modify existing key (type auto-detected)')
    batch_parser.add_argument('--add', action='append', dest='additions', metavar='KEY=VALUE:TYPE', default=[],
                              help='Add new key, e.g. --add llama.expert_count=8:uint32')
    
    args = parser.parse_args()
    
    if args.command == 'dump':
        dump_metadata(args.input)
    elif args.command == 'tensors':
        dump_tensors(args.input)
    elif args.command == 'set':
        set_metadata_inplace(args.input, args.key, args.value)
    elif args.command == 'batch':
        modifications = {}
        for s in args.modifications:
            key, value = s.split('=', 1)
            modifications[key] = (value, 'auto')
        
        additions = {}
        for a in args.additions:
            parts = a.split('=', 1)
            key = parts[0]
            val_and_type = parts[1].rsplit(':', 1)
            if len(val_and_type) == 2:
                value, type_str = val_and_type
            else:
                value, type_str = val_and_type[0], 'uint32'
            additions[key] = (value, type_str)
        
        set_metadata(args.input, args.output, modifications, additions)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
