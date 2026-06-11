"""Quick smoke test: open page, select model, load, click generate, screenshot the overlay."""
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

# Fresh tab
send("Target.createTarget", {"url": "about:blank"})
time.sleep(1)
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

# Navigate with cache-bust
send("Page.enable", sid)
send("Page.navigate", {"url": f"https://phantomic12.github.io/voxelforge-tts/?t={int(time.time())}"}, sid)
print("Waiting for page...")
for i in range(20):
    time.sleep(1)
    c = v(ev("document.querySelectorAll('.model-card').length || 0"))
    if c and c >= 7:
        print(f"  ✓ rendered ({c} cards) after {i+1}s")
        break

# Wait for page to settle after navigation
time.sleep(2)

# Screenshot: initial state
mid = send("Page.captureScreenshot", {"format": "png"}, sid)
r = wait(mid)
if r and "result" in r:
    Path(SHOT_DIR / "overlay-01-init.png").write_bytes(base64.b64decode(r["result"]["data"]))
    print("  screenshot: overlay-01-init.png")
else:
    print(f"  ⚠ screenshot failed: {r}")

# Click load
ev("document.getElementById('load-btn').click()")
print("Loading model...")
for i in range(30):
    time.sleep(1)
    t = v(ev("document.getElementById('load-btn')?.querySelector('span')?.textContent || ''"))
    if "loaded" in t.lower() or "✓" in t:
        print(f"  ✓ loaded after {i+1}s")
        break

# Screenshot: ready
mid = send("Page.captureScreenshot", {"format": "png"}, sid)
r = wait(mid)
Path(SHOT_DIR / "overlay-02-ready.png").write_bytes(base64.b64decode(r["result"]["data"]))
print("  screenshot: overlay-02-ready.png")

# Type text — make it longer to ensure generation takes measurable time
ev("""(function(){
    const ta = document.getElementById('text-input');
    ta.value = 'The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. How vexingly quick daft zebras jump. Sphinx of black quartz, judge my vow. The five boxing wizards jump quickly. Jackdaws love my big sphinx of quartz.';
    ta.dispatchEvent(new Event('input', {bubbles:true}));
})()""")
print("Typed long text (~300 chars)")

# Capture the overlay WHILE it's still visible
# Strategy: use Page.captureScreenshot immediately on click
# But to make generation slow enough to catch, we could pause the page first.
# Better: race the screenshot with the click.

# Get the audio element ready state to track when generation finishes
mid = send("Page.captureScreenshot", {"format": "png"}, sid)  # pre-click
wait(mid)

# Click generate
ev("document.getElementById('generate-btn').click()")

# Take screenshot fast — overlay should be in DOM
for i in range(5):
    mid = send("Page.captureScreenshot", {"format": "png"}, sid)
    r = wait(mid, 5)
    if r and "result" in r:
        Path(SHOT_DIR / f"overlay-03-generating-{i}.png").write_bytes(base64.b64decode(r["result"]["data"]))
        print(f"  screenshot: overlay-03-generating-{i}.png")
    # Check if overlay is still there
    s = v(ev("""(function(){
        return { hasOverlay: !!document.querySelector('.gen-overlay'),
                 card: document.querySelector('.gen-overlay__card')?.textContent };
    })()"""))
    print(f"  [{i}] overlay={s.get('hasOverlay')}  card={s.get('card')[:60]}")
    if not s.get("hasOverlay") and i > 0:
        break
    time.sleep(0.1)

# Wait for generation to complete
for i in range(60):
    time.sleep(2)
    s = v(ev("""(function(){
        const p = document.getElementById('player');
        const a = document.getElementById('audio-element');
        return { visible: p?.classList.contains('player--visible'), dur: a?.duration, src: !!a?.src, overlay: !!document.querySelector('.gen-overlay') };
    })()"""))
    print(f"  [{i*2:3d}s] player={s.get('visible')} overlay={s.get('overlay')} dur={s.get('dur')}")
    if s.get("visible") and s.get("dur"):
        print(f"  ✓ done after {(i+1)*2}s")
        break

# Final screenshot
time.sleep(0.5)
mid = send("Page.captureScreenshot", {"format": "png"}, sid)
r = wait(mid)
Path(SHOT_DIR / "overlay-04-done.png").write_bytes(base64.b64decode(r["result"]["data"]))
print("  screenshot: overlay-04-done.png")

ws.close()
print("\nDONE")
