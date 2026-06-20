#!/usr/bin/env python3
"""
capture_sunbiz.py — provenance capture of Florida Sunbiz corporate records.

Sunbiz blocks bare downloads (urllib gets 403), but a real browser session works.
This drives Playwright through the public search UI and records each step as a hashed
artifact in the evidence manifest, so the authoritative corporate record (entity
detail, filing PDFs, officer/registered-agent results) carries full chain of custody.

Captures, for an entity-name search:
  1. the search results page,
  2. the matched entity's detail page,
  3. the entity's filing-document PDFs (fetched WITH the browser session),
and optionally, for each officer/registered-agent name:
  4. the officer search results page.

Selectors verified live 2026-06-20 (#SearchTerm; results link to SearchResultDetail;
detail pages link filing PDFs via GetDocument).

Usage:
  python scripts/capture_sunbiz.py --evidence examples/fedfiling-case/evidence \
      --prefix sunbiz --term "Fed Filing" --entity "FED FILING, LLC" \
      --officer "Hernandez Humberto" --officer "Gobea Adrian" --officer "Foit Dana"
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path

from investigation_graph.capture import EvidenceManifest

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BASE = "https://search.sunbiz.org"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def capture_current_page(page, manifest, artifact_id, *, source_url, http_status,
                         notes, pw_version, out_subdir="sunbiz"):
    """Save screenshot + rendered HTML + print-PDF of the currently-loaded page."""
    art_dir = manifest.root / "artifacts" / out_subdir
    art_dir.mkdir(parents=True, exist_ok=True)
    common = dict(capture_group=artifact_id, source_url=source_url,
                  http_status=http_status,
                  tool_version=f"playwright {pw_version} / chromium",
                  notes=f"final_url={page.url}; headless chromium. {notes}".strip())
    # full-page screenshot
    shot = art_dir / f"{artifact_id}.png"
    page.screenshot(path=str(shot), full_page=True)
    manifest.record_file(shot, artifact_id=f"{artifact_id}-screenshot", kind="screenshot",
                         capture_method="playwright-chromium-fullpage",
                         media_type="image/png", **common)
    # rendered HTML
    html = art_dir / f"{artifact_id}.html"
    html.write_text(page.content(), encoding="utf-8")
    manifest.record_file(html, artifact_id=f"{artifact_id}-html", kind="html",
                         capture_method="playwright-chromium-dom",
                         media_type="text/html", **common)
    # print-to-PDF
    pdf = art_dir / f"{artifact_id}.pdf"
    page.pdf(path=str(pdf), print_background=True)
    manifest.record_file(pdf, artifact_id=f"{artifact_id}-pdf", kind="pdf",
                         capture_method="playwright-chromium-printpdf",
                         media_type="application/pdf", **common)


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture FL Sunbiz records with provenance.")
    ap.add_argument("--evidence", required=True, type=Path)
    ap.add_argument("--prefix", default="sunbiz")
    ap.add_argument("--term", required=True, help="entity name to search")
    ap.add_argument("--entity", default="", help="exact result name to open (else first result)")
    ap.add_argument("--officer", action="append", default=[], help="officer/RA name 'Last First' (repeatable)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    pw_version = _pkg_version("playwright")
    manifest = EvidenceManifest(args.evidence)
    failed = 0

    with sync_playwright() as p:
        ctx = p.chromium.launch(headless=True).new_context(user_agent=UA,
                                                           viewport={"width": 1366, "height": 1000})
        page = ctx.new_page()

        # --- 1) entity-name search + results ---------------------------------
        try:
            page.goto(f"{BASE}/Inquiry/CorporationSearch/ByName",
                      wait_until="domcontentloaded", timeout=40000)
            page.fill("#SearchTerm", args.term)
            page.press("#SearchTerm", "Enter")
            page.wait_for_load_state("domcontentloaded", timeout=40000)
            page.wait_for_timeout(600)
            rid = f"{args.prefix}-{_slug(args.term)}-results"
            capture_current_page(page, manifest, rid, source_url=page.url,
                                 http_status=200,
                                 notes=f"Entity-name search for '{args.term}'.",
                                 pw_version=pw_version)
            print(f"  ok: {rid}")
        except Exception as e:
            print(f"  ! results capture failed: {e}")
            failed += 1

        # --- 2) open the matched entity detail -------------------------------
        try:
            target = args.entity.strip().upper()
            link = None
            for a in page.query_selector_all("a[href*='SearchResultDetail']"):
                txt = (a.inner_text() or "").strip().upper()
                if not target or txt == target:
                    link = a
                    break
            if link is None:  # fall back to first detail link
                link = page.query_selector("a[href*='SearchResultDetail']")
            if link is None:
                raise RuntimeError("no SearchResultDetail link on results page")
            name = (link.inner_text() or args.term).strip()
            link.click()
            page.wait_for_load_state("domcontentloaded", timeout=40000)
            page.wait_for_timeout(600)
            did = f"{args.prefix}-{_slug(name)}-detail"
            capture_current_page(page, manifest, did, source_url=page.url,
                                 http_status=200,
                                 notes=f"Entity detail for '{name}'.",
                                 pw_version=pw_version)
            print(f"  ok: {did}  ({page.url})")

            # --- 3) filing-document PDFs (fetched WITH the session) ----------
            doc_links = []
            for a in page.query_selector_all("a[href*='GetDocument']"):
                href = a.get_attribute("href") or ""
                if href:
                    doc_links.append(href if href.startswith("http") else BASE + href)
            doc_links = list(dict.fromkeys(doc_links))  # dedupe, keep order
            art_dir = manifest.root / "artifacts" / "sunbiz"
            for i, url in enumerate(doc_links[:3]):  # most-recent filings first
                try:
                    resp = page.context.request.get(url, timeout=40000)
                    body = resp.body()
                    dest = art_dir / f"{args.prefix}-{_slug(name)}-doc{i}.pdf"
                    dest.write_bytes(body)
                    manifest.record_file(
                        dest, artifact_id=f"{args.prefix}-{_slug(name)}-doc{i}",
                        kind="registry_pdf",
                        capture_method="playwright-session-request",
                        tool_version=f"playwright {pw_version}",
                        media_type=resp.headers.get("content-type", "application/pdf"),
                        source_url=url, http_status=resp.status,
                        notes=f"Sunbiz filing PDF #{i} for '{name}' (browser session).")
                    print(f"    ok doc{i}: http={resp.status} {len(body)}B")
                except Exception as e:
                    print(f"    ! doc{i} failed: {e}")
                    failed += 1
        except Exception as e:
            print(f"  ! detail/docs capture failed: {e}")
            failed += 1

        # --- 4) officer / registered-agent searches --------------------------
        for officer in args.officer:
            try:
                page.goto(f"{BASE}/Inquiry/CorporationSearch/ByOfficerRegisteredAgentName",
                          wait_until="domcontentloaded", timeout=40000)
                page.fill("#SearchTerm", officer)
                page.press("#SearchTerm", "Enter")
                page.wait_for_load_state("domcontentloaded", timeout=40000)
                page.wait_for_timeout(600)
                oid = f"{args.prefix}-officer-{_slug(officer)}"
                capture_current_page(page, manifest, oid, source_url=page.url,
                                     http_status=200,
                                     notes=f"Officer/registered-agent search for '{officer}'.",
                                     pw_version=pw_version)
                print(f"  ok: {oid}")
            except Exception as e:
                print(f"  ! officer '{officer}' failed: {e}")
                failed += 1

        ctx.close()

    print(f"\nmanifest: {manifest.path} ({len(manifest.load())} rows); failures={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
