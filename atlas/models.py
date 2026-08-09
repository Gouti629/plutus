"""Typed views over the raw policy records in atlas/data/policies.json."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Coverage:
    coverage_id: str
    coverage_type: str
    limit: float
    deductible: float


@dataclass
class Exclusion:
    exclusion_id: str
    description: str
    applies_to: list[str] = field(default_factory=list)


@dataclass
class PolicyRecord:
    policy_number: str
    policyholder_name: str
    policy_type: str
    status: str
    effective_date: str
    expiration_date: str
    coverages: list[Coverage]
    exclusions: list[Exclusion]
    cancellation_date: str | None = None
    cancellation_reason: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyRecord":
        return cls(
            policy_number=d["policy_number"],
            policyholder_name=d["policyholder_name"],
            policy_type=d["policy_type"],
            status=d["status"],
            effective_date=d["effective_date"],
            expiration_date=d["expiration_date"],
            coverages=[Coverage(**c) for c in d["coverages"]],
            exclusions=[Exclusion(**e) for e in d["exclusions"]],
            cancellation_date=d.get("cancellation_date"),
            cancellation_reason=d.get("cancellation_reason"),
        )


# Maps a policy's coverage_type to the FNOL loss_type(s) it responds to.
# This is the semantic bridge between "what the agent extracted" and
# "what's actually in the policy" — it lives here, not in the agent's prompt.
COVERAGE_LOSS_TYPE_MAP: dict[str, list[str]] = {
    "collision": ["auto_collision"],
    "comprehensive": ["auto_comprehensive", "theft", "fire", "wind_hail", "vandalism"],
    "liability": ["liability"],
    "dwelling": ["fire", "wind_hail", "water_damage_sudden", "earth_movement"],
    "personal_property": ["theft", "fire", "water_damage_sudden"],
    "water_damage_sudden": ["water_damage_sudden"],
    "theft": ["theft"],
}
