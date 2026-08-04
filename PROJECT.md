REMEMBER: EVERYTHING here is under `llama.cpp` subdir

You will work with the `llama.cpp` source code, located under git submodule `./llama.cpp`

Make sure to regularly pull from upstream to keep the `master` branch up-to-date.

## Bug scopes

- Nasty buffer overflow, integer underflow, etc
- Bugs that can lead to RCE
- Logic bugs

Out-of-scope:
- DoS
- Web UI related
- Debugging-related code

## Build guide

Configure:

```sh
cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_SHARED_LIBS=ON -DLLAMA_SANITIZE_ADDRESS=ON -DLLAMA_BUILD_BORINGSSL=ON
```

Example:

```sh
cmake --build build --target llama-mtmd-cli -j
```

Run it:

```sh
./build/bin/llama-mtmd-cli
```

## Working with llama-server

The llama-server has 2 models:

Mode "router": acts as a router that will spawn one child process per model. To enter this mode, run `llama-server` without `-m` or `-hf`

(Special case: if `-hf user/my_preset` and the HF repo contains one single `preset.ini` file, start server as router and use that `preset.ini` file)

Mode "normal" or "single model": run and create `llama_context`, load model, etc. Example: `./build/bin/llama-server -m ./models/my_model.gguf --mmproj ./models/my_model-mmproj.gguf`

Options:
- `--port` set the port
- more options: see server docs

TIPS:
- Always runs server on port `9990`, run in the background and save its PID to a file (do all in one command)
- In case server cannot bind, it means one of your previous run still have server in the background; stop it by asking me to run `sudo kill -9 $(sudo lsof -t -i :9990 -sTCP:LISTEN)` --> ASK, do NOT run it yourself

## Useful Resources

To conserve context space, load these resources as needed:

IMPORTANT: these are under `llama.cpp` subdir

General documentations:
- [Contributing guidelines](CONTRIBUTING.md)
- [Existing issues](https://github.com/ggml-org/llama.cpp/issues) and [Existing PRs](https://github.com/ggml-org/llama.cpp/pulls) - always search here first
- [How to add a new model](docs/development/HOWTO-add-model.md)
- [PR template](.github/pull_request_template.md)
- [multimodal syste](tools/mtmd/README-dev.md)

Server:
- [Build documentation](docs/build.md)
- [Server usage documentation](tools/server/README.md)
- [Server development documentation](tools/server/README-dev.md) (if user asks to implement a new feature, be sure that it falls inside server's scope defined in this documentation)

Chat template and parser:
- [PEG parser](docs/development/parsing.md) - alternative to regex that llama.cpp uses to parse model's output
- [Auto parser](docs/autoparser.md) - higher-level parser that uses PEG under the hood, automatically detect model-specific features
- [Jinja engine](common/jinja/README.md)