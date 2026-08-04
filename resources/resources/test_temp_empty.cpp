// Test: OOB read in llama_sampler_temp_impl when cur_p->size == 0
//
// llama_sampler_temp_impl accesses cur_p->data[0] without checking cur_p->size > 0
// when temp <= 0.0f. If cur_p is empty (size == 0), this is an OOB read.
//
// This test uses a non-null data pointer (1-element vector, size set to 0)
// to demonstrate the logical OOB — ASAN catches the read past the vector's
// logical size when using heap-allocated memory.

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
    if (!model) {
        fprintf(stderr, "Failed to load model\n");
        return 1;
    }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = 32;
    cparams.n_batch = 32;
    cparams.n_ubatch = 32;
    cparams.no_perf = true;
    llama_context * ctx = llama_init_from_model(model, cparams);
    if (!ctx) {
        fprintf(stderr, "Failed to create context\n");
        return 1;
    }

    // Create a temp sampler with temp = -1.0 (triggers the temp <= 0 path)
    llama_sampler * smpl_temp = llama_sampler_init_temp(-1.0f);

    llama_sampler * chain = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(chain, smpl_temp);

    // Approach: allocate 2 elements, then set size=0 to trigger OOB read
    // The data[0] access reads from heap memory that was allocated for element 0,
    // but ASAN tracks the logical size via vector annotations
    std::vector<llama_token_data> cur_data(2);
    cur_data[0] = {0, 1.0f, 0.5f};
    cur_data[1] = {1, 2.0f, 0.5f};

    // Now resize to 0 — ASAN should mark the memory as inaccessible
    cur_data.resize(0);
    // But data() might be nullptr after resize(0)...
    // Let's use a different approach: keep the vector at size 2 but
    // manually construct cur_p with size = 0

    // Actually, let's use a raw heap allocation to have precise control
    llama_token_data * heap_data = (llama_token_data *)malloc(sizeof(llama_token_data));
    heap_data[0] = {42, 3.14f, 0.0f};
    // free immediately — ASAN will mark this as freed (use-after-free)
    free(heap_data);

    llama_token_data_array cur_p = {
        /* .data     = */ heap_data,  // points to freed memory
        /* .size     = */ 0,
        /* .selected = */ -1,
        /* .sorted   = */ false,
    };

    printf("Calling llama_sampler_apply with cur_p.size = %zu, data = %p (freed)...\n",
           cur_p.size, (void*)cur_p.data);

    // temp <= 0 path will access cur_p->data[0] → use-after-free!
    llama_sampler_apply(chain, &cur_p);

    printf("cur_p.selected = %lld\n", (long long)cur_p.selected);

    llama_sampler_free(chain);
    llama_free(ctx);
    llama_model_free(model);
    llama_backend_free();

    return 0;
}