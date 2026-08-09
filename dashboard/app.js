// Prism dashboard: list view + detail drill-down over Navigator decision traces.
// No build step, no framework - plain DOM manipulation over a small JSON array.

const LOW_CONFIDENCE_THRESHOLD = 0.7;

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

function renderList(traces, onSelect) {
  const listEl = document.getElementById("claim-list");
  const summaryEl = document.getElementById("list-summary");
  listEl.innerHTML = "";

  const flagged = traces.filter((t) => decisionClass(t.decision) === "critical").length;
  const lowConf = traces.filter((t) => t.confidence !== null && t.confidence !== undefined && t.confidence < LOW_CONFIDENCE_THRESHOLD).length;
  summaryEl.textContent = `${traces.length} claims · ${flagged} flagged for review · ${lowConf} low-confidence`;

  traces.forEach((trace) => {
    const cls = decisionClass(trace.decision);
    const extracted = trace.extracted || {};
    const name = extracted.policyholder_name || "(name not extracted)";
    const lossType = extracted.loss_type ? extracted.loss_type.replaceAll("_", " ") : "unclassified";

    const badges = [el("span", { class: `badge badge-${cls}` }, decisionLabel(trace.decision))];
    if (trace.confidence !== null && trace.confidence !== undefined && trace.confidence < LOW_CONFIDENCE_THRESHOLD) {
      badges.push(el("span", { class: "badge badge-low-confidence" }, "⚠ low confidence"));
    }

    const row = el(
      "div",
      { class: `claim-row decision-${cls}`, "data-claim-id": trace.claim_id },
      el(
        "div",
        { class: "claim-row-main" },
        el("div", { class: "claim-row-id" }, trace.claim_id),
        el("div", { class: "claim-row-sub" }, `${name} · ${lossType}`)
      ),
      el("div", {}, ...badges)
    );
    row.addEventListener("click", () => onSelect(trace, row));
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

function renderDetail(trace) {
  const pane = document.getElementById("detail-pane");
  pane.innerHTML = "";

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
      trace.confidence !== null && trace.confidence !== undefined
        ? el("span", { style: "margin-left:8px;font-size:12px;color:var(--text-muted)" }, `confidence ${trace.confidence.toFixed(2)}`)
        : null
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
  const listEl = document.getElementById("claim-list");

  if (traces.length === 0) {
    document.getElementById("list-summary").textContent = "No claims found.";
    listEl.innerHTML =
      '<div class="empty-state">No trace data yet. Run <code>python -m agent.run_batch</code> (needs ANTHROPIC_API_KEY), then reload.</div>';
    return;
  }

  let selectedRow = null;
  renderList(traces, (trace, row) => {
    if (selectedRow) selectedRow.classList.remove("selected");
    row.classList.add("selected");
    selectedRow = row;
    renderDetail(trace);
  });

  // Auto-select the first flagged claim if there is one, else the first claim,
  // so a reviewer's eye lands somewhere useful immediately.
  const firstFlagged = traces.find((t) => decisionClass(t.decision) === "critical");
  const initial = firstFlagged || traces[0];
  const initialRow = listEl.querySelector(`[data-claim-id="${CSS.escape(initial.claim_id)}"]`);
  if (initialRow) initialRow.click();
}

main();
