"""
Splink MULTI-FIELD structured-dedup tier (P2.4 / PUB.5 — the `[er-multifield]` extra).

WHY this exists, separate from the name-only `splink_tier.py`
-------------------------------------------------------------
The name-only resolver (and the deterministic normalized-name tier) is correct for
the single-field tabular path, but it fails a registry feed in BOTH directions:

  * UNDER-MERGE: cross-source SPELLING variants of one company ("J.P. Morgan" /
    "JP Morgan" / "JPMorgan Chase") have DIFFERENT normalized names, so no name
    rule merges them — even though they carry the SAME registration id + address
    and are obviously the same legal entity.
  * OVER-MERGE (the libel direction): two genuinely DIFFERENT companies that happen
    to share a name ("Acme Holdings" in Delaware vs in London) have the SAME
    normalized name, so a name rule WRONGLY fuses them — even though their reg_id
    and jurisdiction differ. Fusing two distinct real entities is the libel failure.

THE CATEGORY CHANGE — deterministic auto-merge, ambiguity → human review
------------------------------------------------------------------------
Two prior builds adjudicated this with string-similarity THRESHOLDS (difflib ratios,
a 0.85 "contradiction veto"). A verifier broke both with libel-grade over-merges:
no single threshold can simultaneously avoid over-merge (fusing distinct entities =
libel) and over-split (breaking a real entity). The threshold IS the leak.

So this build removes fuzzy ratios from the merge decision ENTIRELY. The decision is
a small deterministic table with exactly three outcomes; anything ambiguous routes to
HUMAN REVIEW rather than being auto-decided:

  DECISION TABLE (per candidate pair, same entity_type)
  ─────────────────────────────────────────────────────────────────────────────────
  | reg_id (normalized)        | address (normalized)      | name (normalized) | -> |
  |----------------------------|---------------------------|-------------------|----|
  | present & EQUAL            | EXACTLY equal             | (any)             | MERGE
  | present & EQUAL            | differ / missing / either | (any)             | REVIEW
  |                            | side blank                |                   |
  | NO reg_id (both)           | EXACTLY equal             | EXACTLY equal     | MERGE
  | anything else (incl. reg_id present & DIFFERENT, or no reg_id with name OR
  |   address not exactly equal)                                               | APART
  ─────────────────────────────────────────────────────────────────────────────────

  * MERGE  = union the pair (deterministic, conclusive identity agreement).
  * REVIEW = do NOT union (the two records stay SEPARATE entities, satisfying the
    libel floor) but the pair is recorded in the review feed with a reason, so a
    human adjudicates the data-error-vs-two-companies question. This is NOT a
    threshold call — it is exactly the judgment a human must make.
  * APART  = not even a candidate; the records never pair.

  reg_id equality is conclusive ONLY when a second identity-bearing field (address)
  also EXACTLY agrees. A bare shared reg_id is treated as a strong-but-unconfirmed
  signal → review, never an auto-merge, because a shared reg_id string can be a
  data-entry error or a coincidental collision across feeds (e.g. "Galaxy Mining
  Corp" and "Tulip Bakery Ltd" both stamped US-4242). A human, not a ratio, decides.

reg_id NORMALIZATION rejects meaningless tokens
-----------------------------------------------
A reg_id is only a merge key when it is MEANINGFUL. `_norm_reg_id` strips ALL unicode
whitespace — including the zero-width space U+200B and the non-breaking space U+00A0,
which an ASCII-only `.strip()` / `<> ''` guard leaves intact — and then REJECTS any
value that is empty or punctuation-only (e.g. "---"). A rejected reg_id becomes
"no reg_id" (None), so a zero-width-space sentinel or a "---" sentinel can NEVER act
as a merge key and never mass-fuse a reg_id-less feed. This closes the blank-sentinel
over-merge a verifier found.

THE RECALL TRADE (now IMPLEMENTED via deterministic address canonicalization)
-----------------------------------------------------------------------------
The address comparison remains EXACT-normalized (no fuzzy ratio anywhere), but the
normalization is now stronger: `_norm_address` deterministically canonicalizes common
US street-address abbreviations (ave->avenue, st->street, n->north, ste->suite, ...)
BEFORE the exact-equality test. So a real single entity whose two records spell the
address only by an accepted abbreviation ("270 Park Ave" vs "270 Park Avenue") now
canonicalizes to the SAME string and AUTO-MERGES — the recall this section used to
trade away is recovered, with NO similarity score: it is pure token substitution
followed by the same exact-equality test (see `_norm_address`).

The boundary still routes to REVIEW (the safe under-merge, preferred over a libel
over-merge): anything that is NOT a known abbreviation-only variant. A genuinely
different address ("270 Park Ave" vs "5th Avenue"), a misspelling ("Avenue" vs
"Avanue"), a transposed street number ("270" vs "207"), or the "#5" vs "Suite 5"
unit-marker ambiguity all leave the canonicalized strings DIFFERENT, so the pair
stays in REVIEW for a human. The decision table is unchanged; only the address
spelling fed into it is canonicalized. This explicitly does NOT reintroduce a fuzzy
ratio into the merge decision.

WHY Splink, and HOW it is configured given the tiny-fixture estimation problem
-------------------------------------------------------------------------------
Splink (UK MoJ, MIT) is a Fellegi-Sunter linker that runs natively on the DuckDB
substrate this project already uses. Its FULL F-S machinery (estimate u by random
sampling, m by EM) is DEGENERATE on a tiny fixture: with only a handful of records
and no large pool of true non-matches to learn from, the EM pass cannot estimate
calibrated weights. We therefore use Splink's **deterministic linking** path
(`Linker.inference.deterministic_link`), which needs NO parameter estimation: it
emits a candidate pair for every record pair satisfying a blocking rule. The blocking
rule here proposes only the MERGE-or-REVIEW candidates (same meaningful reg_id, OR no
reg_id + same name+address); the deterministic decision table above then adjudicates
each candidate into MERGE / REVIEW / APART. The same `deterministic_link` surface
scales: on a real corpus the rule is Splink's high-precision blocking layer, and a
deployment with enough records can layer trained probabilistic comparisons on top by
switching `deterministic_link()` to `predict()` — the cluster-map contract this
module returns does not change.
"""
from __future__ import annotations

