"""The FNOL Navigator agent: extraction -> Atlas grounding -> decision.

Core loop: send the claim narrative + tool definitions to Claude, dispatch
each tool_use block Claude emits (record_extracted_fields / lookup_policy /
check_policy_status / check_coverage / check_exclusions / submit_decision),
feed the results back, and repeat until Claude calls submit_decision or we
hit a turn cap. The full sequence of tool calls *is* the decision trace -
there's no separate step where we ask the model to summarize what it did.
"""

from __future__ import annotations

import json
import os

import anthropic

from agent.schemas import Decision, DecisionTrace, EvidenceCitation, ExtractedFields, Flag, ToolCallRecord
from agent.tools import ALL_TOOLS
from atlas import rules as atlas_rules

DEFAULT_MODEL = os.environ.get("NAVIGATOR_MODEL", "claude-sonnet-4-5")
MAX_TURNS = 8

SYSTEM_PROMPT = """You are Navigator, an intake triage agent for First Notice of Loss (FNOL) \
submissions in P&C insurance claims. You read a policyholder's claim narrative and turn it into \
a structured, policy-grounded intake decision.

For each submission:

1. Call record_extracted_fields first, with everything you can confidently extract from the raw \
text: policyholder name, policy number, date/time of loss, loss type, location, a short \
description, and estimated damage if stated. Use null for anything the text does not clearly \
state - never guess a policy number, date, or dollar amount.

2. If you extracted a policy_number, call check_policy_status (with the date of loss), then \
check_coverage and check_exclusions for the loss_type you extracted. These are your only source \
of truth about the policy - there is no policy data anywhere else in this conversation. If no \
policy_number was extracted, skip these lookups.

3. Decide:
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

4. Call submit_decision last. Every entry in the `evidence` array must be copied directly from \
the `evidence` field of a tool result you actually received earlier in this conversation - never \
invent a citation, a rule_id, or a policy fact that didn't come back from a tool call. Set flags \
for anything an adjuster should notice (missing fields, ambiguity, high value, a matched \
exclusion, a policy status problem), even on claims you're auto-approving.

Be decisive: don't call the same lookup twice for the same policy/loss_type pair, and don't call \
tools you don't need. If a policy number doesn't resolve (lookup_policy returns found: false), \
that alone is grounds for "flag for adjuster review"."""


class AgentRunState:
    """Accumulates everything a run produces, independent of the transport."""

    def __init__(self) -> None:
        self.extracted: ExtractedFields | None = None
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


def _build_trace(claim_id: str, submitted_text: str, state: AgentRunState, model: str) -> DecisionTrace:
    trace = DecisionTrace(
        claim_id=claim_id,
        submitted_text=submitted_text,
        extracted=state.extracted,
        decision=state.decision,
        confidence=state.confidence,
        reasoning_summary=state.reasoning_summary,
        evidence=state.evidence,
        flags=state.flags,
        tool_calls=state.tool_calls,
        model=model,
    )
    if not state.done:
        trace.error = "Agent did not call submit_decision within the turn limit."
    return trace


def process_claim(
    claim_id: str,
    submitted_text: str,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> DecisionTrace:
    """Run one claim through the Navigator loop and return its full trace."""
    client = client or anthropic.Anthropic()
    state = AgentRunState()
    messages: list[dict] = [
        {"role": "user", "content": f"New FNOL submission (claim_id={claim_id}):\n\n{submitted_text}"}
    ]
    state = _run_agent_loop(messages, state, model, client)
    return _build_trace(claim_id, submitted_text, state, model)


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
