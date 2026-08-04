// Minimal test to trigger OOB write in get_bpe_merges() via llama_model_save_to_file
#include <stdio.h>
#include "llama.h"

int main(int argc, char ** argv) {
    const char * model_path = argv[1] ? argv[1] : "models/crafted/vocab_dup_merges_oob.gguf";
    const char * save_path  = "/tmp/test_save_oob.gguf";

    fprintf(stderr, "Loading model: %s\n", model_path);
    struct llama_model_params params = llama_model_default_params();
    params.vocab_only = true;
    struct llama_model * model = llama_model_load_from_file(model_path, params);
    if (!model) {
        fprintf(stderr, "Failed to load model\n");
        return 1;
    }
    fprintf(stderr, "Model loaded, calling llama_model_save_to_file...\n");
    llama_model_save_to_file(model, save_path);
    fprintf(stderr, "Save completed (if we get here, no OOB)\n");
    llama_model_free(model);
    return 0;
}