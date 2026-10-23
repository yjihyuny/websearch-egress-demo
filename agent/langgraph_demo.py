"""LangGraph agents that run INSIDE an OpenShell sandbox. Every tool call is subject to the sandbox policy.

Model:   https://inference.local/v1  (OpenShell routes it to the configured endpoint)
Graph 1 "react":    agent <-> tools   (tools: http_get, write_file, read_file, git)
Graph 2 "research": planner -> researcher x N (parallel, via Send) -> synthesizer   (a small "deep research" agent)

Install (inside the sandbox):  python3 -m pip install --target /sandbox/lg langgraph langchain-openai
Run:   python3 langgraph_demo.py {fetch-allowed|fetch-denied|write-denied|write-ok|all|graph [name]|json|custom}
  json   = emit one JSON trace per built-in task for langgraph_viewer.html
  custom = prompt from PROMPT_B64 (base64), graph from GRAPH=react|research, GROUNDED=0|1, LEGACY_TOOLS=0|1; prints a JSON trace
"""
import sys
sys.path.insert(0, "/sandbox/lg")
import html as htmllib, json, operator, os, re, shlex, subprocess, time, urllib.error, urllib.parse, urllib.request
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Send

MODEL = os.environ.get("MODEL", "/models/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4")
BASE = os.environ.get("BASE_URL", "https://inference.local/v1")
WORK = "/sandbox/work"
UA = "LangGraphDemo/1.0 (+OpenShell sandbox demo)"  # honest user agent; we do not try to evade bot protection
GROUNDED = os.environ.get("GROUNDED", "1") != "0"
LEGACY_TOOLS = os.environ.get("LEGACY_TOOLS", "0") == "1"  # original http_get: raw first 300 chars, opaque errors
SYSTEM = ("You are a careful assistant with tools. Base every factual claim on tool results from THIS conversation and name the source URL. "
          "If a tool is blocked, refused, or returns no readable content, say so plainly and do NOT fill the gap from memory. "
          "Distinguish 'blocked by the sandbox policy' from 'refused by the website' (the site returned 403/captcha/JavaScript-only page). "
          "Only add general knowledge if the user asks, and label it clearly as not from the tools.")


# ------------------------------------------------------------------ tools
def readable(body):
    t = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", body)
    title = (re.search(r"(?is)<title[^>]*>(.*?)</title>", t) or [None, ""])[1].strip()
    text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", t))).strip()
    return title, text