import logging
import unicodedata

# Splink is chatty; keep its INFO noise out of our logs.
for _n in ("splink", "py4j"):
    logging.getLogger(_n).setLevel(logging.WARNING)

# Fields, beyond name/entity_type, that carry legal IDENTITY for an organization.
# A record "has multi-field props" (and so is eligible for this tier) iff at least
# one of these is present and non-empty (after unicode normalization).
MULTIFIELD_KEYS = ("reg_id", "address", "jurisdiction")


def has_multifield_props(record: dict) -> bool:
    """True iff the record carries at least one identity-bearing field this tier
    can weigh (reg_id / address / jurisdiction). Name-only records return False, so
    they never enter this tier and keep the unaffected name-only resolution path.

    Eligibility uses the SAME unicode-aware emptiness test as the rest of this module
    (`_strip_unicode`), so a record whose only "signal" is a zero-width-space reg_id
    is correctly treated as having NO multi-field signal there — though it may still
    qualify via a real address/jurisdiction."""
    return any(_strip_unicode(record.get(k, "")) for k in MULTIFIELD_KEYS)


def _strip_unicode(v) -> str:
    """Strip ALL unicode whitespace from a value and return the remainder.

    This is stricter than str.strip(), which only removes a fixed ASCII/unicode set
    and notably leaves the ZERO-WIDTH SPACE (U+200B) and other format characters
    intact. We remove every character whose unicode category is a separator (Z*) OR a
    format control (Cf, which covers U+200B / U+200C / U+FEFF), so a reg_id consisting
    only of zero-width spaces collapses to "". The result is NOT lowercased here —
    callers that need case-folding use `_norm`."""
    return "".join(
        ch for ch in str(v or "")
        if not (unicodedata.category(ch).startswith("Z")
                or unicodedata.category(ch) == "Cf")
    ).strip()


