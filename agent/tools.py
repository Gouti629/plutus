"""Anthropic tool-use definitions for the FNOL Navigator agent.

Seven tools, three purposes:
  - record_extracted_fields / record_attachment_review / submit_decision are
    "sinks": the agent calls them to hand back typed data, and we just
    capture the input. record_attachment_review is the multimodal
    counterpart to record_extracted_fields - it's how the agent's read of an
    invoice PDF or a damage photo becomes structured data instead of buried
    prose in the reasoning summary.
  - lookup_policy / check_policy_status / check_coverage / check_exclusions
    are read-only queries into Atlas (atlas/rules.py) — the agent's only way
    to learn anything about a policy. There is no policy data in the system
    prompt, so any coverage/exclusion claim in the final decision has to be
    backed by one of these calls.
"""

from __future__ import annotations

LOSS_TYPE_ENUM = [
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

RECORD_EXTRACTED_FIELDS = {
    "name": "record_extracted_fields",
    "description": (
        "Record the structured fields extracted from the claim submission. "
        "Call this first, before any Atlas lookups. Use null for any field "
        "the submission does not clearly state - do not guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "policyholder_name": {"type": ["string", "null"]},
            "policy_number": {"type": ["string", "null"], "description": "e.g. POL-10234"},
            "date_of_loss": {"type": ["string", "null"], "description": "YYYY-MM-DD if statable"},
            "time_of_loss": {"type": ["string", "null"]},
            "loss_type": {
                "type": ["string", "null"],
                "enum": LOSS_TYPE_ENUM + [None],
                "description": "Best-fit category for the loss. Use 'other' if genuinely ambiguous.",
            },
            "location": {"type": ["string", "null"]},
            "description": {"type": "string", "description": "One or two sentence plain-language summary of what happened."},
            "estimated_damage_usd": {"type": ["number", "null"]},
        },
        "required": ["description"],
    },
}

LOOKUP_POLICY = {
    "name": "lookup_policy",
    "description": "Retrieve the policy record (holder, type, status, coverages, term dates) for a policy number.",
    "input_schema": {
        "type": "object",
        "properties": {"policy_number": {"type": "string"}},
        "required": ["policy_number"],
    },
}

CHECK_POLICY_STATUS = {
    "name": "check_policy_status",
    "description": "Check whether a policy was in force (active, not lapsed/cancelled/outside its term) on the date of loss.",
    "input_schema": {
        "type": "object",
        "properties": {
            "policy_number": {"type": "string"},
            "loss_date": {"type": "string", "description": "YYYY-MM-DD"},
        },
        "required": ["policy_number", "loss_date"],
    },
}

CHECK_COVERAGE = {
    "name": "check_coverage",
    "description": "Check whether any coverage on the policy responds to the given loss_type, and return its limit/deductible if so.",
    "input_schema": {
        "type": "object",
        "properties": {
            "policy_number": {"type": "string"},
            "loss_type": {"type": "string", "enum": LOSS_TYPE_ENUM},
        },
        "required": ["policy_number", "loss_type"],
    },
}

CHECK_EXCLUSIONS = {
    "name": "check_exclusions",
    "description": "Check whether any exclusion on the policy applies to the given loss_type.",
    "input_schema": {
        "type": "object",
        "properties": {
            "policy_number": {"type": "string"},
            "loss_type": {"type": "string", "enum": LOSS_TYPE_ENUM},
        },
        "required": ["policy_number", "loss_type"],
    },
}

RECORD_ATTACHMENT_REVIEW = {
    "name": "record_attachment_review",
    "description": (
        "Record what you observed in each attached invoice/bill PDF or damage photo. Call this "
        "once, after reviewing every attachment, before the Atlas lookups - but only if the "
        "submission actually included attachments. Skip this tool entirely if none were provided."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "Must match the filename given for this attachment."},
                        "kind": {"type": "string", "enum": ["invoice", "damage_photo"]},
                        "observation": {
                            "type": "string",
                            "description": "1-2 sentence factual description of what the document/photo actually shows.",
                        },
                        "supports_claim": {
                            "type": ["boolean", "null"],
                            "description": (
                                "true if this evidence is consistent with the narrative and the "
                                "estimated damage; false if it contradicts or raises a concern; "
                                "null only if genuinely inconclusive (e.g. an unreadable scan)."
                            ),
                        },
                    },
                    "required": ["filename", "kind", "observation", "supports_claim"],
                },
            },
        },
        "required": ["reviews"],
    },
}

SUBMIT_DECISION = {
    "name": "submit_decision",
    "description": (
        "Submit the final intake decision. Call this last, after recording extracted fields and "
        "querying Atlas for policy status/coverage/exclusions. Every item in `evidence` must come from "
        "the `evidence` field of a prior tool result - do not fabricate citations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["auto-approve intake", "flag for adjuster review", "request more info"],
            },
            "confidence": {
                "type": "number",
                "description": "0.0-1.0 confidence in this decision.",
            },
            "reasoning_summary": {
                "type": "string",
                "description": "2-4 sentence explanation an adjuster could read to understand the decision.",
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "rule_id": {"type": ["string", "null"]},
                        "text": {"type": "string"},
                    },
                    "required": ["source", "text"],
                },
            },
            "flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                    },
                    "required": ["code", "message", "severity"],
                },
            },
        },
        "required": ["decision", "confidence", "reasoning_summary", "evidence", "flags"],
    },
}

ALL_TOOLS = [
    RECORD_EXTRACTED_FIELDS,
    RECORD_ATTACHMENT_REVIEW,
    LOOKUP_POLICY,
    CHECK_POLICY_STATUS,
    CHECK_COVERAGE,
    CHECK_EXCLUSIONS,
    SUBMIT_DECISION,
]
