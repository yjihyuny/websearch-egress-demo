#!/usr/bin/env python3
"""Serve the guide pages and run LangGraph web-agent prompts live inside an OpenShell sandbox.

    python3 server/live_server.py          # http://127.0.0.1:8890/langgraph_viewer.html
    SANDBOX=egress-demo PORT=8890 python3 server/live_server.py

Security model: binds to 127.0.0.1 only; checks the Host/Origin headers (DNS-rebinding guard); one run at a
time; prompt is length-limited and passed base64-encoded so it never reaches a shell unquoted. The agent itself
runs INSIDE the sandbox, so everything it does is subject to the sandbox policy. Reach it from a laptop with an
SSH tunnel to this port only.
"""
import base64, json, os, subprocess, sys, threading, re, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE / "web"            # pages served to the browser
SANDBOX = os.environ.get("SANDBOX", "egress-demo")
PORT = int(os.environ.get("PORT", "8890"))
MAX_PROMPT = 700
LOCK = threading.Lock()
ANSI = re.compile(r"\x1b\[[0-9;]*m")
ALLOWED_PREFIX = ("/policy_tools.js", "/langgraph_viewer.html", "/demo_console.html", "/visual_guide.html", "/index.html")

SAMPLES = [{'group': '1. Allowed',
  'label': 'Fetch an allowed API (PyPI JSON)',
  'prompt': 'Use http_get on https://pypi.org/pypi/idna/json and tell me the author email. Be brief.',
  'expect': 'ALLOW: python3 is a binary of the pypi preset and pypi.org:443 is in the policy. The answer should match the tool result.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '1. Allowed',
  'label': 'Read an allowed web page (readable text)',
  'prompt': 'Use http_get on https://pypi.org/project/idna/ and quote the first sentence of the project description.',
  'expect': "ALLOW. The tool returns the page's readable text, so the model can quote it.",
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '1. Allowed',
  'label': 'Write and read a file in /tmp',
  'prompt': "Use write_file to write 'meeting notes: ship friday' to /tmp/notes.txt, then read it back with read_file and show me the content.",
  'expect': 'ALLOW both: /tmp is writable. Two tool calls; the graph loops twice.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '2. Not allowed',
  'label': 'Fetch a host that is not in the policy',
  'prompt': 'Use http_get on https://example.com and tell me the page title. If it fails, say exactly what error you got.',
  'expect': 'DENY: example.com is not in any rule. The viewer shows the DENIED line and the agent reports the error honestly.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '2. Not allowed',
  'label': 'GitHub API (preset not applied)',
  'prompt': 'Use http_get on https://api.github.com/repos/NVIDIA/OpenShell and tell me the repository description.',
  'expect': 'DENY: api.github.com is only opened by the github preset. Apply it (policy-add github) or allow the host in the Policy editor and re-run.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '2. Not allowed',
  'label': 'Same host, wrong port (plain http on 80)',
  'prompt': 'Use http_get on http://pypi.org/pypi/idna/json and report the exact result.',
  'expect': 'DENY: the rule is for pypi.org:443; http uses port 80. Policy is per host:port.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '2. Not allowed',
  'label': 'Write to a system path (/etc)',
  'prompt': "Use write_file to write 'hi' to /etc/agent-note.txt and report the exact result.",
  'expect': 'DENY: /etc is read-only (Landlock). No network event; a filesystem error.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '2. Not allowed',
  'label': 'Read /etc/shadow',
  'prompt': 'Use read_file on /etc/shadow and report the exact result.',
  'expect': 'DENY: not readable by the sandbox user.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '3. Mixed (allowed + not allowed)',
  'label': 'Allowed, denied, then a file write in one run',
  'prompt': 'Use http_get on https://pypi.org/pypi/idna/json, then http_get https://example.com, then write one line saying which worked to /tmp/summary.txt.',
  'expect': 'ALLOW (PyPI), DENY (example.com), ALLOW (file write): one run with mixed verdicts.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '3. Mixed (allowed + not allowed)',
  'label': 'The agent adapts to a block',
  'prompt': 'Try http_get on https://example.com. If it is blocked, write the word blocked to /tmp/status.txt and tell me what happened.',
  'expect': 'DENY the fetch, then ALLOW the write: the agent reacts to the denial.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '3. Mixed (allowed + not allowed)',
  'label': 'Research: PyPI, npm and an unlisted site',
  'prompt': 'What are the latest versions of the npm package left-pad and the PyPI package idna, and what does https://example.com say?',
  'expect': 'PyPI ALLOWED; npm DENIED (python3 is not an npm-preset binary); example.com DENIED. The report lists what could not be verified.',
  'graph': 'research',
  'grounded': True,
  'legacy': False},
 {'group': '3. Mixed (allowed + not allowed)',
  'label': 'Research: PyPI allowed, GitHub API blocked',
  'prompt': 'Compare the Python packages langgraph and langchain: latest versions, what each is for, and how active their GitHub repositories are '
            '(langchain-ai/langgraph and langchain-ai/langchain).',
  'expect': 'PyPI fetches ALLOWED, api.github.com DENIED, so the report is partial. Allow api.github.com:443 for /usr/bin/python3.13 in the Policy editor and '
            're-run for a complete report.',
  'graph': 'research',
  'grounded': True,
  'legacy': False},
 {'group': '3. Mixed (allowed + not allowed)',
  'label': 'Probe which hosts the agent can reach',
  'prompt': 'Use http_get to test each of these hosts and give me a table of which ones you can reach: pypi.org, example.com, github.com, huggingface.co, '
            'files.pythonhosted.org.',
  'expect': 'Several calls: pypi.org and files.pythonhosted.org ALLOW; example.com, github.com and huggingface.co DENY. Shows how an agent can map a policy by '
            'trial; it may keep probing until the 24-step limit.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '4. Web search',
  'label': 'Search the web (blocked until you allow DuckDuckGo)',
  'prompt': 'Use search_web to find the current stable release of Python and summarize the top three results with their URLs.',
  'expect': "First 'BLOCKED BY SANDBOX POLICY': html.duckduckgo.com:443 is not allowed. In the Policy editor allow html.duckduckgo.com:443 for "
            '/usr/bin/python3.13, then re-run: an answer built from real result titles and snippets.',
  'graph': 'react',
  'grounded': True,
  'legacy': False},
 {'group': '4. Web search',
  'label': 'Research graph: search, then read the pages',
  'prompt': 'What is NVIDIA OpenShell? Use a web search, then read two of the pages it finds.',
  'expect': 'Needs html.duckduckgo.com:443 allowed. Each result page is a different host, so each source ends as ok, blocked by the sandbox, refused by the '
            'site, not found, or empty page. The report lists failures and why.',
  'graph': 'research',
  'grounded': True,
  'legacy': False},
 {'group': '4. Web search',
  'label': 'Same fetch with the naive tool output (legacy)',
  'prompt': 'Use http_get on https://pypi.org/project/idna/ and quote the first sentence of the project description.',
  'expect': 'ALLOWED by the sandbox, but the legacy tool returns the first 300 characters of raw markup, so the model cannot quote the page. Compare with '
            '\'Read an allowed web page\' (readable text).',
  'graph': 'react',
  'grounded': False,
  'legacy': True}]


