// Test OOB access in KV cache via large seq_id
#include <stdio.h>
#include "llama.h"

int main(int argc, char ** argv) {
    const char * model_path = argv[1] ? argv[1] : "models/LFM2-Audio-1.5B-Q8_0.gguf";

    fprintf(stderr, "Loading model: %s\n", model_path);
    struct llama_model * model = llama_model_load_from_file(model_path, llama_model_default_params());
    if (!model) { fprintf(stderr, "Failed to load model\n"); return 1; }

    struct llama_context_params ctx_params = llama_context_default_params();
    ctx_params.n_ctx = 512;
    struct llama_context * ctx = llama_init_from_model(model, ctx_params);
    if (!ctx) { fprintf(stderr, "Failed to create context\n"); return 1; }

    llama_memory_t mem = llama_get_memory(ctx);

    fprintf(stderr, "Calling llama_memory_seq_rm with seq_id=999999 (LLAMA_MAX_SEQ=256)...\n");
    // seq_to_stream is sized LLAMA_MAX_SEQ=256. seq_id=999999 → OOB
    bool ok = llama_memory_seq_rm(mem, 999999, 0, -1);
    fprintf(stderr, "seq_rm returned %d (if we get here, no OOB crash)\n", ok);

    llama_free(ctx);
    llama_model_free(model);
    return 0;
}