#include <iostream>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "jinja/runtime.h"
#include "jinja/parser.h"
#include "jinja/lexer.h"
#include "jinja/value.h"

using json = nlohmann::ordered_json;

static int test_one(const std::string & tmpl, const json & vars, const std::string & label) {
    try {
        jinja::lexer lexer;
        auto tokens = lexer.tokenize(tmpl);
        jinja::program ast = jinja::parse_from_tokens(tokens);
        jinja::context ctx(tmpl);
        jinja::global_from_json(ctx, vars, true);
        jinja::runtime runtime(ctx);
        auto results = runtime.execute(ast);
        auto parts = jinja::runtime::gather_string_parts(results);
        auto s = parts->as_string().str();
        std::cout << "OK: " << label << " (out_len=" << s.size() << ")" << std::endl;
        return 0;
    } catch (const std::exception & e) {
        std::cout << "ERR: " << label << " => " << e.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "CRASH: " << label << std::endl;
        return 2;
    }
}

int main() {
    int passed = 0, errored = 0, crashed = 0;
    json empty_vars = json::object({});

    auto run = [&](const std::string & t, const json & v, const std::string & l) {
        int r = test_one(t, v, l);
        if (r == 0) passed++; else if (r == 1) errored++; else crashed++;
    };

    // 1. Deep recursion (stack overflow target)
    for (int depth : {100, 500, 1000, 2000, 5000, 10000}) {
        std::string ifs, ends;
        for (int i = 0; i < depth; i++) ifs += "{% if true %}";
        for (int i = 0; i < depth; i++) ends += "{% endif %}";
        run(ifs + "x" + ends, empty_vars, "nested_if_" + std::to_string(depth));
    }

    // 2. Recursive macro
    for (int depth : {100, 200, 500, 1000}) {
        std::string t = "{% macro foo(n) %}{% if n > 0 %}{{ foo(n - 1) }}{% endif %}{% endmacro %}{{ foo(" + std::to_string(depth) + ") }}";
        run(t, empty_vars, "recursive_macro_" + std::to_string(depth));
    }

    // 3. Range with extreme values
    run("{% for i in range(0, 1, 9223372036854775807) %}{{ i }}{% endfor %}", empty_vars, "range_step_int64max");
    run("{% for i in range(0, -1000, -9223372036854775807) %}{{ i }}{% endfor %}", empty_vars, "range_neg_step");

    // 4. Slice with INT64 extremes
    json arr = json::array({0,1,2,3,4,5,6,7,8,9});
    for (int64_t s : {(int64_t)INT64_MIN, (int64_t)INT64_MAX, (int64_t)0, (int64_t)-1}) {
        run("{{ arr[" + std::to_string(s) + ":" + std::to_string(s) + "] }}", json({{"arr", arr}}), "slice_" + std::to_string(s));
    }

    // 5. strftime with long format (100-byte buffer)
    for (int len : {50, 99, 100, 101, 200, 500}) {
        std::string fmt(len, 'A');
        run("{{ strftime_now(\"" + fmt + "\") }}", empty_vars, "strftime_len_" + std::to_string(len));
    }

    // 6. Replace with empty old_str
    run("{{ 'hello' | replace('', 'X') }}", empty_vars, "replace_empty_old");

    // 7. Array index with INT64 extremes
    for (int64_t idx : {INT64_MIN, INT64_MAX}) {
        run("{{ arr[" + std::to_string(idx) + "] }}", json({{"arr", arr}}), "arr_idx_" + std::to_string(idx));
    }

    // 8. Namespace self-ref
    run("{% set ns = namespace(x=1) %}{% set ns.x = ns %}{{ ns.x.x.x.x }}", empty_vars, "namespace_cycle");

    std::cout << "\nPassed:" << passed << " Errored:" << errored << " Crashed:" << crashed << std::endl;
    return crashed > 0 ? 1 : 0;
}
