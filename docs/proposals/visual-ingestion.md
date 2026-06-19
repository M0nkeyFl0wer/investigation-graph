# Proposal — visual artifact ingestion (OSINT is visual)

**Status:** design / not yet built. Scoped from the 2026-06-19 critique + research.
**Problem:** today the tool reads digital text only (`pdftotext`). Scanned
filings, photographed documents, screenshots, charts, maps, and photos — *most of
a real OSINT corpus* — can't enter the graph. OCR alone isn't enough: a lot of
the signal is layout, geometry, and pixels (a redaction box, a stamp, a
handwritten margin note, who's standing next to whom, where on a map).

This proposes a **tiered, privacy-respecting visual pipeline** behind one
processor interface, with heavy models running on **controlled compute you own**,
not a third-party SaaS.

---

## What the research says (2026)

OCR-first RAG corrupts on exactly the documents investigators care about: dense
multi-column layouts, tables, forms, scans. The current best practice for
visually-rich/scanned material is **visual late-interaction retrieval** —
**ColQwen2.5 / ColPali**: encode each *page image* into a grid of patch
embeddings, score a query against every patch (MaxSim), skip OCR entirely.
Financial-PDF recall jumps ~62% (text-only) → ~84% (visual). The patch grid also
gives **region grounding** — you can point at *where on the page* a match is
(patch-to-region propagation), which is the "geometry/pixel-level" piece.

Sources:
- [ColPali / ColQwen visual document retrieval (Mixpeek)](https://mixpeek.com/visual-document-retrieval)
- [ColPali on GPU cloud — visual PDF retrieval without OCR (Spheron, 2026)](https://www.spheron.network/blog/colpali-multimodal-document-rag-gpu-cloud/)
- [Beyond OCR: why ColPali changes document RAG (Medium, 2026)](https://medium.com/@mudassar.hakim/beyond-ocr-why-colpali-is-changing-how-we-build-rag-for-documents-2ebeb853e400)
- [Spatially-grounded retrieval via patch-to-region propagation (arXiv 2512.02660)](https://arxiv.org/pdf/2512.02660)
- [Visual RAG Toolkit — multi-vector pooling at scale (arXiv 2602.12510)](https://arxiv.org/pdf/2602.12510)
- [microsoft/multi-modal-rag-with-colpali (reference impl)](https://github.com/microsoft/multi-modal-rag-with-colpali)

---

## The tiered pipeline (route by document type, not one hammer)

```
artifact
   │
   ├─ digital PDF / office doc ─────► Docling  → text + layout + tables      [CPU, local]
   ├─ scanned PDF (no text layer) ──► OCR (ocrmypdf / Surya)  → text+boxes   [CPU, local]
   ├─ visually-rich / forms / charts► ColQwen2.5 page-embeddings (skip OCR)  [GPU, controlled]
   │                                   → patch grid + region grounding
   └─ photo / screenshot / map ─────► VLM caption (Qwen2-VL/MiniCPM-V) +     [GPU, controlled]
                                       OCR-in-image + optional object/face
                                       detection → text + boxes
        │
        ▼
   ProcessorResult{ text, structured, metadata, page_images?, regions? }
        │
        ▼
   existing pipeline: chunk → embed → DuckDB ; extract → ground → LadybugDB
   + a visual store: page-image patch embeddings + region index (DuckDB multi-vector)
   + provenance edges: entity MENTIONED_IN document  ·  region → page → document
```

- **Docling first** for anything with a real text layer (it's already the stack's
  parser; layout-aware, gets tables right). Cheap, local, no GPU.
- **OCR fallback** when there's no text layer — gets scanned text into the
  existing text pipeline immediately (this is the P0.3 quick win).
- **Visual retrieval (ColQwen)** for documents where layout/figures carry the
  meaning and OCR would mangle them. Stores page-image multi-vectors so a query
  retrieves the *page region*, not just text. Needs a GPU.
- **VLM captioning + detection** for true images (photos, screenshots, maps):
  produce a textual description + extracted text + object/face boxes → flows into
  the same graph as evidence-bearing nodes. Geometry = bounding boxes.

Everything converges on the same `ProcessorResult` contract so the rest of the
pipeline (grounding, ER, graph build) is unchanged.

---

## Compute placement — controlled, not SaaS (preserves the privacy model)

A typical laptop GPU is too small for ColQwen2 (2B+) or a VLM, so heavy visual
models run on **compute the operator controls**. The backend is **pluggable and
off by default**, mirroring `PRIVACY_MODE`, via a `VISUAL_BACKEND` knob and a
configurable endpoint — so *which* machine does the work is the operator's
deployment choice, never hardcoded in the repo:

| Tier | Backend | Use for | Notes |
|------|---------|---------|-------|
| **local** | this machine (CPU; small GPU) | Docling, OCR, small jobs | default; nothing leaves the machine |
| **self-hosted remote** ⭐ | an **operator-owned server/GPU box** (configured endpoint) | ColQwen / VLM at scale | your hardware, encrypted transit (SSH/VPN), ephemeral job dirs wiped after — *not* a third party. The right home for sensitive material that needs a GPU. |
| **external inference API** | a configured API endpoint | burst capacity | an external service — **non-sensitive material only**, exactly like the existing `remote` text tier. Credentials via the OS secret store / env, never committed. |
| **rented GPU (fallback)** | a privacy-respecting GPU VPS | operators without their own server | BYO-GPU option; encrypted disk, ephemeral, torn down per job. |

Design rule: `VISUAL_BACKEND = local | remote | api | none`, plus an endpoint URL
and a secret read from the environment / OS keyring. Sensitive corpora stay on
`local`/`remote` (operator-controlled); `api` is gated to non-sensitive material
with the same warning as remote text extraction. Heavy models never see data the
operator hasn't cleared for that tier.

> Operator-specific backends (which server, which API, which VPS provider) are
> **local deployment config**, kept out of this public repo — e.g. in an
> untracked `.env`/keyring, not committed. The repo ships only the generic
> pluggable interface and documented examples.

> Reality check before building: confirm the chosen remote actually has a usable
> GPU. A CPU-only server still hosts Docling/OCR/VLM-CPU at scale; ColQwen-quality
> visual retrieval needs a real GPU (bigger local card, self-hosted GPU box, or a
> rented GPU VPS).

---

## Storage, geometry, and scale

- **Page images + patch embeddings** in DuckDB (the columnar base already holds
  vectors). ColQwen multi-vectors are large — use **training-free pooling** +
  quantization (Visual RAG Toolkit) to keep per-page footprint sane at corpus
  scale; a two-stage search (pooled coarse → full MaxSim rerank on top-k).
- **Region index:** store patch→bbox so a hit resolves to `(document, page,
  x,y,w,h)`. That's the "reference at scale" answer — every visual finding points
  back to a pixel region of a source page, the visual analogue of edge evidence.
- **Graph linkage:** a retrieved region/figure becomes a provenance anchor; an
  entity extracted from a caption/OCR span gets `MENTIONED_IN` the document with
  the region in `properties`. Keeps the audit trail intact for visual evidence.

---

## Where it lives — kg-common (shared), not just here

Per `BOUNDARY.md`, this is shared substrate: build a **`kg_common/media`**
processor subsystem (`BaseProcessor` → `ProcessorResult`; Docling / OCR / ColQwen
/ VLM processors) so every consumer benefits (the seabrick handoff already
sketched this interface). investigation-graph consumes it. New deps
(`docling`, `ocrmypdf`, `colpali-engine`, VLM client) are **optional extras** so
the dependency-light core stays light, and pass the public-export sanitizer gate.

---

## Phasing

1. **P0.3 quick win:** OCR fallback in `read_document` (ocrmypdf/Surya) — scanned
   text into the existing pipeline now. Local, no GPU.
2. **Media interface:** `kg_common/media` `BaseProcessor`/`ProcessorResult` +
   `DocumentProcessor` (Docling). Route ingest through it.
3. **Visual retrieval:** ColQwen page-embeddings + DuckDB multi-vector store +
   region index; `VISUAL_BACKEND` knob; self-hosted remote backend.
4. **Images:** VLM captioning + OCR-in-image + optional detection for photos/
   screenshots/maps; external inference API as optional backup (non-sensitive).
5. **UI/refs:** surface region-grounded hits (page + bbox) in search output.
