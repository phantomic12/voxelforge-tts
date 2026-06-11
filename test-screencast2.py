"""Capture overlay mid-flight by streaming Page.captureScreenshot calls rapidly."""
import json, time, urllib.request, websocket, base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

CDP = "http://100.93.66.35:9335"
SHOT_DIR = Path("/tmp/voxelforge-shots")
SHOT_DIR.mkdir(exist_ok=True)
ws_url = json.loads(urllib.request.urlopen(f"{CDP}/json/version").read())["webSocketDebuggerUrl"]
ws = websocket.create_connection(ws_url, timeout=30)
msg_id = [0]
saved = []

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

# Load
ev("document.getElementById('load-btn').click()")
print("Loading...")
for i in range(30):
    time.sleep(1)
    t = v(ev("document.getElementById('load-btn')?.querySelector('span')?.textContent || ''"))
    if "loaded" in t.lower() or "✓" in t:
        print(f"  ✓ loaded")
        break

# Use a SLOW but reliable capture approach: Page.startScreencast at high rate
# This streams frames from the browser's compositor, not from JS, so even if
# the main thread is frozen, we'll get frames.
print("Starting screencast at 30fps...")
send("Page.enable", sid)
send("Page.startScreencast", {"format": "png", "everyNthFrame": 1, "maxWidth": 800, "maxHeight": 600}, sid)

# Wait a moment for screencast to start
time.sleep(0.5)

# Trigger generation
ev("document.getElementById('generate-btn').click()")

# Collect frames for 3 seconds
print("Collecting frames for 3s...")
deadline = time.time() + 3
frames_with_overlay = []
all_frames = []
while time.time() < deadline:
    try:
        ws.settimeout(0.2)
        r = json.loads(ws.recv())
        if r.get("method") == "Page.screencastFrame":
            params = r["params"]
            data = params.get("data", "")
            ts = params.get("metadata", {}).get("timestamp", 0)
            all_frames.append((ts, data))
            # Acknowledge the frame
            ws.send(json.dumps({
                "id": 999999,
                "method": "Page.screencastFrameAck",
                "params": {"sessionId": params.get("sessionId", 0)}
            }))
    except:
        pass

# Stop screencast
send("Page.stopScreencast", {}, sid)
time.sleep(0.5)

# Drain any remaining frames
while True:
    try:
        ws.settimeout(0.2)
        r = json.loads(ws.recv())
        if r.get("method") == "Page.screencastFrame":
            params = r["params"]
            data = params.get("data", "")
            ts = params.get("metadata", {}).get("timestamp", 0)
            all_frames.append((ts, data))
        elif r.get("id") and r["id"] == msg_id[0]:
            break
    except:
        break

print(f"Total frames: {len(all_frames)}")

# Save all frames
for i, (ts, data) in enumerate(all_frames):
    if data and i % 3 == 0:  # save every 3rd frame
        Path(SHOT_DIR / f"cast-{i:04d}.png").write_bytes(base64.b64decode(data))

# To find frames WITH the overlay, we can't easily detect from PNG without OCR
# So we just save all of them and the user can scan
print(f"Saved {len(all_frames) // 3} frames to {SHOT_DIR}")

# Use Page.captureScreenshot as a sanity check for the final state
mid = send("Page.captureScreenshot", {"format": "png"}, sid)
r = wait(mid)
if r and "result" in r:
    Path(SHOT_DIR / "PROOF-final.png").write_bytes(base64.b64decode(r["result"]["data"]))

ws.close()
print("DONE")
