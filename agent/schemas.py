"""Typed shapes for the FNOL agent's output and decision trace.

LOSS_TYPES is the shared vocabulary between the agent's extraction step and
Atlas's coverage/exclusion lookups (atlas/models.py's COVERAGE_LOSS_TYPE_MAP
and the exclusions in atlas/data/policies.json use the same strings) — that
alignment is what lets the agent's tool calls actually resolve against
policy data instead of talking past it.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

LossType = Literal[
    "auto_collision",
    "auto_comprehensive",
    "theft",
    "fire",
    "wind_hail",
    "vandalism",
    "water_damage_sudden",
    "water_damage_gradual",
    "flood",
    "earth_movement",
    "liability",
    "other",
]


class Decision(str, Enum):
    AUTO_APPROVE = "auto-approve intake"
    FLAG_FOR_REVIEW = "flag for adjuster review"
    REQUEST_MORE_INFO = "request more info"


class ExtractedFields(BaseModel):
    policyholder_name: Optional[str] = None
    policy_number: Optional[str] = None
    date_of_loss: Optional[str] = Field(None, description="YYYY-MM-DD if known")
    time_of_loss: Optional[str] = None
    loss_type: Optional[LossType] = None
    location: Optional[str] = None
    description: str
    estimated_damage_usd: Optional[float] = None


class Attachment(BaseModel):
    """A file uploaded alongside a submission - an invoice/bill PDF or a
    damage photo. `path` is relative to the project root
    (agent/data/attachments/{claim_id}/{filename})."""

    filename: str
    kind: Literal["invoice", "damage_photo"]
    content_type: str
    path: str
    size_bytes: int


class AttachmentReview(BaseModel):
    """What the agent observed when it looked at one attachment - the
    multimodal counterpart to EvidenceCitation. `supports_claim` is null
    when the attachment is present but genuinely inconclusive, not when the
    agent skipped reviewing it."""

    filename: str
    kind: Literal["invoice", "damage_photo"]
    observation: str
    supports_claim: Optional[bool] = None


class EvidenceCitation(BaseModel):
    source: str = Field(..., description="Path into the Atlas record this cites, e.g. policy:POL-1004.exclusions[1]")
    rule_id: Optional[str] = None
    text: str


class Flag(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "critical"] = "info"


class ToolCallRecord(BaseModel):
    """One tool_use -> tool_result pair, kept verbatim for the trace."""

    tool_name: str
    tool_input: dict
    tool_result: dict


class DecisionTrace(BaseModel):
    claim_id: str
    submitted_text: str
    extracted: Optional[ExtractedFields] = None
    decision: Optional[Decision] = None
    confidence: Optional[float] = None
    reasoning_summary: Optional[str] = None
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    attachment_reviews: list[AttachmentReview] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    model: Optional[str] = None
    error: Optional[str] = None
