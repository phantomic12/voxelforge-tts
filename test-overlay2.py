"""Verify the overlay shows in the DOM during generation."""
import json, time, urllib.request, websocket, base64, sys
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

# Find or create tab
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

# Force navigate to fresh page
send("Page.navigate", {"url": f"https://phantomic12.github.io/voxelforge-tts/?t={int(time.time())}"}, sid)
print("Navigating...")
for i in range(20):
    time.sleep(1)
    c = v(ev("document.querySelectorAll('.model-card').length || 0"))
    if c and c >= 7:
        print(f"  ✓ rendered ({c} cards)")
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

# Type VERY long text to slow generation
long_text = ("The quick brown fox jumps over the lazy dog. "
             "Pack my box with five dozen liquor jugs. "
             "How vexingly quick daft zebras jump. "
             "Sphinx of black quartz, judge my vow. "
             "The five boxing wizards jump quickly. "
             "Jackdaws love my big sphinx of quartz. ")  # ~300 chars

ev(f"""(function(){{
    const ta = document.getElementById('text-input');
    ta.value = {json.dumps(long_text)};
    ta.dispatchEvent(new Event('input', {{bubbles:true}}));
}})()""")
print(f"Typed {len(long_text)} chars")

# Click generate
ev("document.getElementById('generate-btn').click()")
print("Clicked generate")

# Try to catch the overlay — poll fast
for i in range(40):
    time.sleep(0.1)
    s = v(ev("""(function(){
        return {
            hasOverlay: !!document.querySelector('.gen-overlay'),
            cardText: document.querySelector('.gen-overlay__card')?.textContent?.trim(),
            playerVisible: document.getElementById('player')?.classList.contains('player--visible'),
            audioDur: document.getElementById('audio-element')?.duration
        };
    })()"""))
    h = s.get('hasOverlay')
    p = s.get('playerVisible')
    d = s.get('audioDur')
    if h and not p:
        print(f"  ✓✓✓ OVERLAY VISIBLE at {i*0.1:.1f}s: {s.get('cardText')!r}")
        # Capture screenshot NOW
        mid = send("Page.captureScreenshot", {"format": "png"}, sid)
        r = wait(mid, 5)
        if r and "result" in r:
            Path(SHOT_DIR / "OVERLAY-CAPTURED.png").write_bytes(base64.b64decode(r["result"]["data"]))
            print(f"  ✓ SCREENSHOT SAVED")
        break
    elif p and not h:
        print(f"  generation done at {i*0.1:.1f}s, dur={d}")
        break
else:
    print("  ❌ never saw overlay (likely too fast)")

# Final state
time.sleep(0.5)
mid = send("Page.captureScreenshot", {"format": "png"}, sid)
r = wait(mid)
if r and "result" in r:
    Path(SHOT_DIR / "OVERLAY-FINAL.png").write_bytes(base64.b64decode(r["result"]["data"]))

ws.close()
print("DONE")
