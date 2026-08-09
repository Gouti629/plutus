"""Shared prompt template for the Part 4 benchmark.

Both api_bench.py (Claude Haiku) and vllm_bench.py (self-hosted) build their
requests from this module, so they're testing the same shared-prefix shape:
a long, fixed extraction-instructions + serialized-policy-context block,
followed by a short per-claim narrative that varies every request. That
fixed/varying split is exactly the structure prefix caching is meant to
exploit - FNOL intake at volume repeats the same instructions and the same
policy-lookup context far more than it repeats any single claim.
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas.store import get_store

CLAIMS_DIR = Path(__file__).parent.parent / "agent" / "data" / "claims"

FIELD_INSTRUCTIONS = """You are an FNOL (First Notice of Loss) extraction engine for a P&C insurance \
intake pipeline. Given a policyholder's claim narrative, extract the following fields as JSON and \
nothing else:

- policyholder_name (string or null)
- policy_number (string or null): looks like "POL-XXXXX"
- date_of_loss (string or null): YYYY-MM-DD if statable
- time_of_loss (string or null)
- loss_type (string or null): one of auto_collision, auto_comprehensive, theft, fire, wind_hail, \
vandalism, water_damage_sudden, water_damage_gradual, flood, earth_movement, liability, other
- location (string or null)
- description (string): one or two sentence plain-language summary
- estimated_damage_usd (number or null)

Use null for anything the text does not clearly state - never guess a policy number, date, or \
dollar amount. Do not evaluate coverage, exclusions, or make an intake decision - extraction only.

Loss type reference (use these definitions to pick the single best-fit category; do not invent \
categories outside this list):

- auto_collision: impact damage to a covered vehicle from a collision with another vehicle, a \
fixed object, or a rollover, regardless of fault.
- auto_comprehensive: non-collision auto loss not otherwise categorized below (falling objects, \
animal strikes, glass breakage) that would typically fall under a comprehensive auto coverage.
- theft: unauthorized taking of property, whether a vehicle, its contents, or property from a home \
or other insured location. Distinguish from vandalism, which involves damage rather than removal.
- fire: loss caused by fire or smoke, including kitchen fires, electrical fires, and wildfire \
damage to a structure.
- wind_hail: loss caused by wind, hailstorm, or a named storm event acting on a structure or its \
exterior (roof, siding, fencing, skylights).
- vandalism: intentional malicious damage to property by a third party, without removal of items.
- water_damage_sudden: water discharge from a specific, identifiable, sudden event - a burst pipe, \
a failed appliance hose, an overflowing fixture - as opposed to a slow leak.
- water_damage_gradual: water intrusion that developed over an extended period (a slow leak, long-\
term seepage, or moisture buildup) rather than a single sudden event.
- flood: damage from rising surface water, storm surge, or the overflow of a river, stream, or \
other body of water onto normally dry land.
- earth_movement: damage from earthquake, landslide, sinkhole, or other movement of the earth.
- liability: damage or injury the policyholder is responsible for causing to a third party or \
their property, as opposed to damage to the policyholder's own property.
- other: use only when the narrative genuinely does not fit any category above, or the cause of \
loss is not yet known.

Worked examples (for calibration only - do not copy these values into your output):

Example 1 - narrative: "John Doe, POL-99001. On 2026-01-05 a pipe burst under my kitchen sink \
overnight and flooded the kitchen floor. About $3,000 in damage." -> \
{"policyholder_name": "John Doe", "policy_number": "POL-99001", "date_of_loss": "2026-01-05", \
"time_of_loss": null, "loss_type": "water_damage_sudden", "location": "kitchen", "description": \
"A burst pipe under the kitchen sink flooded the kitchen floor overnight.", \
"estimated_damage_usd": 3000}

Example 2 - narrative: "This is Jane Roe. My car got broken into and my bag was stolen from the \
back seat, window was smashed. Not sure of the exact date, maybe last weekend." -> \
{"policyholder_name": "Jane Roe", "policy_number": null, "date_of_loss": null, "time_of_loss": \
null, "loss_type": "theft", "location": null, "description": "Vehicle break-in; bag stolen from \
the back seat, window smashed.", "estimated_damage_usd": null}

