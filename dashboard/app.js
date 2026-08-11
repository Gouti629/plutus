// Prism dashboard: list view + detail drill-down over Navigator decision traces.
// No build step, no framework - plain DOM manipulation over a small JSON array.

const LOW_CONFIDENCE_THRESHOLD = 0.7;

const DECISION_FILTERS = [
  { key: "all", label: "All", cls: "all" },
  { key: "auto-approve intake", label: "Auto-approved", cls: "good" },
  { key: "flag for adjuster review", label: "Flagged", cls: "critical" },
  { key: "request more info", label: "Request info", cls: "warning" },
];

function decisionClass(decision) {
  if (decision === "auto-approve intake") return "good";
  if (decision === "request more info") return "warning";
  if (decision === "flag for adjuster review") return "critical";
  return "warning"; // error / missing decision reads as needing attention
}

function decisionLabel(decision) {
  return decision || "no decision (error)";
}

function fmtMoney(v) {
  if (v === null || v === undefined) return null;
  return "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function isLowConfidence(trace) {
  return trace.confidence !== null && trace.confidence !== undefined && trace.confidence < LOW_CONFIDENCE_THRESHOLD;
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function confidenceMeter(confidence) {
  const pct = Math.max(0, Math.min(100, Math.round(confidence * 100)));
  const low = confidence < LOW_CONFIDENCE_THRESHOLD;
  return el(
    "span",
    { class: "confidence-meter" },
    el(
      "span",
      { class: "confidence-track" },
      el("span", { class: `confidence-fill ${low ? "low" : ""}`, style: `width:${pct}%` })
    ),
    el("span", { class: "confidence-label" }, confidence.toFixed(2))
  );
}

async function loadTraces() {
  try {
    const res = await fetch("/api/claims");
    if (res.ok) return await res.json();
  } catch (e) {
    // Not served via dashboard/server.py - fall through to the static bundle.
  }
  if (typeof FNOL_TRACES !== "undefined") return FNOL_TRACES;
  return [];
}

function applyFilters(traces, state) {
  return traces.filter((t) => {
    if (state.decision !== "all" && t.decision !== state.decision) return false;
    if (state.lowConfidenceOnly && !isLowConfidence(t)) return false;
    return true;
  });
}

function renderFilters(traces, state, onChange) {
  const container = document.getElementById("list-filters");
  container.innerHTML = "";

  DECISION_FILTERS.forEach((f) => {
    const count = f.key === "all" ? traces.length : traces.filter((t) => t.decision === f.key).length;
    const pressed = state.decision === f.key;
    const tile = el(
      "button",
      { type: "button", class: `filter-tile filter-tile--${f.cls}`, "aria-pressed": pressed },
      el("span", { class: "filter-count" }, String(count)),
      el("span", { class: "filter-label" }, f.label)
    );
    tile.addEventListener("click", () => onChange({ ...state, decision: f.key }));
    container.appendChild(tile);
  });

  const lowConfCount = traces.filter(isLowConfidence).length;
  const lowConfTile = el(
    "button",
    { type: "button", class: "filter-tile filter-tile--lowconf", "aria-pressed": state.lowConfidenceOnly },
    el("span", { class: "filter-count" }, String(lowConfCount)),
    el("span", { class: "filter-label" }, "Low confidence")
  );
  lowConfTile.addEventListener("click", () => onChange({ ...state, lowConfidenceOnly: !state.lowConfidenceOnly }));
  container.appendChild(lowConfTile);
}

function renderList(traces, onSelect, selectedClaimId) {
  const listEl = document.getElementById("claim-list");
  listEl.innerHTML = "";

  if (traces.length === 0) {
    listEl.appendChild(el("div", { class: "empty-state" }, "No claims match this filter."));
    return;
  }

  traces.forEach((trace) => {
    const cls = decisionClass(trace.decision);
    const extracted = trace.extracted || {};
    const name = extracted.policyholder_name || "(name not extracted)";
    const lossType = extracted.loss_type ? extracted.loss_type.replaceAll("_", " ") : "unclassified";

    const badges = [el("span", { class: `badge badge-${cls}` }, decisionLabel(trace.decision))];
    if (isLowConfidence(trace)) {
      badges.push(el("span", { class: "badge badge-low-confidence" }, "⚠ low confidence"));
    }

    const selected = trace.claim_id === selectedClaimId;
    const row = el(
      "div",
      {
        class: `claim-row decision-${cls}${selected ? " selected" : ""}`,
        "data-claim-id": trace.claim_id,
        tabindex: "0",
        role: "button",
        "aria-label": `${trace.claim_id}: ${name}, ${lossType}, ${decisionLabel(trace.decision)}`,
      },
      el(
        "div",
        { class: "claim-row-main" },
        el("div", { class: "claim-row-id" }, trace.claim_id),
        el("div", { class: "claim-row-sub" }, `${name} · ${lossType}`)
      ),
      el("div", {}, ...badges)
    );
    row.addEventListener("click", () => onSelect(trace));
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onSelect(trace);
      }
    });
    listEl.appendChild(row);
  });
}

