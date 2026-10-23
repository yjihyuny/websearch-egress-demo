"""Rebuild web/langgraph_viewer.html and web/demo_console.html from build/ templates + the policy export.
   python3 build/build_all.py        (from the project root)
   Refresh the policy export first if the live policy changed:
     openshell policy get <sandbox> --full   -> build/policy.yaml  (strip the header lines before 'version:')
     python3 -c "import yaml,json;print(json.dumps(yaml.safe_load(open('build/policy.yaml'))))" > build/policy.json"""
import json, time
from pathlib import Path
root = Path(__file__).resolve().parent.parent
pol = (root / "build/policy.json").read_text().replace("</", "<\\/")
yml = (root / "build/policy.yaml").read_text().replace("&", "&amp;").replace("<", "&lt;")
tr = (root / "build/traces_embedded.json").read_text().replace("</", "<\\/")
v = (root / "build/lg_viewer.template.html").read_text().replace("__POLICY__", pol).replace("__TRACES__", tr).replace("__YAML__", yml)
(root / "web/langgraph_viewer.html").write_text(v)
c = (root / "build/console.template.html").read_text().replace("__POLICY__", pol).replace("__YAML__", yml).replace("__STAMP__", time.strftime("%Y-%m-%d"))
(root / "web/demo_console.html").write_text(c)
print("built web/langgraph_viewer.html (%d traces) and web/demo_console.html" % len(json.loads(tr)))
