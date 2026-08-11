"""Writes ~26 synthetic FNOL narrative submissions to agent/data/claims/.

All names, policy numbers, and addresses are invented. Policy numbers match
records in atlas/data/policies.json so the agent's lookups actually resolve.
`edge_case` is a label for our own tracking (README / interview walkthrough)
- it is never shown to the agent, which only ever sees `submitted_text`.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).parent / "data" / "claims"

CLAIMS = [
    {
        "claim_id": "claim-001",
        "edge_case": "clean auto collision, active policy, covered -> expect auto-approve",
        "submitted_text": (
            "My name is Maria Alvarez, policy POL-10234. On 2026-07-14 around 5:30pm I was "
            "rear-ended at a stoplight on Route 9 in Albany, NY. The other driver hit my rear "
            "bumper and trunk. Repair shop estimate came back at $4,200. No injuries."
        ),
    },
    {
        "claim_id": "claim-002",
        "edge_case": "clean homeowners sudden water damage, active, covered -> auto-approve",
        "submitted_text": (
            "James Whitfield here, policy number POL-10891. On July 2, 2026 our washing machine "
            "supply hose burst overnight and flooded the laundry room and part of the hallway. "
            "We're at 44 Birchwood Lane. A plumber already capped the line. Estimated damage to "
            "flooring and drywall is about $6,500."
        ),
    },
    {
        "claim_id": "claim-003",
        "edge_case": "missing policy number entirely -> expect request more info",
        "submitted_text": (
            "Hi, I need to file a claim. Someone broke into my car last night and stole my "
            "laptop and a bag of tools from the trunk. This happened in the parking lot at my "
            "apartment complex. I don't have my policy number handy, can you look it up by my "
            "name, David Kim?"
        ),
    },
    {
        "claim_id": "claim-004",
        "edge_case": "flood, excluded loss type on POL-10891 -> expect flag for adjuster review",
        "submitted_text": (
            "This is James Whitfield, policy POL-10891. After the storm on 2026-06-28 the creek "
            "behind our house overflowed and about eight inches of water came into the basement. "
            "Carpet, boxes, and the water heater down there are ruined. Looking at around $18,000 "
            "in damage."
        ),
    },
    {
        "claim_id": "claim-005",
        "edge_case": "lapsed policy, loss date after expiration -> expect flag",
        "submitted_text": (
            "Priya Natarajan, policy POL-11045. I was backing out of my driveway on 2026-07-20 "
            "and clipped the mailbox post, denting the rear quarter panel. Estimate is around "
            "$1,800."
        ),
    },
    {
        "claim_id": "claim-006",
        "edge_case": "ambiguous water damage (sudden vs gradual not stated) -> expect flag or request info",
        "submitted_text": (
            "Policy POL-10891, James Whitfield. We noticed a water stain spreading across the "
            "kitchen ceiling this week and when we opened it up there's clearly been water "
            "getting in for a while. Not sure exactly when it started. Damage looks like it could "
            "be a few thousand dollars once we get someone in to look at it properly."
        ),
    },
    {
        "claim_id": "claim-007",
        "edge_case": "high damage estimate on auto, active + covered -> expect flag",
        "submitted_text": (
            "Sofia Marchetti, POL-11689. On 2026-07-10 I hit a deer on Route 22 north of town "
            "around 9pm. Front end is completely caved in, airbags deployed, and the shop I "
            "towed it to thinks it might be closer to $42,000 given the frame damage. No other "
            "vehicles involved."
        ),
    },
    {
        "claim_id": "claim-008",
        "edge_case": "theft claim on a policy without comprehensive -> not covered -> expect flag",
        "submitted_text": (
            "Angela Brooks, policy POL-11367. My car was broken into on 2026-07-05 while parked "
            "outside my office downtown and the stereo and a set of golf clubs were taken from the "
            "back seat. Window was smashed. Damage and stolen items add up to about $2,100."
        ),
    },
    {
        "claim_id": "claim-009",
        "edge_case": "theft on a home that had been vacant 60+ days -> matches vacancy exclusion",
        "submitted_text": (
            "David Kim, policy POL-11220. We've been out of the country since early May and just "
            "got back on 2026-07-08 to find the back door forced open and the TV, a laptop, and "
            "some jewelry gone. House had been sitting empty the whole time we were away, about "
            "ten weeks. Estimated loss around $9,000."
        ),
    },
    {
        "claim_id": "claim-010",
        "edge_case": "commercial/rideshare use exclusion -> expect flag",
        "submitted_text": (
            "Angela Brooks again, POL-11367. I drive for a rideshare app on weekends. On "
            "2026-07-12 while I had a passenger in the car I rear-ended someone who stopped short "
            "on Elm Street. My front bumper and headlight are damaged, about $2,600 to fix."
        ),
    },
    {
        "claim_id": "claim-011",
        "edge_case": "unlisted driver exclusion -> expect flag",
        "submitted_text": (
            "Sofia Marchetti, POL-11689. My nephew was visiting and borrowed my car on 2026-07-16 "
            "to run an errand - he's not on the policy. He backed into a parking garage pillar and "
            "damaged the rear bumper and taillight, roughly $3,000 in repairs."
        ),
    },
    {
        "claim_id": "claim-012",
        "edge_case": "racing exclusion -> expect flag",
        "submitted_text": (
            "Maria Alvarez, POL-10234. I took my car to an autocross event at the fairgrounds on "
            "2026-07-18 and spun out into a tire barrier during a timed run. Front bumper and "
            "wheel damage, about $3,500."
        ),
    },
    {
        "claim_id": "claim-013",
        "edge_case": "cancelled policy -> expect flag",
        "submitted_text": (
            "Marcus Devereaux, policy POL-11734. A tree branch came down in a storm on 2026-07-11 "
            "and put a hole in the roof over the garage. Water got into the garage ceiling too. "
            "Estimated repair cost around $7,200."
        ),
    },
    {
        "claim_id": "claim-014",
        "edge_case": "earth movement exclusion -> expect flag",
        "submitted_text": (
            "Robert Chen, POL-11502. There was a small earthquake in the area on 2026-06-30 and "
            "it cracked the foundation and a load-bearing wall in the basement. A contractor "
            "quoted around $22,000 to repair the foundation."
        ),
    },
    {
        "claim_id": "claim-015",
        "edge_case": "no date of loss stated -> expect request more info",
        "submitted_text": (
            "This is Maria Alvarez, policy POL-10234. Someone sideswiped my car while it was "
            "parked on the street and took off. Left a long scrape and dented the driver's side "
            "doors. I haven't had it looked at yet but it's probably a couple thousand dollars."
        ),
    },
    {
        "claim_id": "claim-016",
        "edge_case": "extremely vague description, no usable loss type -> expect request more info",
        "submitted_text": (
            "Hi, filing a claim for policy POL-11045. Something happened to my car and it needs "
            "to be fixed. Can someone call me to go over the details?"
        ),
    },
    {
        "claim_id": "claim-017",
        "edge_case": "clean liability auto claim -> expect auto-approve",
        "submitted_text": (
            "James here - wait, sorry, this is Angela Brooks, policy POL-11367. On 2026-07-09 I "
            "changed lanes on the highway and clipped another car, causing damage to their "
            "passenger door. My insurance needs to cover their repair, estimated at $3,100. My "
            "own car has no damage."
        ),
    },
    {
        "claim_id": "claim-018",
        "edge_case": "clean theft claim, covered, no vacancy issue -> expect auto-approve",
        "submitted_text": (
            "David Kim, POL-11220. We were home all week but on the night of 2026-07-15 someone "
            "broke a side window and took a bike and a power tool set from the garage while we "
            "were asleep. Reported to police, report number on file. Estimated loss $2,400."
        ),
    },
    {
        "claim_id": "claim-019",
        "edge_case": "clean fire claim on homeowners dwelling -> expect auto-approve",
        "submitted_text": (
            "James Whitfield, POL-10891. A grease fire in the kitchen on 2026-07-06 damaged the "
            "stove, cabinets, and scorched part of the ceiling before we got it out with an "
            "extinguisher. Fire department confirmed the cause. Contractor estimate is $14,000."
        ),
    },
    {
        "claim_id": "claim-020",
        "edge_case": "clean wind/hail claim on homeowners dwelling -> expect auto-approve",
        "submitted_text": (
            "Robert Chen, policy POL-11502. Hailstorm on 2026-07-19 put dozens of dents in the "
            "roof shingles and cracked two skylights. Roofer quoted $11,500 to replace the "
            "affected sections."
        ),
    },
    {
            "claim_id": "claim-021",
            "edge_case": "gradual water leak, explicitly stated as long-term -> matches gradual-water exclusion",
            "submitted_text": (
                "James Whitfield again, POL-10891. We finally found out why the bathroom floor has "
                "been soft - there's been a slow leak under the shower pan for what the plumber "
                "thinks is at least a year. Subfloor and some framing are rotted. Repair estimate is "
                "$9,800."
            ),
        },
    {
            "claim_id": "claim-022",
            "edge_case": "Auto damage",
            "submitted_text": (
                "My name is Goutham Srirangam, POL-28456. I was parking in front of my house when some one came from behind and hit my car."
                "The whole trunk got damaged and the the estimated cost is 5000 dollars. It happened on July 20th, 2026"
            ),
        },
    {
        "claim_id": "claim-023",
        "edge_case": "clean vandalism claim under comprehensive -> expect auto-approve",
        "submitted_text": (
            "Sofia Marchetti, POL-11689. Woke up on 2026-07-21 to find both mirrors snapped off "
            "and a long key-scratch down the side of my car in the apartment parking lot. No idea "
            "who did it. Estimate to repair is $2,900."
        ),
    },
    {
        "claim_id": "claim-024",
        "edge_case": "policy number typo / not found -> expect flag",
        "submitted_text": (
            "This is Maria Alvarez, my policy number is POL-10239 I think - could be off by a "
            "digit. On 2026-07-17 I hit a pothole hard on the interstate and blew out both "
            "passenger-side tires and bent a rim. About $1,100 total."
        ),
    },
    {
        "claim_id": "claim-025",
        "edge_case": "auto damage above coverage limit -> expect flag",
        "submitted_text": (
            "Angela Brooks, POL-11367. Multi-car pileup on the highway on 2026-07-13 in heavy "
            "fog, I was one of about six cars involved. My car is likely a total loss - shop is "
            "estimating $27,000 to repair versus the car's value, and my policy is on the lower "
            "coverage tier so I'm not sure what will actually be paid out."
        ),
    },
    {
        "claim_id": "claim-026",
        "edge_case": "ambiguous cause on homeowners, no clear loss_type -> expect request more info",
        "submitted_text": (
            "Robert Chen, POL-11502. Something happened to the side of the house over the "
            "weekend - there's a big gouge in the siding and some of the gutter is bent up. Not "
            "sure if it was the wind, a branch, or someone's car backing into it. Haven't had a "
            "chance to look closely yet."
        ),
    },
    {
        "claim_id": "claim-027",
        "edge_case": "multiple minor risk indicators combined (no time of loss + high estimate) -> expect flag",
        "submitted_text": (
            "David Kim, POL-11220. At some point over the last few days someone got into the "
            "detached shed and took a ride-on mower, a generator, and various tools. We're not "
            "sure exactly when since we don't check the shed daily. Total value of everything "
            "taken is around $16,000."
        ),
    },
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for claim in CLAIMS:
        path = OUT_DIR / f"{claim['claim_id']}.json"
        path.write_text(json.dumps(claim, indent=2))
    print(f"Wrote {len(CLAIMS)} synthetic claims to {OUT_DIR}")


if __name__ == "__main__":
    main()