def _norm(v) -> str:
    """Lowercase + whitespace-collapse a field value for robust EXACT equality, so
    "US" == "us " and "270 Park Avenue,  New York" == "270 park avenue, new york".
    Empty / missing fields normalize to "" (which the decision table treats as
    "no signal"). No fuzzy comparison is ever applied to this value — equality is
    the only test."""
    return " ".join(_strip_unicode(v).lower().split())


# ── Deterministic US street-address canonicalization (the recovered RECALL TRADE) ──
# Maps the common abbreviation forms of address TOKENS to a single canonical spelling
# so that two records whose addresses differ ONLY by an accepted abbreviation
# ("270 Park Ave" vs "270 Park Avenue") normalize to the SAME string and therefore
# pass the module's EXISTING exact-equality test. NO fuzzy ratio is involved: each
# entry is an exact token-for-token substitution, applied after lower-casing and
# trailing-punctuation stripping. Both the abbreviated and the already-expanded form
# map to the canonical word, so the relation is idempotent and direction-free.
_ADDRESS_TOKEN_CANON = {
    # Street-type suffixes -> full canonical word. We expand BOTH the abbreviation and
    # the full word to the same key so "ave", "ave.", and "avenue" all canonicalize to
    # "avenue". (The full word maps to itself, harmlessly, for documentation clarity.)
    "ave": "avenue", "av": "avenue", "avenue": "avenue",
    "st": "street", "street": "street",
    "rd": "road", "road": "road",
    "blvd": "boulevard", "boulevard": "boulevard",
    "dr": "drive", "drive": "drive",
    "ln": "lane", "lane": "lane",
    "ct": "court", "court": "court",
    "pl": "place", "place": "place",
    "sq": "square", "square": "square",
    "ter": "terrace", "terr": "terrace", "terrace": "terrace",
    "pkwy": "parkway", "pkway": "parkway", "parkway": "parkway",
    "hwy": "highway", "highway": "highway",
    "cir": "circle", "circle": "circle",
    "pt": "point", "point": "point",
    "plz": "plaza", "plaza": "plaza",
    "expy": "expressway", "expressway": "expressway",
    # Directionals -> full word (covers prefix "N Park" and suffix "Park Ave NW").
    "n": "north", "north": "north",
    "s": "south", "south": "south",
    "e": "east", "east": "east",
    "w": "west", "west": "west",
    "ne": "northeast", "northeast": "northeast",
    "nw": "northwest", "northwest": "northwest",
    "se": "southeast", "southeast": "southeast",
    "sw": "southwest", "southwest": "southwest",
    # Unit / secondary-address markers -> full word.
    "ste": "suite", "suite": "suite",
    "apt": "apartment", "apartment": "apartment",
    "fl": "floor", "floor": "floor",
    "rm": "room", "room": "room",
    "bldg": "building", "building": "building",
    "dept": "department", "department": "department",
    "unit": "unit",
}


