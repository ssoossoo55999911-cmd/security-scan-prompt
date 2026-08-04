## MEMORY: Security Research Knowledge Base

### Scope Rule (IMPORTANT)
**DoS-only findings are NOT accepted as valid bugs.** Stack exhaustion, CPU blowup, memory exhaustion, regex ReDoS, etc. without a memory-corruption / UB impact are out of scope. Only track: OOB read/write, use-after-free, type confusion, uninitialized read, integer overflow leading to memory corruption, and similar. DoS-via-recursion guards may still be *applied* as defensive hardening, but do not count them as findings.

### Local Build / Tooling Notes (IMPORTANT)
- **NEVER mess with system-wide ASAN / Xcode toolchain.** Binaries are built with `-DLLAMA_SANITIZE_ADDRESS=ON` against the *current* Xcode clang (now clang-21). If a stale `build/` was linked against an older clang (e.g. clang-16), the ASAN dynamic lib won't load (symbol `___asan_version_mismatch_check_apple_clang_1600` missing). Fix by wiping `build/` and reconfiguring from scratch:
  ```sh
  rm -rf build && cmake -S llama.cpp -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_SHARED_LIBS=ON -DLLAMA_SANITIZE_ADDRESS=ON -DLLAMA_BUILD_BORINGSSL=ON -G Ninja
  cmake --build build --target llama-cli -j
  ```
- Do NOT try to run binaries with a mismatched `DYLD_LIBRARY_PATH` pointing at a different clang's ASAN dylib — it always fails with a version-mismatch symbol error. Rebuild instead.
- **llama-cli invocation for quick tests**: use `--single-turn -p "..."` (NOT `--no-cnv`; that flag does not exist). Example:
  ```sh
  ./build/bin/llama-cli -m <model.gguf> --single-turn -p "hello" -n 2
  ```
- Source root for CMake is `llama.cpp` (the submodule), not the repo root. CMakeCache lives at `build/CMakeCache.txt`.
- **0014 — clip.cpp Array OOB Reads & Divide-by-Zero (High)**
  - *Finding 1-4*: See report for details
  - *Pattern*: GGUF arrays read without length validation; GGUF metadata used in division without zero guard

- **0015 — mtmd Runtime Vulnerabilities via Malicious GGUF (High)**
  - *6 runtime bugs across mtmd-image.cpp and mtmd-audio.cpp*
  - *Finding 5*: `3*target_width*target_height` int overflow → heap OOB (L1263)
  - *Finding 6*: `audio_chunk_len+1` int overflow → huge allocation (L562)
  - *Finding 7*: `patch_size*n_merge` overflow → assertion crash (L941)
  - *Finding 8*: `patch_size*patch_size` overflow → div-by-zero SIGFPE (L1504)
  - *Finding 9*: `h_bar*w_bar` overflow → wrong resize decision (L179)
  - *Finding 10*: `num_patches_h*num_patches_w` overflow (L1527)
  - *Pattern*: Unchecked `int*int` used as buffer size/divisor → overflow
  - *Fix pattern*: Cast to `(size_t)` or `(int64_t)` before multiplication; add zero-guards before division
  - *Key insight*: GGUF `get_u32` returns values ≤INT32_MAX but no upper bound beyond that; two medium-sized ints (e.g. 65536×65536) easily overflow
  - *Audited safe*: `mtmd_encode_impl`, `clip_image::set_size`, `log_mel_spectrogram` (all use safe size_t casts)

- **0001 — n_mel_bins Overflow (High)**
  - *Pattern*: User-controllable `clip.audio.num_mel_bins` → integer overflow in warmup
  - *Fix*: Added validation `(n_mel_bins <= 0 || n_mel_bins > 256)`
  - *Key insight*: Only **user-controllable** parameters are exploitable

- **0002 — Audio Mel Index Overflow (High)**
  - *Pattern*: `int` dimensions (`n_mel`/`n_len`) → silent overflow in `j * n_len + i`
  - *Fix*: Changed struct fields to `int64_t`, widened computations

- **0003 — Image Area Integer Overflow (High)**
  - *Pattern*: `width*height` overflow in image preprocessing
  - *Fix*: Changed to `int64_t`, added overflow check

- **0004 — Audio Sample Offset Overflow (High)**
  - *Pattern*: `offset = i * frame_step` with int32 overflow
  - *Fix*: Changed to `int64_t`, added bounds check

- **0005 — RETRACTED**: `audio_n_fft` is hardcoded (512) in `clip.cpp`, not GGUF-controllable

- **0006 — Insufficient Allocation Size Check (High)**
  - *Pattern*: `fill_mel_filterbank_matrix` uses `SIZE_MAX` (2^64-1) as limit, allowing 552 GB allocation
  - *Fix*: Replaced with 8 GiB practical limit

- **0007 — uint32_t→int Overflow in get_u32 (High)**
  - *Pattern*: `get_u32()` in `clip.cpp` reads UINT32 into signed `int` → values > INT32_MAX become negative → `vector::resize(negative)` crash
  - *Fix*: Added `val <= INT_MAX` check + sanity checks for n_head/n_layer

