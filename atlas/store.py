"""Loads atlas/data/policies.json into a small networkx knowledge graph.

This is Atlas: the semantic layer the Navigator agent grounds its reasoning
in. It is deliberately small and explicit (a handful of policies, coverages,
and exclusions) rather than a full production knowledge graph, but the shape
is the same one a larger system would use: entities as nodes, relationships
as typed edges, and every fact traceable back to a specific record.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from atlas.models import COVERAGE_LOSS_TYPE_MAP, PolicyRecord

DATA_PATH = Path(__file__).parent / "data" / "policies.json"


class AtlasStore:
    """Holds the loaded policy records and the graph built from them."""

    def __init__(self, data_path: Path = DATA_PATH):
        raw = json.loads(data_path.read_text())
        self.policies: dict[str, PolicyRecord] = {
            d["policy_number"]: PolicyRecord.from_dict(d) for d in raw
        }
        self.graph = self._build_graph()

    def _build_graph(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for policy in self.policies.values():
            policy_node = f"policy:{policy.policy_number}"
            g.add_node(policy_node, type="Policy", record=policy)

            for cov in policy.coverages:
                cov_node = f"coverage:{policy.policy_number}:{cov.coverage_id}"
                g.add_node(cov_node, type="Coverage", record=cov)
                g.add_edge(policy_node, cov_node, relation="HAS_COVERAGE")

            for excl in policy.exclusions:
                excl_node = f"exclusion:{policy.policy_number}:{excl.exclusion_id}"
                g.add_node(excl_node, type="Exclusion", record=excl)
                g.add_edge(policy_node, excl_node, relation="HAS_EXCLUSION")

                # Link each exclusion to the coverages it can knock out, so a
                # graph walk from a coverage node reaches the exclusions that
                # constrain it — not just a flat list per policy.
                for cov in policy.coverages:
                    covered_loss_types = COVERAGE_LOSS_TYPE_MAP.get(cov.coverage_type, [])
                    if set(excl.applies_to) & set(covered_loss_types):
                        cov_node = f"coverage:{policy.policy_number}:{cov.coverage_id}"
                        g.add_edge(cov_node, excl_node, relation="EXCLUDED_BY")

        return g

    def get_policy(self, policy_number: str) -> PolicyRecord | None:
        return self.policies.get(policy_number)


_store: AtlasStore | None = None


def get_store() -> AtlasStore:
    global _store
    if _store is None:
        _store = AtlasStore()
    return _store


if __name__ == "__main__":
    # Smoke test: build the graph and print a summary, no API key needed.
    store = get_store()
    print(f"Loaded {len(store.policies)} policies")
    print(f"Graph: {store.graph.number_of_nodes()} nodes, {store.graph.number_of_edges()} edges")
    for policy_number, policy in store.policies.items():
        cov_count = sum(1 for _, _, d in store.graph.out_edges(f"policy:{policy_number}", data=True) if d["relation"] == "HAS_COVERAGE")
        excl_count = sum(1 for _, _, d in store.graph.out_edges(f"policy:{policy_number}", data=True) if d["relation"] == "HAS_EXCLUSION")
        print(f"  {policy_number} ({policy.policy_type}, {policy.status}): {cov_count} coverages, {excl_count} exclusions")
