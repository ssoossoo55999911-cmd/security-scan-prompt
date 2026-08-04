// Test RWKV tokenizer OOB read via \x00 token
#include <stdio.h>
#include <string.h>
#include "llama.h"

int main(int argc, char ** argv) {
    const char * model_path = argv[1] ? argv[1] : "models/crafted/vocab_rwkv_null_oob.gguf";

    fprintf(stderr, "Loading model: %s\n", model_path);
    struct llama_model_params params = llama_model_default_params();
    params.vocab_only = true;
    struct llama_model * model = llama_model_load_from_file(model_path, params);
    if (!model) {
        fprintf(stderr, "Failed to load model\n");
        return 1;
    }

    const struct llama_vocab * vocab = llama_model_get_vocab(model);

    // Input: 30 'a's — heap-allocated (>22 SSO limit).
    // The trie has a path 'a'×30 → '\0'. When the inner loop reaches position=30,
    // text[30]='\0' matches the trie's '\0' child, then text[31] is OOB.
    char input[129];
    memset(input, 'a', 128);
    input[128] = '\0';

    fprintf(stderr, "Tokenizing input (len=128)...\n");
    llama_token tokens[256];
    int n = llama_tokenize(vocab, input, 128, tokens, 256, false, false);
    fprintf(stderr, "Tokenized: %d tokens", n);
    if (n > 0) fprintf(stderr, " (first token id=%d)", tokens[0]);
    fprintf(stderr, "\n");
    // If tokens[0] == 0 (the 129-byte token), the tokenizer read past the 128-byte input
    // to match the '\0' byte — that's the OOB read bug.
    if (n == 1 && tokens[0] == 0) {
        fprintf(stderr, "BUG CONFIRMED: matched 129-byte token on 128-byte input (read past end)\n");
    }

    llama_model_free(model);
    return 0;
}