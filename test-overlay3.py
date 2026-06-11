"""Proof of overlay: instrument the page to log when overlay appears/disappears, read via CDP."""
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

# Force navigate
send("Page.navigate", {"url": f"https://phantomic12.github.io/voxelforge-tts/?t={int(time.time())}"}, sid)
print("Waiting for page...")
for i in range(20):
    time.sleep(1)
    c = v(ev("document.querySelectorAll('.model-card').length || 0"))
    if c and c >= 7:
        print(f"  ✓ rendered ({c} cards)")
        break

# Load model
ev("document.getElementById('load-btn').click()")
print("Loading model...")
for i in range(30):
    time.sleep(1)
    t = v(ev("document.getElementById('load-btn')?.querySelector('span')?.textContent || ''"))
    if "loaded" in t.lower() or "✓" in t:
        print(f"  ✓ loaded after {i+1}s")
        break

# Click generate with default text
print("Clicking generate...")
ev("document.getElementById('generate-btn').click()")

# Now use a MutationObserver to log when overlay appears/disappears
# We instrument the page to push log entries to a global array
r = ev("""(function(){
    window._overlayLog = [];
    const start = performance.now();
    const obs = new MutationObserver(() => {
        const ov = document.querySelector('.gen-overlay');
        const card = ov?.querySelector('.gen-overlay__card');
        const t = (performance.now() - start).toFixed(1);
        if (ov && !window._overlayLog.some(x => x.t === t + '-in')) {
            window._overlayLog.push({t: t + '-in', text: card?.textContent?.trim()});
        }
        if (!ov && !window._overlayLog.some(x => x.t === t + '-out')) {
            window._overlayLog.push({t: t + '-out'});
        }
    });
    obs.observe(document.body, {childList: true, subtree: true});
    return { installed: true };
})()""")
print(f"Instrumented: {v(r)}")

# Wait for generation to complete
for i in range(20):
    time.sleep(0.5)
    s = v(ev("""(function(){
        const p = document.getElementById('player');
        const a = document.getElementById('audio-element');
        return { 
            visible: p?.classList.contains('player--visible'), 
            dur: a?.duration,
            log: window._overlayLog || []
        };
    })()"""))
    log = s.get("log", [])
    if s.get("visible") and s.get("dur"):
        print(f"  ✓ generation done after {(i+1)*0.5:.1f}s, dur={s.get('dur')}")
        print(f"\n--- Overlay lifecycle log ---")
        for entry in log:
            print(f"  {entry}")
        break
else:
    print("  ❌ never completed")
    s = v(ev("window._overlayLog || []"))
    print(f"  log so far: {s}")

# Take final screenshot
time.sleep(0.5)
mid = send("Page.captureScreenshot", {"format": "png"}, sid)
r = wait(mid)
if r and "result" in r:
    Path(SHOT_DIR / "PROOF-final.png").write_bytes(base64.b64decode(r["result"]["data"]))

ws.close()
print("DONE")
