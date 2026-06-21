"""
Raw Chrome DevTools Protocol (CDP) capture — drive an already-running real-profile
browser (the osint-browser) directly over its CDP WebSocket.

Why raw CDP instead of Playwright: Playwright's ``connect_over_cdp`` handshake hangs
against very-new Chrome (149) reached through the container's socat CDP relay — the
post-connect target discovery never completes. Raw CDP (Page.navigate /
Page.captureScreenshot / Page.printToPDF / Runtime.evaluate) is protocol-stable and
verified working through the same relay, so this module is the reliable path for
bot-walled / Cloudflare-gated / JS-heavy pages the headless Playwright layer can't get.

Used when ``CDP_ENDPOINT`` is set (web.capture_url delegates here). Records the same
three artifacts as the headless path (screenshot + rendered HTML + print-PDF), each
hashed into the evidence manifest, so a CDP capture carries identical provenance.

Needs only ``websocket-client`` (lightweight) — no Playwright. The browser itself is
the shared osint-browser; this never launches or closes it, only opens/closes a tab.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request

from investigation_graph.capture.manifest import Artifact, EvidenceManifest


class _CDP:
    """Minimal CDP client over the browser-level WebSocket with a message pump.

    Multiplexes command responses and events on one socket; ``send`` blocks for a
    command's matching reply while buffering events (status/redirects) seen meanwhile.
    """

    def __init__(self, endpoint: str, timeout: int = 30):
        import websocket  # lazy: only needed for CDP captures
        ver = json.load(urllib.request.urlopen(f"{endpoint}/json/version", timeout=10))  # noqa: S310
        self.browser_version = ver.get("Browser", "")
        self.ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=timeout, max_size=None)
        self._id = 0
        self.events: list[dict] = []

    def send(self, method: str, params: dict | None = None, session: str | None = None, wait: int = 30) -> dict:
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        deadline = time.time() + wait
        while time.time() < deadline:
            m = json.loads(self.ws.recv())
            if m.get("id") == self._id:
                return m
            self.events.append(m)  # an event (or another session's reply) — buffer it
        raise TimeoutError(f"CDP {method} timed out")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def capture_url_cdp(
    endpoint: str,
    url: str,
    manifest: EvidenceManifest,
    *,
    artifact_id: str,
    out_subdir: str = "web",
    notes: str = "",
    settle_secs: float = 3.0,
    nav_timeout: int = 45,
) -> list[Artifact]:
    """Capture one page via raw CDP through the real-profile browser. Returns the
    recorded artifacts (screenshot + HTML + PDF). Per-file write failures are caught.
    """
    art_dir = manifest.root / "artifacts" / out_subdir
    art_dir.mkdir(parents=True, exist_ok=True)
    c = _CDP(endpoint, timeout=nav_timeout)
    recorded: list[Artifact] = []
    target = None
    try:
        target = c.send("Target.createTarget", {"url": "about:blank"})["result"]["targetId"]
        sess = c.send("Target.attachToTarget", {"targetId": target, "flatten": True})["result"]["sessionId"]
        c.send("Page.enable", session=sess)
        c.send("Network.enable", session=sess)
        c.send("Page.navigate", {"url": url}, session=sess, wait=nav_timeout)
        time.sleep(settle_secs)
        # nudge lazy content, then read final URL
        try:
            c.send("Runtime.evaluate", {"expression":
                   "(async()=>{for(let y=0;y<document.body.scrollHeight;y+=700){scrollTo(0,y);"
                   "await new Promise(r=>setTimeout(r,60));}scrollTo(0,0);})()", "awaitPromise": True},
                   session=sess, wait=15)
        except Exception:
            pass
        final_url = c.send("Runtime.evaluate", {"expression": "location.href", "returnByValue": True},
                           session=sess)["result"]["result"]["value"]
        # best-effort HTTP status + redirect chain from buffered Network events
        status, redirects = None, []
        for e in c.events:
            if e.get("method") == "Network.responseReceived":
                r = e["params"]["response"]
                if e["params"].get("type") == "Document":
                    status = r.get("status")
            if e.get("method") == "Network.requestWillBeSent" and e["params"].get("redirectResponse"):
                redirects.append(e["params"]["redirectResponse"].get("url", ""))

        common = dict(
            capture_group=artifact_id, source_url=url, http_status=status, redirect_chain=redirects,
            tool_version=f"cdp / {c.browser_version}",
            notes=(f"final_url={final_url}; real-profile browser via raw CDP (osint-browser)."
                   + (f" {notes}" if notes else "")),
        )
        # 1) full-page screenshot
        try:
            metrics = c.send("Page.getLayoutMetrics", session=sess)["result"]
            cs = metrics.get("cssContentSize") or metrics.get("contentSize")
            shot = c.send("Page.captureScreenshot", {
                "format": "png", "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": cs["width"], "height": cs["height"], "scale": 1},
            }, session=sess, wait=nav_timeout)["result"]["data"]
            p = art_dir / f"{artifact_id}.png"
            p.write_bytes(base64.b64decode(shot))
            recorded.append(manifest.record_file(p, artifact_id=f"{artifact_id}-screenshot", kind="screenshot",
                            capture_method="cdp-chromium-fullpage", media_type="image/png", **common))
        except Exception as ex:  # pragma: no cover
            print(f"  ! cdp screenshot failed for {url}: {ex}")
        # 2) rendered HTML
        try:
            html = c.send("Runtime.evaluate", {"expression": "document.documentElement.outerHTML",
                          "returnByValue": True}, session=sess)["result"]["result"]["value"]
            p = art_dir / f"{artifact_id}.html"
            p.write_text(html, encoding="utf-8")
            recorded.append(manifest.record_file(p, artifact_id=f"{artifact_id}-html", kind="html",
                            capture_method="cdp-chromium-dom", media_type="text/html", **common))
        except Exception as ex:  # pragma: no cover
            print(f"  ! cdp html failed for {url}: {ex}")
        # 3) print-to-PDF
        try:
            pdf = c.send("Page.printToPDF", {"printBackground": True}, session=sess, wait=nav_timeout)["result"]["data"]
            p = art_dir / f"{artifact_id}.pdf"
            p.write_bytes(base64.b64decode(pdf))
            recorded.append(manifest.record_file(p, artifact_id=f"{artifact_id}-pdf", kind="pdf",
                            capture_method="cdp-chromium-printpdf", media_type="application/pdf", **common))
        except Exception as ex:  # pragma: no cover
            print(f"  ! cdp pdf failed for {url}: {ex}")
    finally:
        if target:
            try:
                c.send("Target.closeTarget", {"targetId": target}, wait=10)
            except Exception:
                pass
        c.close()
    return recorded
