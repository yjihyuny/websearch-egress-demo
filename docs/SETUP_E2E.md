# Setup, end to end

Goal: a sandbox named `egress-demo` whose agent can be watched and re-permissioned live.
Legend: **[ran]** executed on the reference machine (aarch64, GB10, Ubuntu 24.04, NemoClaw v0.0.55, OpenShell 0.0.44);
**[docs]** from NVIDIA's documentation, not executed by us; **[verify]** flags and output may differ in your version.

## 0. Prerequisites
- Linux, macOS or WSL2 host with a Docker daemon your user can use (`docker info`). **[ran]**
- Node.js 22.16 or newer (the installer installs it if missing). **[docs]**
- Python 3.10+ on the host (the demo server uses only the standard library plus PyYAML for "set YAML").
- A model endpoint the sandbox can reach: a local OpenAI-compatible server (vLLM, Ollama, NIM) or an NVIDIA API key (`nvapi-...`, entitled to the model you choose).
- RAM and disk for a sandbox image build; check with `bash scripts/verify_env.sh`.
```bash
bash scripts/verify_env.sh        # read-only preflight  [ran]
```
> `nemoclaw <name> status` is not read-only: when the sandbox is missing from the live gateway it removes the stale local registry entry. Use `openshell sandbox list` (live truth) and `nemoclaw list` (registry). **[ran]**

## 1. Install NemoClaw and OpenShell
```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh -o nemoclaw.sh && less nemoclaw.sh     # read it first
NEMOCLAW_INSTALL_TAG=v0.0.55 bash nemoclaw.sh                                         # [ran] installs Node, OpenShell, the pinned NemoClaw
nemoclaw --version; openshell --version
```
If an older NemoClaw refuses newer OpenShell (`openshell X is above the maximum supported`), upgrade NemoClaw. Upgrading can recreate gateway containers and stop other sandboxes: `nemoclaw backup-all` first. **[ran]**

## 2. Make the model reachable from the sandbox
Inside the sandbox `127.0.0.1` is the sandbox itself. The host is `host.openshell.internal`, which resolves to the Docker bridge (often `172.20.0.1`; check with `getent hosts host.openshell.internal` from inside). So the model server must listen on that bridge address, not only on loopback. **[ran]**

Example with vLLM (adapt image, model and flags to your hardware; this was the reference setup):
```bash
docker run -d --name my-model --gpus all --ipc=host \
  -p 127.0.0.1:8080:8000 -p 172.20.0.1:8080:8000 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:v0.27.1 --model <hf-model> --served-model-name <served-id> --host 0.0.0.0 --port 8000 \
  --reasoning-parser <parser> --tool-call-parser <parser> --enable-auto-tool-choice
until curl -sf -m3 172.20.0.1:8080/v1/models >/dev/null; do sleep 5; done; echo READY
```
Bind the bridge address, not `0.0.0.0`, to avoid exposing the model to your LAN. Tool-calling models need the server's tool-call parser enabled, or the agent cannot call tools. Reasoning models print a "thinking" preamble first: the agent allows 1500 output tokens.
If port 8080 is taken (the OpenShell gateway defaults to it), set `NEMOCLAW_GATEWAY_PORT=18080` during onboarding.

Using NVIDIA-hosted models instead: run the interactive wizard (section 3b) and choose "NVIDIA Endpoints". The key must be entitled to that model; one test key was rejected with "not deployed for your account". **[ran]**

## 3. Create the sandbox
### 3a. Non-interactive, OpenAI-compatible endpoint **[ran with `NEMOCLAW_AGENT=hermes`; the OpenClaw form is the same command with `openclaw`: [verify]]**
```bash
ENDPOINT_URL=http://172.20.0.1:8080/v1 MODEL=<served-id> SANDBOX=egress-demo bash scripts/onboard.sh
```
This runs `nemoclaw onboard --fresh` with `NEMOCLAW_PROVIDER=custom`, accepts the third-party-software notice (`--yes-i-accept-third-party-software`: read it first), and applies the "suggested" policy presets. Onboarding may restart other sandboxes' containers on the same gateway (seen: exit 137); run it on a host where that is acceptable.
### 3b. Interactive wizard
```bash
nemoclaw onboard         # inference menu: NVIDIA Endpoints, OpenAI, other OpenAI-compatible, Anthropic, Gemini, Ollama, vLLM, router [ran]
```
Name the sandbox `egress-demo` (or set `SANDBOX=<yourname>` for every script here). Accept the suggested presets; the demo's "blocked" results depend on `duckduckgo`, GitHub and arbitrary sites **not** being in the default set.

Verify:
```bash
nemoclaw list; openshell sandbox list           # sandbox Ready
openshell policy get egress-demo --full | head -60
```
Possible wizard snags **[ran]**: stale session (`--fresh`); dashboard port busy (`--control-ui-port 18800`); `Port 8080 is not available` (`NEMOCLAW_GATEWAY_PORT=18080`).

## 4. Check the model route from inside the sandbox
```bash
openshell sandbox exec -n egress-demo -- sh -c 'curl -sS -m20 https://inference.local/v1/models | head -c 300'
```
You should see your model id. If you get `inference service unavailable` the gateway could not reach the model (loopback-only bind, section 2). If you get a 403, apply the local-inference preset and point the provider at the bridge:
```bash
openshell provider update compatible-endpoint --config OPENAI_BASE_URL=http://host.openshell.internal:8080/v1
nemoclaw egress-demo policy-add local-inference --yes
```
Switch model later without re-onboarding (0.0.44 flags are long-form): `openshell inference set -g nemoclaw --provider compatible-endpoint --model <id>`; check with `openshell inference get`. **[ran]**

