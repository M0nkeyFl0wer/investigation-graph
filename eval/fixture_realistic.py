"""Realistic-prose fixture for GATE-R2 — the messy, indirect language a real leaked
document actually uses, NOT clean textbook SVO.

WHY THIS EXISTS. The original GATE-R2 fixture is clean single-clause sentences
("Acme Corp paid John Smith $5,000") with good adversarial traps. A frontier model
scored 0.94 on it — but that's "the best model on the easiest realistic input." It
does NOT tell you what happens on a 40-page filing where the relationship is implied
through legalese, apposition, nominee structures, and hedged denials. This fixture is
that harder input: every positive case states a REAL relationship a careful reader
would extract, but states it INDIRECTLY; every distractor is a genuine
non-relationship dressed in language that tempts a naive extractor.

GOLD DISCIPLINE. A triple is in the gold only if a fair human reader would clearly
agree the sentence asserts it (affirmatively, in the present/past — not hypothetically
or under denial). Direction must be correct. Edge-type vocabulary matches the rest of
R2 (OWNS, DIRECTOR_OF, PAID, FUNDS, LOCATED_IN). A couple of cases are deliberately
*inferential* (control-implies-ownership) and are exactly what an independent gold
review should adjudicate — this file is the BUILDER's gold; a separate verifier reads
each sentence cold and checks these labels aren't wrong, over-reaching, or missing an
edge a fair reader would mark.

Each entry: (sentence, {gold triples}).  Empty set = a distractor with NO edge.
"""
from __future__ import annotations

REALISTIC_FIXTURE: list[tuple[str, set[tuple[str, str, str]]]] = [
    # ── Positive cases: a real relationship, stated indirectly ──────────────
    # Legalese + "came to control a 62% interest" = ownership.
    ("Pursuant to the 2019 share-purchase agreement, Brightwater Holdings came to "
     "control a 62 percent interest in Lazaro Marine.",
     {("Brightwater Holdings", "OWNS", "Lazaro Marine")}),
    # Apposition relative clause; "has chaired ... board" = a directorship.
    ("Ms. Okonkwo, who has chaired Lazaro Marine's board since the 2020 "
     "restructuring, declined to comment.",
     {("Ms. Okonkwo", "DIRECTOR_OF", "Lazaro Marine")}),
    # "remitted roughly €240,000 to" = a payment (no clean verb "paid").
    ("Over eighteen months the Health Ministry remitted roughly €240,000 to "
     "Verbena Advisory.",
     {("Health Ministry", "PAID", "Verbena Advisory")}),
    # Inferential control: "an arm of ... appointed every member of the board" =
    # de-facto ownership/control. (A case for the independent gold review.)
    ("Orion Freight is, for all practical purposes, an arm of Meridian Capital, "
     "which appointed every member of the freight company's board.",
     {("Meridian Capital", "OWNS", "Orion Freight")}),
    # Location buried in a descriptive clause.
    ("Castellan Group runs its commodities desk out of a converted bank building "
     "in Geneva.",
     {("Castellan Group", "LOCATED_IN", "Geneva")}),
    # "founded ... and remains its sole shareholder" = ownership; founding year is noise.
    ("Mr. Halloran founded Meridian Capital in 2008 and remains its sole shareholder.",
     {("Mr. Halloran", "OWNS", "Meridian Capital")}),
    # Funding stated as a flow with a direction; the "favorable review" clause is a
    # suggestive non-edge the model must not type.
    ("A $1.2 million grant flowed from the Delacroix Foundation to the Pelham "
     "Institute the same quarter the institute published its favorable review.",
     {("Delacroix Foundation", "FUNDS", "Pelham Institute")}),
    # Nominee structure: "beneficial ownership ... rests with" = ownership despite the
    # prospectus naming nominees. Tests that "lists only nominees" doesn't mislead.
    ("Though the prospectus lists only nominees, beneficial ownership of Adriatic "
     "Lines rests with Mr. Halloran.",
     {("Mr. Halloran", "OWNS", "Adriatic Lines")}),
    # Inferential funding: "covers its payroll" = funds it. (For the gold review.)
    ("Verbena Advisory operates almost entirely on staff seconded from Castellan "
     "Group, which covers its payroll.",
     {("Castellan Group", "FUNDS", "Verbena Advisory")}),
    # Shared registered address = both located in Valletta (multi-edge, indirect).
    ("Both Lazaro Marine and Adriatic Lines list the same Valletta post-office box "
     "as their registered address.",
     {("Lazaro Marine", "LOCATED_IN", "Valletta"),
      ("Adriatic Lines", "LOCATED_IN", "Valletta")}),

    # ── Distractors: real-looking language, NO extractable edge ──────────────
    # Co-occurrence + explicit no-relationship.
    ("Mr. Halloran and the energy minister were photographed together at Davos, but "
     "there is no record of any dealing between them.",
     set()),
    # Denial — no payment relationship to assert.
    ("Verbena Advisory has categorically denied ever invoicing the Defense Ministry.",
     set()),
    # Conditional / future — nothing has happened.
    ("Should the merger clear review, Castellan Group would acquire control of "
     "Orion Freight.",
     set()),
    # Mere listing of co-named entities — no relationship between them.
    ("The dossier lists Brightwater Holdings, Meridian Capital and the Pelham "
     "Institute among entities of concern.",
     set()),
    # "criticized ... bid" is not an ontology relationship — must not be typed.
    ("Adriatic Lines publicly criticized Meridian Capital's latest bid.",
     set()),
    # Vague, untypeable "commercial relationship" — must not be forced into OWNS/PAID/FUNDS.
    ("A spokesman would confirm only that Castellan Group and Lazaro Marine "
     "'maintain a longstanding commercial relationship.'",
     set()),
]
