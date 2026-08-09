"""Citation-bearing query functions over the Atlas graph.

These are the functions the FNOL agent calls as tools. Every result carries
an `evidence` object that points at a specific field in atlas/data/policies.json
(via a `source` path and a `rule_id`) rather than prose the model generated —
that's what makes the agent's citations checkable against ground truth.
"""

from __future__ import annotations

from datetime import date, datetime

from atlas.models import COVERAGE_LOSS_TYPE_MAP, PolicyRecord
from atlas.store import get_store


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def get_policy(policy_number: str) -> dict:
    """Look up a policy by number. Returns a plain summary dict, or an error."""
    policy = get_store().get_policy(policy_number)
    if policy is None:
        return {
            "found": False,
            "error": f"No policy on file with number '{policy_number}'.",
        }
    return {
        "found": True,
        "policy_number": policy.policy_number,
        "policyholder_name": policy.policyholder_name,
        "policy_type": policy.policy_type,
        "status": policy.status,
        "effective_date": policy.effective_date,
        "expiration_date": policy.expiration_date,
        "coverages": [
            {"coverage_type": c.coverage_type, "limit": c.limit, "deductible": c.deductible}
            for c in policy.coverages
        ],
        "evidence": {
            "source": f"policy:{policy.policy_number}",
            "text": f"{policy.policyholder_name}'s {policy.policy_type} policy {policy.policy_number}, "
            f"status={policy.status}, effective {policy.effective_date} to {policy.expiration_date}.",
        },
    }


def check_policy_status(policy_number: str, loss_date: str) -> dict:
    """Was the policy active on the date of loss? loss_date is 'YYYY-MM-DD'."""
    policy = get_store().get_policy(policy_number)
    if policy is None:
        return {"active": False, "reason": f"No policy on file with number '{policy_number}'."}

    try:
        loss_dt = _parse_date(loss_date)
    except ValueError:
        return {"active": False, "reason": f"Could not parse loss_date '{loss_date}' as YYYY-MM-DD."}

    eff = _parse_date(policy.effective_date)
    exp = _parse_date(policy.expiration_date)

    evidence = {
        "source": f"policy:{policy.policy_number}.status",
        "text": f"Policy status is '{policy.status}'; term {policy.effective_date} to {policy.expiration_date}.",
    }

    if policy.status == "cancelled":
        cancel_dt = _parse_date(policy.cancellation_date) if policy.cancellation_date else None
        if cancel_dt and loss_dt >= cancel_dt:
            return {
                "active": False,
                "reason": f"Policy was cancelled on {policy.cancellation_date}"
                + (f" ({policy.cancellation_reason})" if policy.cancellation_reason else "")
                + f", before the loss date {loss_date}.",
                "evidence": evidence,
            }
    if loss_dt < eff:
        return {
            "active": False,
            "reason": f"Loss date {loss_date} is before the policy's effective date {policy.effective_date}.",
            "evidence": evidence,
        }
    if loss_dt > exp:
        return {
            "active": False,
            "reason": f"Loss date {loss_date} is after the policy's expiration date {policy.expiration_date} "
            f"(policy status on file: '{policy.status}').",
            "evidence": evidence,
        }
    if policy.status == "lapsed":
        return {
            "active": False,
            "reason": "Policy is marked lapsed on file even though the loss date falls within the nominal term.",
            "evidence": evidence,
        }
    return {"active": True, "reason": "Policy was in force on the loss date.", "evidence": evidence}


def check_coverage(policy_number: str, loss_type: str) -> dict:
    """Does any coverage on this policy respond to the given loss_type?"""
    policy = get_store().get_policy(policy_number)
    if policy is None:
        return {"covered": False, "reason": f"No policy on file with number '{policy_number}'."}

    for idx, cov in enumerate(policy.coverages):
        if loss_type in COVERAGE_LOSS_TYPE_MAP.get(cov.coverage_type, []):
            return {
                "covered": True,
                "coverage_type": cov.coverage_type,
                "limit": cov.limit,
                "deductible": cov.deductible,
                "evidence": {
                    "source": f"policy:{policy.policy_number}.coverages[{idx}]",
                    "rule_id": cov.coverage_id,
                    "text": f"{cov.coverage_type} coverage, limit ${cov.limit:,.0f}, "
                    f"deductible ${cov.deductible:,.0f}, responds to '{loss_type}' losses.",
                },
            }

    held = [c.coverage_type for c in policy.coverages]
    return {
        "covered": False,
        "reason": f"No coverage on this policy responds to loss_type '{loss_type}'. "
        f"Coverages on file: {', '.join(held) if held else 'none'}.",
        "evidence": {
            "source": f"policy:{policy.policy_number}.coverages",
            "text": f"Policy {policy.policy_number} carries: {', '.join(held) if held else 'no coverages'}.",
        },
    }


def check_exclusions(policy_number: str, loss_type: str) -> dict:
    """Do any exclusions on this policy apply to the given loss_type?"""
    policy = get_store().get_policy(policy_number)
    if policy is None:
        return {"excluded": False, "matches": []}

    matches = []
    for idx, excl in enumerate(policy.exclusions):
        if loss_type in excl.applies_to:
            matches.append(
                {
                    "exclusion_id": excl.exclusion_id,
                    "description": excl.description,
                    "evidence": {
                        "source": f"policy:{policy.policy_number}.exclusions[{idx}]",
                        "rule_id": excl.exclusion_id,
                        "text": excl.description,
                    },
                }
            )

    return {"excluded": len(matches) > 0, "matches": matches}
