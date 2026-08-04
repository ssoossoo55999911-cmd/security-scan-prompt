#!/usr/bin/env python3
"""
Jinja VM fuzz testing - targets memory corruption in the jinja template engine.
Compiles and runs a custom C++ fuzz harness.
"""

import subprocess
import json
import os
import sys
import tempfile
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLAMA_DIR = os.path.join(PROJECT_DIR, 'llama.cpp')
BUILD_DIR = os.path.join(LLAMA_DIR, 'build')


def compile_fuzz_harness():
    """Compile a custom fuzz harness"""
    cpp_src = '''
#include <iostream>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "jinja/runtime.h"
#include "jinja/parser.h"
#include "jinja/lexer.h"
#include "jinja/value.h"

using json = nlohmann::ordered_json;

// Test a single template + vars. Returns 0 on success, 1 on exception, -1 on crash.
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
        std::cout << "OK: " << label << " (len=" << s.size() << ")\" << std::endl;
        return 0;
    } catch (const std::exception & e) {
        std::cout << "ERR: " << label << " -> " << e.what() << std::endl;
        return 1;
    } catch (...) {
        std::cout << "CRASH: " << label << std::endl;
        return -1;
    }
}

int main(int argc, char ** argv) {
    bool quiet = argc > 1 && std::string(argv[1]) == "--quiet";
    const std::string padding(50 * 1024 * 1024, 'A'); // 50MB string
    int passed = 0, errored = 0, crashed = 0;

    auto run = [&](const std::string & tmpl, const json & vars, const std::string & label) {
        int r = test_one(tmpl, vars, label);
        if (r == 0) passed++;
        else if (r == 1) errored++;
        else crashed++;
    };

    // ===== DEEP RECURSION (STACK OVERFLOW) =====
    std::vector<int> depths = {100, 500, 1000, 2000, 5000, 10000};
    for (int depth : depths) {
        std::string tmpl;
        for (int i = 0; i < depth; i++) tmpl += "{% if true %}";
        tmpl += "x";
        for (int i = 0; i < depth; i++) tmpl += "{% endif %}";
        run(tmpl, json::object(), "nested_if_" + std::to_string(depth));
    }

    for (int depth : depths) {
        std::string tmpl;
        for (int i = 0; i < depth; i++) tmpl += "(";
        tmpl += "1";
        for (int i = 0; i < depth; i++) tmpl += ")";
        run("{{" + tmpl + "}}", json::object(), "nested_parens_" + std::to_string(depth));
    }

    for (int depth : std::vector<int>{100, 200, 500, 1000}) {
        std::string tmpl = "{% macro foo(n) %}{% if n > 0 %}{{ foo(n - 1) }}{% endif %}{% endmacro %}{{ foo(" 
            + std::to_string(depth) + ") }}";
        run(tmpl, json::object(), "recursive_macro_" + std::to_string(depth));
    }

    // ===== VERY LARGE RANGE / ARRAY =====
    if (depth <= 100) {
        run("{% for i in range(" + std::to_string(INT64_MAX) + ") %}{{ i }}{% endfor %}", 
            json::object(), "range_INT64_MAX");
        run("{% for i in range(0, -1, -1) %}{{ i }}{% endfor %}",
            json::object(), "range_neg_step");
    }

    // ===== LARGE OBJECT =====
    {
        json obj;
        for (int i = 0; i < 10000; i++) obj["key_" + std::to_string(i)] = i;
        run("{% for k, v in obj.items() %}{{ k }}:{{ v }},{% endfor %}", 
            json{{"obj", obj}}, "large_object_10k");
    }

    // ===== SLICE EDGE CASES =====
    json arr = json::array({0,1,2,3,4,5,6,7,8,9});
    for (int64_t start : std::vector<int64_t>{0, -1, INT32_MAX, INT64_MIN}) {
        for (int64_t stop : std::vector<int64_t>{0, -1, INT32_MAX, INT64_MIN}) {
            std::string tmpl = "{{ arr[" + std::to_string(start) + ":" + std::to_string(stop) + "] }}";
            run(tmpl, json{{"arr", arr}}, "slice_" + std::to_string(start) + "_" + std::to_string(stop));
        }
    }

    // ===== STRFTIME EDGE CASES =====
    for (int len : std::vector<int>{100, 500, 1000, 5000}) {
        std::string fmt(len, '%');
        run("{{ strftime_now(\"" + fmt + "\") }}", json::object(), "strftime_len_" + std::to_string(len));
    }

    // ===== HUGE STRING =====
    run("{{ huge }}", json{{"huge", padding}}, "huge_string_50mb");

    // ===== EMPTY DELIMITER SPLIT =====
    run("{{ '' | split('') }}", json::object(), "empty_delim");

    // ===== JOIN WITH LARGE ARRAY =====
    {
        json large_arr = json::array();
        for (int i = 0; i < 100000; i++) large_arr.push_back("item_" + std::to_string(i));
        run("{{ arr | join(',') }}", json{{"arr", large_arr}}, "join_large");
    }

    // ===== SET CYCLES =====
    run("{% set a = namespace(x=1) %}{% set a.x = a %}{{ a.x }}", 
        json::object(), "set_cycle_namespace");

    if (!quiet) {
        std::cout << "\\n===== SUMMARY =====" << std::endl;
        std::cout << "Passed: " << passed << std::endl;
        std::cout << "Errored: " << errored << std::endl;
        std::cout << "Crashed: " << crashed << std::endl;
    }

    return crashed > 0 ? 2 : 0;
}
'''
    
    tmp_dir = tempfile.mkdtemp(prefix='jinja_fuzz_')
    src_path = os.path.join(tmp_dir, 'fuzz.cpp')
    bin_path = os.path.join(tmp_dir, 'fuzz')
    
    with open(src_path, 'w') as f:
        f.write(cpp_src)
    
    # Get compile flags from test-jinja
    cmake_cache = os.path.join(BUILD_DIR, 'CMakeCache.txt')
    includes = [
        os.path.join(LLAMA_DIR, 'common'),
        os.path.join(LLAMA_DIR, 'tests'),
    ]
    
    # Find nlohmann json include
    for root, dirs, files in os.walk(BUILD_DIR):
        if 'nlohmann' in root:
            includes.append(os.path.dirname(os.path.dirname(root)))
            break
    
    include_flags = ' '.join(f'-I{i}' for i in includes)
    
    cmd = f'c++ -std=c++17 -O0 -g {include_flags} -o {bin_path} {src_path}'
    print(f'Compiling: {cmd}')
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, 
                           cwd=LLAMA_DIR, timeout=30)
    if result.returncode != 0:
        print(f'Compilation failed:\n{result.stderr}')
        return None
    
    return bin_path


def main():
    # Instead of compiling a separate harness, use test-jinja with -py for cross-validation
    bin_path = os.path.join(BUILD_DIR, 'bin', 'test-jinja')
    if not os.path.exists(bin_path):
        print('test-jinja not found. Building...')
        result = subprocess.run(
            ['cmake', '--build', BUILD_DIR, '--target', 'test-jinja', '-j'],
            capture_output=True, text=True, timeout=60,
            cwd=LLAMA_DIR
        )
        if result.returncode != 0:
            print(f'Build failed:\n{result.stderr}')
            return 1
    
    print('Running test-jinja with fuzz tests...')
    result = subprocess.run([bin_path, 'fuzz'], capture_output=True, text=True, timeout=120)
    print(result.stdout)
    if result.stderr:
        print('STDERR:', result.stderr)
    
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
