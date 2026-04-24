const eventList = document.getElementById("event-list");
const agentList = document.getElementById("agent-list");
const agentEmpty = document.getElementById("agent-empty");
const eventEmpty = document.getElementById("event-empty");
const sidebarStats = document.getElementById("sidebar-stats");
const showSelectedButton = document.getElementById("show-selected");
const showAllButton = document.getElementById("show-all");
const openCreateAgent = document.getElementById("open-create-agent");
const modal = document.getElementById("create-agent-modal");
const createAgentForm = document.getElementById("create-agent-form");
const createAgentError = document.getElementById("create-agent-error");
const interactionList = document.getElementById("interaction-list");
const terminalForm = document.getElementById("terminal-form");
const terminalInput = document.getElementById("terminal-input");

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatAgentTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function buildAgentRow(agent, isActive) {
  const row = document.createElement("div");
  row.setAttribute("role", "button");
  row.tabIndex = 0;
  row.className = "agent-row" + (isActive ? " is-active" : "");
  row.dataset.agentId = agent.agent_id;
  row.dataset.agentName = agent.name;
  row.dataset.agentRole = agent.role;
  const runtimeStatus = agent.runtime_status || "stopped";
  const btn = runtimeStatus === "running"
    ? `<button class="acp-btn acp-btn--stop" type="button" data-session-action="stop" data-agent-id="${agent.agent_id}">停止</button>`
    : `<button class="acp-btn acp-btn--start" type="button" data-session-action="start" data-agent-id="${agent.agent_id}">启动</button>`;
  row.innerHTML = `
    <div class="agent-row__top">
      <div>
        <strong>${escapeHtml(agent.name)}</strong>
        <p>${escapeHtml(agent.role)} · ${escapeHtml(agent.profile_name)}</p>
      </div>
      <span class="status-badge status-${escapeHtml(agent.status)}">${escapeHtml(agent.status)}</span>
    </div>
    <div class="agent-row__body">
      <div class="load-track"><span style="width: ${agent.load || 0}%"></span></div>
      <dl>
        <div><dt>Task</dt><dd>${escapeHtml(agent.current_task || "—")}</dd></div>
        <div><dt>Last Output</dt><dd>${escapeHtml(formatAgentTime(agent.last_output_at))}</dd></div>
        <div><dt>State</dt><dd>${escapeHtml(agent.interaction_state || "idle")}</dd></div>
        <div><dt>Queue</dt><dd>${agent.queue_depth || 0}</dd></div>
      </dl>
      <div class="agent-row__session">
        <span class="acp-dot acp-${runtimeStatus}"></span>
        <span class="acp-label">Session ${escapeHtml(runtimeStatus)}</span>
        ${btn}
      </div>
    </div>
  `;
  return row;
}

function buildInteractionCard(agent) {
  const interaction = agent.pending_interaction;
  if (!interaction) return "";
  const isApproval = interaction.kind === "awaiting_approval";
  return `
    <article class="interaction-card">
      <div class="interaction-card__head">
        <strong>${escapeHtml(agent.name)}</strong>
        <span>${escapeHtml(interaction.kind)}</span>
      </div>
      <p>${escapeHtml(interaction.prompt || "需要人工处理")}</p>
      ${
        isApproval
          ? `<div class="interaction-card__actions">
              <button class="primary-button primary-button--sm" type="button" data-interaction-response="y" data-agent-id="${agent.agent_id}" data-request-id="${interaction.request_id}">允许</button>
              <button class="filter-chip" type="button" data-interaction-response="n" data-agent-id="${agent.agent_id}" data-request-id="${interaction.request_id}">拒绝</button>
            </div>`
          : `<form class="interaction-form" data-agent-id="${agent.agent_id}" data-request-id="${interaction.request_id}">
              <input name="response" placeholder="输入回复后继续执行">
              <button class="primary-button primary-button--sm" type="submit">提交</button>
            </form>`
      }
    </article>
  `;
}