def fetch_readable(url, max_chars=2500, timeout=20):
    """Fetch a URL and say WHY it failed. kind: ok | empty_shell | not_found | sandbox_blocked | site_refused | error.
    The sandbox and the website can both answer 403: sandbox denials mention the proxy / policy_denied; a site refusal carries the site's own page."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(3_000_000); status = r.status; ctype = r.headers.get("content-type", "")
        body = raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read(20000).decode("utf-8", "replace")
        if "policy_denied" in body or "not permitted by policy" in body:
            return {"url": url, "ok": False, "kind": "sandbox_blocked", "status": e.code, "text": f"BLOCKED BY SANDBOX POLICY (proxy answered {e.code}): the destination is not allowed for this program."}
        _, txt = readable(body)
        if e.code in (404, 410):
            return {"url": url, "ok": False, "kind": "not_found", "status": e.code,
                    "text": f"NOT FOUND (HTTP {e.code}): the sandbox allowed the connection, but this URL does not exist on the site (the model may have guessed it). Page said: {txt[:100]}"}
        return {"url": url, "ok": False, "kind": "site_refused", "status": e.code,
                "text": f"REFUSED BY THE SITE (HTTP {e.code} {e.reason}): the sandbox allowed the connection but the website rejected this automated request. Page said: {txt[:160]}"}
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "Tunnel connection failed" in reason:
            return {"url": url, "ok": False, "kind": "sandbox_blocked", "status": 403, "text": "BLOCKED BY SANDBOX POLICY (proxy refused the tunnel, 403): this host:port is not allowed for this program."}
        return {"url": url, "ok": False, "kind": "error", "status": None, "text": f"NETWORK ERROR: {type(e).__name__}: {reason}"}
    except Exception as e:
        return {"url": url, "ok": False, "kind": "error", "status": None, "text": f"ERROR: {type(e).__name__}: {e}"}
    if url.startswith("https://html.duckduckgo.com/"):
        res = parse_ddg(body)
        return {"url": url, "ok": bool(res), "kind": "ok" if res else "empty_shell", "status": status,
                "text": "\n".join(f"{n}. {t} - {u} - {sn}" for n, (t, u, sn) in enumerate(res, 1))[:max_chars] or "search returned no parseable results"}
    if "json" in ctype or body.lstrip().startswith(("{", "[")):
        try:
            o = json.loads(body)
        except Exception:
            o = None
        if isinstance(o, dict) and "info" in o and "pypi.org" in url:
            i = o["info"]; text = f"PyPI {i.get('name')} {i.get('version')}: {i.get('summary')} (requires python {i.get('requires_python')})"
        elif isinstance(o, dict) and "full_name" in o:
            text = (f"GitHub {o['full_name']}: {o.get('description')} | stars {o.get('stargazers_count')} forks {o.get('forks_count')} issues {o.get('open_issues_count')} "
                    f"| language {o.get('language')} | license {(o.get('license') or {}).get('spdx_id')} | pushed {o.get('pushed_at')}")
        elif isinstance(o, dict) and "dist-tags" in o:
            text = f"npm {o.get('name')}: latest {o['dist-tags'].get('latest')} | {o.get('description')}"
        elif isinstance(o, dict) and ("pipeline_tag" in o or "modelId" in o):
            text = f"HF {o.get('id') or o.get('modelId')}: task {o.get('pipeline_tag')} | downloads {o.get('downloads')} | likes {o.get('likes')}"
        else:
            text = "JSON: " + (json.dumps(o) if o is not None else body)[:max_chars]
        return {"url": url, "ok": True, "kind": "ok", "status": status, "text": text[:max_chars]}
    title, text = readable(body)
    full = (f"Title: {title}. " if title else "") + text
    if len(text) < 200:
        return {"url": url, "ok": False, "kind": "empty_shell", "status": status,
                "text": f"PAGE HAS NO READABLE CONTENT (HTTP {status}, {len(raw)} bytes of markup, {len(text)} chars of text; usually a JavaScript-only page or a bot check). Text found: {full[:200]}"}
    return {"url": url, "ok": True, "kind": "ok", "status": status, "text": full[:max_chars]}


def parse_ddg(body):
    out = []
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    for (href, title), sn in zip(links, snips + [""] * len(links)):
        m = re.search(r"uddg=([^&]+)", href)
        u = urllib.parse.unquote(m.group(1)) if m else href
        clean = lambda x: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", x))).strip()
        out.append((clean(title)[:90], u[:140], clean(sn)[:220]))
    return out[:8]


@tool
def http_get(url: str) -> str:
    """HTTP GET a URL. Returns the readable text of the page (first 2500 characters; JSON from PyPI/GitHub/npm/HF is summarised).
    Failures say whether the SANDBOX blocked it or the WEBSITE refused it, or whether the page had no readable content."""
    if LEGACY_TOOLS:  # the original tool: raw markup, opaque errors
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return f"HTTP {resp.status}: {resp.read(300).decode('utf-8', 'replace')}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
    r = fetch_readable(url, 2500)
    if r["kind"] == "ok":
        return f"HTTP {r['status']} readable text: {r['text']}"
    if r["kind"] == "empty_shell":
        return f"WARNING: {r['text']}"
    return f"ERROR: {r['text']}"


@tool
def search_web(query: str) -> str:
    """Search the web (DuckDuckGo HTML endpoint) and return up to 8 results as 'n. title - url - snippet'. Needs html.duckduckgo.com:443 to be allowed by the sandbox policy."""
    r = fetch_readable("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query), 2500)
    return (f"RESULTS for {query!r}:\n" + r["text"]) if r["kind"] == "ok" else f"ERROR: {r['text']}"


@tool
def write_file(path: str, text: str) -> str:
    """Write text to a file path inside the sandbox (parent directories are created under /sandbox and /tmp)."""
    try:
        if path.startswith(("/sandbox/", "/tmp/")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return f"wrote {len(text)} bytes to {path}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@tool
def read_file(path: str) -> str:
    """Read the first 400 characters of a text file inside the sandbox."""
    try:
        with open(path) as f:
            return f.read(400)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


GIT_OK = {"ls-files", "ls-tree", "tag", "init", "status", "add", "commit", "log", "remote", "push", "clone", "pull", "fetch", "branch", "checkout", "switch", "diff", "show", "rev-parse"}
GIT_BAD = re.compile(r"upload-pack|receive-pack|exec-path|sshCommand|alias\.|--config|(^|\s)-c(\s|$)")


@tool
def git(command: str, cwd: str = WORK) -> str:
    """Run one git command inside the sandbox. Example: command="init demo" or command="commit -m 'first commit'".
    cwd must be under /sandbox (default /sandbox/work). Network commands (clone, push, pull, fetch) go through the sandbox proxy."""
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return f"ERROR: {e}"
    if argv and argv[0] == "git":
        argv = argv[1:]
    if not argv or argv[0] not in GIT_OK or GIT_BAD.search(command):
        return f"ERROR: git subcommand or option not allowed here: {command[:60]}"
    cwd = os.path.normpath(cwd)
    if not cwd.startswith("/sandbox"):
        return "ERROR: cwd must be under /sandbox"
    try:
        os.makedirs(cwd, exist_ok=True)
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", HOME="/sandbox", GIT_AUTHOR_NAME="LangGraph Agent", GIT_AUTHOR_EMAIL="agent@example.invalid",
                   GIT_COMMITTER_NAME="LangGraph Agent", GIT_COMMITTER_EMAIL="agent@example.invalid",
                   GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="init.defaultBranch", GIT_CONFIG_VALUE_0="main")
        p = subprocess.run(["git"] + argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=45)
        return f"exit {p.returncode}: {(p.stdout + p.stderr).strip()[:700]}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


TOOLS = [http_get, search_web, write_file, read_file, git]
base_llm = ChatOpenAI(model=MODEL, base_url=BASE, api_key="none", temperature=0, max_tokens=1500, timeout=180)
llm = base_llm.bind_tools(TOOLS)


# ------------------------------------------------------------------ graph 1: react
class State(TypedDict):
    messages: Annotated[list, add_messages]


def agent(state: State):
    msgs = ([SystemMessage(SYSTEM)] if GROUNDED else []) + state["messages"]
    return {"messages": [llm.invoke(msgs)]}


g = StateGraph(State)
g.add_node("agent", agent)
g.add_node("tools", ToolNode(TOOLS))
g.add_edge(START, "agent")
g.add_conditional_edges("agent", tools_condition)  # tool call -> "tools", else END
g.add_edge("tools", "agent")
app = g.compile()


# ------------------------------------------------------------------ graph 2: deep research
SOURCES = """Sources you may choose from (use the exact URL shapes):
- PyPI package metadata:        https://pypi.org/pypi/<package>/json
- GitHub repository metadata:   https://api.github.com/repos/<owner>/<repo>
- GitHub README (raw):          https://raw.githubusercontent.com/<owner>/<repo>/HEAD/README.md
- Hugging Face model metadata:  https://huggingface.co/api/models/<owner>/<name>
- npm package metadata:         https://registry.npmjs.org/<package>
- Example page:                 https://example.com
- Web search (text results):    https://html.duckduckgo.com/html/?q=<url-encoded query>"""


