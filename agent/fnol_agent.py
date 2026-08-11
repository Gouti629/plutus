"""The FNOL Navigator agent: extraction -> Atlas grounding -> decision.

Core loop: send the claim narrative + tool definitions to Claude, dispatch
each tool_use block Claude emits (record_extracted_fields /
record_attachment_review / lookup_policy / check_policy_status /
check_coverage / check_exclusions / submit_decision), feed the results back,
and repeat until Claude calls submit_decision or we hit a turn cap. The full
sequence of tool calls *is* the decision trace - there's no separate step
where we ask the model to summarize what it did.

Attached invoices/damage photos ride along as real multimodal content in the
first user turn (image/document blocks, not a text description of them) -
see _load_attachment_content_blocks.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import anthropic

from agent.schemas import (
    Attachment,
    AttachmentReview,
    Decision,
    DecisionTrace,
    EvidenceCitation,
    ExtractedFields,
    Flag,
    ToolCallRecord,
)
from agent.tools import ALL_TOOLS
from atlas import rules as atlas_rules

DEFAULT_MODEL = os.environ.get("NAVIGATOR_MODEL", "claude-sonnet-4-5")
MAX_TURNS = 8
PROJECT_ROOT = Path(__file__).parent.parent

SYSTEM_PROMPT = """You are Navigator, an intake triage agent for First Notice of Loss (FNOL) \
submissions in P&C insurance claims. You read a policyholder's claim narrative and turn it into \
a structured, policy-grounded intake decision.

For each submission:

1. Call record_extracted_fields first, with everything you can confidently extract from the raw \
text: policyholder name, policy number, date/time of loss, loss type, location, a short \
description, and estimated damage if stated. Use null for anything the text does not clearly \
state - never guess a policy number, date, or dollar amount.

2. If the submission includes attached invoice/bill documents or damage photos, look at each one \
and call record_attachment_review with your honest observation of what it actually shows and \
whether it's consistent with the narrative and the estimated damage - skip this tool entirely if \
no attachments were provided. A photo that shows different, less severe, or no visible damage than \
described, or an invoice whose total is far from the stated estimated_damage_usd, is grounds for a \
flag even if the text-only fields look otherwise clean. A claim with a high estimated damage \
(roughly above $10,000) and no supporting invoice or photo attached at all is itself worth a flag - \
missing evidence is a data point, not nothing.

3. If you extracted a policy_number, call check_policy_status (with the date of loss), then \
check_coverage and check_exclusions for the loss_type you extracted. These are your only source \
of truth about the policy - there is no policy data anywhere else in this conversation. If no \
policy_number was extracted, skip these lookups.

4. Decide:
   - "auto-approve intake": the policy is active on the date of loss, a coverage responds to the \
loss type, no exclusion matches, the extraction is complete and unambiguous, and the estimated \
damage (if stated) is not unusually high for the loss type.
   - "flag for adjuster review": the policy is lapsed, cancelled, or outside its term; an \