function renderInteractions(agents) {
  if (!interactionList) return;
  const html = agents
    .filter((agent) => agent.pending_interaction)
    .map((agent) => buildInteractionCard(agent))
    .join("");
  interactionList.innerHTML = html;
  interactionList.hidden = !html;
}

function renderAgents(agents, stats) {
  if (!agentList) return;
  const selected = eventList?.dataset.selectedAgent || (agents[0] && agents[0].agent_id) || "";
  agentList.innerHTML = "";
  agents.forEach((agent) => {
    agentList.appendChild(buildAgentRow(agent, agent.agent_id === selected));
  });
  renderInteractions(agents);
  if (agentEmpty) agentEmpty.hidden = agents.length > 0;
  if (sidebarStats && stats) {
    sidebarStats.innerHTML = stats
      .slice(0, 2)
      .map((s) => `<article class="mini-stat"><span>${escapeHtml(s.label)}</span><strong>${escapeHtml(s.value)}</strong></article>`)
      .join("");
  }
  if (agents.length > 0) {
    const active = agents.find((a) => a.agent_id === selected) || agents[0];
    setSelectedAgent(active.agent_id);
  } else {
    if (eventList) eventList.dataset.selectedAgent = "";
  }
}

function buildEventItem(event) {
  const item = document.createElement("article");
  item.className = "event-item";
  item.dataset.agentId = event.agent_id || "";
  item.dataset.eventType = event.event_type || "";
  item.textContent = cleanTerminalText((event.data && event.data.text) || "");
  return item;
}

function cleanTerminalText(text) {
  return String(text || "")
    .split("\n")
    .filter((line) => {
      const value = line.trim();
      if (!value) return true;
      if (/^[$⚕]?\s*gpt-[\w.-]+\s*\|.*\|\s*\[.*\]\s*\d+%/i.test(value)) return false;
      if (/\[\d+\s*q\s*\[\d+\s*q/.test(value)) return false;
      return true;
    })
    .join("\n")
    .trimEnd();
}

function removeAgentTerminalSnapshots(agentId) {
  if (!eventList || !agentId) return;
  eventList.querySelectorAll('.event-item[data-event-type="agent.terminal.snapshot"]').forEach((item) => {
    if (item.dataset.agentId !== agentId) return;
    item.remove();
  });
}

function applyEventFilter() {
  if (!eventList) return;
  const mode = eventList.dataset.filterMode || "selected";
  const selectedAgent = eventList.dataset.selectedAgent || "";
  const items = eventList.querySelectorAll(".event-item");
  let visibleCount = 0;
  items.forEach((item) => {
    const matches = item.dataset.agentId === selectedAgent;
    const hidden = mode === "selected" && !matches;
    item.classList.toggle("is-hidden", hidden);
    if (!hidden) visibleCount += 1;
  });
  if (eventEmpty) eventEmpty.hidden = visibleCount > 0;
}

function hydrateTerminalSnapshots() {
  if (!eventList) return;
  eventList.querySelectorAll(".event-item").forEach((item) => {
    if (item.dataset.eventType !== "agent.terminal.snapshot") {
      item.remove();
      return;
    }
    item.textContent = cleanTerminalText(item.textContent || "");
  });
}

function prependEvent(event) {
  if (!eventList) return;
  if (event.event_type !== "agent.terminal.snapshot") return;
  removeAgentTerminalSnapshots(event.agent_id || "");
  eventList.append(buildEventItem(event));
  while (eventList.children.length > 40) {
    eventList.firstElementChild.remove();
  }
  applyEventFilter();
  eventList.scrollTop = eventList.scrollHeight;
}

function setSelectedAgent(agentId, agentName) {
  if (!agentList || !eventList) return;
  const row = agentList.querySelector(`.agent-row[data-agent-id="${CSS.escape(agentId)}"]`);
  const name = agentName || row?.dataset.agentName || agentId || "尚未选择";
  agentList.querySelectorAll(".agent-row").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.agentId === agentId);
  });
  eventList.dataset.selectedAgent = agentId;
  if (terminalInput) terminalInput.placeholder = agentId ? `发送到 ${name} 的终端，Enter 提交` : "请选择 Agent";
  applyEventFilter();
}