def _norm_address(v) -> str:
    """Canonicalize a US street address for robust EXACT equality — deterministic
    token substitution, NOT fuzzy matching.

    This recovers the recall the module header's "THE RECALL TRADE" section described:
    a single real entity whose two records spell the address only by an accepted
    abbreviation ("270 Park Ave" vs "270 Park Avenue") used to normalize to DIFFERENT
    strings and route to REVIEW. After this canonicalization they normalize to the SAME
    string ("270 park avenue ...") and so pass the EXISTING exact-equality test in
    `_decide` / the blocking SQL — auto-merging without any similarity score.

    HOW (and why it is canonicalization, not a ratio):
      1. Lower-case the value and split on whitespace into tokens. (We split FIRST,
         before any unicode-whitespace stripping, because `_strip_unicode` removes ALL
         separators incl. ordinary spaces — running it first would glue every word
         together. Per-token we then `_strip_unicode` to drop any interior zero-width /
         format characters, matching the rest of the module's unicode-aware emptiness.)
      2. Each token has trailing punctuation stripped (so "ave." == "ave" and
         "blvd," == "blvd") and a leading "#" stripped, while INTERIOR characters and
         digits are left intact (so "270", "5th", "270-272" are untouched).
      3. If the cleaned token is an exact key in the ASCII canonicalization dictionary
         `_ADDRESS_TOKEN_CANON`, it is REPLACED by its single canonical full word;
         otherwise it is kept verbatim. This is a pure lookup — there is no edit
         distance, no similarity threshold, no partial match. A token either IS a known
         abbreviation (and is rewritten) or it is not (and is left alone). Two addresses
         merge only if, after this exact rewrite, they are CHARACTER-FOR-CHARACTER equal.
      4. Re-join the canonical tokens with single spaces.

    WHAT IT COVERS (the deterministic dictionary, see `_ADDRESS_TOKEN_CANON`):
      * street-type suffixes (ave/st/rd/blvd/dr/ln/ct/pl/sq/ter/pkwy/hwy/cir/pt/plz/expy
        and their full words) -> the full canonical word;
      * directionals (n/s/e/w/ne/nw/se/sw and full words) -> the full word;
      * unit markers (ste/apt/fl/rm/bldg/dept/unit and full words) -> the full word.

    WHAT IT DELIBERATELY DOES NOT COVER (the documented boundary — left to REVIEW):
      * The "#5" vs "suite 5" equivalence. We strip a LEADING "#" so "#5" becomes "5",
        but we do NOT insert a "suite"/"apartment" marker, because the marker is genuinely
        ambiguous (suite? apartment? unit?) and guessing it would be a fabrication, not a
        canonicalization. "270 Park Ave #5" and "270 Park Ave Suite 5" therefore stay in
        REVIEW for a human — the safe under-merge.
      * Misspellings, transpositions, or any NON-abbreviation difference ("Avenue" vs
        "Avanue", "270" vs "207"). Those are not in the dictionary, so the tokens differ,
        the strings differ, and the pair stays in REVIEW. This is the point: a genuinely
        different address ("270 Park Ave" vs "5th Avenue") never merges here — only
        accepted abbreviation-only variants of the SAME address do.
      * No USPS database, no city/state/ZIP parsing, no street-number range logic. The
        dictionary is a small, fixed, ASCII table intentionally kept auditable.

    Empty / missing addresses normalize to "" (which the decision table treats as
    "no signal"), exactly as before. No fuzzy comparison is ever applied to the result —
    exact equality remains the only test downstream."""
    canon_tokens = []
    # Split on whitespace FIRST (see step 1 in the docstring) — never via `_norm`, which
    # would collapse every word together by stripping ordinary spaces.
    for raw in str(v or "").lower().split():
        # Drop any interior zero-width / format chars (unicode-aware, like the rest of
        # the module); a normal token is unchanged.
        tok = _strip_unicode(raw)
        # Strip a leading '#' (so "#5" -> "5") and strip trailing punctuation
        # (so "ave." -> "ave", "blvd," -> "blvd"). We only strip from the ENDS; interior
        # characters and all digits are preserved ("270-272", "5th" survive intact).
        tok = tok.lstrip("#").rstrip(".,;:#")
        if not tok:
            continue  # token was punctuation/whitespace only — carries no address signal
        # Exact dictionary lookup — abbreviation OR full word maps to the canonical word;
        # an unknown token is kept verbatim. Pure substitution, never a similarity score.
        canon_tokens.append(_ADDRESS_TOKEN_CANON.get(tok, tok))
    return " ".join(canon_tokens)


def _norm_reg_id(v) -> str | None:
    """Normalize a reg_id and REJECT meaningless tokens, returning None for "no
    reg_id" so a meaningless value can NEVER be a merge key.

    Rejection rules (deterministic, no thresholds):
      * strip ALL unicode whitespace incl. zero-width (via `_strip_unicode`);
      * an empty remainder            -> None  (a reg_id-less feed is common);
      * a PUNCTUATION-ONLY remainder  -> None  (sentinels like "---", "n/a"-style
        dashes, "."): if no character is alphanumeric, the token carries no identity.
    Otherwise return the lowercased, whitespace-collapsed reg_id (a real merge key)."""
    s = _norm(v)
    if not s:
        return None
    # Punctuation-only sentinel: no alphanumeric character means no identity content.
    if not any(ch.isalnum() for ch in s):
        return None
    return s


