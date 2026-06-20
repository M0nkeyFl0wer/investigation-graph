#!/usr/bin/env python3
"""
capture_domain.py — passive domain-infrastructure workup with provenance.

Collects the domain-investigation fields a proper OSINT domain worksheet expects
(registration, DNS, TLS/subdomains, capture history) for one or more domains, and
records each lookup as a hashed artifact in the evidence manifest. All sources are
PASSIVE (no contact with the target's own server beyond public-resolver/registry
queries) and keyless:

  - RDAP        registrar, registration/expiry events, name servers, registrant org
                (modern structured WHOIS) — https://rdap.org/domain/<d>
  - DNS (dig)   A / AAAA / MX / NS / TXT
  - crt.sh      TLS certificate transparency → issued certs + subdomains
  - archive.org CDX capture history (first/last seen)

Each saved response → a manifest row (sha256 + source + UTC time + method), so a
domain finding (e.g. "fedfiling.com and federalfiling.com share a name server")
carries the same chain of custody as a captured web page. A source that fails is
logged as a documented gap, not silently dropped.

Usage:
  python scripts/capture_domain.py --evidence examples/fedfiling-case/evidence \
      fedfiling.com federalfiling.com
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from investigation_graph.capture import EvidenceManifest

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _http_get(url: str, accept: str = "", timeout: int = 20, retries: int = 2) -> tuple[int, bytes]:
    """GET with redirect-following + small retry. Returns (status, body)."""
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    last = (0, b"")
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (trusted public endpoints)
                return r.status, r.read()
        except urllib.error.HTTPError as e:  # noqa: PERF203
            return e.code, e.read() if hasattr(e, "read") else b""
        except Exception as e:  # network hiccup → retry
            last = (0, str(e).encode())
    return last


def _save(manifest: EvidenceManifest, domain: str, source: str, ext: str, data: bytes,
          *, kind: str, method: str, tool_version: str, source_url: str = "",
          status=None, notes: str = "") -> None:
    art_dir = manifest.root / "artifacts" / "domain"
    art_dir.mkdir(parents=True, exist_ok=True)
    dest = art_dir / f"{domain}-{source}.{ext}"
    dest.write_bytes(data)
    manifest.record_file(dest, artifact_id=f"domain-{domain}-{source}", kind=kind,
                         capture_method=method, tool_version=tool_version,
                         source_url=source_url, http_status=status, notes=notes)


def workup(domain: str, manifest: EvidenceManifest) -> dict:
    """Run all passive lookups for one domain, record artifacts, return a summary dict."""
    summary: dict = {"domain": domain}

    # --- RDAP (registration) ------------------------------------------------
    url = f"https://rdap.org/domain/{domain}"
    status, body = _http_get(url, accept="application/rdap+json")
    if status == 200 and body:
        _save(manifest, domain, "rdap", "json", body, kind="osint_rdap",
              method="rdap.org", tool_version="rdap", source_url=url, status=status,
              notes="Registration data (RDAP).")
        try:
            d = json.loads(body)
            ev = {e.get("eventAction"): e.get("eventDate") for e in d.get("events", [])}
            registrar = next((e.get("vcardArray", [None, []])[1]
                              for e in d.get("entities", []) if "registrar" in (e.get("roles") or [])), None)
            reg_name = None
            if registrar:
                for f in registrar:
                    if f and f[0] == "fn":
                        reg_name = f[3]
            summary["rdap"] = {
                "registered": ev.get("registration"),
                "expires": ev.get("expiration"),
                "last_changed": ev.get("last changed"),
                "registrar": reg_name,
                "nameservers": [n.get("ldhName") for n in d.get("nameservers", [])],
                "status": d.get("status"),
            }
        except Exception as e:
            summary["rdap"] = {"parse_error": str(e)}
    else:
        summary["rdap"] = {"GAP": f"http={status}"}

    # --- DNS (dig) ----------------------------------------------------------
    dns_out = []
    for rr in ("A", "AAAA", "MX", "NS", "TXT"):
        try:
            out = subprocess.run(["dig", "+short", domain, rr], capture_output=True,
                                 text=True, timeout=15).stdout.strip()
        except Exception as e:
            out = f"(dig {rr} failed: {e})"
        dns_out.append(f"=== {rr} ===\n{out}")
    dns_text = "\n".join(dns_out)
    _save(manifest, domain, "dns", "txt", dns_text.encode(), kind="osint_dns",
          method="dig", tool_version="dig", source_url="", status=None,
          notes=f"DNS A/AAAA/MX/NS/TXT for {domain}.")
    summary["dns"] = {
        "A": [ln for ln in dns_out[0].splitlines()[1:] if ln],
        "MX": [ln for ln in dns_out[2].splitlines()[1:] if ln],
        "NS": [ln for ln in dns_out[3].splitlines()[1:] if ln],
    }

    # --- crt.sh (TLS certs + subdomains) ------------------------------------
    url = f"https://crt.sh/?q=%25.{domain}&output=json"
    status, body = _http_get(url, timeout=30, retries=3)
    if status == 200 and body:
        _save(manifest, domain, "crtsh", "json", body, kind="osint_cert",
              method="crt.sh-json", tool_version="crt.sh", source_url=url, status=status,
              notes="Certificate transparency (crt.sh).")
        try:
            rows = json.loads(body)
            names = sorted({n.strip().lower() for r in rows
                            for n in r.get("name_value", "").splitlines() if "*" not in n})
            issuers = sorted({r.get("issuer_name", "") for r in rows})
            summary["crtsh"] = {"cert_rows": len(rows), "subdomains": names[:30],
                                "n_subdomains": len(names), "issuers": issuers[:5]}
        except Exception as e:
            summary["crtsh"] = {"parse_error": str(e)}
    else:
        summary["crtsh"] = {"GAP": f"http={status}"}

    # --- archive.org CDX (capture history) ----------------------------------
    url = (f"http://web.archive.org/cdx/search/cdx?url={domain}"
           "&output=json&collapse=timestamp:6&limit=200")
    status, body = _http_get(url, timeout=25)
    if status == 200 and body:
        _save(manifest, domain, "archive-cdx", "json", body, kind="osint_archive",
              method="archive-cdx", tool_version="wayback-cdx", source_url=url, status=status,
              notes="Wayback Machine capture history (CDX).")
        try:
            rows = json.loads(body)
            stamps = [r[1] for r in rows[1:]] if len(rows) > 1 else []
            summary["archive"] = {"snapshots": len(stamps),
                                  "first": stamps[0] if stamps else None,
                                  "last": stamps[-1] if stamps else None}
        except Exception as e:
            summary["archive"] = {"parse_error": str(e)}
    else:
        summary["archive"] = {"GAP": f"http={status}"}

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Passive domain workup with provenance.")
    ap.add_argument("--evidence", required=True, type=Path)
    ap.add_argument("domains", nargs="+")
    args = ap.parse_args()

    manifest = EvidenceManifest(args.evidence)
    summaries = []
    for dom in args.domains:
        print(f"\n>>> {dom}")
        s = workup(dom, manifest)
        summaries.append(s)
        r = s.get("rdap", {})
        print(f"  registrar={r.get('registrar')}  registered={r.get('registered')}  expires={r.get('expires')}")
        print(f"  NS={s.get('dns',{}).get('NS')}")
        print(f"  A={s.get('dns',{}).get('A')}")
        print(f"  crt.sh: {s.get('crtsh',{}).get('n_subdomains')} subdomains; rows={s.get('crtsh',{}).get('cert_rows')}")
        print(f"  archive: {s.get('archive',{}).get('snapshots')} snapshots, first={s.get('archive',{}).get('first')}")

    # --- sibling comparison (shared infra = sibling signal) ------------------
    if len(summaries) > 1:
        print("\n=== SIBLING COMPARISON (shared infrastructure) ===")
        def ns(s): return set((s.get("dns") or {}).get("NS") or [])
        def a(s): return set((s.get("dns") or {}).get("A") or [])
        def reg(s): return (s.get("rdap") or {}).get("registrar")
        for i in range(len(summaries)):
            for j in range(i + 1, len(summaries)):
                a1, a2 = summaries[i], summaries[j]
                print(f"  {a1['domain']} vs {a2['domain']}:")
                print(f"    shared NS: {ns(a1) & ns(a2) or 'none'}")
                print(f"    shared A:  {a(a1) & a(a2) or 'none'}")
                print(f"    same registrar: {reg(a1)==reg(a2)} ({reg(a1)} / {reg(a2)})")

    print(f"\nmanifest: {manifest.path} ({len(manifest.load())} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
