const eventList = document.getElementById("event-list");
const agentList = document.getElementById("agent-list");
const agentEmpty = document.getElementById("agent-empty");
const eventEmpty = document.getElementById("event-empty");
const sidebarStats = document.getElementById("sidebar-stats");
const messageForm = document.getElementById("message-form");
const toAgentIdInput = document.getElementById("to-agent-id");
const selectedAgentLabel = document.getElementById("selected-agent-label");
const showSelectedButton = document.getElementById("show-selected");
const showAllButton = document.getElementById("show-all");
const openCreateAgent = document.getElementById("open-create-agent");
const modal = document.getElementById("create-agent-modal");
const createAgentForm = document.getElementById("create-agent-form");
const createAgentError = document.getElementById("create-agent-error");

function buildAgentRow(agent, isActive) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "agent-row" + (isActive ? " is-active" : "");
  row.dataset.agentId = agent.agent_id;
  row.dataset.agentName = agent.name;
  row.innerHTML = `
    <div class="agent-row__top">
      <div>
        <strong>${agent.name}</strong>
        <p>${agent.role} · ${agent.profile_name}</p>
      </div>
      <span class="status-badge status-${agent.status}">${agent.status}</span>
    </div>
    <div class="agent-row__body">
      <div class="load-track"><span style="width: ${agent.load || 0}%"></span></div>
      <dl>
        <div><dt>Task</dt><dd>${agent.current_task || "—"}</dd></div>
        <div><dt>Output</dt><dd>${agent.last_output || "—"}</dd></div>
      </dl>
    </div>
  `;
  return row;
}

function renderAgents(agents, stats) {
  if (!agentList) return;
  const selected = eventList?.dataset.selectedAgent || (agents[0] && agents[0].agent_id) || "";
  agentList.innerHTML = "";
  agents.forEach((agent) => {
    agentList.appendChild(buildAgentRow(agent, agent.agent_id === selected));
  });
  if (agentEmpty) agentEmpty.hidden = agents.length > 0;
  if (sidebarStats && stats) {
    sidebarStats.innerHTML = stats
      .slice(0, 2)
      .map((s) => `<article class="mini-stat"><span>${s.label}</span><strong>${s.value}</strong></article>`)
      .join("");
  }
  if (agents.length > 0) {
    const active = agents.find((a) => a.agent_id === selected) || agents[0];
    setSelectedAgent(active.agent_id, active.name);
  } else {
    if (toAgentIdInput) toAgentIdInput.value = "";
    if (selectedAgentLabel) selectedAgentLabel.textContent = "target · 尚未选择";
    if (eventList) eventList.dataset.selectedAgent = "";
  }
}

function buildEventItem(event) {
  const item = document.createElement("article");
  item.className = "event-item";
  item.dataset.agentId = event.agent_id || "";
  item.innerHTML = `
    <div class="event-head">
      <span class="event-type">${event.event_type}</span>
      <span class="event-agent">${event.agent_id || ""}</span>
    </div>
    <p>${(event.data && event.data.text) || ""}</p>
    <small>${event.timestamp}</small>
  `;
  return item;
}

function applyEventFilter() {
  if (!eventList) return;
  const mode = eventList.dataset.filterMode || "selected";
  const selectedAgent = eventList.dataset.selectedAgent || "";
  const items = eventList.querySelectorAll(".event-item");
  items.forEach((item) => {
    const matches = item.dataset.agentId === selectedAgent;
    item.classList.toggle("is-hidden", mode === "selected" && !matches);
  });
  if (eventEmpty) eventEmpty.hidden = items.length > 0;
}

function prependEvent(event) {
  if (!eventList) return;
  eventList.prepend(buildEventItem(event));
  while (eventList.children.length > 40) {
    eventList.lastElementChild.remove();
  }
  applyEventFilter();
}

function setSelectedAgent(agentId, agentName) {
  if (!agentList || !eventList) return;
  agentList.querySelectorAll(".agent-row").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.agentId === agentId);
  });
  if (toAgentIdInput) toAgentIdInput.value = agentId;
  if (selectedAgentLabel) selectedAgentLabel.textContent = `target · ${agentName}`;
  eventList.dataset.selectedAgent = agentId;
  applyEventFilter();
}

if (agentList) {
  agentList.addEventListener("click", (event) => {
    const row = event.target.closest(".agent-row");
    if (!row) return;
    setSelectedAgent(row.dataset.agentId, row.dataset.agentName);
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

if (messageForm) {
  messageForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(messageForm);
    const content = String(formData.get("content") || "").trim();
    const toAgentId = String(formData.get("to_agent_id") || "");
    if (!content || !toAgentId) return;
    const response = await fetch("/api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_agent_id: toAgentId, content }),
    });
    if (response.ok) {
      messageForm.querySelector('textarea[name="content"]').value = "";
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

async function refreshDashboard() {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) return;
    const data = await res.json();
    renderAgents(data.agents || [], data.stats || []);
  } catch (e) {
    /* noop */
  }
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
  } catch (e) { /* ignore comments */ }
};

applyEventFilter();
