# Web-search egress demo: NemoClaw + OpenShell

A self-contained demo of one idea: **an agent with a web-search tool can only reach what the sandbox policy allows, and you
can watch, widen and narrow that policy live.** A LangGraph agent runs *inside* an OpenShell sandbox; every fetch, search,
file write and `git` call it makes is judged by the real policy. A browser UI shows each step, the verdict (allowed or
denied), the YAML rule that decided it, and lets you edit the policy and re-run.

Tested on NemoClaw v0.0.55, OpenShell 0.0.44, Ubuntu 24.04 aarch64 (DGX Spark class), local vLLM Nemotron model.
NemoClaw is alpha software: flags change between releases (see `docs/SETUP_E2E.md` section 9).

## Layout
| Path | Purpose |
|---|---|
| `docs/SETUP_E2E.md` | **Start here.** Install, onboard, inference, bootstrap, run, policy edits, troubleshooting, clean-up |
| `agent/langgraph_demo.py` | The agent that runs inside the sandbox: `react` (http_get, search_web, write_file, read_file, git) and `research` (planner, parallel researchers, synthesizer) |
| `agent/tool_debug.py` | Prints exactly what a fetch returns for a URL (status, size, raw start, readable text) |
| `server/live_server.py` | Local server (127.0.0.1 only): serves `web/`, runs prompts in the sandbox, edits and diffs policy |
| `web/langgraph_viewer.html` | The UI: live runs, step replay (with delete), allowed/denied per call, Policy editor (with default-policy card), Policy diff |
| `web/demo_console.html`, `web/visual_guide.html` | Offline explainers: predict allow/deny, policy map, stack diagram |
| `scripts/` | `onboard.sh`, `setup_sandbox.sh`, `run.sh`, `demo.sh` (shell-level checks), `verify_env.sh`, `access.sh` |
| `tests/smoke_test.sh` | End-to-end check of server + agent against a live sandbox |
| `build/` | Templates and policy export used to regenerate the HTML (`python3 build/build_all.py`) |
| `state/` | Created at run time: default-policy snapshot and the policy change log (git-ignored) |

## Quick start (sandbox already exists and has inference)
```bash
bash scripts/verify_env.sh                       # read-only preflight
SANDBOX=egress-demo bash scripts/setup_sandbox.sh  # installs langgraph in the sandbox, uploads the agent (once)
SANDBOX=egress-demo bash scripts/run.sh          # open http://127.0.0.1:8890/langgraph_viewer.html
SANDBOX=egress-demo bash tests/smoke_test.sh     # optional: prove it works end to end
```
No sandbox yet? Follow `docs/SETUP_E2E.md` sections 1 to 4 (install NemoClaw, point it at a model, create the sandbox).
No sandbox at all? `web/langgraph_viewer.html` opened as a plain file still replays 7 saved traces offline.
Remote host: `ssh -N -L 8890:127.0.0.1:8890 <user>@<host>`, then browse the same URL on your laptop.

## Running the demo
The viewer has 16 sample prompts in four groups; each prints the outcome to expect under the default policy.
1. **Allowed:** fetch a PyPI JSON API, read a web page, write a file in `/tmp`.
2. **Not allowed:** an unlisted host, the GitHub API without its preset, plain http on port 80, writing `/etc`, reading `/etc/shadow`.
3. **Mixed:** allowed, denied, then a file write in one run; an agent that adapts to a block; research across PyPI, npm and an unlisted site; probing which hosts are reachable.
4. **Web search:** search is blocked until you allow DuckDuckGo; a research graph that searches and reads pages; the same fetch with a naive tool.

**The core flow (about 5 minutes):**
1. Pick **4. Web search / Search the web**, press **Run in sandbox**: `BLOCKED BY SANDBOX POLICY`, and the answer says so instead of inventing results.
2. **Policy editor** tab: host `html.duckduckgo.com`, port `443`, binary `/usr/bin/python3.13`; **Preview (dry run)**, then **Apply**. No restart.
3. **Apply and re-run last prompt**: real results. **Policy diff** shows exactly what changed. **Reset to default** restores the default policy.
4. Replays pile up in the "Run (replay)" list; **Delete replay** / **Delete all** clear them.

Shell-level companion (`bash scripts/demo.sh 4`): the same destination can be denied for `curl` and allowed for `pip`, because policy keys on binary, host and port.

