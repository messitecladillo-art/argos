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
const selectionModal = document.getElementById("selection-modal");
const selectionModalBody = document.getElementById("selection-modal-body");
const terminalSnapshots = new Map();
const terminalHasLiveOutput = new Set();
const resolvedInteractionIds = new Set();
const submittingInteractionIds = new Set();
const resolvedSelectionSignatures = new Set();
let agentContextMenu = null;
let deletingAgentId = "";
let dismissAgentModal = null;
let term = null;
let fitAddon = null;
let resizeTimer = 0;

function interactionKey(agentId, requestId) {
  return `${agentId || ""}:${requestId || ""}`;
}

function selectionSignature(agentId, interaction) {
  const choices = Array.isArray(interaction?.choices) ? interaction.choices : [];
  return `${agentId || ""}:selection:${choices.map(cleanChoiceLabel).join("|")}`;
}

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
  row.dataset.agentStatus = agent.status || "idle";
  row.dataset.agentOrchestrationState = agent.orchestration_state || "none";
  const runtimeStatus = agent.runtime_status || "stopped";
  const displayStatus = agent.orchestration_state === "waiting_workers"
    ? "waiting"
    : (agent.orchestration_state === "summarizing" ? "busy" : (agent.status || "idle"));
  const displayState = agent.orchestration_state && agent.orchestration_state !== "none"
    ? agent.orchestration_state
    : (agent.interaction_state || "idle");
  const btn = runtimeStatus === "running"
    ? `<button class="acp-btn acp-btn--stop" type="button" data-session-action="stop" data-agent-id="${agent.agent_id}">停止</button>`
    : `<button class="acp-btn acp-btn--start" type="button" data-session-action="start" data-agent-id="${agent.agent_id}">启动</button>`;
  row.innerHTML = `
    <div class="agent-row__top">
      <div>
        <strong>${escapeHtml(agent.name)}</strong>
        <p>${escapeHtml(agent.role)} · ${escapeHtml(agent.profile_name)}</p>
      </div>
      <span class="status-badge status-${escapeHtml(displayStatus)}">${escapeHtml(displayState)}</span>
    </div>
    <div class="agent-row__body">
      <div class="load-track"><span style="width: ${agent.load || 0}%"></span></div>
      <dl>
        <div><dt>Task</dt><dd>${escapeHtml(agent.current_task || "—")}</dd></div>
        <div><dt>Last Output</dt><dd>${escapeHtml(formatAgentTime(agent.last_output_at))}</dd></div>
        <div><dt>State</dt><dd>${escapeHtml(displayState)}</dd></div>
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
  if (getSelectionInteraction(agent)) return "";
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

function getSelectionPrompt(prompt) {
  const lines = String(prompt || "")
    .split("\n")
    .map((line) => line.trim().replace(/^[│┃║▏▕▌▐]+|[│┃║▏▕▌▐]+$/g, "").trim())
    .filter(Boolean);
  return lines.find((line) => /[\u4e00-\u9fa5].*[？?]/.test(line)) || "Hermes 需要你选择一个选项后继续。";
}

function cleanChoiceLabel(label) {
  return String(label || "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s*\([0-9.]+s\)\s*$/, "")
    .trim();
}

function parseSelectionFromPrompt(prompt) {
  const lines = String(prompt || "")
    .split("\n")
    .map((line) => line.trim().replace(/^[│┃║▏▕▌▐]+|[│┃║▏▕▌▐]+$/g, "").trim());
  const choicePattern = /\bagent_[\w-]+\b|Other \(type your answer\)/i;
  const scannedChoices = [];
  let scannedSelectedIndex = null;
  for (const line of lines) {
    if (!line) continue;
    const selectedMatch = line.match(/^[›>❯]\s*(.+?)\s*$/);
    const choiceLine = selectedMatch ? selectedMatch[1] : line;
    if (!selectedMatch && !choicePattern.test(choiceLine)) continue;
    const label = cleanChoiceLabel(choiceLine);
    if (!label || scannedChoices.includes(label)) continue;
    if (selectedMatch) scannedSelectedIndex = scannedChoices.length;
    scannedChoices.push(label);
  }
  if (scannedSelectedIndex !== null && scannedChoices.length) {
    return { choices: scannedChoices, selectedIndex: scannedSelectedIndex };
  }

  let selectedIndex = null;
  const choices = [];
  let collecting = false;

  for (const line of lines) {
    if (!line) {
      if (collecting && choices.length) break;
      continue;
    }
    if (/\b(to select|Enter to confirm)\b/i.test(line)) {
      if (collecting && choices.length) break;
      continue;
    }

    const selectedMatch = line.match(/^[›>❯]\s*(.+?)\s*$/);
    if (selectedMatch) {
      const label = cleanChoiceLabel(selectedMatch[1]);
      if (label) {
        selectedIndex = choices.length;
        choices.push(label);
        collecting = true;
      }
      continue;
    }

    if (collecting) {
      if (line.startsWith("?") || line.startsWith("$")) break;
      if (/^[┌└├╭╰─━═]+$/.test(line)) break;
      if (line.length <= 140) choices.push(cleanChoiceLabel(line));
    }
  }

  return selectedIndex === null || choices.length === 0 ? null : { choices, selectedIndex };
}

function getSelectionInteraction(agent) {
  const interaction = agent.pending_interaction;
  if (!interaction) return null;
  if (interaction.kind === "awaiting_selection") return interaction;
  const parsed = parseSelectionFromPrompt(interaction.prompt);
  if (!parsed) return null;
  return {
    ...interaction,
    kind: "awaiting_selection",
    choices: parsed.choices,
    selected_index: parsed.selectedIndex,
  };
}

function renderSelectionModal(agents) {
  if (!selectionModal || !selectionModalBody) return;
  const agent = agents.find((item) => {
    const interaction = getSelectionInteraction(item);
    if (!interaction) return false;
    return !resolvedInteractionIds.has(interactionKey(item.agent_id, interaction.request_id))
      && !resolvedSelectionSignatures.has(selectionSignature(item.agent_id, interaction));
  });
  const interaction = agent ? getSelectionInteraction(agent) : null;
  if (!agent || !interaction) {
    selectionModal.hidden = true;
    selectionModalBody.innerHTML = "";
    return;
  }

  const choices = Array.isArray(interaction.choices) ? interaction.choices : [];
  const selectedIndex = Number.isInteger(interaction.selected_index) ? interaction.selected_index : 0;
  const isSubmitting = submittingInteractionIds.has(interactionKey(agent.agent_id, interaction.request_id));
  const choiceButtons = choices.map((choice, index) => `
    <button class="choice-button${index === selectedIndex ? " is-selected" : ""}" type="button" data-interaction-response="${index}" data-agent-id="${agent.agent_id}" data-request-id="${interaction.request_id}" ${isSubmitting ? "disabled" : ""}>
      <span>${index === selectedIndex ? "当前" : "选择"}</span>
      <strong>${escapeHtml(choice)}</strong>
    </button>
  `).join("");

  selectionModalBody.innerHTML = `
    <div class="selection-modal__agent">
      <span>等待 Agent</span>
      <strong>${escapeHtml(agent.name)}</strong>
    </div>
    <p class="selection-modal__prompt">${escapeHtml(getSelectionPrompt(interaction.prompt))}</p>
    <div class="selection-modal__choices">${choiceButtons}</div>
    <p class="form-hint">${isSubmitting ? "已发送选择，等待 Hermes 继续执行…" : "选择后会自动发送到 Hermes 终端继续执行。"}</p>
  `;
  selectionModal.hidden = false;
}

function renderInteractions(agents) {
  if (!interactionList) return;
  const activeElement = document.activeElement;
  const activeForm = activeElement?.closest?.(".interaction-form");
  const activeRequestId = activeForm?.dataset.requestId || "";
  const activeValue = activeElement?.name === "response" ? activeElement.value : "";
  const html = agents
    .filter((agent) => agent.pending_interaction)
    .map((agent) => buildInteractionCard(agent))
    .join("");
  if (interactionList.innerHTML === html) {
    interactionList.hidden = !html;
    return;
  }
  interactionList.innerHTML = html;
  interactionList.hidden = !html;
  if (activeRequestId) {
    const restoredInput = interactionList.querySelector(`.interaction-form[data-request-id="${CSS.escape(activeRequestId)}"] input[name="response"]`);
    if (restoredInput) {
      restoredInput.value = activeValue;
      restoredInput.focus();
    }
  }
}

function renderAgents(agents, stats) {
  if (!agentList) return;
  closeAgentContextMenu();
  const activeInteractionKeys = new Set();
  agents.forEach((agent) => {
    const requestId = agent.pending_interaction?.request_id;
    if (requestId) activeInteractionKeys.add(interactionKey(agent.agent_id, requestId));
  });
  resolvedInteractionIds.forEach((key) => {
    if (!activeInteractionKeys.has(key)) resolvedInteractionIds.delete(key);
  });
  const selected = eventList?.dataset.selectedAgent || (agents[0] && agents[0].agent_id) || "";
  agentList.innerHTML = "";
  agents.forEach((agent) => {
    agentList.appendChild(buildAgentRow(agent, agent.agent_id === selected));
  });
  renderInteractions(agents);
  renderSelectionModal(agents);
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

function bootstrapTerminalSnapshots() {
  const events = Array.isArray(window.__BOOTSTRAP__?.events) ? window.__BOOTSTRAP__.events : [];
  events.forEach((event) => {
    if (event.event_type !== "agent.terminal.snapshot") return;
    terminalSnapshots.set(event.agent_id || "", cleanTerminalText(event.data?.text || ""));
  });
}

function applyEventFilter() {
  if (eventEmpty) eventEmpty.hidden = Boolean(eventList?.dataset.selectedAgent);
}

function hydrateTerminalSnapshots() {
  bootstrapTerminalSnapshots();
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
      background: "#01070e",
      foreground: "#e8f4ff",
      cursor: "#77f0ff",
      selectionBackground: "#234d59",
      black: "#0b1118",
      red: "#ff6b7a",
      green: "#77e09a",
      yellow: "#ffd166",
      blue: "#8ab4ff",
      magenta: "#d597ff",
      cyan: "#77f0ff",
      white: "#e8f4ff",
      brightBlack: "#5b7088",
      brightWhite: "#ffffff",
    },
  });
  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(terminalViewport);
  term.onData((data) => {
    sendTerminalData(data);
  });
  fitTerminal();
}

function fitTerminal() {
  if (!term || !fitAddon || !terminalViewport) return;
  try {
    fitAddon.fit();
    sendTerminalResize(term.rows, term.cols);
  } catch (e) {
    /* xterm can throw while hidden or before fonts/layout are ready */
  }
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
    term.clear();
    const snapshot = terminalSnapshots.get(agentId);
    if (snapshot) {
      term.write(`${snapshot}\r\n`);
    } else if (agentId && !terminalHasLiveOutput.has(agentId)) {
      term.write("\x1b[90m等待 Agent 终端输出。启动会话后可直接输入。\x1b[0m\r\n");
    }
  }
  fitTerminal();
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
  if (agentId !== (eventList.dataset.selectedAgent || "")) return;
  if (term) term.write(String(event.data?.text || ""));
}

async function postInteractionResponse(agentId, requestId, response) {
  const result = await fetch(`/api/agents/${agentId}/interactions/${requestId}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ response }),
  });
  return result.ok;
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
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(fitTerminal, 120);
});