function fieldBlock(label, value) {
  const missing = value === null || value === undefined || value === "";
  return el(
    "div",
    { class: "field" },
    el("div", { class: "field-label" }, label),
    el("div", { class: `field-value ${missing ? "missing" : ""}` }, missing ? "not extracted" : String(value))
  );
}

function renderFollowUp(trace, onReprocessed) {
  const textarea = el("textarea", { class: "followup-textarea", rows: "4" });
  textarea.value = trace.submitted_text;

  const status = el("div", { class: "followup-status" });
  const btn = el("button", { class: "followup-btn", type: "button" }, "Re-run extraction & decision");

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Re-running…";
    status.className = "followup-status";
    status.textContent = "";
    try {
      const res = await fetch("/api/claims/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ claim_id: trace.claim_id, submitted_text: textarea.value }),
      });
      if (!res.ok) throw new Error(`server returned ${res.status}`);
      const updated = await res.json();
      updated.edge_case = trace.edge_case;
      status.textContent = `Updated: ${decisionLabel(updated.decision)}${
        updated.confidence !== null && updated.confidence !== undefined ? ` (confidence ${updated.confidence.toFixed(2)})` : ""
      }`;
      status.classList.add("ok");
      if (onReprocessed) onReprocessed(updated);
    } catch (e) {
      status.textContent =
        "Couldn't reach the live agent. This only works when served via `dashboard/server.py` with ANTHROPIC_API_KEY set - not on a static hosted snapshot.";
      status.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Re-run extraction & decision";
    }
  });

  return el(
    "section",
    { class: "block followup" },
    el("h3", {}, "Missing policy number"),
    el(
      "p",
      { class: "followup-hint" },
      "The agent couldn't extract a policy number from this narrative, so it can't be matched to a policy. Add it below (or edit the narrative directly) and re-run."
    ),
    textarea,
    el("div", { class: "followup-actions" }, btn, status)
  );
}