- **0008 — block_count=0 causes GGML_ABORT (Medium)**
  - *Pattern*: `n_head()` accessor falls through to `GGML_ABORT("fatal error")`
  - *Fix*: Validate `n_layer_all > 0` after loading

- **0016 — llama-model OOB writes via GGUF block_count (High)**
  - *Pattern*: `hparams.n_layer_all` read directly from GGUF `block_count` (llama-model.cpp:1084) with NO global bound check; used as loop bound for fixed `std::array<*, LLAMA_MAX_LAYERS=512>` writes (`is_recr_impl`, `is_swa_impl`, `n_head_arr`, `n_head_kv_arr`, `n_ff_arr`, `xielu_*`, `dsv4_compress_ratios`, `deepstack_mapping_arr`, `swiglu_clamp_*`) in arch loaders
  - *Key insight*: `get_key_or_arr(..., n_layer() ...)` only guards `n <= N_MAX` when the key is PRESENT. Omitting feed_forward_length/attention.head_count[_kv]/attention.recurrent_layers lets you skip those guards AND enables the vulnerable fallback loops (qwen35/qwen35moe/qwen3next loop by `n_layer_all`; lfm2/lfm2moe/jamba/granite-hybrid/kimi-linear/nemotron-h/plamo2 loop by `n_layer()` which defaults to `n_layer_all - n_layer_nextn`). n_layer_nextn defaults to 0 → n_layer()==n_layer_all==block_count.
  - *Confirmed PoCs*: `models/crafted/qwen35_oob_big.gguf` (block_count=100000) crashes at qwen35.cpp:25; `models/crafted/lfm2_oob_big.gguf` crashes at lfm2.cpp:10. ASAN heap-buffer-overflow WRITE of size 4 past the 27800-byte model object. (block_count=600 OOBs intra-object; 100000 OOBs into heap redzone → ASAN fires.)
  - *Crafters*: `resources/craft_oob_qwen35.py`, `resources/craft_oob_lfm2.py`
  - *Fix*: Add `GGML_ASSERT(hparams.n_layer_all > 0 && hparams.n_layer_all <= LLAMA_MAX_LAYERS)` at llama-model.cpp right after `get_key(BLOCK_COUNT)`, mirroring the existing `LLAMA_MAX_EXPERTS` guard. Verifies both PoCs blocked; legit model (LFM2-Audio-1.5B) still loads.

- **0009 — n_discard Overflow → Server Crash (High)**
  - *Pattern*: `n_discard=INT32_MAX` → `vector::resize(wrapped_unsigned)` crash
  - *Two variants*: n_keep=0 (direct resize crash), n_keep=INT32_MAX (signed overflow in n_keep+n_discard)
  - *Fix*: `n_discard = std::max(0, std::min(n_discard, n_left))`

- **0010 — penalty_last_n / dry_penalty_last_n → 8GB Vector Allocation (Medium/DoS)**
  - *Pattern*: `repeat_last_n=INT32_MAX` → `ring_buffer<llama_token>(2.1B)` = 8GB allocation
  - *Status*: DoS/out-of-scope per mission criteria. Fix: clamp hard limits to 65536

### Rejected/Out-of-Scope Findings
- **Jinja parser stack overflow** (DoS only, ~2000 nesting depth, no memory corruption)
- **JSON copy recursion** (nlohmann::json, external lib, DoS only)
- **Large base64 payloads** (10MB limit via read timeout, no memory corruption, DoS only)



**Parameter validation model**:
- `field_num<T>` with `set_hard_limits(min,max)` → throws on out-of-bounds
- `set_limits(min,max)` → silently clamps
- Some float fields have NO limits: `dynatemp_range`, `dynatemp_exponent`, `repeat_penalty`, etc.

**Fuzz test scripts**: `resources/scripts/server_fuzz.py`, `resources/scripts/test_context_shift.py`, `resources/scripts/test_image_audio_fuzz.py`

### GGUF Crafting Tools
- `resources/gguf_craft.py` — custom tool for GGUF metadata manipulation
- `gguf_set_metadata.py` fails for UINT32 > 2^31; use `gguf_craft.py set` for large values
- `gguf_dump.py` for dumping metadata

### Models Available
| Model | Path |
|-------|------|
| SmolVLM-500M-Instruct-Q8_0 | `models/SmolVLM-500M-Instruct-Q8_0.gguf` + mmproj |
| Qwen2.5-Omni-3B-Q4_K_M | `models/Qwen2.5-Omni-3B-Q4_K_M.gguf` + mmproj |
| LFM2-Audio-1.5B-Q8_0 | `models/LFM2-Audio-1.5B-Q8_0.gguf` + mmproj |
| granite-vision-3.2-2b | `models/granite-vision-3.2-2b-Q4_K_M.gguf` + mmproj |

