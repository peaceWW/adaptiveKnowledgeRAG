import json
import urllib.request
from pathlib import Path

kbs = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/knowledge-bases"))
kb_id = kbs[0]["id"]
path = Path("backend/fixtures/cdc_design_guide.md")
data = path.read_bytes()
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
body = (
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"kb_id\"\r\n\r\n{kb_id}\r\n"
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: text/markdown\r\n\r\n"
).encode() + data + f"\r\n--{boundary}--\r\n".encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/documents/upload",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
)
resp = json.load(urllib.request.urlopen(req, timeout=60))
print("upload", resp["status"], resp["recommended_strategy"], resp["classification"]["knowledge_type"])
sid = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/strategies"))[0]["id"]
req2 = urllib.request.Request(
    f"http://127.0.0.1:8000/api/documents/{resp['id']}/confirm-strategy",
    data=json.dumps({"strategy_id": sid}).encode(),
    headers={"Content-Type": "application/json"},
)
resp2 = json.load(urllib.request.urlopen(req2, timeout=60))
print("extract", resp2["status"], resp2["parse_progress"])
units = json.load(urllib.request.urlopen(f"http://127.0.0.1:8000/api/knowledge-units?document_id={resp['id']}"))
print("units", len(units), [u["semantic_role"] for u in units])
graph = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/graph?name=CDC"))
print("graph_nodes", len(graph.get("nodes") or []), "edges", len(graph.get("edges") or []))