async function handleInteractionClick(event) {
  const btn = event.target.closest("[data-interaction-response]");
  if (!btn) return;
  event.preventDefault();
  const key = interactionKey(btn.dataset.agentId, btn.dataset.requestId);
  if (submittingInteractionIds.has(key) || resolvedInteractionIds.has(key)) return;

  const isSelectionModal = selectionModal?.contains(btn);
  let modalSelectionSignature = "";
  if (isSelectionModal) {
    const interaction = {
      choices: Array.from(selectionModal.querySelectorAll(".choice-button strong")).map((item) => item.textContent || ""),
    };
    modalSelectionSignature = selectionSignature(btn.dataset.agentId, interaction);
    resolvedSelectionSignatures.add(modalSelectionSignature);
  }
  submittingInteractionIds.add(key);
  if (isSelectionModal) selectionModal.hidden = true;
  btn.disabled = true;
  try {
    const ok = await postInteractionResponse(
      btn.dataset.agentId,
      btn.dataset.requestId,
      btn.dataset.interactionResponse,
    );
    if (ok) {
      resolvedInteractionIds.add(key);
      return;
    }
    if (modalSelectionSignature) resolvedSelectionSignatures.delete(modalSelectionSignature);
    if (isSelectionModal) selectionModal.hidden = false;
  } finally {
    submittingInteractionIds.delete(key);
    btn.disabled = false;
  }
}

if (interactionList) {
  interactionList.addEventListener("click", handleInteractionClick);

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

selectionModal?.addEventListener("click", handleInteractionClick);

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