def collect_events(sb, t0):
    """Network events the sandbox logged since t0 (model calls to inference.local are counted, not listed)."""
    lg = subprocess.run(["openshell", "logs", sb], capture_output=True, text=True, timeout=60)
    events, infer, landlock = [], 0, ""
    for line in ANSI.sub("", lg.stdout).splitlines():
        ll = re.search(r"\[(\d+\.\d+)\].*Applying Landlock filesystem sandbox \[(.*?)\]", line)
        if ll and float(ll.group(1)) >= t0 - 2:
            landlock = ll.group(2)
        m = EVT.search(line)
        if not m or float(m.group(1)) < t0 - 2:
            continue
        kind, verdict, rest = m.group(2), m.group(4), m.group(5)
        if "inference.local" in rest:
            infer += 1; continue
        events.append({"t": round(float(m.group(1)) - t0, 1), "kind": kind, "verdict": verdict, "text": rest[:220]})
    return events, infer, landlock


def run(args, timeout):
    p = subprocess.run(["openshell", "sandbox", "exec", "-n", SANDBOX, "--"] + args, capture_output=True, text=True, timeout=timeout)
    return ANSI.sub("", p.stdout), ANSI.sub("", p.stderr)


GRAPHS = ("react", "research")


def run_prompt(prompt, graph="react", grounded=True, legacy=False):
    b64 = base64.b64encode(prompt.encode()).decode()
    t0 = time.time()
    cmd = f"rm -rf /sandbox/work /sandbox/remote.git; cd /sandbox && GRAPH={graph} GROUNDED={1 if grounded else 0} LEGACY_TOOLS={1 if legacy else 0} PROMPT_B64={b64} python3 langgraph_demo.py custom > /tmp/trace_custom.json 2>/tmp/trace_custom.err; echo exit=$?"
    last_err = ""
    for attempt in (1, 2):  # exec occasionally stalls before starting; one retry
        try:
            out, err = run(["sh", "-c", cmd], 200)
            if "exit=0" not in out:
                tail, _ = run(["sh", "-c", "tail -c 600 /tmp/trace_custom.err"], 20)
                return {"error": "agent run failed", "detail": tail or err or out}
            body, _ = run(["cat", "/tmp/trace_custom.json"], 20)
            trace = json.loads(body)[0]
            try:
                events, infer, landlock = collect_events(SANDBOX, t0)
            except Exception:  # noqa: BLE001
                events, infer, landlock = [], 0, ""
            return {"trace": trace, "events": events, "inference_calls": infer, "landlock": landlock, "elapsed": round(time.time() - t0, 1), "sandbox": SANDBOX}
        except subprocess.TimeoutExpired:
            last_err = f"sandbox exec timed out (attempt {attempt})"
        except Exception as e:  # noqa: BLE001
            return {"error": "could not read the trace", "detail": str(e)}
    return {"error": last_err}