### Research Patterns
1. **Always check parameter controllability** before reporting: verify via `gguf_dump` + code inspection
2. **Prefer int64_t for dimensions** — silent int32 overflows are the most common bug pattern
3. **Bound check at the source** — type-level fixes (int64_t struct fields) prevent downstream overflow
4. **Test with actual execution** — never speculate, always verify with crafted GGUF + ASAN
5. **Server fuzzing: use Python scripts** — easier to maintain than C++ test files

### Key Attack Surfaces Verified

**Image/Audio via Server API** (tested with Qwen2.5-Omni):
- stb_image rejects images with extreme dimensions (65535x65535, INT32_MAX)
- miniaudio handles WAV with contradictory data_size (4GB claim, 100 bytes actual) — no crash
- Malformed audio/MP3 → graceful 400 error
- Base64 limit: 5-sec HTTP read timeout provides implicit 10-15MB body limit
- FLAC format rejected by OAI compat validation (only wav/mp3 allowed)

**GGUF Reader/Writer Audit (gguf.cpp)** — Inspired by GHSA-3p4r-fq3f-q74v
- Read full file (1689 lines): reader + writer paths
- `mem_size` overflow already patched upstream: `SIZE_MAX - overhead < ctx->size` at L811
- All three overflow checks present: `n_tensors` division check, `(n_tensors+1)` division check, `SIZE_MAX - overhead < ctx->size`
- Negative `n_tensors`/`n_kv` caught by signed → unsigned conversion in division check
- `ggml_new_object` has overflow guard at L1690: `cur_end + size_needed > SIZE_MAX - GGML_OBJECT_SIZE`
- Writer side: `buf.resize(offset + nbytes)` uses checked allocation (no overflow in practice)
- Attack surfaces: `llama-quantize`, `llama-imatrix`, `llama-gguf`, control vectors — all use `no_alloc=false`
- **No new vulns found**. Code is well-defended against this class of overflow.

**INI Preset Infrastructure** (tested via server):
- PEG parser: flat grammar (no recursion), `zero_or_more` uses while loops
- `std::stoi` throws on overflow → handler_int safe from overflow
- `std::stoul` throws on overflow → `handler_string` handlers safe
- Null bytes in values → treated as literal, passed to handlers
- Binary data in values → same, no exploit
- 100MB INI file → OOM (DoS only, no exploitation)
- All validated via `resources/scripts/test_preset_ini.py`

**Multimodal Processing Chain** (server → mtmd → clip):
- `stbi_load_from_memory()`: handles extreme dimensions gracefully
- `audio_helpers::decode_audio_from_buf()`: miniaudio handles malformed WAV headers
- `mtmd_bitmap_init_from_audio()`: allocates based on actual decoded data, not header claim
- `mtmd_image_preprocessor_*`: uses GGUF metadata for dimension limits
- All previously found overflow bugs (0001-0007) are in the **clip.cpp/GGUF path**, not the **server API input path**

### Active Test Environment
- **Server**: `llama-server` running on port 9990 (background, PID stored)
- **Model**: Qwen2.5-Omni-3B-Q4_K_M (multimodal with vision + audio)
- **Build flags**: ASAN enabled, RelWithDebInfo