## How the policy decides (measured on the reference machine, **[ran]**)
- **Binary + host + port (+ method + path).** The agent's tools run as `/usr/bin/python3.13`; shell `curl` is `/usr/bin/curl`. A rule that lists only python3 lets `http_get` through while `curl` to the same host is denied.
- **Port matters.** `http://` is port 80, `https://` is 443; allowing one does not allow the other.
- **Parent process can count.** With the Hermes agent, `curl` launched by the agent was allowed to a host whose preset lists the agent's Python, while the same `curl` started directly via `openshell sandbox exec` was denied. Do not assume identity is only the binary's own path.
- **Presets are bundles with binary lists.** `pypi` = `python3*`/`pip*` to pypi.org and files.pythonhosted.org. `npm` = `npm*/npx*/node*/yarn*`. `brew` also opens `github.com` for `git`. Read `policy-add <preset> --dry-run` before applying.
- **Search needs an explicit allow** for `html.duckduckgo.com:443`, and each result page is a different host that needs its own rule.
- **Evidence:** `openshell logs <sandbox> | grep -E "DENIED|ALLOWED"` names binary, pid, destination, engine. An HTTP error alone does not prove which rule fired.

### "Allowed" is not "answered"
A fetch can be allowed and still give the model nothing. The agent's tools classify the result so the model (and you) can tell which layer said no:
| Label | Meaning |
|---|---|
| `sandbox_blocked` | Proxy denied the tunnel; the log shows `DENIED` |
| `site_refused` | Sandbox allowed it; the website answered 401/403/429 (bot wall) |
| `not_found` | Allowed, but the URL does not exist (often one the model guessed) |
| `empty_shell` | Allowed, 200 OK, almost no text: a JavaScript app or bot check |
The system prompt forbids filling the gap from memory. `LEGACY_TOOLS=1` (viewer option "legacy") shows the naive tool: raw first 300 characters and opaque errors. A sandbox decides reachability; grounding decides whether the answer can be trusted. The sandbox does not make answers correct, and an allowed endpoint is full duplex (a request can carry data out, a response can carry instructions in). NVIDIA's own caveat: no sandbox fully protects against advanced prompt injection.

## The agent
`agent/langgraph_demo.py` runs inside the sandbox and talks to `https://inference.local/v1`, which OpenShell routes to your model.
- **react:** `agent <-> tools`. Tools: `http_get` (readable text; PyPI/GitHub/npm/HF JSON summarised), `search_web` (DuckDuckGo HTML), `write_file`, `read_file`, `git` (allow-listed subcommands).
- **research:** `planner` picks 2 to 5 URLs, parallel `researcher` nodes fetch them, `synthesizer` writes a cited report that must list failed sources and why.
- **Environment variables:** `GRAPH=react|research`, `GROUNDED=1|0`, `LEGACY_TOOLS=0|1`, `MODEL`, `BASE_URL`, `PROMPT_B64` (the prompt, base64).
- **Without the UI:**
```bash
P=$(printf '%s' 'Use http_get on https://example.com and report the title.' | base64 -w0)
openshell sandbox exec -n egress-demo -- sh -c "cd /sandbox && GRAPH=react PROMPT_B64=$P python3 langgraph_demo.py custom 2>&1 | tail -c 3000"
```
`openshell sandbox exec` runs a program, not a shell string: wrap commands in `sh -c '...'`. It occasionally stalls before starting; retry.
- **Trace format:** `{"task","prompt","graph","model","base_url","events":[...]}`. react events are `tool_call`, `tool_result`, `final`; research events are `plan`, `research`, `final`. Paste one into the viewer's "Offline" box, or add it to `build/traces_embedded.json` and run `python3 build/build_all.py`.
- **Adding a tool:** add a `@tool` function, append it to `TOOLS`, add a case to `check()` in `build/lg_viewer.template.html` so predictions cover it, rebuild, re-upload with `scripts/setup_sandbox.sh`.

## Safety notes
- The server binds `127.0.0.1` only and checks Host/Origin; reach it from a laptop with an SSH tunnel to that one port.
- The Policy editor changes the **live** policy of the sandbox you point it at. Use a dedicated demo sandbox. The first server start snapshots the policy to `state/baselines/` and **Reset to default** returns to it: start the server before making manual policy edits, or fix the stored default in the editor's **Default policy** card.
- No credentials are stored or read by this project. Never paste gateway tokens into tickets or chats.