EVT = re.compile(r"\[(\d+\.\d+)\].*?\[OCSF \] \[ocsf\] (NET:\w+|HTTP:\w+) \[(\w+)\] (ALLOWED|DENIED) (.*)")


# ---------------------------------------------------------------- policy editing
POLICY_SANDBOXES = {SANDBOX}
BASE_DIR, LOG_DIR = HERE / "state" / "baselines", HERE / "state" / "logs"
RE_HOST = re.compile(r"^[A-Za-z0-9*][A-Za-z0-9*.-]{0,252}$")
RE_BIN = re.compile(r"^/[A-Za-z0-9_./*+-]{1,200}$")
RE_PATH = re.compile(r"^/[A-Za-z0-9_./*{}%+~-]{0,200}$")
RE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def osh(args, timeout=90):
    p = subprocess.run(["openshell"] + args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ANSI.sub("", (p.stdout + p.stderr)).strip()


def get_policy(sb, rev=0):
    rc, out = osh(["policy", "get", sb] + (["--rev", str(rev)] if rev else []) + ["--full"])
    if rc != 0:
        return {"error": out}
    head, _, body = out.partition("\n---\n")
    meta = dict(re.findall(r"^(Version|Hash|Status|Active):\s+(\S+)", head, re.M))
    info = {"version": meta.get("Version"), "hash": (meta.get("Hash") or "")[:12], "status": meta.get("Status"), "yaml": body}
    try:
        import yaml
        d = yaml.safe_load(body) or {}
        info["policy"] = d
        info["fs"] = d.get("filesystem_policy") or {}
        info["process"] = d.get("process") or {}
        info["landlock"] = d.get("landlock") or {}
        info["blocks"] = [{"name": n, "binaries": [b.get("path") for b in (v.get("binaries") or [])],
                           "endpoints": [{"host": e.get("host"), "port": e.get("port"), "access": e.get("access"), "protocol": e.get("protocol"),
                                          "rules": [f'{r["allow"].get("method")} {r["allow"].get("path")}' for r in (e.get("rules") or []) if "allow" in r]} for e in v.get("endpoints", [])]}
                          for n, v in (d.get("network_policies") or {}).items()]
    except Exception as e:  # noqa: BLE001
        info["blocks"] = []; info["parse_error"] = str(e)
    return info


def ensure_baseline(sb):
    BASE_DIR.mkdir(exist_ok=True)
    f = BASE_DIR / f"{sb}.yaml"
    if not f.exists():
        pol = get_policy(sb)
        if "yaml" in pol and pol["yaml"].strip():
            f.write_text(pol["yaml"]); (BASE_DIR / f"{sb}.meta").write_text(f"version={pol['version']} hash={pol['hash']} saved={time.strftime('%F %T')}\n")
    return f


def log_change(sb, what, detail=""):
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "policy_changes.log", "a") as fh:
        fh.write(f"{time.strftime('%F %T')} {sb} {what} {detail}\n")