### 0016 — llama-model OOB Write via GGUF block_count (High)
- **Root cause**: `block_count` → `n_layer_all` read from GGUF with **no upper bound** at `llama-model.cpp:1084`.
- **Impact**: All 16 fixed-size `std::array<*, LLAMA_MAX_LAYERS=512>` members can be written OOB.
- **Fix**: Single `GGML_ASSERT(n_layer_all > 0 && n_layer_all <= 512)` right after `get_key(BLOCK_COUNT)`, mirroring existing `LLAMA_MAX_EXPERTS` guard. Also added guard in `llama-quant.cpp:1357` for the desc->n_layer override path.
- **Bypass**: Omit `feed_forward_length`, `attention.head_count[_kv]`, `attention.recurrent_layers` from GGUF → skip `get_key_or_arr` N_MAX guards → reach arch loaders with `n_layer_all >> 512`.
- **Vulnerable code sites**:
  - Recurrent fallback (n_layer_all): qwen35, qwen35moe, qwen3next
  - Recurrent manual (n_layer()): lfm2:9&26, lfm2moe, jamba, granite-hybrid, kimi-linear, nemotron-h, plamo2
  - SWA pattern callers (n_layer()): modern-bert, cohere2, gemma3n, deepseek4, phi3, olmo2, smallthinker, gemma3, gemma2, laguna, mellum, gemma-embedding, llama4, afmoe, exaone-moe, plamo3, openai-moe, exaone4, cohere2moe
  - Granite-switch direct writes (PR #25107, not yet merged)
  - llama-quant.cpp override path (offline tool, lower severity)
- **PoCs**: `resources/craft_oob_qwen35.py`, `resources/craft_oob_lfm2.py` → ASAN-confirmed heap-buffer-overflow
- **Safe patterns**: `get_key_or_arr` with `required=true` (validates n ≤ N_MAX); `get_arr` for std::array (validates length ≤ N_MAX).

### Extended OOB Write Hunt — src/ Audit (2025)
- **Scope**: All of `src/` — GGUF model loading, vocab, adapter, kv-cache, graph.
- **Verdict**: Report 0016 covers the ONLY exploitable OOB write. No additional OOB writes found.
- **Patterns checked and verified safe**:
  - `rope_sections` (std::array<int,4>): `get_key_or_arr(key, arr, n=4, ...)` validates n ≤ N_MAX=4; array length > 4 → throws. Constant index reads at `llama-model.cpp:1826`.
  - Vocab arrays: `n_scores < n_tokens` / `n_toktypes < n_tokens` throw before indexing; `id_to_token` is a vector.
  - Adapter/LoRA: `alora_invocation_tokens` is a vector (resized to `seq_len`); `std::copy` into properly-sized vector.
  - C-style arrays (`int sections[4]`, `split_sizes_qkvz[4]`): constant indices only.
  - `memcpy`/`memset` in graph/kv-cache: write into properly-sized tensor data (runtime, not GGUF-driven).
  - `n_layer_dense_lead`, `dsv4_hash_layer_count`: used as thresholds (`if (i < val)`), not as loop bounds on `layers`.
  - KV-cache (`map_layer_ids`, `v_heads`, `v_cells`): vectors, not fixed arrays.
  - Integer overflow in tensor shape multiplication: all widen to `int64_t` before multiply.
- **wavtokenizer-dec posnet/convnext block_count** (DoS, NOT OOB write):
  - `posnet.block_count` / `convnext.block_count` (GGUF) used as loop bound on `layers[i]` in `wavtokenizer-dec.cpp:21,87` without ensuring they don't exceed `n_layer_all`.
  - BUT: `create_tensor()` calls `pimpl->dev_layer.at(tn.bid)` (`llama-model.cpp:1665`) — `std::vector::at()` throws `std::out_of_range("vector")` before the OOB write to `layers[i]` can happen.
  - Result: DoS crash (unhandled "vector" exception), NOT memory corruption. `dev_layer` is sized by `n_layer_all` while `layers` loop bound comes from the separate `posnet.n_layer`.
  - Same pattern in `t5.cpp` (`dec_n_layer` resizes `layers` but NOT `dev_layer`).
  - PoC: `resources/craft_oob_wavtokenizer.py` (crashes with "vector" exception, not ASAN OOB).
- **Key insight**: `dev_layer.at()` at `llama-model.cpp:1665` is a **de facto bounds check** that prevents ALL `layers[i]` OOB writes via `create_tensor`. Only the `LLAMA_MAX_LAYERS` fixed arrays (report 0016) were truly exploitable because they're written DIRECTLY (not through `create_tensor`).

### 0017 — llama-vocab OOB read/write via unchecked default special_eos_id (High)
- **Root cause**: SPM tokenizer defaults `special_eos_id = 2` at `llama-vocab.cpp:1952` without checking against `id_to_token.size()`. When GGUF omits `tokenizer.ggml.eos_token_id`, the default is kept. The sanity check at line 2855 inserts it into `special_eog_ids` without bounds checking. The EOG loops at lines 2867 and 2901 access `id_to_token[tid]` via `operator[]` (NO bounds check) → heap OOB read. If OOB memory matches `"<|end|>"`, `id_to_token[end_id].attr = ...` is an OOB WRITE.
- **Trigger**: arch=llama, 1-token vocab, no `eos_token_id` key → default eos_id=2, but `id_to_token.size()=1`.
- **Fix**: Added `tid < 0 || tid >= (llama_token) id_to_token.size()` bounds checks at both EOG loops.
- **PoC**: `resources/craft_oob_vocab_eos.py` → ASAN heap-buffer-overflow READ at `llama-vocab.cpp:2870`.
- **Other default special tokens**: `special_bos_id=1` (SPM), `special_bos_id=101`/`sep_id=102`/`mask_id=103` (bert) can also be OOB with tiny vocabs, but `print_info` uses `.at()` (caught exception = DoS only). The EOG loops used `operator[]` (no check = memory corruption).
- **Safe patterns in vocab**: `get_key_or_arr` validates `n <= N_MAX`; vocab arrays check `n_scores < n_tokens` before indexing; `cache_special_tokens` loop is bounded by `n_tokens`; `token_to_piece_for_cache` checks `0 <= token < id_to_token.size()`.

### 0018 — llama-vocab OOB write via duplicate BPE merges in get_bpe_merges (Medium)
- **Root cause**: `bpe_ranks.emplace(pair, i)` deduplicates duplicate merge entries from GGUF. `bpe_ranks.size() < n_merges`, but rank values (original indices) can exceed `bpe_ranks.size()`. `get_bpe_merges()` creates `result(bpe_ranks.size())` and indexes `result[pair.second]` → OOB write.
- **Trigger**: GGUF with duplicate `tokenizer.ggml.merges` entries (e.g. `["a b", "a b", "c d"]`). Load with `vocab_only=true`, then call `llama_model_save_to_file()` → `add_kv_from_model()` → `get_bpe_merges()`.
- **Severity**: Medium — requires model save after loading (not just loading).
- **Fix**: Size result by `max_rank + 1` instead of `bpe_ranks.size()`.
- **PoC**: `resources/craft_oob_vocab_dup_merges.py` + `resources/test_dup_merges.cpp` → ASAN heap-buffer-overflow in `get_bpe_merges()`.
- **Affected paths**: `llama-vocab.cpp:2002` (gpt2 BPE), `llama-vocab.cpp:2093` (gemma4 BPE).

### 0019 — llama-vocab OOB read in RWKV tokenizer via null-byte token (Medium)
- **Root cause**: `llm_tokenizer_rwkv_session::tokenize()` inner loop does `text[++position]` without checking `position < text.size()`. When `position == text.size()`, `text[position]` returns '\0' (null terminator, valid). If the trie has a '\0' child (from a token with escaped `\x00`), `traverse('\0')` returns non-NULL, and `text[++position]` reads `text[size+1]` → OOB read.
- **Trigger**: RWKV GGUF with token containing `\x00` escape (e.g., `"aaa...a\\x00"`). Tokenize input "aaa...a" (one byte shorter). The inner loop matches all 'a's, hits '\0' at the end, reads past the string.
- **Severity**: Medium — OOB read (information disclosure), not write. ASAN doesn't catch it (std::string extra capacity), but proven by incorrect tokenization: 129-byte token matched on 128-byte input.
- **Fix**: Added `if (position + 1 >= text.size()) break;` before `text[++position]` in the inner loop.
- **PoC**: `resources/craft_oob_vocab_rwkv_null.py` + `resources/test_rwkv_null.cpp`.

### Extended src/ OOB Audit (beyond llama-vocab)
- **KV cache seq_id paths** (`llama-kv-cache.cpp`): All 18 `seq_to_stream[seq_id]` accesses are guarded by `GGML_ASSERT(seq_id < seq_to_stream.size())` → DoS (abort), not OOB memory corruption. `seq_to_stream` sized `LLAMA_MAX_SEQ=256`.
- **Recurrent memory** (`llama-memory-recurrent.cpp`): `seq_rm` checks `seq_id >= size` before `cells[seq_id]`. `seq_cp` checks `seq_id < size`. `set_rs_idx` checks `seq_id < rs_idx.size()`. All safe.
- **Hybrid memory** (`llama-memory-hybrid.cpp`): `seq_rm` returns early if recurrent fails. `seq_cp` calls both unconditionally but both sub-memories are guarded.
- **Batch validation** (`llama-batch.cpp`): Validates `n_seq_max <= LLAMA_MAX_SEQ` and `seq_id < n_seq_max`. All `p0[seq_id]` accesses bounded.
- **DSV4 KV cache** (`llama-kv-cache-dsv4.cpp`): `seq_idx[seq_id_unq[s]]` bounded by batch validation. `GGML_ASSERT(seq_id < n_stream)` guards.
- **kv-cells.h**: Uses `assert()` (debug-only, no-op in release) for `seq_pos[seq_id]`, but callers have `GGML_ASSERT` guards.
- **Grammar parser** (`llama-grammar.cpp`): `pos[1]`, `pos[2]` accesses on null-terminated strings — safe due to C++ short-circuit + null terminator. `parse_hex` checks bounds. All errors throw exceptions.
- **Chat templates** (`llama-chat.cpp`): Uses `std::string::find()` and `substr()` — bounds-checked by std library.
- **Server** (`tools/server/`): `slot.id` from `0..n_parallel-1` (bounded by `n_seq_max`). HTTP parsing uses `std::string/map`.
- **Sampler** (`llama-sampler.cpp`): `cur_p->data[0]` guarded by `GGML_ASSERT(cur_p->size > 0)`. Penalties use `unordered_map`.
- **mmap** (`llama-mmap.cpp`): Handles EOF, throws on read past end. No OOB write.
- **Tensor loading** (`llama-model-loader.cpp`): `w.offs + ggml_nbytes` from GGUF — OOB read (SIGBUS) at most, not write. Destination `cur->data` properly sized.
- **Integer overflow in `n_embd_r()`**: `n_embd * (n_shortconv_l_cache - 1)` can overflow `uint32_t`, but both allocation and usage use the same overflowed value → self-consistent, no OOB.
- **Quant** (`llama-quant.cpp`): Tensor dimensions from loaded model (validated). `desc->n_layer` guard added (report 0016).
- **Verdict**: No additional exploitable OOB writes found beyond reports 0016-0019.

### Context State Save/Load Audit (0020, 0022)
- **0020**: Informational — no OOB found in initial audit. All tensor writes protected by `ggml_backend_tensor_set` bounds check.
- **0022 — Partial KV Cache Write on State Load Failure (Medium)**: When `state_read_data` throws (truncated buffer), cleanup (`seq_rm`/`clear`) is skipped because it's gated on `if (!res)` not exception-safe. `llama_io_read_host` destructor writes queued partial tensor data even after API returns 0 (failure). Fix: wrap `state_read_data` in try-catch in both `kv_cache::state_read` and `memory_recurrent::state_read`, set `res = false` on exception so cleanup runs.
- **Key pattern**: `io.read_tensor()` in `llama_io_read_host` defers writes to destructor via `rinfos` queue. If exception thrown mid-stream, queued writes execute after caller catches → partial attacker data written to KV cache tensors. `ggml_backend_tensor_set` still validates bounds (no OOB), but cells are left populated with attacker metadata + partial tensor data.
- **Device io bug (not fixed)**: `llama_io_read_device::read_tensor` doesn't check `size > buf_size`, doesn't advance `ptr`, doesn't decrement `buf_size`. But `rinfo.ptr` is unused in destructor (device path uses `ggml_backend_tensor_copy` from staging buffers). `GGML_ASSERT(buf_size == 0)` in destructor only checks metadata reads, not tensor reads. This is a latent bug but not directly exploitable since device path requires `LLAMA_STATE_SEQ_FLAGS_ON_DEVICE`.
- **DoS vectors (not OOB)**: Large `cell_count` (OOM in `ubatch_reserve`), large `str_size` in `read_string()` (OOM).
- **`ggml_backend_tensor_set`** at `ggml-backend.cpp`: `GGML_ASSERT(offset + size <= ggml_nbytes(tensor))` — always-on bounds check, final gatekeeper preventing OOB writes during state load.
- **Recurrent transposed path is dead code**: `s_trans` must be 0 (line 1063 rejects non-zero), so `if (!s_trans)` is always true → transposed `else` branch unreachable.
- **Recurrent `cells[seq_id]` safe**: `mem_size = max(1, n_seq_max) >= n_seq_max`, so `seq_id < n_seq_max` is always within `cells.size()`.
- **All blob values validated**: n_stream, n_layer, cell_count, seq_id, tensor type/row-size, v_trans, magic/version — all checked against model/context values.
- **Verdict**: No OOB write vulnerabilities found. Code is robust — all blob values validated, tensor writes protected by `ggml_backend_tensor_set` bounds check.
- **Attack surface**: Session files (`llama_state_load_file`, `llama_state_seq_load_file`) and raw state buffers (`llama_state_set_data`, `llama_state_seq_set_data`) — all binary content is attacker-controlled.
- **Entry points**: `src/llama-context.cpp:2909-3200` (state_get/set_data, state_load/save_file, state_seq_*), `src/llama-kv-cache.cpp:1957-2500` (KV cache state_read/write), `src/llama-memory-recurrent.cpp:733-1160` (recurrent state_read/write), `src/llama-kv-cache-dsv4.cpp:249-430` (DSV4 state_read/write)
- **Key protections found**:
  - `ggml_backend_tensor_set` at `ggml-backend.cpp` has always-on `GGML_ASSERT(offset + size <= ggml_nbytes(tensor))` — final gatekeeper preventing OOB tensor writes
  - `GGML_ASSERT` is always enabled (calls `ggml_abort()`, not debug-only `assert()`)
  - All blob values validated: `n_stream_cur` vs `n_stream`, `n_layer` vs `layers.size()`, `cell_count` vs `cells.size()` (whole-cache), `seq_id` vs `n_seq_max`, `k_type_i_ref`/`k_size_row_ref` vs actual, `v_type_i_ref`/`v_size_row_ref` vs actual, `version`/`magic` checks
  - `find_slot()` validates `seq_id >= size` before any cell access
  - `ubatch_reserve(cell_count, 1)` properly sizes all arrays → loop accesses within bounds
  - `n_pos_per_embd()` returns 1 or 4 (never 2 or 3), so `pos[i + n_tokens*2]` accesses are within `pos.size() = cell_count * n_pos_per_embd`
  - Recurrent memory: `mem_size = max(1, n_seq_max) >= n_seq_max`, so `cells[seq_id]` with `seq_id < n_seq_max` is always within `cells.size()`
  - DSV4: `ns` validated by `dsv4_state_dst_stream_range` against `n_stream`
  - `read_string()`: `uint32_t str_size` → `vector<char> buf(str_size)` allocation before read — DoS (OOM) if huge, not OOB. `read()` throws if `str_size > buf_size`
  - `llama_io_read_host::read_tensor()` checks `size > buf_size` before recording, defers actual write to destructor
  - `llama_io_read_file::read_tensor()` reads to temp buffer then `ggml_backend_tensor_set` (bounds-checked)
  - `llama_file::read_raw()` throws on truncated file
- **DoS vectors (not OOB)**:
  - Large `cell_count` in single-seq path → OOM in `ubatch_reserve()` (allocation before io.read throws)
  - Large `str_size` in `read_string()` → OOM in `vector<char> buf(str_size)`
  - Large `n_seq_id` per cell → long loop (bounded by io buffer size)
  - Mismatched metadata → abort/exception
- **Server path**: `/slots/:id_slot?action=restore` → `llama_state_seq_load_file()` with `fs_validate_filename()` preventing path traversal. `slot->id` bounded by `n_parallel <= n_seq_max`.

### Sampler System Audit (0021)
- **Verdict**: One OOB read found (0021). Rest of sampler system is well-defended.
- **0021 — OOB Read in temp_impl via Empty cur_p (Low)**: `llama_sampler_temp_impl` accesses `cur_p->data[0]` without checking `cur_p->size > 0` when `temp <= 0.0f`. All other `data[0]` accesses in samplers have size guards. Fix: added `if (cur_p->size == 0) return;` at top of `temp_impl`.
- **Attack vector**: Malicious GGUF with 0-token vocab → `n_vocab = 0` → `cur_p.size = 0, data = nullptr` → null deref. Also via API misuse (empty cur_p + temp sampler).
- **All `data[0]` accesses audited**:
  - `temp_impl` (line 269): **VULNERABLE** — no size check
  - `softmax_impl` (line 297): `GGML_ASSERT(cur_p->size > 0)` — safe
  - `dist_apply` (line 1048, 1053): `size == 0` and `size == 1` checks — safe
  - `temp_ext_apply` (line 1959): `size <= 1` check — safe
  - `top_n_sigma_apply` (line 2787): `size <= 1` check — safe
  - `min_p_apply` (line 1583): `!cur_p->size` check — safe
  - `infill_apply` (line 3742): `size = 1` set before access — safe
- **cur_p->size never increases**: All samplers only decrease `cur_p->size` (top_k: `min(k, size)`, top_p: `last_idx <= size`, min_p: filtered, etc.). Starting size = `n_vocab` (or `sampled_probs_count`). Can't grow beyond allocation.
- **cur_p->size can't reach 0 via built-in samplers** (from size >= 1): top_k keeps `k >= 1`, top_p keeps `last_idx >= 1`, min_p keeps `i >= 1`, xtc checks `pos_last > 0`, infill sets `size = 1` if empty. But `n_vocab == 0` gives `size = 0` directly.
- **Compaction pattern safe**: `cur_p->data[cur_p->size++] = cur_p->data[i]` in infill — write index always <= read index, never exceeds original allocation.
- **XTC pointer advance safe**: `cur_p->data += pos_last; cur_p->size -= pos_last;` — stays within original allocation.
- **llama_sample_dist safe**: `std::discrete_distribution` returns `[0, size)` — always valid index.
- **Logit bias safe**: `cur_p->size > (size_t) lb.token` checked before `data[lb.token]` access.
- **Grammar safe**: `reject.index` from `candidates_grammar` which stores `i < cur_p->size`.
- **Penalties safe**: uses `unordered_map` for `token_count`, not array indexing.
- **DRY safe**: `dry_repeat_count` sized `last_n_repeat`, indexed within bounds. `last_tokens.rat(i)` has bounds check (`i >= sz → throw`).
- **Adaptive_p safe**: `original_probs` sized `cur_p->size` before `pending_token_idx` use. `pending_token_idx` from `llama_sample_dist` (always valid).
- **Ring buffer safe**: `rat(i)` checks `i >= sz → throw`. `push_back` handles `capacity == 0`.
- **Backend set_input safe**: logit_bias validates `lb.token >= 0 && lb.token < n_vocab`. dist writes single float to pre-sized tensor.

### Grammar System Audit (0023)
- **0023 — OOB Read in Raw Grammar Init via Invalid RULE_REF (Low)**: `llama_grammar_init_impl` (raw element API) doesn't validate RULE_REF values before indexing `rules[rule_id]`. ASAN confirmed heap-buffer-overflow in `detect_left_recursion`. Fix: added validation loop before recursion check.
- **Attack surface**: Raw element API only used in tests; string parser path validates in `parse()`. NOT exploitable via HTTP server (uses string API).
- **String parser (safe)**: `parse()` validates all RULE_REF values.
- **token_to_piece (safe)**: Uses `cache_token_to_piece.at(token)` — bounds-checked.
- **tokenize (safe)**: Checks `n_tokens_max < res.size()` before writing.
- **decode_utf8 (safe)**: Checks `*pos != 0` (null terminator) before each read.
- **parse_hex (safe)**: Checks `pos < end && *pos` — stops at null if truncated.
- **match_char pos[1] (safe)**: Only accessed when pos->type is CHAR/CHAR_NOT/CHAR_ANY. Rule always ends with END.
- **parse_char src[1] (safe)**: If *src == backslash, src[1] reads null terminator if at end — valid read, switch falls through to throw.
- **advance_stack (safe for string path)**: rule_id from pos->value, validated by string parser. Raw API fixed (0023).
- **detect_left_recursion (safe for string path)**: rule_index from rule[i].value, validated by string parser. Raw API fixed (0023).
- **code_points pointer advance (safe)**: decode_utf8 always ends with 0. *tok.code_points == 0 checked before advance.
- **trigger_pattern regex (DoS)**: std::regex_search could be slow with malicious regex (ReDoS), but no OOB.
- **left recursion detection (safe)**: Recursive but bounded by rules_visited/rules_in_progress arrays.
- **handle_repetitions (safe)**: MAX_REPETITION_THRESHOLD = 2000 check prevents explosion.
- **Verdict**: Grammar system is well-defended for string API (production). Raw element API had one OOB (0023), now fixed.

### Adapter System Audit
- **Verdict**: No OOB vulnerabilities found.
- **cvec::apply (safe)**: tensors[il] indexed with il < hparams.n_layer() = tensors.size(). data + off checked with off + n_embd <= len.
- **lora init (safe)**: Tensor shapes validated against model tensors. ggml_backend_tensor_set provides bounds check. ab_map is unordered_map.
- **alora_invocation_tokens (safe)**: resize(seq_len) then std::copy(data, data + seq_len, ...) — seq_len from GGUF array count, data from gguf_get_arr_data (validated by GGUF reader).
- **set_tensor (safe)**: offs from GGUF, size = ggml_nbytes(orig), read_buf.resize(size), ggml_backend_tensor_set(dev, ...) — dev is ggml_dup_tensor same size as orig.

### chat-* / PEG Parser Audit
- **Scope rule**: DoS-only findings (e.g. stack exhaustion, CPU blowup, memory exhaustion without memory-corruption impact) are NOT accepted as valid bugs in this project. Only OOB read/write, use-after-free, and similar memory-corruption / UB issues are tracked.
- **Verdict**: chat-* / peg-parser has **no OOB/UAF/memory-corruption vulnerabilities**.
- **Parsed/output code is consistently safe**: API JSON parsing uses try/catch + `.at()`; PEG `peg-parser.cpp` bounds every `ctx.input[pos]` with `pos >= size()`; `parse_hex_escape`/`parse_char_class_char` validate lengths; `string_view::substr` clamps on overflow.
- **`common_chat_msgs_parse_oaicompat` / `common_chat_tools_parse_oaicompat` (safe)**: fully wrapped in try/catch, all JSON access via `.at()` (throws, caught). Throws `runtime_error` on any malformed field.
- **`compute_diffs` / `string_diff` (safe)**: tool_calls index guarded by `size()` comparison; `string_starts_with` before `substr`.
- **`segmentize_markers` / `calculate_diff_split` (safe)**: `cur_pos < text.length()` bound; iterator arithmetic with `start != end` guards; bounded substrings.
- **`normalize_quotes_to_json` / `escape_json_string_inner` / `json_brace_depth` (safe)**: `i+1 < input.size()` before `input[i+1]`; `i == 0` check before `input[i-1]`; `size() >= 2` before `front()/back()`.
- **`common_chat_peg_mapper::map` (safe)**: AST-driven, no raw array index; `current_tool`/`pending_tool_call` guarded; `text.front()/back()` guarded by `size() >= 2` / `!empty()`.
- **`tagged_peg_parser::parse_anywhere_and_extract` (safe)**: `i < input.size()` loop; trailing `GGML_ABORT` unreachable.
- **`llama_chat_apply_template` legacy path (safe)**: standard "call with 0 to get size, then resize" pattern; callee checks size.
- **two latent UB hardenings applied defensively** (report 0024 also documents the DoS finding, now out-of-scope):
  - `parse_char_classes` (`common/peg-parser.cpp`): guarded `content.front()`/`back()` with `!content.empty()`.
  - `safe_args_parse` (`common/chat.cpp`): added `empty()` early-return + `front()`/`back()`.
- Note: `peg-parser.cpp` also gained a `COMMON_PEG_MAX_PARSE_DEPTH = 1024` recursion guard (DoS hardening, NOT a tracked vuln).

### Chat Parser / Auto-Parser Audit (0013)
- **Verdict**: No memory-corruption bugs found. System well-defended.
- **Key attack surface**: User-controlled assistant prefill (via `/chat/completions`) → PEG parser mapper
- **Three input channels**: (1) Template analysis (trusted), (2) Prefill content (user-controlled), (3) Model output (partially controlled)
- **Mapper (map())**: Processes AST nodes → `json_brace_depth()` for brace auto-close, `normalize_quotes_to_json()` for Python→JSON conversion
- **`json_brace_depth` signed underflow**: Depth can go negative when more `}` than `{` → auto-close loop silently does nothing (format correctness, not memory issue)
- **`segmentize_markers`**: Doesn't handle nested `<[...]>` markers → may cause incorrect diff analysis (known limitation, handled by workarounds)
- **`args_target` unbounded append**: String growth via `+=` → DoS only (limited by parser `repeat()` and model output constraints)
- **No pointer invalidation**: `current_tool` reassigned after `push_back`, no UAF
- **`normalize_quotes_to_json` state machine**: Verified correct, O(n) single-pass, no infinite loop
- **Tested with**: Control characters (all 0x00-0x1f pass), 100KB prefill, nested escaped quotes, unbalanced braces
- **`continue_final_message` flow**: Server detects assistant → sets `add_generation_prompt=false` → template renders with prefill → generation_prompt extracted via diff → prepended before PEG parsing
- **Pattern**: Prefill content flows through the PEG parser’s `wrap_for_generation_prompt()` → mapper extracts tool calls, reasoning, content
- **Fuzz scripts**: `resources/scripts/test_chat_parser_fuzz.py`, `resources/scripts/test_brace_depth.py`