Example 3 - narrative: "Tom Alvi, policy POL-88112. Hailstorm on 2025-11-02 dented the roof and \
cracked a skylight, contractor quoted $9,400." -> {"policyholder_name": "Tom Alvi", "policy_number": \
"POL-88112", "date_of_loss": "2025-11-02", "time_of_loss": null, "loss_type": "wind_hail", \
"location": null, "description": "Hailstorm dented the roof and cracked a skylight.", \
"estimated_damage_usd": 9400}

Example 4 - narrative: "This is regarding my house. Someone hit my parked car in the driveway and \
drove off, this was on the evening of 2026-02-11 around 7pm. Rear bumper is cracked, maybe $1,500 \
to fix. Policy is POL-77003." -> {"policyholder_name": null, "policy_number": "POL-77003", \
"date_of_loss": "2026-02-11", "time_of_loss": "19:00", "loss_type": "auto_collision", "location": \
"driveway", "description": "Parked car struck by an unknown driver who left the scene.", \
"estimated_damage_usd": 1500}

Example 5 - narrative: "We've had water coming into the basement on and off for months now, \
finally had someone look at it and there's mold starting. Not sure of the exact source yet." -> \
{"policyholder_name": null, "policy_number": null, "date_of_loss": null, "time_of_loss": null, \
"loss_type": "water_damage_gradual", "location": "basement", "description": "Ongoing water \
intrusion into the basement over several months, cause not yet identified.", \
"estimated_damage_usd": null}

Edge-case handling notes:

- If the narrative names two different possible policy numbers (e.g. a stated number and a "might \
be off by a digit" correction), extract the number the policyholder states with the most \
confidence, and do not attempt to guess or correct a digit yourself - that reconciliation happens \
downstream against the policy master list, not during extraction.
- If a date is given only as a relative reference ("last weekend", "a few days ago") with no \
absolute date stated or inferable from context, leave date_of_loss null rather than computing a \
guess relative to today's date.
- If the narrative mixes multiple loss causes (for example, wind followed by resulting water \
intrusion), pick the loss_type that best characterizes the primary cause of the reported damage, \
not every contributing factor.
- If a dollar figure is described as a rough range ("a couple thousand", "maybe $10k-ish"), extract \
your best single-number estimate rather than leaving the field null, but do not fabricate false \
precision (round to a sensible figure).
- Never infer a loss_type of "liability" unless the narrative describes damage or injury the \
policyholder caused to a third party or their property, as opposed to damage to the \
policyholder's own vehicle or home.
- If the description mentions an insured party by a name that does not match the stated \
policyholder_name (for example, a claim filed on behalf of a family member), still extract \
policyholder_name as whoever the narrative identifies as being on the phone with the intake system \
or filing the claim, and note the discrepancy only within the description field.
- Treat "the house was broken into" and similar phrasing as theft unless the narrative explicitly \
states nothing was taken, in which case prefer vandalism.
- Any field not explicitly and unambiguously stated in the narrative must be null - this pipeline \
is used for automated downstream policy lookups, and a fabricated policy number or date is worse \
than a missing one.

Field-level formatting rules, restated in full for clarity:

- policyholder_name: full name as stated, title case, no titles (Mr./Ms./Dr.) or trailing \
punctuation. If only a first name is given, extract that first name alone rather than leaving the \
field null.
- policy_number: preserve the exact format given, including the "POL-" prefix and any leading \
zeros in the numeric portion. Do not add or remove punctuation the policyholder didn't use.
- date_of_loss: always YYYY-MM-DD when an absolute date can be determined from the narrative \
itself. If the narrative gives a date in another format (e.g. "July 14th" or "7/14"), you may \
convert it to YYYY-MM-DD only if the year is unambiguous from context; otherwise leave it null.
- time_of_loss: 24-hour HH:MM format when a specific time or a clear part of day with a \
conventional time (e.g. "around 5:30pm" -> "17:30") is stated. Leave null for vague references \
like "sometime last week" or "overnight" with no hour given.
- loss_type: exactly one value from the loss type reference above - never a list, never a novel \
category, never left as free text.
- location: as specific as the narrative allows (street name, room of the house, "parking lot at \
work"), or null if no location is given at all.
- description: your own concise paraphrase, not a verbatim quote of the narrative. Two sentences \
maximum. Do not include policy numbers, dates, or dollar amounts in the description text itself - \
those belong in their own fields.
- estimated_damage_usd: a plain number with no currency symbol or thousands separator in the JSON \
value itself (the field is numeric, not a string).