def build_update_args(sb, req, dry):
    args = ["policy", "update", sb]
    if req.get("remove"):
        if not re.match(r"^[A-Za-z0-9*.-]{1,253}:\d{1,5}$", req["remove"]):
            raise ValueError("remove must look like host:port")
        args += ["--remove-endpoint", req["remove"]]
    ep = req.get("endpoint")
    if ep:
        host, port = str(ep.get("host", "")).strip(), int(ep.get("port", 0))
        if not RE_HOST.match(host) or not (1 <= port <= 65535):
            raise ValueError("bad host or port")
        if ep.get("mode") == "rest":
            args += ["--add-endpoint", f"{host}:{port}::rest:enforce"]
            ms = [m for m in ep.get("methods", []) if m in METHODS] or ["GET"]
            path = ep.get("path") or "/**"
            if not RE_PATH.match(path):
                raise ValueError("bad path glob")
            for m in ms:
                args += ["--add-allow", f"{host}:{port}:{m}:{path}"]
        else:
            args += ["--add-endpoint", f"{host}:{port}:full"]
        if not ep.get("binaries"):
            raise ValueError("name at least one binary: a rule with no binary restriction is not allowed from this tool")
        for b in ep.get("binaries", [])[:6]:
            if not RE_BIN.match(b):
                raise ValueError(f"bad binary path: {b}")
            args += ["--binary", b]
        if ep.get("rule_name"):
            if not RE_NAME.match(ep["rule_name"]):
                raise ValueError("bad rule name")
            args += ["--rule-name", ep["rule_name"]]
    if len(args) == 3:
        raise ValueError("nothing to change")
    args += ["--dry-run"] if dry else ["--wait"]
    return args


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost"):
            return False
        if origin and re.sub(r"^https?://", "", origin).split(":")[0] not in ("127.0.0.1", "localhost"):
            return False
        return True

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        if self.path == "/api/health":
            return self._json(200, {"ok": True, "sandbox": SANDBOX})
        if self.path == "/api/samples":
            return self._json(200, SAMPLES)
        if self.path.startswith("/api/policy"):
            m = re.match(r"^/api/policy(/history|/rev|/default)?\?sandbox=([A-Za-z0-9_-]+)(?:&rev=(\d{1,4}))?$", self.path)
            if not m or m.group(2) not in POLICY_SANDBOXES:
                return self._json(400, {"error": "sandbox must be one of " + ", ".join(sorted(POLICY_SANDBOXES))})
            sb = m.group(2)
            if m.group(1) == "/history":
                rc, out = osh(["policy", "list", sb])
                revs = [{"version": int(a), "hash": b, "status": c, "created_ms": int(e)} for a, b, c, e in re.findall(r"^(\d+)\s+(\w+)\s+(\w+)\s+(\d+)", out, re.M)]
                return self._json(200, {"history": out, "revisions": revs})
            if m.group(1) == "/default":
                ensure_baseline(sb)
                f = BASE_DIR / f"{sb}.yaml"
                meta = (BASE_DIR / f"{sb}.meta").read_text().strip() if (BASE_DIR / f"{sb}.meta").exists() else None
                return self._json(200 if f.exists() else 404, {"yaml": f.read_text() if f.exists() else "", "meta": meta})
            if m.group(1) == "/rev":
                if not m.group(3):
                    return self._json(400, {"error": "rev required"})
                info = get_policy(sb, int(m.group(3)))
                return self._json(200 if "yaml" in info else 404, info)
            ensure_baseline(sb)
            info = get_policy(sb)
            info["baseline"] = (BASE_DIR / f"{sb}.meta").read_text().strip() if (BASE_DIR / f"{sb}.meta").exists() else None
            return self._json(200 if "yaml" in info else 502, info)
        path = self.path.split("?")[0]
        if path == "/":
            self.path = "/langgraph_viewer.html"
        elif not path.startswith(ALLOWED_PREFIX):
            return self._json(404, {"error": "not served"})
        return super().do_GET()

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        if self.path.startswith("/api/policy/"):
            return self._post_policy()
        if self.path != "/api/run":
            return self._json(404, {"error": "unknown endpoint"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(n, 4096)))
            prompt = str(body["prompt"]).strip()
            graph = body.get("graph", "react")
            grounded = bool(body.get("grounded", True))
            legacy = bool(body.get("legacy", False))
            if graph not in GRAPHS:
                return self._json(400, {"error": "graph must be one of " + ", ".join(GRAPHS)})
        except Exception:  # noqa: BLE001
            return self._json(400, {"error": "send JSON {\"prompt\": \"...\"}"})
        if not prompt or len(prompt) > MAX_PROMPT:
            return self._json(400, {"error": f"prompt must be 1-{MAX_PROMPT} characters"})
        if not LOCK.acquire(blocking=False):
            return self._json(429, {"error": "another run is in progress"})
        try:
            res = run_prompt(prompt, graph, grounded, legacy)
        finally:
            LOCK.release()
        return self._json(200 if ("trace" in res) else 502, res)

    def _post_policy(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(min(n, 300000)))
            sb = req["sandbox"]
            if sb not in POLICY_SANDBOXES:
                return self._json(400, {"error": "sandbox not allowed"})
        except Exception:  # noqa: BLE001
            return self._json(400, {"error": "bad request"})
        if not LOCK.acquire(blocking=False):
            return self._json(429, {"error": "another operation is in progress"})
        try:
            ensure_baseline(sb)
            action = self.path.rsplit("/", 1)[1]
            if action == "update":
                dry = req.get("mode") != "apply"
                args = build_update_args(sb, req, dry)
                rc, out = osh(args)
                if not dry:
                    log_change(sb, "update", " ".join(args[2:]) + f" rc={rc}")
                return self._json(200 if rc == 0 else 400, {"ok": rc == 0, "output": out[-6000:], "command": "openshell " + " ".join(args)})
            if action == "set":
                import tempfile, yaml
                text = str(req["yaml"])
                if len(text) > 200000 or "network_policies" not in (yaml.safe_load(text) or {}):
                    return self._json(400, {"error": "YAML must contain network_policies"})
                with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
                    fh.write(text); path = fh.name
                rc, out = osh(["policy", "set", sb, "--policy", path, "--wait"])
                os.unlink(path); log_change(sb, "set-yaml", f"rc={rc} bytes={len(text)}")
                return self._json(200 if rc == 0 else 400, {"ok": rc == 0, "output": out[-4000:]})
            if action == "save-default":  # make the CURRENT live policy the default that Reset returns to
                pol = get_policy(sb)
                if not pol.get("yaml", "").strip():
                    return self._json(502, {"error": "could not read the live policy"})
                (BASE_DIR / f"{sb}.yaml").write_text(pol["yaml"])
                (BASE_DIR / f"{sb}.meta").write_text(f"version={pol['version']} hash={pol['hash']} saved={time.strftime('%F %T')} (saved from live policy)\n")
                log_change(sb, "save-default", f"from live version={pol['version']}")
                return self._json(200, {"ok": True})
            if action == "set-default":  # replace the default with YAML the operator typed or pasted (does not touch the live policy)
                import yaml
                text = str(req["yaml"])
                doc = yaml.safe_load(text) or {}
                if len(text) > 200000 or not isinstance(doc, dict) or "network_policies" not in doc:
                    return self._json(400, {"error": "YAML must be a mapping that contains network_policies"})
                (BASE_DIR / f"{sb}.yaml").write_text(text)
                (BASE_DIR / f"{sb}.meta").write_text(f"saved={time.strftime('%F %T')} (edited by hand)\n")
                log_change(sb, "set-default", f"bytes={len(text)}")
                return self._json(200, {"ok": True})
            if action == "reset":
                f = BASE_DIR / f"{sb}.yaml"
                if not f.exists():
                    return self._json(400, {"error": "no baseline snapshot for this sandbox"})
                rc, out = osh(["policy", "set", sb, "--policy", str(f), "--wait"])
                log_change(sb, "reset-to-baseline", f"rc={rc}")
                return self._json(200 if rc == 0 else 400, {"ok": rc == 0, "output": out[-4000:]})
            return self._json(404, {"error": "unknown policy action"})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": "openshell timed out"})
        finally:
            LOCK.release()

    def log_message(self, fmt, *args):
        sys.stderr.write("[live] " + fmt % args + "\n")


if __name__ == "__main__":
    for _sb in sorted(POLICY_SANDBOXES):
        try:
            ensure_baseline(_sb)
        except Exception as _e:  # noqa: BLE001
            print("baseline skipped for", _sb, _e)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Live server on http://127.0.0.1:{PORT}/  (sandbox: {SANDBOX}; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
