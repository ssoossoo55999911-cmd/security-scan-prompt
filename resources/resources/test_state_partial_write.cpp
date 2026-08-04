// Test: Partial KV cache write on state load failure
//
// When state_seq_set_data encounters an exception during state_read_data
// (truncated buffer), the llama_io_read_host destructor writes any
// already-queued tensor data to the KV cache EVEN THOUGH the operation
// "failed" (returned 0). The cleanup (clear/seq_rm) only runs when
// state_read returns false, not when it throws.
//
// This test:
// 1. Decodes tokens to populate KV cache
// 2. Saves the state
// 3. Truncates the state buffer to cause failure during tensor reading
// 4. Loads the truncated state — should fail but may have written partial data
// 5. Checks if decode still works (corrupted state)

#include "llama.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

int main(int argc, char ** argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <model.gguf>\n", argv[0]);
        return 1;
    }

    llama_backend_init();

    llama_model_params mparams = llama_model_default_params();
    mparams.n_gpu_layers = 0;
    llama_model * model = llama_model_load_from_file(argv[1], mparams);
    if (!model) { fprintf(stderr, "Failed to load model\n"); return 1; }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = 128;
    cparams.n_batch = 128;
    cparams.n_ubatch = 128;
    cparams.no_perf = true;
    llama_context * ctx = llama_init_from_model(model, cparams);
    if (!ctx) { fprintf(stderr, "Failed to create context\n"); return 1; }

    const llama_vocab * vocab = llama_model_get_vocab(model);
    const int n_vocab = llama_vocab_n_tokens(vocab);

    // Step 1: Decode some tokens to populate the KV cache
    llama_token tokens[] = {1, 2, 3, 4, 5, 6, 7, 8};
    llama_batch batch = llama_batch_get_one(tokens, 8);
    int rc = llama_decode(ctx, batch);
    printf("Step 1: Decode returned %d\n", rc);

    // Step 2: Save state for seq 0
    size_t state_size = llama_state_seq_get_size(ctx, 0);
    printf("Step 2: State size = %zu bytes\n", state_size);

    std::vector<uint8_t> state_data(state_size, 0);
    size_t n_written = llama_state_seq_get_data(ctx, state_data.data(), state_data.size(), 0);
    printf("Step 2: Wrote %zu bytes\n", n_written);

    if (state_size < 100) {
        printf("State too small — need at least some tensor data\n");
        llama_free(ctx);
        llama_model_free(model);
        llama_backend_free();
        return 0;
    }

    // Step 3: Corrupt the state — modify positions in the metadata
    // and truncate the tensor data to cause a mid-stream failure
    // The state format: magic(4) + seq_id(4) + n_stream(4) + per-stream: cell_count(4) + per-cell: pos(4)+n_seq(4)+seq_ids
    // Then state_read_data: v_trans(4) + n_layer(4) + per-layer tensor data
    //
    // We'll modify the first cell's position (byte 16 area) and truncate
    // to cut off tensor data mid-way through layer reading

    // Truncate to ~75% to allow metadata + some tensor data
    size_t truncated_size = state_size * 3 / 4;
    printf("Step 3: Truncating to %zu bytes (was %zu)\n", truncated_size, state_size);

    // Step 4: Load the truncated state
    size_t n_read = llama_state_seq_set_data(ctx, state_data.data(), truncated_size, 0);
    printf("Step 4: Load returned: %zu (0 = failure)\n", n_read);

    if (n_read == 0) {
        printf("BUG: Load reported failure but destructor may have written partial tensor data\n");
        printf("     Cell metadata was modified by state_read_meta (which succeeded)\n");
        printf("     Some tensor data was queued by state_read_data before the exception\n");
        printf("     The io destructor writes that partial data — KV cache is now corrupted\n");
    }

    // Step 5: Try to decode again — may produce garbage due to corrupted KV state
    llama_batch batch2 = llama_batch_get_one(tokens, 1);
    rc = llama_decode(ctx, batch2);
    printf("Step 5: Decode after failed load returned %d\n", rc);

    llama_free(ctx);
    llama_model_free(model);
    llama_backend_free();
    return 0;
}