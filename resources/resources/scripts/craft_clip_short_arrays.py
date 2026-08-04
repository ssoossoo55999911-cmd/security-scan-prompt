#!/usr/bin/env python3
"""
Create a GGUF with short image_mean (1 element) from SmolVLM's mmproj.
"""
import sys
from pathlib import Path

gguf_path = Path(__file__).resolve().parent.parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))

import gguf

def make_short_arrays(src_gguf, dst_gguf):
    reader = gguf.GGUFReader(src_gguf, 'r')
    arch = reader.get_field('general.architecture').contents()
    writer = gguf.GGUFWriter(dst_gguf, arch=arch, endianess=reader.endianess)

    for key, field in reader.fields.items():
        if key.startswith('GGUF.') or key == 'general.architecture':
            continue
        if key == 'clip.vision.image_mean':
            writer.add_key_value(key, [0.5], gguf.GGUFValueType.ARRAY,
                                sub_type=gguf.GGUFValueType.FLOAT32)
            print(f"  REPLACED: {key} = [0.5] (len=1, expected=3)")
        elif key == 'clip.vision.image_std':
            writer.add_key_value(key, [0.5], gguf.GGUFValueType.ARRAY,
                                sub_type=gguf.GGUFValueType.FLOAT32)
            print(f"  REPLACED: {key} = [0.5] (len=1, expected=3)")
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
        writer.write_tensor_data(tensor.data)
    writer.close()
    print(f"  Written: {dst_gguf}")

if __name__ == '__main__':
    make_short_arrays(sys.argv[1], sys.argv[2])