class RState(TypedDict):
    question: str
    urls: list
    findings: Annotated[list, operator.add]
    report: str


def planner(state: RState):
    msg = base_llm.invoke([SystemMessage(f"You plan web research. Reply with ONLY a JSON array of 2 to 5 URLs (https) to consult for the user's question, nothing else.\n{SOURCES}"),
                           HumanMessage(state["question"])])
    urls = []
    for u in re.findall(r"https?://[^\s\"'\]\),>]+", str(msg.content)):
        if u not in urls:
            urls.append(u)
    return {"urls": urls[:5]}


def fan_out(state: RState):
    if not state["urls"]:
        return "synthesizer"
    return [Send("researcher", {"url": u}) for u in state["urls"]]


def researcher(state: dict):
    f = fetch_readable(state["url"], 900)
    return {"findings": [{"url": f["url"], "ok": f["ok"], "outcome": f["kind"], "text": f["text"]}]}


def synthesizer(state: RState):
    lines = [f"[{i + 1}] {f['url']} -> {'OK' if f['ok'] else 'FAILED (' + f.get('outcome', 'error') + ')'}: {f['text']}" for i, f in enumerate(state.get("findings", []))]
    msg = base_llm.invoke([SystemMessage("Write a short research report (under 180 words) answering the question using ONLY the findings. Cite sources as [n]. "
                                          "List any sources that FAILED and say why (blocked by sandbox policy, refused by the website, or no readable content), and say what could not be verified. Never state facts that are not in the findings."),
                           HumanMessage(f"Question: {state['question']}\n\nFindings:\n" + "\n".join(lines or ["(no sources could be consulted)"]))])
    return {"report": str(msg.content).strip()}