exclusion matches the loss type; no coverage responds to the loss type; the estimated damage is \
high (roughly above $25,000, or above a coverage's limit); the description is ambiguous about \
what actually happened or which loss type applies; or several smaller risk indicators are \
present together.
   - "request more info": you could not extract a policy number, a date of loss, or a usable loss \
type, so you have nothing to look up - or the description is too vague to classify the loss at \
all.

5. Call submit_decision last. Every entry in the `evidence` array must be copied directly from \
the `evidence` field of a tool result you actually received earlier in this conversation - never \
invent a citation, a rule_id, or a policy fact that didn't come back from a tool call. An \
attachment observation is not an `evidence` entry (that field is Atlas citations only) - it's \
already captured by record_attachment_review, so reflect it in `reasoning_summary` and in a `flag` \
if it raised a concern. Set flags for anything an adjuster should notice (missing fields, \
ambiguity, high value, a matched exclusion, a policy status problem, attachment evidence that \
doesn't line up), even on claims you're auto-approving.

Be decisive: don't call the same lookup twice for the same policy/loss_type pair, and don't call \
tools you don't need. If a policy number doesn't resolve (lookup_policy returns found: false), \
that alone is grounds for "flag for adjuster review"."""


class AgentRunState:
    """Accumulates everything a run produces, independent of the transport."""

    def __init__(self) -> None:
        self.extracted: ExtractedFields | None = None
        self.attachment_reviews: list[AttachmentReview] = []
        self.decision: Decision | None = None
        self.confidence: float | None = None
        self.reasoning_summary: str | None = None
        self.evidence: list[EvidenceCitation] = []
        self.flags: list[Flag] = []
        self.tool_calls: list[ToolCallRecord] = []
        self.done = False


def dispatch_tool(tool_name: str, tool_input: dict, state: AgentRunState) -> dict:
    """Execute one tool call against Atlas (or record a sink's payload)."""
    if tool_name == "record_extracted_fields":
        state.extracted = ExtractedFields(**tool_input)
        return {"recorded": True}
    if tool_name == "record_attachment_review":
        state.attachment_reviews = [AttachmentReview(**r) for r in tool_input["reviews"]]
        return {"recorded": True}
    if tool_name == "lookup_policy":
        return atlas_rules.get_policy(tool_input["policy_number"])
    if tool_name == "check_policy_status":
        return atlas_rules.check_policy_status(tool_input["policy_number"], tool_input["loss_date"])
    if tool_name == "check_coverage":
        return atlas_rules.check_coverage(tool_input["policy_number"], tool_input["loss_type"])
    if tool_name == "check_exclusions":
        return atlas_rules.check_exclusions(tool_input["policy_number"], tool_input["loss_type"])
    if tool_name == "submit_decision":
        state.decision = Decision(tool_input["decision"])
        state.confidence = tool_input["confidence"]
        state.reasoning_summary = tool_input["reasoning_summary"]
        state.evidence = [EvidenceCitation(**e) for e in tool_input["evidence"]]
        state.flags = [Flag(**f) for f in tool_input["flags"]]
        state.done = True
        return {"recorded": True}
    return {"error": f"Unknown tool '{tool_name}'"}


def _run_agent_loop(
    messages: list[dict],
    state: AgentRunState,
    model: str,
    client: anthropic.Anthropic,
) -> AgentRunState:
    """Drives tool_use <-> tool_result turns until submit_decision fires or
    MAX_TURNS is hit. Shared by process_claim (fresh extraction) and
    resume_claim (extraction already known - e.g. a policy number a reviewer
    attached after the fact)."""
    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break

        tool_results = []
        for block in tool_use_blocks:
            result = dispatch_tool(block.name, block.input, state)
            state.tool_calls.append(
                ToolCallRecord(tool_name=block.name, tool_input=block.input, tool_result=result)
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
            )

        messages.append({"role": "user", "content": tool_results})

        if state.done:
            break

    return state


def _load_attachment_content_blocks(attachments: list[dict]) -> list[dict]:
    """Turns saved attachment files into real multimodal content blocks - an
    image block for damage photos, a document block for invoice PDFs - each
    preceded by a small text label so the model can tie its
    record_attachment_review filenames back to the right block."""
    blocks: list[dict] = []
    for att in attachments:
        file_path = PROJECT_ROOT / att["path"]
        data = base64.standard_b64encode(file_path.read_bytes()).decode("ascii")
        blocks.append({"type": "text", "text": f"Attached {att['kind']} — filename: {att['filename']}"})
        if att["kind"] == "damage_photo":
            blocks.append(
                {"type": "image", "source": {"type": "base64", "media_type": att["content_type"], "data": data}}
            )
        else:
            blocks.append(
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
            )
    return blocks


def _build_trace(
    claim_id: str,
    submitted_text: str,
    state: AgentRunState,
    model: str,
    attachments: list[dict] | None = None,
) -> DecisionTrace:
    trace = DecisionTrace(
        claim_id=claim_id,
        submitted_text=submitted_text,
        extracted=state.extracted,
        decision=state.decision,
        confidence=state.confidence,
        reasoning_summary=state.reasoning_summary,
        evidence=state.evidence,
        flags=state.flags,
        attachments=[Attachment(**a) for a in (attachments or [])],
        attachment_reviews=state.attachment_reviews,
        tool_calls=state.tool_calls,
        model=model,
    )
    if not state.done:
        trace.error = "Agent did not call submit_decision within the turn limit."
    return trace


def process_claim(
    claim_id: str,
    submitted_text: str,
    attachments: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> DecisionTrace:
    """Run one claim through the Navigator loop and return its full trace.

    `attachments`, if given, is a list of dicts (filename, kind, content_type,
    path, size_bytes) for files already saved to disk under
    agent/data/attachments/{claim_id}/ - see dashboard/server.py's upload
    handling. Each is sent to Claude as real image/document content, not
    described in text.
    """
    client = client or anthropic.Anthropic()
    state = AgentRunState()
    content: list[dict] = [
        {"type": "text", "text": f"New FNOL submission (claim_id={claim_id}):\n\n{submitted_text}"}
    ]
    content.extend(_load_attachment_content_blocks(attachments or []))
    messages: list[dict] = [{"role": "user", "content": content}]
    state = _run_agent_loop(messages, state, model, client)
    return _build_trace(claim_id, submitted_text, state, model, attachments=attachments)


def resume_claim(
    claim_id: str,
    submitted_text: str,
    extracted: dict,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> DecisionTrace:
    """Resume a claim whose extracted fields are already known - typically
    because a reviewer attached a policy number found via Atlas search or a
    real out-of-band channel (a phone call, another internal system), not
    because the customer narrative itself changed. Skips
    record_extracted_fields entirely and goes straight to the Atlas lookup
    and decision steps, by seeding the conversation with that tool call
    already having "happened" with the known fields.
    """
    client = client or anthropic.Anthropic()
    state = AgentRunState()
    state.extracted = ExtractedFields(**extracted)

    seed_tool_use_id = "seeded_extraction"
    seed_result = {"recorded": True}
    state.tool_calls.append(
        ToolCallRecord(tool_name="record_extracted_fields", tool_input=extracted, tool_result=seed_result)
    )

    messages: list[dict] = [
        {"role": "user", "content": f"New FNOL submission (claim_id={claim_id}):\n\n{submitted_text}"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": seed_tool_use_id,
                    "name": "record_extracted_fields",
                    "input": extracted,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": seed_tool_use_id, "content": json.dumps(seed_result)}
            ],
        },
    ]
    state = _run_agent_loop(messages, state, model, client)
    return _build_trace(claim_id, submitted_text, state, model)


if __name__ == "__main__":
    # Offline plumbing check: exercises dispatch_tool against real Atlas data
    # with hand-built tool inputs, no Anthropic API call involved.
    state = AgentRunState()
    print(dispatch_tool("record_extracted_fields", {"description": "test", "policy_number": "POL-10234"}, state))
    print(dispatch_tool("lookup_policy", {"policy_number": "POL-10234"}, state))
    print(dispatch_tool("check_policy_status", {"policy_number": "POL-10234", "loss_date": "2026-05-01"}, state))
    print(dispatch_tool("check_coverage", {"policy_number": "POL-10234", "loss_type": "auto_collision"}, state))
    print(dispatch_tool("check_exclusions", {"policy_number": "POL-10234", "loss_type": "auto_collision"}, state))
    print(
        dispatch_tool(
            "submit_decision",
            {
                "decision": "auto-approve intake",
                "confidence": 0.9,
                "reasoning_summary": "test",
                "evidence": [],
                "flags": [],
            },
            state,
        )
    )
    print("state.decision =", state.decision, "| state.done =", state.done)