## 5. Prepare the sandbox for the demo agent
```bash
SANDBOX=egress-demo bash scripts/setup_sandbox.sh
```
Installs `langgraph` and `langchain-openai` into `/sandbox/lg` (this uses the `pypi` preset: `python3`/`pip` to pypi.org and files.pythonhosted.org), uploads `agent/langgraph_demo.py`, then imports and queries `inference.local` as a check. Safe to re-run. **[ran]**
If pip is blocked, your sandbox lacks the `pypi` preset: `nemoclaw egress-demo policy-add pypi --yes`.

## 6. Run the demo UI
```bash
SANDBOX=egress-demo bash scripts/run.sh            # http://127.0.0.1:8890/langgraph_viewer.html
```
Remote host: on your laptop `ssh -N -L 8890:127.0.0.1:8890 <user>@<host>` and browse `http://127.0.0.1:8890/langgraph_viewer.html` (or `bash scripts/access.sh tunnel <user>@<host>`). Install `pip install -r server/requirements.txt` for the YAML editor. The header should say "Live runner connected to sandbox egress-demo".

Smoke test (runs two prompts in the sandbox, about a minute): `SANDBOX=egress-demo bash tests/smoke_test.sh`. **[ran]**

## 7. Use the demo
The demo flow is in the README ("Running the demo"). The viewer has 16 sample prompts in four groups: 1. Allowed, 2. Not allowed, 3. Mixed (allowed + not allowed), 4. Web search. Each sample states the outcome to expect with the default policy.

Change policy three ways (all take effect without restarting):
1. Viewer, **Policy editor** tab: allow a host:port for named binaries, optionally restricted to methods and path globs; dry-run shows the CLI and merged result first; **Reset to default** returns to `state/baselines/<sandbox>.yaml`. The **Default policy** card shows that YAML, says whether the live policy still matches it, and lets you replace it: *Save the current live policy as the default* (do this right after a clean onboarding), or *Edit default YAML* (validated, stored only; press Reset afterwards to apply).
2. CLI: `openshell policy update egress-demo --add-endpoint html.duckduckgo.com:443:full --binary /usr/bin/python3.13 --rule-name allow_ddg_search --wait` (`--remove-endpoint host:port` undoes it; `--dry-run` previews). **[ran]**
3. Presets: `nemoclaw egress-demo policy-list`, `policy-add <preset> --dry-run`, `policy-add <preset> --yes`, `policy-remove <preset> --yes`. Presets are per binary: read the preset's binaries before expecting `curl` to work.

Inspect decisions: `openshell logs egress-demo | grep -E "DENIED|ALLOWED" | tail -20`. Every line names binary, pid, destination and engine.

## 8. Operate and clean up
```bash
nemoclaw egress-demo snapshot create --name demo-start      # before a client session
nemoclaw egress-demo snapshot restore demo-start            # after
nemoclaw egress-demo destroy --yes                          # remove only the demo sandbox
nemoclaw gc --dry-run                                       # orphaned images
```
Do **not** run `nemoclaw uninstall` on a shared machine: it removes the tool itself. `nemoclaw debug --quick` collects diagnostics for a bug report.

## 9. Version drift and what to re-verify
NemoClaw is alpha. Re-check against your versions: onboarding flags and environment variables (`NEMOCLAW_*`), preset names and their binaries (`policy-list`, `openshell policy get --full`), `openshell policy update` flag syntax, the log line format that `server/live_server.py` parses (`[OCSF ] [ocsf] NET:... ALLOWED|DENIED`), and `openshell sandbox exec/upload` behaviour. If the log format changes the viewer still works but the "network events" panel will be empty.

## 10. Troubleshooting
| Symptom | Try |
|---|---|
| `Could not query gateway` | `openshell status`; `openshell doctor` |
| Sandbox in `nemoclaw list` but not `openshell sandbox list` | Stale registry entry; re-onboard or `destroy` it |
| Viewer says no live runner | Server not running, tunnel on a different port, or `SANDBOX` name mismatch (`/api/health` shows the name) |
| "agent run failed" in the viewer | Run `agent/langgraph_demo.py custom` by hand (README, "The agent"); usually missing deps (`setup_sandbox.sh`) or model route (section 4) |
| `openshell sandbox exec` hangs before starting | Known to stall occasionally; Ctrl+C and retry. The server retries once automatically |
| `openshell sandbox exec -n x "a; b"` says `No such file or directory` | It runs a program, not a shell string: `-- sh -c 'a; b'` |
| Everything returns 403, including things you allowed | Binary mismatch: the agent's Python is `/usr/bin/python3.13`, not `curl`; read the deny line in `openshell logs` |
| Search allowed but answer still thin | The *sites* refuse bots (403) or serve JavaScript shells; see the README section "Allowed is not answered" |
| `Previous onboarding session failed` | `nemoclaw onboard --fresh` |
| `migration N was previously applied but is missing` | Mixed OpenShell binaries (e.g. `/usr/bin` 0.0.38 vs `~/.local/bin` 0.0.44); move `~/.local/state/nemoclaw/openshell-docker-gateway` aside and onboard with `--fresh` |
| Policy editor "no baseline snapshot" | Start `server/live_server.py` once while the policy is pristine (it writes `state/baselines/<sandbox>.yaml`), or place a YAML there yourself |
| Chromium or a browser cannot reach the page remotely | Use the SSH tunnel; the server intentionally refuses non-localhost Host headers |