def _decide(la: dict, lb: dict) -> str:
    """Adjudicate ONE candidate pair into "merge" / "review" / "apart".

    Pure, deterministic, threshold-free — this is the decision table from the module
    header in code. `la`/`lb` are normalized row dicts (see `splink_dedupe_multifield`)
    carrying: entity_type, reg_id (already `_norm_reg_id`'d, may be None), address,
    jurisdiction, name_norm."""
    # Different type is never the same entity (defensive; the blocking rule already
    # requires matching type, but the decision must stand on its own).
    if la["entity_type"] != lb["entity_type"]:
        return "apart"

    reg_a, reg_b = la["reg_id"], lb["reg_id"]
    addr_a, addr_b = la["address"], lb["address"]

    # ── reg_id branch: both have a MEANINGFUL reg_id and they are EQUAL ───────────
    if reg_a is not None and reg_b is not None and reg_a == reg_b:
        # A meaningful shared reg_id is conclusive ONLY when the address also EXACTLY
        # agrees (a second identity-bearing field corroborates it). Then MERGE.
        if addr_a and addr_b and addr_a == addr_b:
            # Defensive deterministic jurisdiction guard: if both declare a
            # jurisdiction and they DISAGREE, even an identical reg_id+address is
            # suspect (a reused id namespace across national registers) — route to
            # review rather than auto-merge. Exact equality, not a fuzzy ratio.
            jur_a, jur_b = la["jurisdiction"], lb["jurisdiction"]
            if jur_a and jur_b and jur_a != jur_b:
                return "review"
            return "merge"
        # Shared reg_id but the address differs, is missing, or is blank on either
        # side: this is the data-error-vs-two-companies judgment a HUMAN must make
        # (e.g. Galaxy/Tulip both US-4242; noaddr1/noaddr2 with missing address). Do
        # NOT auto-merge on a bare reg_id and do NOT silently drop — route to REVIEW.
        return "review"

    # reg_id present & DIFFERENT (or present on one side only): different registered
    # entities — never a candidate. (Two distinct Acmes with different reg_ids.)
    if reg_a is not None or reg_b is not None:
        return "apart"

    # ── no-reg_id branch: NEITHER record has a meaningful reg_id ──────────────────
    # We do NOT fall back to name-only (that fuses two distinct same-name companies,
    # e.g. two "Summit Capital" at different addresses). Require BOTH the normalized
    # name AND the normalized address to EXACTLY agree to MERGE; otherwise APART.
    name_a, name_b = la["name_norm"], lb["name_norm"]
    if name_a and name_b and name_a == name_b and addr_a and addr_b and addr_a == addr_b:
        return "merge"
    return "apart"


