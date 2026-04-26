const terminalShell = document.getElementById("terminal-shell");
const terminalViewport = document.getElementById("terminal-viewport");
const terminalTitle = document.getElementById("terminal-title");
const eventList = terminalShell;
const agentList = document.getElementById("agent-list");
const agentEmpty = document.getElementById("agent-empty");
const eventEmpty = document.getElementById("event-empty");
const sidebarStats = document.getElementById("sidebar-stats");
const openCreateAgent = document.getElementById("open-create-agent");
const modal = document.getElementById("create-agent-modal");
const createAgentForm = document.getElementById("create-agent-form");
const createAgentError = document.getElementById("create-agent-error");
const interactionList = document.getElementById("interaction-list");
const terminalSnapshots = new Map();
const terminalOutputLogs = new Map();
const terminalHasLiveOutput = new Set();
const maxTerminalLogLength = 200000;
let agentContextMenu = null;
let deletingAgentId = "";
let dismissAgentModal = null;
let term = null;
let fitAddon = null;
let resizeTimer = 0;
let lastTerminalRows = 0;
let lastTerminalCols = 0;

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

function formatRuntimeStatus(value) {
  if (value === "running") return "在岗";
  if (value === "crashed") return "异常";
  return "离岗";
}

function getAgentDisplayStatus(agent) {
  const runtimeStatus = agent.runtime_status || "stopped";
  const interactionState = agent.interaction_state || "idle";
  const orchestrationState = agent.orchestration_state || "none";
  const status = agent.status || "idle";

  if (runtimeStatus === "stopped" || runtimeStatus === "crashed") {
    return { label: "不可用", className: "offline" };
  }
  if (["awaiting_approval", "awaiting_selection", "awaiting_input"].includes(interactionState)) {
    return { label: "需介入", className: "waiting" };
  }
  if (
    status === "busy" ||
    status === "waiting" ||
    interactionState === "queued" ||
    interactionState === "running" ||
    orchestrationState === "waiting_workers" ||
    orchestrationState === "summarizing"
  ) {
    return { label: "处理中", className: "busy" };
  }
  return { label: "空闲", className: "idle" };
}

function buildAgentRow(agent, isActive) {
  const row = document.createElement("div");
  row.setAttribute("role", "button");
  row.tabIndex = 0;
  row.className = "agent-row" + (isActive ? " is-active" : "");
  row.dataset.agentId = agent.agent_id;
  row.dataset.agentName = agent.name;
  row.dataset.agentRole = agent.role;
  row.dataset.agentStatus = agent.status || "idle";
  row.dataset.agentOrchestrationState = agent.orchestration_state || "none";
  const runtimeStatus = agent.runtime_status || "stopped";
  const displayStatus = getAgentDisplayStatus(agent);
  const btn = runtimeStatus === "running"
    ? `<button class="acp-btn acp-btn--stop" type="button" data-session-action="stop" data-agent-id="${agent.agent_id}">停止</button>`
    : `<button class="acp-btn acp-btn--start" type="button" data-session-action="start" data-agent-id="${agent.agent_id}">启动</button>`;
  row.innerHTML = `
    <div class="agent-row__top">
      <div>
        <strong>${escapeHtml(agent.name)}</strong>
        <p>${escapeHtml(agent.role)} · ${escapeHtml(agent.profile_name)}</p>
      </div>
      <span class="status-badge status-${escapeHtml(displayStatus.className)}">${escapeHtml(displayStatus.label)}</span>
    </div>
    <div class="agent-row__body">
      <div class="load-track"><span style="width: ${agent.load || 0}%"></span></div>
      <dl>
        <div><dt>最后消息</dt><dd>${escapeHtml(formatAgentTime(agent.last_output_at))}</dd></div>
        <div><dt>任务数量</dt><dd>${agent.queue_depth || 0}</dd></div>
      </dl>
      <div class="agent-row__session">
        <span class="acp-dot acp-${runtimeStatus}"></span>
        <span class="acp-label">${escapeHtml(formatRuntimeStatus(runtimeStatus))}</span>
        ${btn}
      </div>
    </div>
  `;
  return row;
}

function renderInteractions(agents) {
  if (!interactionList) return;
  interactionList.innerHTML = "";
  interactionList.hidden = true;
}

function renderAgents(agents, stats) {
  if (!agentList) return;
  closeAgentContextMenu();
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
    if (terminalTitle) terminalTitle.textContent = "Agent Terminal";
    if (term) {
      term.clear();
      term.write("\x1b[90m还没有 Agent。创建并启动 Agent 后，这里会显示交互终端。\x1b[0m\r\n");
    }
  }
}