async function sendTerminalInput(text) {
  const agentId = eventList?.dataset.selectedAgent || "";
  if (!agentId || !text) return false;
  const response = await fetch(`/api/agents/${agentId}/terminal-input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return response.ok;
}

async function postInteractionResponse(agentId, requestId, response) {
  await fetch(`/api/agents/${agentId}/interactions/${requestId}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ response }),
  });
}

if (agentList) {
  agentList.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-session-action]");
    if (btn) {
      event.stopPropagation();
      const action = btn.dataset.sessionAction;
      const agentId = btn.dataset.agentId;
      btn.disabled = true;
      fetch(`/api/agents/${agentId}/${action}`, { method: "POST" })
        .catch(() => {})
        .finally(() => { btn.disabled = false; });
      return;
    }
    const row = event.target.closest(".agent-row");
    if (!row) return;
    setSelectedAgent(row.dataset.agentId, row.dataset.agentName);
  });
}

if (interactionList) {
  interactionList.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-interaction-response]");
    if (!btn) return;
    btn.disabled = true;
    await postInteractionResponse(
      btn.dataset.agentId,
      btn.dataset.requestId,
      btn.dataset.interactionResponse,
    ).finally(() => { btn.disabled = false; });
  });

  interactionList.addEventListener("submit", async (event) => {
    const form = event.target.closest(".interaction-form");
    if (!form) return;
    event.preventDefault();
    const input = form.querySelector('input[name="response"]');
    const response = String(input?.value || "").trim();
    if (!response) return;
    await postInteractionResponse(form.dataset.agentId, form.dataset.requestId, response);
  });
}

if (showSelectedButton && showAllButton && eventList) {
  showSelectedButton.addEventListener("click", () => {
    eventList.dataset.filterMode = "selected";
    showSelectedButton.classList.add("is-active");
    showAllButton.classList.remove("is-active");
    applyEventFilter();
  });
  showAllButton.addEventListener("click", () => {
    eventList.dataset.filterMode = "all";
    showAllButton.classList.add("is-active");
    showSelectedButton.classList.remove("is-active");
    applyEventFilter();
  });
}

if (terminalForm && terminalInput) {
  terminalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = terminalInput.value.trim();
    if (!text) return;
    terminalInput.disabled = true;
    try {
      const ok = await sendTerminalInput(text);
      if (ok) terminalInput.value = "";
    } finally {
      terminalInput.disabled = false;
      terminalInput.focus();
    }
  });
}

function openModal() {
  if (!modal) return;
  modal.hidden = false;
  if (createAgentError) {
    createAgentError.hidden = true;
    createAgentError.textContent = "";
  }
  createAgentForm?.querySelector('input[name="name"]').focus();
}

function closeModal() {
  if (!modal) return;
  modal.hidden = true;
  createAgentForm?.reset();
}

if (openCreateAgent) openCreateAgent.addEventListener("click", openModal);
if (modal) {
  modal.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeModal !== undefined) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
}

if (createAgentForm) {
  createAgentForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(createAgentForm);
    const payload = {
      name: formData.get("name"),
      profile_name: formData.get("profile_name"),
      role: formData.get("role"),
      description: formData.get("description"),
    };
    const submitBtn = createAgentForm.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
      const response = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        if (createAgentError) {
          createAgentError.textContent = data.error || "创建失败";
          createAgentError.hidden = false;
        }
        return;
      }
      closeModal();
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

const stream = new EventSource("/api/events/stream");
stream.addEventListener("event", (event) => {
  const payload = JSON.parse(event.data);
  prependEvent(payload);
});
stream.addEventListener("agents", (event) => {
  const payload = JSON.parse(event.data);
  renderAgents(payload.agents || [], payload.stats || []);
});
stream.onmessage = (event) => {
  try {
    const payload = JSON.parse(event.data);
    if (payload && payload.event_type) prependEvent(payload);
  } catch (e) {
    /* ignore */
  }
};

hydrateTerminalSnapshots();
applyEventFilter();