def splink_dedupe_multifield(
    records: list[dict], *, seed: int = 42
) -> dict[str, str] | tuple[dict[str, str], list[dict]]:
    """Cluster registry records by MULTI-FIELD identity using a deterministic
    decision table, with ambiguity routed to human review.

    ``records``: ``[{"unique_id","name","entity_type","reg_id","address",
    "jurisdiction"}, ...]`` (any subset of the multi-field keys may be missing).

    Returns ``(cluster_map, review_pairs)`` where:
      * ``cluster_map`` = ``{unique_id: cluster_id}`` — only MERGE decisions union
        records; REVIEW and APART leave each record in its own singleton cluster, so
        the pipeline keeps reviewed-not-merged records as SEPARATE entities (the libel
        floor is satisfied by construction).
      * ``review_pairs`` = ``[{"unique_id_l","unique_id_r","reason","needs_review":
        True, ...}, ...]`` — every AMBIGUOUS pair, surfaced for the P1.3 human-review
        feed so a wrong reg_id collision is a decision, not a silent merge or a silent
        drop.

    Backward-compatible: a caller that wants only the map can ignore the second tuple
    element; the pipeline unpacks both.

    Mechanism: Splink's training-free `deterministic_link` proposes candidate pairs
    via a blocking rule (same meaningful reg_id, OR no-reg_id + same name + same
    address); `_decide` then adjudicates each candidate into merge / review / apart.
    Degrades safe (identity clusters, no review pairs) if Splink is unavailable or
    errors.
    """
    try:
        import pandas as pd
        from splink import DuckDBAPI, Linker, SettingsCreator
        from splink import comparison_library as cl
        from splink.blocking_rule_library import CustomRule
    except Exception as e:  # splink not installed (it is an OPTIONAL extra)
        logging.getLogger(__name__).warning(
            "splink multifield unavailable (%s); identity clusters", e)
        return ({str(r["unique_id"]): str(r["unique_id"]) for r in records}, [])

    # Normalize the comparison columns up front so equality is robust to case /
    # spacing / unicode whitespace. We keep the ORIGINAL unique_id untouched (it is the
    # join key back to the pipeline's entities). reg_id is normalized AND validated:
    # a meaningless token (blank / zero-width / punctuation-only) becomes "" here so
    # the blocking SQL's `reg_id <> ''` guard treats it as absent, and `_decide` reads
    # it back as None via `_norm_reg_id`.
    rows = []
    for r in records:
        reg = _norm_reg_id(r.get("reg_id", ""))
        rows.append({
            "unique_id": str(r["unique_id"]),
            "entity_type": _norm(r.get("entity_type", "")),
            # Empty string in the dataframe iff reg_id is meaningless — so the SQL
            # `<> ''` guard never fires on a sentinel. `_decide` re-derives None.
            "reg_id": reg or "",
            # Canonicalized address (deterministic abbreviation expansion, NOT fuzzy).
            # This is the SINGLE point of address normalization: the value written here
            # is what the SQL blocking rule (`l.address = r.address`) compares AND what
            # `_decide` reads back via `by_id` (built from this same dataframe), so the
            # candidate-pair blocking and the adjudication always agree on the address.
            "address": _norm_address(r.get("address", "")),
            "jurisdiction": _norm(r.get("jurisdiction", "")),
            "name": str(r.get("name", "")),
            # Normalized name, used ONLY as a blocking key for the no-reg_id fallback.
            "name_norm": _norm(r.get("name", "")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return ({}, [])
    # A single record cannot merge with anything.
    if len(df) == 1:
        return ({df.iloc[0]["unique_id"]: df.iloc[0]["unique_id"]}, [])

    api = DuckDBAPI()

    # Multi-field comparisons. With deterministic linking these are descriptive (the
    # blocking rule decides the candidate pairs and `_decide` adjudicates them); they
    # become trained Fellegi-Sunter comparisons on a real corpus when a deployment
    # swaps deterministic_link() for predict().
    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[
            cl.ExactMatch("reg_id"),
            cl.ExactMatch("address"),
            cl.ExactMatch("name_norm"),
        ],
        # Candidate-pair blocking rules (training-free): a pair is a CANDIDATE iff it
        # satisfies ANY rule. The deterministic `_decide` table then turns each
        # candidate into merge / review / apart. We write CustomRule SQL (not block_on)
        # because block_on(...) compiles to bare column equality and SQL `'' = ''` is
        # TRUE — so a block_on("reg_id") rule fires on a pair where BOTH reg_ids are
        # blank, mass-fusing every reg_id-less record of a type (a libel-grade
        # over-merge). The explicit `<> ''` guards mean a blank/meaningless reg_id (see
        # `_norm_reg_id`, which already mapped sentinels to "") is never a blocking key.
        blocking_rules_to_generate_predictions=[
            # (1) Same MEANINGFUL reg_id within a type — proposes the spelling-variant
            #     merges (JPMorgan) AND the reg_id-collision review cases (Galaxy/Tulip,
            #     spring1/spring2, noaddr1/noaddr2). `_decide` separates merge from
            #     review by whether the address EXACTLY agrees. Never fires on a blank
            #     reg_id (the `<> ''` guard on BOTH sides).
            CustomRule(
                "l.reg_id = r.reg_id AND l.reg_id <> '' "
                "AND l.entity_type = r.entity_type"
            ),
            # (2) NO-REG_ID FALLBACK — when reg_id is absent/meaningless we do NOT fall
            #     back to name-only (that fuses two distinct same-name companies).
            #     Propose only pairs where same type + same normalized name + same
            #     non-empty address; `_decide` confirms the exact agreement and MERGEs.
            #     Same name + DIFFERENT address (Summit) never becomes a candidate, so
            #     it stays APART. The `<> ''` guards keep `'' = ''` from manufacturing a
            #     match on two name-less or address-less records.
            CustomRule(
                "l.entity_type = r.entity_type "
                "AND l.name_norm = r.name_norm AND l.name_norm <> '' "
                "AND l.address = r.address AND l.address <> ''"
            ),
        ],
        retain_intermediate_calculation_columns=True,
    )
    try:
        linker = Linker(df, settings, db_api=api)
        # Deterministic linking — NO parameter estimation, so it is correct on a tiny
        # fixture (where EM would be degenerate). Emits a pairwise frame of all
        # rule-satisfying candidate pairs.
        df_pred = linker.inference.deterministic_link()
        pdf = df_pred.as_pandas_dataframe()
    except Exception as e:
        logging.getLogger(__name__).warning(
            "splink multifield link failed (%s); identity clusters", e)
        return ({r["unique_id"]: r["unique_id"] for _, r in df.iterrows()}, [])

    # ── Adjudicate every candidate pair with the deterministic decision table ─────
    # A blocking rule only PROPOSES a candidate. `_decide` is where each candidate
    # becomes a MERGE (union), a REVIEW (recorded, NOT unioned), or APART (ignored).
    # reg_id was already validated by `_norm_reg_id`; re-derive None here so `_decide`
    # reads the same meaningful/absent distinction (blank string -> None).
    by_id = {row["unique_id"]: dict(row) for _, row in df.iterrows()}
    for v in by_id.values():
        v["reg_id"] = v["reg_id"] or None  # "" (sentinel) -> None ("no reg_id")

    merge_pairs: list[tuple[str, str]] = []
    review_pairs: list[dict] = []
    for _, p in pdf.iterrows():
        lid, rid = p["unique_id_l"], p["unique_id_r"]
        la, lb = by_id[lid], by_id[rid]
        decision = _decide(la, lb)
        if decision == "merge":
            merge_pairs.append((lid, rid))
        elif decision == "review":
            # Reviewed-not-merged: the two records stay SEPARATE (not unioned), but the
            # pair is surfaced for a human with a precise reason. The reason names the
            # corroboration gap so a reviewer can act (same reg_id but address differs /
            # missing / jurisdiction disagrees).
            jur_a, jur_b = la["jurisdiction"], lb["jurisdiction"]
            if jur_a and jur_b and jur_a != jur_b:
                reason = "shared reg_id, jurisdiction mismatch"
            elif not la["address"] or not lb["address"]:
                reason = "shared reg_id, address missing"
            else:
                reason = "shared reg_id, address mismatch"
            review_pairs.append({
                "unique_id_l": lid, "unique_id_r": rid,
                "reg_id": la["reg_id"], "reason": reason, "needs_review": True,
                "label_l": la["name"], "label_r": lb["name"],
                "entity_type": la["entity_type"],
            })
        # decision == "apart": not a real candidate; ignore.

    # ── Union ONLY the MERGE pairs into clusters (connected components) ───────────
    # REVIEW and APART pairs are deliberately NOT unioned, so reviewed-not-merged
    # records remain distinct entities (the libel floor holds by construction).
    parent: dict[str, str] = {u: u for u in df["unique_id"]}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:           # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Deterministic keeper: smaller id is the root, so the cluster id is
            # stable across runs regardless of pair iteration order.
            lo, hi = (ra, rb) if ra < rb else (rb, ra)
            parent[hi] = lo

    for lid, rid in merge_pairs:
        union(lid, rid)

    cluster_map = {u: find(u) for u in df["unique_id"]}
    return (cluster_map, review_pairs)