function cleanTerminalText(text) {
  return String(text || "")
    .replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[0-9;?: ]*[A-Za-z~]/g, "")
    .replace(/\x1b[()#][0-9A-Za-z]/g, "")
    .replace(/\x1b./g, "")
    .split("\n")
    .filter((line) => {
      const value = line.trim();
      if (!value) return true;
      if (/^[\s\-─━═│┃║┌┐└┘┏┓┗┛╭╮╰╯├┤┬┴┼╞╡╪╥╨╔╗╚╝╠╣╦╩╬]+$/.test(value)) return false;
      if (/^[Jj0-9]{1,3}$/.test(value)) return false;
      if (/^[$⚕]?\s*gpt-[\w.-]+\s*\|.*\|\s*\[.*\]\s*\d+%/i.test(value)) return false;
      if (/\bgpt-[\w.-]+\b.*\[[█░▒▓\s]+\].*\d+%/i.test(value)) return false;
      if (/Hermes/.test(value) && /[─━═╭╮╰╯┌┐└┘]/.test(value)) return false;
      if (/type a message \+ Enter to interrupt/i.test(value)) return false;
      if (/cursor position requests/i.test(value)) return false;
      if (/^[\w.-]+\s+❯$/.test(value)) return false;
      if (/^[⚕$]\s*❯/.test(value)) return false;
      if (/\[\d+\s*q\s*\[\d+\s*q/.test(value)) return false;
      return true;
    })
    .join("\n")
    .trimEnd();
}

function bootstrapTerminalSnapshots() {
  const events = Array.isArray(window.__BOOTSTRAP__?.events) ? window.__BOOTSTRAP__.events : [];
  events.slice().reverse().forEach((event) => {
    const agentId = event.agent_id || "";
    if (event.event_type === "agent.terminal.output") {
      terminalHasLiveOutput.add(agentId);
      appendTerminalOutput(agentId, String(event.data?.text || ""));
      return;
    }
    if (event.event_type === "agent.terminal.snapshot") {
      terminalSnapshots.set(agentId, cleanTerminalText(event.data?.text || ""));
    }
  });
}

function applyEventFilter() {
  if (eventEmpty) eventEmpty.hidden = Boolean(eventList?.dataset.selectedAgent);
}

function hydrateTerminalSnapshots() {
  bootstrapTerminalSnapshots();
}

function appendTerminalOutput(agentId, text) {
  if (!agentId || !text) return;
  const current = terminalOutputLogs.get(agentId) || "";
  const next = `${current}${text}`;
  terminalOutputLogs.set(agentId, next.length > maxTerminalLogLength ? next.slice(-maxTerminalLogLength) : next);
}

function resetTerminalView() {
  if (!term) return;
  term.reset();
  term.clear();
}

function writeSnapshotFallback(snapshot) {
  if (!term || !snapshot) return;
  term.write(`${snapshot.replace(/\n/g, "\r\n")}\r\n`);
}

function initTerminal() {
  if (!terminalViewport || !window.Terminal || !window.FitAddon) return;
  term = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 13,
    lineHeight: 1.35,
    scrollback: 5000,
    theme: {
      background: "#020201",
      foreground: "#f4efe4",
      cursor: "#f6cf75",
      selectionBackground: "#4a3511",
      black: "#090704",
      red: "#ff7b73",
      green: "#61e294",
      yellow: "#d99a21",
      blue: "#b88935",
      magenta: "#d6a85a",
      cyan: "#f6cf75",
      white: "#f4efe4",
      brightBlack: "#82786a",
      brightWhite: "#fff8e8",
    },
  });
  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(terminalViewport);
  term.onData((data) => {
    sendTerminalData(data);
  });
  scheduleTerminalFit(0);
  scheduleTerminalFit(80);
  requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
}

function fitTerminal() {
  if (!term || !fitAddon || !terminalViewport) return;
  try {
    fitAddon.fit();
    if (term.rows !== lastTerminalRows || term.cols !== lastTerminalCols) {
      lastTerminalRows = term.rows;
      lastTerminalCols = term.cols;
      sendTerminalResize(term.rows, term.cols);
    }
  } catch (e) {
    /* xterm can throw while hidden or before fonts/layout are ready */
  }
}

function scheduleTerminalFit(delay = 120) {
  window.setTimeout(fitTerminal, delay);
}

function debounceTerminalFit(delay = 120) {
  clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(fitTerminal, delay);
}

function setSelectedAgent(agentId, agentName, force = false) {
  if (!agentList || !eventList) return;
  const row = agentList.querySelector(`.agent-row[data-agent-id="${CSS.escape(agentId)}"]`);
  const name = agentName || row?.dataset.agentName || agentId || "尚未选择";
  const changed = eventList.dataset.selectedAgent !== agentId;
  agentList.querySelectorAll(".agent-row").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.agentId === agentId);
  });
  eventList.dataset.selectedAgent = agentId;
  if (terminalTitle) terminalTitle.textContent = agentId ? `${name} · Hermes Terminal` : "Agent Terminal";
  if (term && (changed || force)) {
    fitTerminal();
    resetTerminalView();
    const outputLog = terminalOutputLogs.get(agentId);
    if (outputLog) {
      term.write(outputLog);
    } else if (terminalSnapshots.has(agentId)) {
      writeSnapshotFallback(terminalSnapshots.get(agentId));
    } else if (agentId && !terminalHasLiveOutput.has(agentId)) {
      term.write("\x1b[90m等待 Agent 终端输出。启动会话后可直接输入。\x1b[0m\r\n");
    }
  }
  scheduleTerminalFit(0);
  applyEventFilter();
}

