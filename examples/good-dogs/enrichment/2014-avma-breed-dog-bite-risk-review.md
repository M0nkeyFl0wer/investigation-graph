---
note_id: enrich_2014_avma_breed_bite_risk_review
source_url: https://www.avma.org/sites/default/files/resources/dog_bite_risk_and_prevention_bgnd.pdf
source_title: "Literature Review on the Welfare Implications of The Role of Breed in Dog Bite Risk and Prevention"
source_date: "2014-01-01"
source_publisher: "American Veterinary Medical Association (AVMA)"
secondary_source_url: https://www.avma.org/resources-tools/pet-owners/dog-bite-prevention/why-breed-specific-legislation-not-answer
license: fair_use_excerpt
license_note: "AVMA public literature review + AVMA public-education page. Fair-use summary plus attribution; full text not republished."
accessed_on: "2026-06-21"
domain: enrichment
added_by: "good-dog OSINT loop (CASE-STUDY.md final act) — closes the measured research<->policy structural gap"
tags: [enrichment, bridge, bsl, pit_bull, german_shepherd, dog_bite, avma, breed_identification]

# Gold annotations for the enrichment note. The IDs on the behavioral side
# (pub_bollen_horowitz_2012_safer_validity, concept_safer_assessment) and the
# policy side (concept_bsl) ALREADY exist in the corpus; this note is the document
# that finally links them — closing the measured research<->policy structural gap.
entities:
  - id: pub_avma_2014_breed_bite_risk
    type: publication
    canonical: "Literature Review on the Welfare Implications of The Role of Breed in Dog Bite Risk and Prevention (AVMA, 2014)"
    aliases: ["AVMA breed-bite-risk review", "The Role of Breed in Dog Bite Risk and Prevention"]

edges:
  # Policy side — the review is squarely about breed-specific legislation.
  - from: pub_avma_2014_breed_bite_risk
    type: subject_of
    to: concept_bsl
    evidence: "The review is the AVMA's evidentiary basis for opposing breed-specific legislation: 'breed-specific bans are a simplistic answer to a far more complex social problem.'"
  # Behavioral side — THE bridge edge: the review weighs the behavior-assessment
  # research, including the SAFER validity work, against the policy.
  - from: pub_avma_2014_breed_bite_risk
    type: cites
    to: pub_bollen_horowitz_2012_safer_validity
    evidence: "The review synthesizes behavior-assessment and bite-incidence research (including SAFER-style aggression-assessment validity work) and concludes the breed-bite connection is weak or absent."
  - from: pub_avma_2014_breed_bite_risk
    type: mentions
    to: concept_safer_assessment
    evidence: "Discusses behavior-assessment instruments used to predict aggression as more informative than breed."
  - from: pub_avma_2014_breed_bite_risk
    type: mentions
    to: breed_american_pit_bull_terrier
    evidence: "Notes pit-bull-type dogs are over-reported in bites but that visual breed identification is unreliable, confounding the signal."
  - from: pub_avma_2014_breed_bite_risk
    type: mentions
    to: breed_american_staffordshire_terrier
    evidence: "AmStaff is among the breeds frequently conflated with 'pit bull' under unreliable visual identification."
  - from: pub_avma_2014_breed_bite_risk
    type: mentions
    to: breed_german_shepherd_dog
    evidence: "The German Shepherd Dog is among the breeds the review reports as over-represented in bite incidents."
---

# The AVMA Review of Breed in Dog-Bite Risk — the bridge between the behavioral science and the breed bans

## Why this note was added

The first build of the good-dog graph left a **structural gap**: the
behavioral-research cluster (temperament testing such as **SAFER**, bite-incident
studies, breed-aggression findings) and the municipal-policy cluster (the
**breed-specific legislation** bylaws of **Denver**, **Calgary**, **Montreal**, and
**Ontario**) both turn on the same breeds — the **American Pit Bull Terrier**, the
**American Staffordshire Terrier**, and the **German Shepherd Dog** — yet no single
document in the corpus connected the science to the law. This note is the
public-records source that closes that gap.

## What the document is

The **American Veterinary Medical Association (AVMA)** published a literature
review, *The Role of Breed in Dog Bite Risk and Prevention* (2014), synthesizing
the peer-reviewed evidence on whether a dog's **breed** predicts bite risk, and on
whether **breed-specific legislation** reduces dog bites. It is the canonical
document that the breed-ban debate cites, and it explicitly weighs the behavioral
evidence against the policy response.

## What it found — and how it bridges the two clusters

On the **behavioral-science** side, the review reports that the breeds most often
reported in bite incidents include **pit bull-type** dogs, the **German Shepherd
Dog**, the **Rottweiler**, and mixed-breed dogs — but it cautions that this
reporting is confounded by **unreliable breed identification**. In the AVMA's
words, "It is extremely difficult to determine a dog's breed or breed mix simply by
looking at it," and even breed experts frequently misidentify mixed-breed dogs as
"pit bulls." It concludes that the connection between breed and bite risk is weak
or absent, and that "responsible ownership variables such as socialization,
neutering and proper containment of dogs are much more strongly indicated as
important risk factors" — directly engaging the temperament-and-behavior research
that the corpus already holds.

On the **policy** side, the review is the evidentiary basis for the AVMA's opposition
to **breed-specific legislation**. The AVMA holds that "breed-specific bans are a
simplistic answer to a far more complex social problem, and they have the potential
to divert attention and resources from more effective approaches." This is the same
**BSL** that the Denver, Calgary, Montreal, and Ontario ordinances enact or repeal,
and that the breed-ban court challenges contest.

## The connection this makes explicit

Because the AVMA review is *about* the pit-bull and German-Shepherd breeds, *cites*
the behavioral and bite-incidence research, and *bears directly on* breed-specific
legislation, it is the missing bridge: it ties the behavioral-research community to
the municipal-policy community through a single, sourced, public document. A reader
who starts from the SAFER behavioral assessment can now reach a Calgary or Denver
BSL bylaw along an evidence-bearing path, rather than across a gap that flat search
would never have surfaced.

## Sources

- AVMA, *Literature Review on the Welfare Implications of The Role of Breed in Dog
  Bite Risk and Prevention* (2014):
  https://www.avma.org/sites/default/files/resources/dog_bite_risk_and_prevention_bgnd.pdf
- AVMA, "Why breed-specific legislation is not the answer":
  https://www.avma.org/resources-tools/pet-owners/dog-bite-prevention/why-breed-specific-legislation-not-answer
