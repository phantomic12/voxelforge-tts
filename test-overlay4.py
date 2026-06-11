"""Try to catch the overlay with a 50ms-delay screenshot."""
import json, time, urllib.request, websocket, base64
from pathlib import Path

CDP = "http://100.93.66.35:9335"
SHOT_DIR = Path("/tmp/voxelforge-shots")
SHOT_DIR.mkdir(exist_ok=True)
ws_url = json.loads(urllib.request.urlopen(f"{CDP}/json/version").read())["webSocketDebuggerUrl"]
ws = websocket.create_connection(ws_url, timeout=30)
msg_id = [0]

def send(method, params=None, sid=None):
    msg_id[0] += 1
    m = {"id": msg_id[0], "method": method, "params": params or {}}
    if sid: m["sessionId"] = sid
    ws.send(json.dumps(m))
    return msg_id[0]

def wait(mid, timeout=30):
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            ws.settimeout(max(0.1, dl - time.time()))
            r = json.loads(ws.recv())
            if r.get("id") == mid: return r
        except: pass
    return None

def v(resp):
    if not resp: return {}
    return resp.get("result",{}).get("result",{}).get("value",{}) or {}

tabs = json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
page = [t for t in tabs if t["type"] == "page"][-1]
tid = page["id"]
mid = send("Target.attachToTarget", {"targetId": tid, "flatten": True})
sid = None
for _ in range(20):
    ws.settimeout(2)
    r = json.loads(ws.recv())
    if r.get("id") == mid and "result" in r: sid = r["result"].get("sessionId"); break
    if r.get("method") == "Target.attachedToTarget": sid = r["params"].get("sessionId"); break

def ev(expr, await_p=False):
    mid = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_p}, sid)
    return wait(mid, 30)

# Navigate fresh
send("Page.navigate", {"url": f"https://phantomic12.github.io/voxelforge-tts/?t={int(time.time())}"}, sid)
print("Waiting for page...")
for i in range(20):
    time.sleep(1)
    c = v(ev("document.querySelectorAll('.model-card').length || 0"))
    if c and c >= 7:
        print(f"  ✓ rendered")
        break

# Load model
ev("document.getElementById('load-btn').click()")
print("Loading...")
for i in range(30):
    time.sleep(1)
    t = v(ev("document.getElementById('load-btn')?.querySelector('span')?.textContent || ''"))
    if "loaded" in t.lower() or "✓" in t:
        print(f"  ✓ loaded")
        break

# Click generate, then immediately try to capture
print("\nClicking generate...")

# Use a precomputed screenshot request ID
mid_shot = send("Page.captureScreenshot", {"format": "png"}, sid)
# Now click generate
ev("document.getElementById('generate-btn').click()")
# Try to wait for the screenshot response, which will fire when the renderer
# has a moment. But the main thread is frozen, so the renderer will only
# paint the overlay when it gets a chance.
r = wait(mid_shot, 3)
if r and "result" in r:
    Path(SHOT_DIR / "ATTEMPT-overlay.png").write_bytes(base64.b64decode(r["result"]["data"]))
    print(f"  saved ATTEMPT-overlay.png")
else:
    print(f"  no response: {r}")

# Try multiple times in case
for attempt in range(5):
    mid_shot = send("Page.captureScreenshot", {"format": "png"}, sid)
    ev("document.getElementById('generate-btn').click()")
    r = wait(mid_shot, 3)
    if r and "result" in r:
        Path(SHOT_DIR / f"ATTEMPT-overlay-{attempt}.png").write_bytes(base64.b64decode(r["result"]["data"]))
        print(f"  saved ATTEMPT-overlay-{attempt}.png")
    time.sleep(1)  # let things settle

ws.close()
print("DONE")