async function sendTerminalData(data) {
  const agentId = eventList?.dataset.selectedAgent || "";
  if (!agentId || !data) return false;
  const response = await fetch(`/api/agents/${agentId}/terminal-data`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data }),
  });
  return response.ok;
}

async function sendTerminalResize(rows, cols) {
  const agentId = eventList?.dataset.selectedAgent || "";
  if (!agentId || !rows || !cols) return false;
  const response = await fetch(`/api/agents/${agentId}/terminal-resize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows, cols }),
  });
  return response.ok;
}

function handleTerminalEvent(event) {
  if (!eventList) return;
  const agentId = event.agent_id || "";
  if (event.event_type === "agent.terminal.snapshot") {
    terminalSnapshots.set(agentId, cleanTerminalText(event.data?.text || ""));
    return;
  }
  if (event.event_type !== "agent.terminal.output") return;
  terminalHasLiveOutput.add(agentId);
  appendTerminalOutput(agentId, String(event.data?.text || ""));
  if (agentId !== (eventList.dataset.selectedAgent || "")) return;
  if (term) term.write(String(event.data?.text || ""));
}

function isIdleAgentRow(row) {
  return row?.dataset.agentStatus === "idle"
    && (row.dataset.agentOrchestrationState || "none") === "none";
}

function ensureAgentContextMenu() {
  if (agentContextMenu) return agentContextMenu;
  agentContextMenu = document.createElement("div");
  agentContextMenu.className = "agent-context-menu";
  agentContextMenu.hidden = true;
  agentContextMenu.innerHTML = `
    <button class="agent-context-menu__item agent-context-menu__item--danger" type="button" data-agent-delete>
      解雇
    </button>
  `;
  agentContextMenu.addEventListener("click", async (event) => {
    event.stopPropagation();
    const btn = event.target.closest("[data-agent-delete]");
    if (!btn || btn.disabled) return;
    const agentId = agentContextMenu.dataset.agentId || "";
    const agentName = agentContextMenu.dataset.agentName || agentId;
    if (!agentId || deletingAgentId) return;

    const confirmed = await confirmAgentDismissal(agentName);
    if (!confirmed) {
      closeAgentContextMenu();
      return;
    }

    deletingAgentId = agentId;
    btn.disabled = true;
    try {
      const response = await fetch(`/api/agents/${agentId}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        alert(data.error || "解雇失败");
        return;
      }
      closeAgentContextMenu();
    } finally {
      deletingAgentId = "";
      btn.disabled = false;
    }
  });
  document.body.appendChild(agentContextMenu);
  return agentContextMenu;
}

function positionAgentContextMenu(menu, clientX, clientY) {
  menu.hidden = false;
  const padding = 8;
  const rect = menu.getBoundingClientRect();
  const left = Math.min(clientX, window.innerWidth - rect.width - padding);
  const top = Math.min(clientY, window.innerHeight - rect.height - padding);
  menu.style.left = `${Math.max(padding, left)}px`;
  menu.style.top = `${Math.max(padding, top)}px`;
}

function showAgentContextMenu(row, clientX, clientY) {
  const menu = ensureAgentContextMenu();
  const deleteBtn = menu.querySelector("[data-agent-delete]");
  const canDelete = isIdleAgentRow(row);
  menu.dataset.agentId = row.dataset.agentId || "";
  menu.dataset.agentName = row.dataset.agentName || "";
  if (deleteBtn) {
    deleteBtn.disabled = !canDelete;
    deleteBtn.textContent = canDelete ? "解雇" : "仅 idle 可解雇";
  }
  positionAgentContextMenu(menu, clientX, clientY);
}

