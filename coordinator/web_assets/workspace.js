"use strict";
const $ = (id) => document.getElementById(id);
const state = { csrf: null, project: null, editing: null };
const commandId = () => crypto.randomUUID();
function showError(error, login = false) {
  const element = $(login ? "login-error" : "workspace-error");
  element.textContent = error.message || "The request failed. Inspect the workspace and try again.";
  element.hidden = false;
}
function clearErrors() { $("login-error").hidden = true; $("workspace-error").hidden = true; }
async function api(path, method = "GET", body) {
  const headers = {};
  let pendingKey = null;
  if (body && body.command_id) {
    const intent = { ...body }; delete intent.command_id;
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${method}|${path}|${JSON.stringify(intent)}`));
    pendingKey = "orchestrator.pending." + Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join("");
    const existing = sessionStorage.getItem(pendingKey);
    if (existing) body.command_id = existing;
    else sessionStorage.setItem(pendingKey, body.command_id);
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.csrf && method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 401) setSignedIn(false);
    throw new Error(value.message || value.detail || "The request was refused. Refresh current state before retrying.");
  }
  if (pendingKey) sessionStorage.removeItem(pendingKey);
  return value;
}
function node(tag, value, className) { const element = document.createElement(tag); if (value !== undefined) element.textContent = value; if (className) element.className = className; return element; }
function setSignedIn(signedIn) { $("login-panel").hidden = signedIn; $("workspace").hidden = !signedIn; $("sign-out").hidden = !signedIn; if (!signedIn) { state.csrf = null; state.project = null; } }
async function busy(button, action) { clearErrors(); button.disabled = true; button.setAttribute("aria-busy", "true"); try { await action(); } catch (error) { showError(error, !state.csrf); } finally { button.disabled = false; button.removeAttribute("aria-busy"); } }
async function loadProjects() {
  const data = await api("/api/projects");
  const target = $("project-list"); target.replaceChildren();
  if (!data.projects.length) target.append(node("p", "No projects yet. Capture one to begin."));
  for (const project of data.projects) {
    const button = node("button", project.name, "project-choice");
    button.setAttribute("aria-current", String(state.project?.project.id === project.id));
    button.addEventListener("click", () => busy(button, () => selectProject(project.id)));
    target.append(button);
  }
}
async function selectProject(id) { state.project = await api(`/api/projects/${encodeURIComponent(id)}`); renderProject(); await loadProjects(); }
function renderDiscovery(project) {
  const target = $("discovery-turns");
  target.replaceChildren(node("h3", "Stored discovery"));
  const stored = (project.spec.context.discovery && project.spec.context.discovery.turns) || [];
  if (!stored.length) {
    target.append(node("p", "No stored discovery turns."));
    return;
  }
  for (const turn of stored) {
    const card = node("article", undefined, "task");
    card.append(node("p", `Revision ${turn.n}`, "eyebrow"), node("p", turn.question), node("p", turn.answer));
    target.append(card);
  }
}
function renderProject() {
  const data = state.project, project = data.project;
  state.editing = null;
  $("project-panel").hidden = false; $("empty-panel").hidden = true; $("create-panel").hidden = true;
  $("project-title").textContent = project.spec.name;
  $("project-state").textContent = project.paused ? "Paused" : "Planning workspace";
  $("project-goal-text").textContent = String(project.spec.context.goal || "Inspect the requirements and context below.");
  $("project-revision").textContent = `Requirements revision ${project.revision} · Project version ${project.version}`;
  $("project-context").textContent = JSON.stringify({ requirements: project.spec.requirements, context: project.spec.context }, null, 2);
  renderDiscovery(project);
  $("pause-project").hidden = Boolean(project.paused); $("resume-project").hidden = !project.paused;
  const plans = $("plans"); plans.replaceChildren();
  for (const plan of data.plans) {
    const milestone = data.milestones.find((m) => m.id === plan.milestone_id);
    const approved = milestone.approved_plan_id === plan.id;
    const card = node("article", undefined, "plan"); card.append(node("p", `${milestone.key} · Revision ${plan.revision}`, "eyebrow"), node("h3", plan.spec.title));
    card.append(node("p", approved ? (plan.spec.requirements_revision === project.revision ? "Approved intent" : "Earlier approval; requirements changed") : "Draft awaiting your decision", "badge"));
    const list = node("ul");
    for (const task of plan.spec.tasks) list.append(node("li", `${task.id}: ${task.title}. ${task.criteria.map((c) => c.description).join("; ")}. Attempt cap: ${task.max_attempts}.`));
    card.append(list);
    const detail = node("details"), summary = node("summary", "Inspect exact plan and digest"), pre = node("pre", JSON.stringify({ digest: plan.digest, spec: plan.spec }, null, 2)); detail.append(summary, pre); card.append(detail);
    if (!approved) {
      const button = node("button", "Approve this exact plan", "secondary");
      button.addEventListener("click", () => busy(button, async () => { await api(`/api/plans/${plan.id}/approve`, "POST", { command_id: commandId(), digest: plan.digest, expected_project_version: project.version, expected_milestone_version: milestone.version }); await selectProject(project.id); }));
      card.append(button);
    }
    plans.append(card);
  }
  const tasks = $("tasks"); tasks.replaceChildren();
  for (const milestone of data.milestones) {
    if (milestone.tasks.length) tasks.append(node("h3", `${milestone.key} task states`));
    for (const task of milestone.tasks) { const card = node("article", undefined, "task"); card.append(node("strong", `${task.id} · ${task.title}`), node("p", `${task.state.replaceAll("_", " ")} · ${task.attempts_consumed} of ${task.max_attempts} attempts consumed`)); tasks.append(card); }
  }
  renderOperator(data);
}
function renderOperator(data) {
  const units = $("cost-units");
  units.replaceChildren();
  for (const [key, label] of [["known_units", "Known units"], ["estimated_units", "Estimated units"], ["pending_units", "Pending units"], ["unknown_units", "Unknown units"]]) {
    units.append(node("dt", label), node("dd", String(data.cost[key])));
  }
  $("scripted-acceptance").textContent = data.scripted_task_accepted
    ? "One scripted integration recorded task acceptance."
    : "No scripted integration has recorded task acceptance.";
  $("capability-flags").textContent = `Task acceptance capability ${String(data.capabilities.task_acceptance)}. Live eligible ${String(data.live_eligible)}.`;
  const pending = $("pending-decisions");
  pending.replaceChildren(node("h3", "Pending decisions"));
  if (!data.pending_decisions.length) pending.append(node("p", "No pending decisions."));
  for (const decision of data.pending_decisions) pending.append(node("article", decision.summary, "task"));
  const reports = $("milestone-costs");
  reports.replaceChildren();
  for (const report of data.model_reports) {
    reports.append(node("p", `${report.milestone_id}: known ${report.known_units}, estimated ${report.estimated_units}, pending ${report.pending_units}, unknown ${report.unknown_units}`, "help"));
  }
}
$("login-form").addEventListener("submit", (event) => { event.preventDefault(); const button = event.submitter; busy(button, async () => { const result = await api("/api/session", "POST", { token: $("access-token").value }); $("access-token").value = ""; state.csrf = result.csrf; setSignedIn(true); await loadProjects(); }); });
$("sign-out").addEventListener("click", (event) => busy(event.currentTarget, async () => { await api("/api/logout", "POST", {}); setSignedIn(false); }));
$("show-create").addEventListener("click", () => { clearErrors(); state.editing = null; $("create-form").reset(); $("create-title").textContent = "Capture a project"; $("create-panel").hidden = false; $("empty-panel").hidden = true; $("project-name").focus(); });
$("refresh-project").addEventListener("click", (event) => busy(event.currentTarget, () => selectProject(state.project.project.id)));
$("revise-project").addEventListener("click", () => {
  clearErrors(); state.editing = state.project.project;
  const spec = state.editing.spec;
  $("project-name").value = spec.name; $("project-repository").value = spec.repository; $("project-goal").value = String(spec.context.goal || "");
  $("project-requirements").value = spec.requirements.map((r) => `${r.id}: ${r.text}`).join("\n");
  $("create-title").textContent = "Revise intent and pause execution";
  $("create-panel").hidden = false; $("project-name").focus();
});
$("cancel-create").addEventListener("click", () => { $("create-panel").hidden = true; $("empty-panel").hidden = Boolean(state.project); });
$("create-form").addEventListener("submit", (event) => { event.preventDefault(); busy(event.submitter, async () => {
  const requirements = $("project-requirements").value.split(/\r?\n/).filter((line) => line.trim()).map((line) => { const match = /^([A-Za-z0-9][A-Za-z0-9_-]{0,79}):\s*(.+)$/.exec(line.trim()); if (!match) throw new Error("Each requirement needs an identifier, a colon and an observable outcome."); return { id: match[1], text: match[2] }; });
  const editing = state.editing;
  const body = { command_id: commandId(), spec: { name: $("project-name").value, repository: $("project-repository").value, requirements, context: { ...(editing?.spec.context || {}), goal: $("project-goal").value } } };
  if (editing) body.expected_version = editing.version;
  const result = await api(editing ? `/api/projects/${editing.id}` : "/api/projects", editing ? "PUT" : "POST", body);
  $("create-form").reset(); await selectProject(result.project_id);
}); });
$("plan-form").addEventListener("submit", (event) => { event.preventDefault(); busy(event.submitter, async () => {
  const file = $("plan-file").files[0]; if (!file || file.size > 1048576) throw new Error("Choose a plan JSON file smaller than one MiB.");
  const spec = JSON.parse(await file.text()); const project = state.project.project;
  await api(`/api/projects/${project.id}/plans`, "POST", { command_id: commandId(), milestone_key: $("milestone-key").value, spec, expected_project_version: project.version });
  $("plan-file").value = ""; await selectProject(project.id);
}); });
for (const action of ["pause", "resume", "recover"]) $(action === "recover" ? "recover-project" : `${action}-project`).addEventListener("click", (event) => busy(event.currentTarget, async () => {
  const project = state.project.project, body = { command_id: commandId(), expected_version: project.version };
  if (action !== "resume") body.reason = action === "pause" ? "Paused by the local developer" : $("recovery-reason").value.trim();
  if (action === "recover" && !body.reason) throw new Error("Describe why the sender needs recovery.");
  await api(`/api/projects/${project.id}/${action}`, "POST", body); await selectProject(project.id);
}));
(async () => { try { const session = await api("/api/session"); state.csrf = session.csrf; setSignedIn(true); await loadProjects(); } catch { setSignedIn(false); } })();
