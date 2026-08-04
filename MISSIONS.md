## First step

Figure out how to manipulate an existing GGUF to enable doing fuzzy yourself. For example, edit metadata to make a new malicious GGUF file.

Certain models are stored inside `models`

To use it with `llama-cli`:

```sh
./build/bin/llama-cli -m ./models/my_model.gguf --mmproj ./models/my_model-mmproj.gguf --single-turn -p "what do you see" --image ../resources/abcdef.png
```

Some files are already created under `resources` but you can create more if you need.

To craft a new GGUF, refer to `gguf_set_metadata.py` and `gguf_new_metadata.py` ; you are free to create your new, tailored tools and store them in `resources` - remember to update your memory.

Newly crafted GGUFs can be stored inside `models/crafted/*`

## Investigate potential bugs in `mtmd-image.cpp` and `mtmd-audio.cpp`

With the knowledge learnt from the last part, investigate and craft GGUFs that can cause nasty vuln like buffer overflow, integer underflow, etc.

Focus more on `mtmd-audio.cpp` as the code is chaotic and bugs may happen more frequently.

Note: do NOT rely solely on your speculations, craft GGUFs and use them to iterate

## Investigate potential bugs in `clip.cpp`

Similar to the last mission, let's see how malicious crafted GGUFs can break things.

## Investigate potential bugs in `llama-model-loader` system

This system is big, so let's try to focus on models with GGUF files stored in `models` dir.

Let's firstly speculate potential undefined behaviors that can lead to memory corruption bugs. Then craft GGUFs to iterate on your findings.

## Investigate undefined behaviors of server endpoints

Some `llama-server` endpoints accept a wide list of arguments, especially `/completions`-based endpoints.

Some value may be handled incorrectly with some extreme value, may lead to memory corruptions.

To research this:
- Investigate `server-context` and `server-common`
- (Optionally) Investigate `server-models` endpoints - this is router mode
- Either use curl or more preferrable, write a temporary python script under `resources/scripts/*.py`

## jinja infrastructure

Read jinja docs in `common/jinja/README.md`

You can compile the binary `test-jinja` to help debugging it.

Important reminder:
- If you find DoS - they are very, very low prio, regroup all DoS problems to one single report, do NOT spam me with small reports about DoS, it's annoying
- Focus on memory corruption & potential RCE issues. Jinja is designed to be a VM, it should be safe

## INI preset infrastructure

See `preset.h|.cpp|.md` files

Since we recently added support for remote presets, it is important to make sure a remote one doesn't cause dangerous problems.

The preset is downloaded to local then loaded similar to `--models-preset`, so if you want to test it, you can skip the "remote" part, simply write a preset to disk and load it.

Note: we only care if preset handling and parsing causes problems. Bugs like for example, unsafe preset itself (e.g. preset have `--log-file /etc/passwd`) is ignored.

## Pick random files and see what can go wrong

Pick 10-20 random file in one of these modules:
- src
- tools/server
- tools/cli
- tools/mtmd
- tools/completion
- common

And scan for vulnerabilities. (Exclude all debug-related code that is not user-facing; exclude DoS)

## Hunt for gguf reader / writer vuln

Target: ggml/src/gguf.cpp      

Inspired by https://github.com/ggml-org/llama.cpp/security/advisories/GHSA-3p4r-fq3f-q74v ; there might be other bugs of the same category (not just size overflow, but maybe something else)

Scan for the vuln in gguf reader / writer that can lead to memory problems.

Approach: Read the code, find patterns, craft minimal PoCs (craft GGUF using gguf_craft.py script), verify with ASAN.

## Chat parsing and auto-parser system

Target: common/chat.cpp, chat-peg-parser, chat-auto-parser

This system is complicated. While it's not actually user-facing, it can still be prone to attacks because server accepts "prefill assistant message", meaning input from `/chat/completions` can end with an assistant message (see `continueAssistantMessage` in llama-ui)

The "prefill assistant message" runs though the parser, so it's user-controlled (prone to attack)

There is also a chance that model itself can output malicious content that may break the system.

And lastly, a built-in malicious jinja template is also another case.

Approach: Read the code, find patterns, craft minimal PoCs (craft jinja template, use `--chat-template-file` to load the jinja file; craft `/chat/completions` requests, etc)

## Investigate potential bugs in mtmd GGUF model load (`clip.cpp`)

Search for code that, for example, assume array lengths without proper checks.

## llama-model OOB writes

Inspired by this comment: https://github.com/ggml-org/llama.cpp/pull/25107#discussion_r3546131104

Identify existing places where OOB write are possible, make PoC to prove it.