function closeAgentContextMenu() {
  if (!agentContextMenu) return;
  agentContextMenu.hidden = true;
  agentContextMenu.dataset.agentId = "";
  agentContextMenu.dataset.agentName = "";
}

function confirmAgentDismissal(agentName) {
  const modal = ensureDismissAgentModal();
  const name = agentName || "该 Agent";
  modal.querySelector("[data-dismiss-agent-message]").textContent = `你要解雇 ${name} 吗？`;
  modal.hidden = false;
  const confirmBtn = modal.querySelector("[data-dismiss-agent-confirm]");
  confirmBtn.focus();

  return new Promise((resolve) => {
    dismissAgentModal.resolve = resolve;
  });
}

function ensureDismissAgentModal() {
  if (dismissAgentModal) return dismissAgentModal;
  const modalEl = document.createElement("div");
  modalEl.className = "modal dismiss-agent-modal";
  modalEl.hidden = true;
  modalEl.innerHTML = `
    <div class="modal__backdrop" data-dismiss-agent-cancel></div>
    <div class="modal__panel panel dismiss-agent-modal__panel" role="dialog" aria-modal="true" aria-labelledby="dismiss-agent-title">
      <div class="modal__head">
        <h2 id="dismiss-agent-title">确认解雇</h2>
      </div>
      <p class="dismiss-agent-modal__message" data-dismiss-agent-message></p>
      <div class="modal__actions">
        <button type="button" class="filter-chip" data-dismiss-agent-cancel>取消</button>
        <button type="button" class="dismiss-agent-modal__confirm" data-dismiss-agent-confirm>解雇</button>
      </div>
    </div>
  `;
  modalEl.resolve = null;
  const closeWith = (value) => {
    modalEl.hidden = true;
    const resolve = modalEl.resolve;
    modalEl.resolve = null;
    if (resolve) resolve(value);
  };
  modalEl.addEventListener("click", (event) => {
    if (event.target.closest("[data-dismiss-agent-confirm]")) {
      closeWith(true);
      return;
    }
    if (event.target.closest("[data-dismiss-agent-cancel]")) {
      closeWith(false);
    }
  });
  document.body.appendChild(modalEl);
  dismissAgentModal = modalEl;
  return dismissAgentModal;
}

if (agentList) {
  agentList.addEventListener("click", (event) => {
    closeAgentContextMenu();
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

  agentList.addEventListener("contextmenu", (event) => {
    const row = event.target.closest(".agent-row");
    if (!row) return;
    event.preventDefault();
    showAgentContextMenu(row, event.clientX, event.clientY);
  });

  agentList.addEventListener("scroll", closeAgentContextMenu, { passive: true });
}

document.addEventListener("click", (event) => {
  if (agentContextMenu?.contains(event.target)) return;
  closeAgentContextMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && dismissAgentModal && !dismissAgentModal.hidden) {
    dismissAgentModal.hidden = true;
    const resolve = dismissAgentModal.resolve;
    dismissAgentModal.resolve = null;
    if (resolve) resolve(false);
  }
  if (event.key === "Escape") closeAgentContextMenu();
});

window.addEventListener("resize", closeAgentContextMenu);
window.addEventListener("resize", () => debounceTerminalFit(120));

if (window.ResizeObserver && terminalViewport) {
  const terminalResizeObserver = new ResizeObserver(() => debounceTerminalFit(60));
  terminalResizeObserver.observe(terminalViewport);
}

if (document.fonts?.ready) {
  document.fonts.ready.then(() => {
    scheduleTerminalFit(0);
    scheduleTerminalFit(160);
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
  handleTerminalEvent(payload);
});
stream.addEventListener("agents", (event) => {
  const payload = JSON.parse(event.data);
  renderAgents(payload.agents || [], payload.stats || []);
});
stream.onmessage = (event) => {
  try {
    const payload = JSON.parse(event.data);
    if (payload && payload.event_type) handleTerminalEvent(payload);
  } catch (e) {
    /* ignore */
  }
};

hydrateTerminalSnapshots();
initTerminal();
if (eventList?.dataset.selectedAgent) {
  const row = agentList?.querySelector(`.agent-row[data-agent-id="${CSS.escape(eventList.dataset.selectedAgent)}"]`);
  setSelectedAgent(eventList.dataset.selectedAgent, row?.dataset.agentName, true);
}
applyEventFilter();