function renderDetail(trace, { onReprocessed } = {}) {
  const pane = document.getElementById("detail-pane");
  pane.innerHTML = "";

  const backBtn = el("button", { class: "back-btn", type: "button" }, "← Back to claims");
  backBtn.addEventListener("click", () => {
    document.body.classList.remove("showing-detail");
  });
  pane.appendChild(backBtn);

  const extracted = trace.extracted || {};
  const cls = decisionClass(trace.decision);

  const header = el(
    "div",
    { class: "detail-header" },
    el(
      "div",
      {},
      el("h2", {}, trace.claim_id),
      trace.edge_case ? el("div", { class: "edge-case" }, trace.edge_case) : null
    ),
    el(
      "div",
      {},
      el("span", { class: `badge badge-${cls}` }, decisionLabel(trace.decision)),
      trace.confidence !== null && trace.confidence !== undefined ? confidenceMeter(trace.confidence) : null
    )
  );
  pane.appendChild(header);

  if (trace.error) {
    pane.appendChild(
      el(
        "section",
        { class: "block" },
        el("h3", {}, "Error"),
        el("div", { class: "reasoning" }, trace.error)
      )
    );
  }

  pane.appendChild(
    el(
      "section",
      { class: "block" },
      el("h3", {}, "Original submission"),
      el("div", { class: "submitted-text" }, trace.submitted_text)
    )
  );

  pane.appendChild(
    el(
      "section",
      { class: "block" },
      el("h3", {}, "Extracted fields"),
      el(
        "div",
        { class: "field-grid" },
        fieldBlock("Policyholder", extracted.policyholder_name),
        fieldBlock("Policy number", extracted.policy_number),
        fieldBlock("Date of loss", extracted.date_of_loss),
        fieldBlock("Time of loss", extracted.time_of_loss),
        fieldBlock("Loss type", extracted.loss_type),
        fieldBlock("Location", extracted.location),
        fieldBlock("Estimated damage", fmtMoney(extracted.estimated_damage_usd))
      )
    )
  );

  if (!extracted.policy_number) {
    pane.appendChild(renderFollowUp(trace, onReprocessed));
  }

  if (trace.reasoning_summary) {
    pane.appendChild(
      el(
        "section",
        { class: "block" },
        el("h3", {}, "Reasoning summary"),
        el("div", { class: "reasoning" }, trace.reasoning_summary)
      )
    );
  }

  const evidenceItems = (trace.evidence || []).map((e) =>
    el(
      "div",
      { class: "evidence-item" },
      el("div", { class: "source" }, e.source + (e.rule_id ? ` (${e.rule_id})` : "")),
      el("div", {}, e.text)
    )
  );
  pane.appendChild(
    el(
      "section",
      { class: "block" },
      el("h3", {}, `Policy evidence cited (${evidenceItems.length})`),
      evidenceItems.length ? el("div", {}, evidenceItems) : el("div", { class: "reasoning" }, "No evidence cited.")
    )
  );

  const flagItems = (trace.flags || []).map((f) =>
    el(
      "div",
      { class: `flag-item badge-${f.severity === "critical" ? "critical" : f.severity === "warning" ? "warning" : "good"}` },
      el("div", { class: "code" }, `${f.code} · ${f.severity}`),
      el("div", {}, f.message)
    )
  );
  pane.appendChild(
    el(
      "section",
      { class: "block" },
      el("h3", {}, `Flags raised (${flagItems.length})`),
      flagItems.length ? el("div", {}, flagItems) : el("div", { class: "reasoning" }, "No flags raised.")
    )
  );

  const toolCalls = (trace.tool_calls || []).map((tc) =>
    el(
      "details",
      { class: "tool-call" },
      el("summary", {}, tc.tool_name),
      el(
        "pre",
        {},
        "input:  " + JSON.stringify(tc.tool_input) + "\n\nresult: " + JSON.stringify(tc.tool_result, null, 2)
      )
    )
  );
  pane.appendChild(
    el(
      "section",
      { class: "block" },
      el("h3", {}, `Full tool-call trace (${toolCalls.length})`),
      toolCalls.length ? el("div", {}, toolCalls) : el("div", { class: "reasoning" }, "No tool calls recorded.")
    )
  );

  if (typeof trace.latency_seconds === "number" || trace.model) {
    pane.appendChild(
      el(
        "section",
        { class: "block" },
        el("h3", {}, "Run metadata"),
        el(
          "div",
          { class: "field-grid" },
          fieldBlock("Model", trace.model),
          fieldBlock("Latency (s)", trace.latency_seconds)
        )
      )
    );
  }
}

async function main() {
  const traces = await loadTraces();
  const filtersEl = document.getElementById("list-filters");
  const listEl = document.getElementById("claim-list");

  if (traces.length === 0) {
    filtersEl.innerHTML = "";
    listEl.innerHTML =
      '<div class="empty-state">No trace data yet. Run <code>python -m agent.run_batch</code> (needs ANTHROPIC_API_KEY), then reload.</div>';
    return;
  }

  const state = { decision: "all", lowConfidenceOnly: false, selectedClaimId: null };

  function selectClaim(trace) {
    state.selectedClaimId = trace.claim_id;
    renderDetail(trace, { onReprocessed: handleReprocessed });
    document.body.classList.add("showing-detail");
    render();
  }

  function handleReprocessed(updated) {
    const idx = traces.findIndex((t) => t.claim_id === updated.claim_id);
    if (idx !== -1) traces[idx] = updated;
    renderDetail(updated, { onReprocessed: handleReprocessed });
    render();
  }

  function render() {
    renderFilters(traces, state, (patch) => {
      Object.assign(state, patch);
      render();
    });
    renderList(applyFilters(traces, state), selectClaim, state.selectedClaimId);
  }

  // Land on the first claim in the list (claim-001), not an auto-picked
  // "most interesting" one - predictable beats clever here.
  selectClaim(traces[0]);
}

main();
