"""Use Page.startScreencast to capture frames during generation."""
import json, time, urllib.request, websocket, base64
from pathlib import Path
from threading import Thread

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

# Listen for screencast frames
frames = []
def listen():
    while True:
        try:
            ws.settimeout(0.5)
            r = json.loads(ws.recv())
            if r.get("method") == "Page.screencastFrame":
                frames.append(r["params"])
            elif r.get("id") and "error" in r:
                pass
        except:
            pass
        # exit condition
        if not listening[0]:
            return
listening = [True]
t = Thread(target=listen, daemon=True)
t.start()

# Start screencast
send("Page.enable", sid)
send("Page.startScreencast", {"format": "png", "everyNthFrame": 1}, sid)
time.sleep(0.5)

# Click generate
print("Clicking generate, waiting for frames...")
ev("document.getElementById('generate-btn').click()")
time.sleep(3)  # wait for completion
send("Page.stopScreencast", sid=sid) if False else None
mid = send("Page.stopScreencast", {}, sid)
wait(mid)
listening[0] = False
time.sleep(0.5)

# Find frame that has the overlay
print(f"Captured {len(frames)} frames")
saved = 0
for i, f in enumerate(frames):
    data = f.get("data")
    meta = f.get("metadata", {})
    if data:
        # Save every 2nd frame to keep file count down
        if i % 2 == 0:
            ts = meta.get("timestamp", 0)
            Path(SHOT_DIR / f"frame-{i:03d}-{ts:.0f}.png").write_bytes(base64.b64decode(data))
            saved += 1

print(f"Saved {saved} frames")
ws.close()