This extraction step feeds a downstream Atlas policy lookup and an adjuster-facing decision \
trace, so field-level precision compounds: an incorrectly extracted policy_number causes the \
downstream lookup to silently resolve against the wrong policy record rather than failing loudly, \
which is worse than a policy_number left null and later requested from the policyholder directly. \
Every value you extract should be one you could defend if an adjuster later asked "where in the \
narrative did that come from."

Handling multi-party and multi-claim narratives:

- If a single narrative describes more than one distinct loss event (for example, storm damage to \
both a roof and a detached fence, reported together), extract the fields for the loss event that \
is described first and in the most detail, and mention the second event only within the \
description field rather than attempting to output multiple records - this pipeline processes one \
loss per extraction call, and multi-event claims are split upstream before reaching this step in a \
production deployment.
- If the narrative is written by someone other than the policyholder (an adjuster relaying a phone \
call, a family member filing on the policyholder's behalf), still extract policyholder_name as the \
name of the person the policy is held under if it is stated, not the name of the person writing \
the narrative.
- If the narrative includes commentary about fault, liability, or what the policyholder believes \
should happen next ("I think this should be covered", "this wasn't my fault"), ignore that \
commentary for extraction purposes - it has no bearing on any of the eight fields above and should \
not influence loss_type selection.

A note on confidence and ambiguity: this extraction step does not output a confidence score - it \
outputs values or null. Ambiguity is handled entirely through the choice between a best-guess \
value and null, not through hedging language inside a field's value. Never write values like \
"possibly $3,000" or "maybe theft" into a field - either commit to the value or leave it null and \
let a later stage in the pipeline (adjuster review, a clarifying question back to the \
policyholder) resolve the ambiguity with more information than this extraction call has access to.

Below is the current policy master list for cross-reference context (the same context a full \
intake pipeline would attach to every extraction call so the model can sanity-check policy \
numbers and loss types against what's actually on file):

"""


def _serialize_policy_context() -> str:
    """Renders every policy in Atlas as deterministic text - the long, fixed
    chunk of context that's identical on every request and is what makes
    this prompt shape a realistic prefix-caching candidate."""
    store = get_store()
    lines = []
    for policy_number in sorted(store.policies.keys()):
        p = store.policies[policy_number]
        cov_str = "; ".join(f"{c.coverage_type} (limit ${c.limit:,.0f}, ded ${c.deductible:,.0f})" for c in p.coverages)
        excl_str = "; ".join(f"{e.exclusion_id}: {e.description}" for e in p.exclusions) or "none"
        lines.append(
            f"- {p.policy_number} | {p.policyholder_name} | {p.policy_type} | status={p.status} | "
            f"term {p.effective_date} to {p.expiration_date} | coverages: {cov_str} | exclusions: {excl_str}"
        )
    return "\n".join(lines)


def build_shared_prefix() -> str:
    """The full fixed prefix: instructions + serialized policy context.

    Deterministic and identical across every call - the only thing that
    changes request to request is the claim narrative appended after it.
    """
    return FIELD_INSTRUCTIONS + _serialize_policy_context()


def load_claim_narratives(limit: int | None = None) -> list[str]:
    texts = []
    for path in sorted(CLAIMS_DIR.glob("*.json")):
        texts.append(json.loads(path.read_text())["submitted_text"])
    return texts[:limit] if limit else texts


EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "policyholder_name": {"type": ["string", "null"]},
        "policy_number": {"type": ["string", "null"]},
        "date_of_loss": {"type": ["string", "null"]},
        "time_of_loss": {"type": ["string", "null"]},
        "loss_type": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "description": {"type": "string"},
        "estimated_damage_usd": {"type": ["number", "null"]},
    },
    "required": ["description"],
    "additionalProperties": False,
}


if __name__ == "__main__":
    prefix = build_shared_prefix()
    narratives = load_claim_narratives()
    print(f"Shared prefix: {len(prefix)} chars (~{len(prefix) // 4} tokens, rough estimate)")
    print(f"Loaded {len(narratives)} claim narratives for benchmarking")
    print("\n--- prefix preview ---\n")
    print(prefix[:600] + ("..." if len(prefix) > 600 else ""))