rg = StateGraph(RState)
rg.add_node("planner", planner)
rg.add_node("researcher", researcher)
rg.add_node("synthesizer", synthesizer)
rg.add_edge(START, "planner")
rg.add_conditional_edges("planner", fan_out, ["researcher", "synthesizer"])
rg.add_edge("researcher", "synthesizer")
rg.add_edge("synthesizer", END)
research_app = rg.compile()


# ------------------------------------------------------------------ tasks, running, tracing
TASKS = {
    "fetch-allowed": "Use http_get on https://pypi.org/pypi/idna/json and tell me the latest version of idna. Be brief.",
    "fetch-denied": "Use http_get on https://example.com and tell me the page title. If it fails, say exactly what error you got.",
    "write-denied": "Use write_file to write 'hi' to /etc/agent-note.txt. Report the exact result.",
    "write-ok": "Use write_file to write 'hello from langgraph' to /tmp/agent-note.txt, then report the exact result.",
}


def custom_prompt():
    """Prompt for the 'custom' task comes base64-encoded in PROMPT_B64 (keeps shell quoting out of it)."""
    import base64
    return base64.b64decode(os.environ["PROMPT_B64"]).decode("utf-8")[:700]


def run(name):
    print(f"\n=== {name}: {TASKS[name]}")
    out = app.invoke({"messages": [HumanMessage(TASKS[name])]}, {"recursion_limit": 24})
    for m in out["messages"][1:]:
        kind = m.type
        if kind == "ai" and m.tool_calls:
            print(f"[ai -> tool] {[(c['name'], c['args']) for c in m.tool_calls]}")
        elif kind == "tool":
            print(f"[tool result] {str(m.content)[:200]}")
        elif kind == "ai":
            print(f"[ai] {str(m.content).strip()[:400]}")


def trace(name, graph="react"):
    """Run one task and return a structured event list (one event per graph step)."""
    t0, events, step = time.time(), [], 0
    try:
        if graph == "research":
            for upd in research_app.stream({"question": TASKS[name], "urls": [], "findings": [], "report": ""}, {"recursion_limit": 24}, stream_mode="updates"):
                for node, delta in upd.items():
                    base = {"node": node, "t": round(time.time() - t0, 2)}
                    if node == "planner":
                        step += 1; events.append({**base, "step": step, "kind": "plan", "urls": delta.get("urls", [])})
                    elif node == "researcher":
                        for f in delta.get("findings", []):
                            step += 1; events.append({**base, "step": step, "kind": "research", "url": f["url"], "ok": f["ok"], "outcome": f.get("outcome", ""), "content": f["text"][:600]})
                    elif node == "synthesizer":
                        step += 1; events.append({**base, "step": step, "kind": "final", "content": delta.get("report", "")[:1500]})
        else:
            for upd in app.stream({"messages": [HumanMessage(TASKS[name])]}, {"recursion_limit": 24}, stream_mode="updates"):
                for node, delta in upd.items():
                    for m in delta["messages"]:
                        step += 1
                        ev = {"step": step, "node": node, "t": round(time.time() - t0, 2)}
                        if m.type == "ai" and m.tool_calls:
                            ev.update(kind="tool_call", calls=[{"name": c["name"], "args": c["args"]} for c in m.tool_calls])
                        elif m.type == "tool":
                            ev.update(kind="tool_result", tool=m.name, content=str(m.content)[:1500])
                        else:
                            ev.update(kind="final", content=str(m.content).strip()[:800])
                        events.append(ev)
    except Exception as e:  # e.g. GraphRecursionError when the agent keeps retrying a blocked call
        events.append({"step": step + 1, "node": "agent", "t": round(time.time() - t0, 2), "kind": "final",
                       "content": f"[run stopped: {type(e).__name__}: the agent kept retrying; partial trace shown]"})
    return {"task": name, "prompt": TASKS[name], "graph": graph, "model": MODEL, "base_url": BASE, "events": events}


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "graph":
        which_g = sys.argv[2] if len(sys.argv) > 2 else "react"
        print({"react": app, "research": research_app}.get(which_g, app).get_graph().draw_mermaid())
    elif which == "custom":
        TASKS["custom"] = custom_prompt()
        print(json.dumps([trace("custom", os.environ.get("GRAPH", "react"))]))
    elif which == "json":
        print(json.dumps([trace(n) for n in TASKS]))
    else:
        for n in (TASKS if which == "all" else [which]):
            run(n)
