"""Debug what an http_get-style tool actually returns to the model (run inside the sandbox).
    python3 tool_debug.py URL [URL ...]
Prints status, content-type, size, the exact 300-char string the ReAct agent's http_get returns, and a readable-text preview."""
import re, sys, urllib.request, urllib.error

def readable(body):
    t = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", body)
    title = (re.search(r"(?is)<title[^>]*>(.*?)</title>", t) or [None, ""])[1].strip()
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()
    return title, text

for url in sys.argv[1:]:
    print("=" * 100, "\nURL:", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Python-urllib"})  # what the tool sends today
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(2_000_000); body = raw.decode("utf-8", "replace")
            print("status:", r.status, "| content-type:", r.headers.get("content-type"), "| bytes:", len(raw), "| final url:", r.geturl()[:100])
    except urllib.error.HTTPError as e:
        body = e.read(4000).decode("utf-8", "replace"); print("HTTPError:", e.code, e.reason, "| body bytes:", len(body))
    except Exception as e:
        print("ERROR:", type(e).__name__, e); continue
    print("--- what the model sees today (first 300 chars) ---"); print(repr(body[:300]))
    title, text = readable(body)
    print("--- readable text: title =", repr(title[:80]), "| text chars =", len(text)); print(repr(text[:300]))
