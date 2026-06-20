"""
Web source capture via Playwright (headless Chromium).

For each URL we load the page in a real browser and preserve it three ways, so the
record survives both link-rot and "but the page renders differently" disputes:

  - **screenshot** (full-page PNG) — what a human saw, pixel-for-pixel.
  - **HTML** (rendered DOM) — the post-JavaScript content, machine-readable and
    the thing the extraction pipeline actually ingests.
  - **PDF** (print-to-PDF) — a portable, paginated rendering for the case file.

Each file is hashed and gets its own manifest row; all three share a
``capture_group`` so they reassemble into one "page load" event. We also record
the final URL, the HTTP status, and the redirect chain.

Design choices that matter for evidence:
  - We do **not** spoof or cloak. A standard desktop browser user agent is used so
    the page behaves as it would for an ordinary visitor; the UA and headless mode
    are recorded in ``capture_method``/``notes``. No deception, per the Berkeley
    Protocol's authenticity expectations.
  - Capture is deterministic and committed (this file), so a third party can re-run
    it. The *bytes* won't be identical to ours (sites change), but the *method* is
    auditable and the original capture's hashes are fixed in the manifest.

Playwright is an optional dependency; install with ``pip install -e '.[capture]'``.
"""

from __future__ import annotations

import os
from importlib.metadata import version as _pkg_version

from investigation_graph.capture.manifest import Artifact, EvidenceManifest

# A standard, current desktop Chrome UA. Honest (it *is* a Chromium browser) and
# avoids the bot-flagging that the default headless UA can trigger.
_DESKTOP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _redirect_chain(response) -> list[str]:
    """Reconstruct the URL hops that led to the final response.

    Playwright exposes the previous request via ``request.redirected_from``; we walk
    that backwards and return the chain in the order it was traversed.
    """
    chain: list[str] = []
    try:
        req = response.request
        seen = set()
        while req is not None and req.url not in seen:
            seen.add(req.url)
            chain.append(req.url)
            req = req.redirected_from
    except Exception:
        return []
    chain.reverse()
    return chain


def capture_url(
    url: str,
    manifest: EvidenceManifest,
    *,
    artifact_id: str,
    out_subdir: str = "web",
    notes: str = "",
    timeout_ms: int = 45_000,
    full_page: bool = True,
    save_pdf: bool = True,
) -> list[Artifact]:
    """Capture one web page (screenshot + HTML + optional PDF) with full provenance.

    Returns the list of recorded :class:`Artifact` rows (one per file written).
    Raises on a hard navigation failure; individual file-write failures are caught
    so that, e.g., a PDF-render error never costs us the screenshot we already have.

    ``artifact_id`` is the base id; per-file ids are suffixed (``-screenshot`` etc.)
    and the shared ``capture_group`` equals ``artifact_id``.
    """
    # Lazy import so the package imports without the [capture] extra installed.
    from playwright.sync_api import sync_playwright

    pw_version = _pkg_version("playwright")
    art_dir = manifest.root / "artifacts" / out_subdir
    art_dir.mkdir(parents=True, exist_ok=True)

    recorded: list[Artifact] = []

    # CDP_ENDPOINT (e.g. http://127.0.0.1:9222) routes capture through an already-running
    # real-profile browser (the osint-browser) — needed for bot-walled sites that block
    # headless Playwright. Empty = launch our own throwaway headless chromium.
    cdp = os.environ.get("CDP_ENDPOINT", "")
    with sync_playwright() as p:
        if cdp:
            browser = p.chromium.connect_over_cdp(cdp)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            owns_browser = False  # shared real-profile browser — never close it
        else:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=_DESKTOP_UA, viewport={"width": 1366, "height": 1000})
            owns_browser = True
        page = context.new_page()
        try:
            # networkidle gives JS-heavy pages time to settle; fall back to a plain
            # load if the page never goes idle (some sites poll forever).
            try:
                response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                response = page.goto(url, wait_until="load", timeout=timeout_ms)

            # Scroll to the bottom to trigger lazy-loaded content before the
            # full-page screenshot, then return to top for a natural framing.
            try:
                page.evaluate(
                    "async () => { for (let y=0; y<document.body.scrollHeight; y+=600)"
                    " { window.scrollTo(0,y); await new Promise(r=>setTimeout(r,80)); }"
                    " window.scrollTo(0,0); }"
                )
                page.wait_for_timeout(400)
            except Exception:
                pass

            final_url = page.url
            http_status = response.status if response is not None else None
            redirects = _redirect_chain(response) if response is not None else []
            captured_at = None  # let the manifest stamp a single time per file

            common = dict(
                capture_group=artifact_id,
                source_url=url,
                http_status=http_status,
                redirect_chain=redirects,
                tool_version=f"playwright {pw_version} / chromium" + (" / cdp-osint-browser" if cdp else ""),
                notes=(f"final_url={final_url}; "
                       + ("real-profile browser via CDP." if cdp else f"headless chromium; UA={_DESKTOP_UA}.")
                       + (f" {notes}" if notes else "")),
                captured_at_utc=captured_at,
            )

            # 1) Full-page screenshot (what a human saw).
            shot = art_dir / f"{artifact_id}.png"
            try:
                page.screenshot(path=str(shot), full_page=full_page)
                recorded.append(manifest.record_file(
                    shot, artifact_id=f"{artifact_id}-screenshot", kind="screenshot",
                    capture_method="playwright-chromium-fullpage", media_type="image/png",
                    **common))
            except Exception as e:  # pragma: no cover
                print(f"  ! screenshot failed for {url}: {e}")

            # 2) Rendered HTML (post-JS DOM — the thing we actually ingest).
            html = art_dir / f"{artifact_id}.html"
            try:
                html.write_text(page.content(), encoding="utf-8")
                recorded.append(manifest.record_file(
                    html, artifact_id=f"{artifact_id}-html", kind="html",
                    capture_method="playwright-chromium-dom", media_type="text/html",
                    **common))
            except Exception as e:  # pragma: no cover
                print(f"  ! html capture failed for {url}: {e}")

            # 3) Print-to-PDF (portable paginated rendering for the case file).
            if save_pdf:
                pdf = art_dir / f"{artifact_id}.pdf"
                try:
                    page.pdf(path=str(pdf), print_background=True)
                    recorded.append(manifest.record_file(
                        pdf, artifact_id=f"{artifact_id}-pdf", kind="pdf",
                        capture_method="playwright-chromium-printpdf", media_type="application/pdf",
                        **common))
                except Exception as e:  # pragma: no cover
                    print(f"  ! pdf capture failed for {url}: {e}")
        finally:
            page.close()
            # In CDP mode the browser/context are shared (the osint-browser) — leave them
            # running; only tear down a browser we launched ourselves.
            if owns_browser:
                context.close()
                browser.close()

    return recorded
