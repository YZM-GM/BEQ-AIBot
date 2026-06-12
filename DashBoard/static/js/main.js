const chatBox = document.getElementById("chat-box");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const usageBar = document.getElementById("usage-bar");

const state = {
  currentPanel: "chat-panel",
  agents: [],
  selectedSkill: null,
  selectedSoul: null,
  mcpData: null,
  skills: [],
  souls: [],
  conversations: [],
  selectedConversation: null,
  teamMode: false,
};

// 全局持久 SSE 状态
let _globalES = null;
let _pendingTurnId = null;

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function api(path, options = {}) {
  const config = { ...options };
  if (config.body && typeof config.body !== "string") {
    config.headers = { ...(config.headers || {}), "Content-Type": "application/json" };
    config.body = JSON.stringify(config.body);
  }
  const res = await fetch(path, config);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    throw new Error(data.error || `请求失败: ${res.status}`);
  }
  return data;
}

function setActivePanel(panelId) {
  state.currentPanel = panelId;
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === panelId);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === panelId);
  });
}

function autoResize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

/* ── row-list helpers ─────────────────────────────────────────── */
function toggleHtml(checked, name, key) {
  return `<label class="toggle"><input type="checkbox" data-toggle="${escapeHtml(key)}" ${checked ? "checked" : ""} /><span class="slider"></span></label>`;
}

function renderRowList(containerId, items, expandedKey, renderHead, renderMeta, renderBody, options = {}) {
  const el = document.getElementById(containerId);
  if (!items.length) {
    el.innerHTML = '<div class="empty-state">暂无数据</div>';
    return;
  }
  el.innerHTML = items.map((item) => {
    const key = item.name || item.id || item.url || "";
    const expanded = expandedKey === key;
    const hasToggle = options.toggleEnabled ? options.toggleEnabled(item) : item.hasOwnProperty("enabled");
    return `
      <div class="row ${expanded ? "expanded" : ""}" data-row="${escapeHtml(key)}">
        <div class="row-head" data-action="expand">
          <span class="row-name">${renderHead(item)}</span>
          <span class="row-meta">${renderMeta(item)}</span>
          ${hasToggle ? toggleHtml(item.enabled, "", key) : ""}
          <span class="row-caret">▶</span>
        </div>
        <div class="row-body">${renderBody(item)}</div>
      </div>
    `;
  }).join("");

  // 行点击 → 展开/收起（点击 toggle 不冒泡）
  el.querySelectorAll(".row-head").forEach((head) => {
    head.addEventListener("click", (e) => {
      if (e.target.closest("input[type='checkbox']")) return;
      const row = head.closest(".row");
      const wasExpanded = row.classList.contains("expanded");
      row.classList.toggle("expanded");
      if (!wasExpanded && options.onExpand) {
        const key = row.dataset.row;
        const item = items.find((x) => (x.name || x.id || x.url) === key);
        options.onExpand(item, row).catch(console.error);
      }
    });
  });

  // toggle 变化 → 调用面板
  if (options.onToggle) {
    el.querySelectorAll("input[data-toggle]").forEach((input) => {
      input.addEventListener("change", () => {
        const row = input.closest(".row");
        const key = row.dataset.row;
        options.onToggle(key, input.checked);
      });
    });
  }
}

/* ── 全局持久 SSE 流 ──────────────────────────────────────────── */
function connectGlobalStream() {
  if (_globalES) _globalES.close();
  _globalES = new EventSource("/api/stream");
  _globalES.onmessage = handleGlobalEvent;
  _globalES.onerror = () => {
    // EventSource 自动重连；若有 pending turn 则保护性恢复按钮防死锁
    if (sendBtn.disabled) {
      sendBtn.disabled = false;
      _pendingTurnId = null;
      appendChatEvent("error", "连接中断", "SSE 断开，请重试");
      input.focus();
    }
  };
}

function handleGlobalEvent(evt) {
  let payload;
  try { payload = JSON.parse(evt.data); } catch (_) { return; }

  const type = payload.type;
  const convId = payload.conversation_id;
  const turnId = payload.turn_id;
  const data = payload.data || {};

  // turn_complete：恢复发送按钮，与当前选中 conversation 无关
  if (type === "turn_complete") {
    if (turnId === _pendingTurnId) {
      sendBtn.disabled = false;
      input.focus();
      _pendingTurnId = null;
      loadConversations().catch(console.error);
    }
    return;
  }

  // 只渲染当前选中 conversation 的事件
  if (!convId || convId !== state.selectedConversation?.id) return;

  const isGroup = state.selectedConversation?.type === "group";
  const agentName = data.agent_name || (isGroup ? "Agent" : (state.selectedConversation?.owner_agent || "Agent"));
  const turnKey = data.turn_key || agentName;

  console.debug("[SSE]", type, "agent=", agentName, "turnKey=", turnKey);

  if (type === "cycle_message") {
    appendCycleMessage(agentName, turnKey, data.content || "", data.cycle_index);
  } else if (type === "tool_call") {
    appendToolCall(agentName, turnKey, data.tool_name || "", data.arguments || {});
  } else if (type === "tool_result") {
    appendToolResult(agentName, turnKey, data.tool_name || "", data.result || "");
  } else if (type === "final_answer" || type === "agent_message") {
    appendFinalAnswer(agentName, turnKey, data.content || "");
  } else if (type === "error") {
    appendChatEvent("error", "错误", payload.message || data.message || "");
    if (sendBtn.disabled && turnId === _pendingTurnId) {
      sendBtn.disabled = false;
      _pendingTurnId = null;
      input.focus();
    }
  }
}

/* ── Chat panel ───────────────────────────────────────────────── */
function renderConversationMeta() {
  const meta = document.getElementById("conversation-meta");
  const conversation = state.selectedConversation;
  if (!conversation) {
    meta.innerHTML = '<span>请选择会话</span>';
    return;
  }
  const tag = conversation.type === "group" ? "群聊" : "单聊";
  const memberText = conversation.type === "group"
    ? `群主：${escapeHtml(conversation.owner_agent || "-")} · 成员：${escapeHtml((conversation.member_agents || []).join(", "))}`
    : `Agent：${escapeHtml(conversation.owner_agent || "-")}`;
  meta.innerHTML = `
    <h3>${escapeHtml(conversation.title)}</h3>
    <span class="badge">${tag}</span>
    <p>${memberText}</p>
  `;
}

function renderConversationList() {
  const el = document.getElementById("conversation-list");
  if (!state.conversations.length) {
    el.innerHTML = '<div class="empty-state">暂无会话</div>';
    return;
  }
  el.innerHTML = state.conversations.map((item) => `
    <div class="list-item ${state.selectedConversation?.id === item.id ? "active" : ""}" data-key="${escapeHtml(item.id)}">
      <h4>${escapeHtml(item.title)}</h4>
      <p>${item.type === "group" ? "群聊" : "单聊"} · ${escapeHtml(item.last_message_preview || "暂无消息")}</p>
      <div class="meta-row">
        <span class="badge">${item.type === "group" ? "Group" : "Single"}</span>
      </div>
    </div>
  `).join("");
  el.querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      const prev = state.selectedConversation;
      state.selectedConversation = state.conversations.find((item) => item.id === node.dataset.key) || null;
      renderConversationList();
      renderConversationMeta();
      if (!prev || prev.id !== state.selectedConversation?.id) {
        loadChatHistory(state.selectedConversation?.id);
      }
    });
  });
}

function clearChatView() {
  chatBox.innerHTML = "";
  usageBar.textContent = "";
}

async function loadChatHistory(convId) {
  clearChatView();
  if (!convId) return;
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(convId)}/history`);
    for (const record of data.records || []) {
      if (record.role === "user") {
        const el = document.createElement("div");
        el.className = "msg user";
        el.textContent = record.content || "";
        chatBox.appendChild(el);
      } else if (record.role === "agent") {
        appendHistoryBlock(record.agent_name || "Agent", record.turn_key || record.agent_name, record.content || "");
      }
    }
    chatBox.scrollTop = chatBox.scrollHeight;
  } catch (_) {}
}

function appendChatEvent(roleClass, title, body = "") {
  const el = document.createElement("div");
  el.className = `msg ${roleClass}`;
  el.innerHTML = `
    <div class="trace-title">${escapeHtml(title)}</div>
    ${body ? `<div class="final-answer">${escapeHtml(body)}</div>` : ""}
  `;
  chatBox.appendChild(el);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// ── agent 块管理 ─────────────────────────────────────────────────
// 每次 CallAgent 产生唯一 turn_key，对应一个独立的 .agent-block
// 同一 turn_key 的事件追加在同一块里；不同 turn_key 新建块

function getOrCreateAgentBlock(agentName, turnKey) {
  const key = turnKey || agentName;
  let block = chatBox.querySelector(`.agent-block[data-turn-key="${CSS.escape(key)}"]`);
  if (!block) {
    // 计算该 agent 本次是第几次发言
    const prev = chatBox.querySelectorAll(`.agent-block[data-agent="${CSS.escape(agentName)}"]`).length;
    block = document.createElement("div");
    block.className = "agent-block";
    block.dataset.agent = agentName;
    block.dataset.turnKey = key;
    block.innerHTML = `
      <div class="agent-block-header">
        <span>${escapeHtml(agentName)}</span>
        ${prev > 0 ? `<span class="agent-turn-label">第 ${prev + 1} 次发言</span>` : ""}
      </div>
      <div class="agent-block-body"></div>
    `;
    chatBox.appendChild(block);
  }
  chatBox.scrollTop = chatBox.scrollHeight;
  return block;
}

function getBlockBody(agentName, turnKey) {
  return getOrCreateAgentBlock(agentName, turnKey).querySelector(".agent-block-body");
}

// 中间思考轮次（cycle_message）→ 折叠 details
function appendCycleMessage(agentName, turnKey, content, cycleIndex) {
  if (!content) return;
  const body = getBlockBody(agentName, turnKey);
  const details = document.createElement("details");
  details.className = "cycle-trace";
  details.innerHTML = `
    <summary>思考 ${cycleIndex != null ? `#${cycleIndex}` : ""}</summary>
    <div class="cycle-body">${escapeHtml(content)}</div>
  `;
  body.appendChild(details);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// 工具调用（tool_call）→ 单行徽章
function appendToolCall(agentName, turnKey, toolName, args) {
  const body = getBlockBody(agentName, turnKey);
  const row = document.createElement("div");
  row.className = "tool-row";
  const argStr = args && Object.keys(args).length
    ? Object.entries(args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")
    : "";
  row.innerHTML = `<span class="tool-badge">⚙ ${escapeHtml(toolName)}</span>
    <span style="color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;">${escapeHtml(argStr)}</span>`;
  body.appendChild(row);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// 工具结果（tool_result）→ 可展开单行
function appendToolResult(agentName, turnKey, toolName, result) {
  const body = getBlockBody(agentName, turnKey);
  const row = document.createElement("div");
  row.className = "tool-row";
  const preview = (result || "").slice(0, 80).replace(/\n/g, " ");
  row.innerHTML = `<span class="tool-badge result">↩ ${escapeHtml(toolName)}</span>
    <span class="tool-result-toggle" title="展开/收起结果">▾</span>
    <span style="color:var(--muted);font-size:11px;">${escapeHtml(preview)}${result && result.length > 80 ? "…" : ""}</span>`;
  const content = document.createElement("div");
  content.className = "tool-result-content";
  content.textContent = result || "";
  row.appendChild(content);
  row.querySelector(".tool-result-toggle").addEventListener("click", () => {
    content.classList.toggle("visible");
  });
  body.appendChild(row);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// 最终答案（final_answer）→ markdown 渲染，分隔线上方
function appendFinalAnswer(agentName, turnKey, content) {
  if (!content) return;
  const body = getBlockBody(agentName, turnKey);
  const div = document.createElement("div");
  div.className = "agent-final md-content";
  div.innerHTML = marked.parse(content);
  body.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// 历史回放（只还原 final_answer 记录，简洁显示）
function appendHistoryBlock(agentName, turnKey, content) {
  if (!content) return;
  const body = getBlockBody(agentName, turnKey || agentName);
  const div = document.createElement("div");
  div.className = "agent-final md-content";
  div.innerHTML = marked.parse(content);
  body.appendChild(div);
}

async function createSingleConversation() {
  const ownerAgent = state.agents[0]?.name;
  if (!ownerAgent) {
    alert("没有可用 agent");
    return;
  }
  await api("/api/conversations", {
    method: "POST",
    body: {
      type: "single",
      title: `${ownerAgent} 单聊`,
      owner_agent: ownerAgent,
      member_agents: [ownerAgent],
    },
  });
  await loadConversations();
}

async function createGroupConversation() {
  if (!state.agents.length) {
    alert("没有可用 agent");
    return;
  }
  const title = prompt("输入群聊名称", `群聊-${new Date().toISOString().slice(11, 19)}`);
  if (title === null) return;
  const ownerAgent = prompt("输入群主 agent 名称", state.agents[0]?.name || "");
  if (!ownerAgent) return;
  const members = prompt("输入成员 agent，使用逗号分隔", state.agents.map((item) => item.name).join(","));
  if (members === null) return;
  await api("/api/conversations", {
    method: "POST",
    body: {
      type: "group",
      title,
      owner_agent: ownerAgent.trim(),
      member_agents: members.split(",").map((item) => item.trim()).filter(Boolean),
    },
  });
  await loadConversations();
}

async function sendMessage() {
  const conversation = state.selectedConversation;
  const text = input.value.trim();
  if (!conversation || !text) return;

  input.value = "";
  autoResize();
  sendBtn.disabled = true;
  usageBar.textContent = "";

  // 立即在本地显示用户消息（乐观更新）
  const userEl = document.createElement("div");
  userEl.className = "msg user";
  userEl.textContent = text;
  chatBox.appendChild(userEl);
  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const createData = await api(`/api/conversations/${encodeURIComponent(conversation.id)}/turns`, {
      method: "POST",
      body: { message: text, team_mode: state.teamMode },
    });
    // 记录等待中的 turn_id，handleGlobalEvent 用它匹配 turn_complete 来恢复按钮
    _pendingTurnId = createData.turn_id;
  } catch (err) {
    appendChatEvent("error", "网络错误", String(err.message || err));
    sendBtn.disabled = false;
    input.focus();
  }
}

/* ── Agent panel ──────────────────────────────────────────────── */
function currentMcpOptions() {
  const items = state.mcpData?.items || [];
  return items.map((item) => ({
    value: item.id,
    label: item.kind === "local" ? `[本地] ${item.name}` : (item.name || item.url || item.id),
  }));
}
function currentSkillNames() {
  return state.skills.map((item) => item.name).sort();
}
function currentSoulNames() {
  return state.souls.map((item) => item.name).sort();
}

function renderCheckboxes(items, selected) {
  const selectedSet = new Set(selected || []);
  return `
    <div class="checkbox-grid">
      ${items.map((item) => `
        <label class="checkbox-item">
          <input type="checkbox" value="${escapeHtml(item.value)}" ${selectedSet.has(item.value) ? "checked" : ""} />
          <span>${escapeHtml(item.label)}</span>
        </label>
      `).join("")}
    </div>
  `;
}

function renderAgents() {
  renderRowList(
    "agent-list",
    state.agents,
    null,
    (item) => escapeHtml(item.name),
    (item) => `MCP ${item.allowed_mcps?.length || 0} · Skill ${item.allowed_skills?.length || 0} · ${item.soul || "default"}`,
    (item) => `
      <form data-agent-form="${escapeHtml(item.name)}">
        <div class="form-grid">
          <label class="form-field">
            <span>Soul 模板（应用后覆盖当前 soul 内容）</span>
            <select name="soul">
              ${currentSoulNames().map((name) => `<option value="${escapeHtml(name)}" ${name === item.soul ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}
            </select>
          </label>
          <button type="button" class="secondary" style="align-self:flex-end;" data-apply-soul="${escapeHtml(item.name)}">应用模板</button>
          <label class="form-field full">
            <span>Soul 内容（直接编辑此 agent 的人格）</span>
            <textarea name="soul_content" rows="8" placeholder="加载中…" data-soul-textarea="${escapeHtml(item.name)}"></textarea>
          </label>
          <label class="form-field full">
            <span>允许的 MCP</span>
            ${renderCheckboxes(currentMcpOptions(), item.allowed_mcps || [])}
          </label>
          <label class="form-field full">
            <span>允许的 Skills</span>
            ${renderCheckboxes(currentSkillNames().map((name) => ({ value: name, label: name })), item.allowed_skills || [])}
          </label>
        </div>
        <div class="toolbar">
          <button type="submit">保存</button>
          <button type="button" class="danger" data-agent-delete="${escapeHtml(item.name)}">删除</button>
        </div>
      </form>
    `,
    {
      onToggle: async (key, enabled) => {
        try {
          await api(`/api/manage/agents/${encodeURIComponent(key)}`, {
            method: "PUT",
            body: { enabled },
          });
          await loadAgents();
        } catch (err) {
          alert(err.message || err);
        }
      },
      onExpand: async (item, row) => {
        // 展开时懒加载该 agent 的 soul 内容
        const ta = row.querySelector(`textarea[data-soul-textarea="${CSS.escape(item.name)}"]`);
        if (!ta || ta.dataset.loaded) return;
        try {
          const data = await api(`/api/manage/agents/${encodeURIComponent(item.name)}/soul`);
          const content = data.content;
          ta.value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
          ta.dataset.loaded = "1";
        } catch (_) {
          ta.placeholder = "暂无 soul 内容";
        }
      },
    }
  );
}

async function submitAgentForm(name, form) {
  const mcpOptions = currentMcpOptions();
  const skillOptions = currentSkillNames().map((n) => ({ value: n, label: n }));
  const checkedValues = Array.from(form.querySelectorAll('input[type="checkbox"]:checked')).map((node) => node.value);
  const mcpValues = new Set(mcpOptions.map((item) => item.value));
  const skillValues = new Set(skillOptions.map((item) => item.value));
  const body = {
    soul: form.elements.soul.value,
    allowed_mcps: checkedValues.filter((v) => mcpValues.has(v)),
    allowed_skills: checkedValues.filter((v) => skillValues.has(v)),
  };
  await api(`/api/manage/agents/${encodeURIComponent(name)}`, { method: "PUT", body });

  // 同步保存 soul 内容（如果 textarea 已加载过）
  const ta = form.querySelector(`textarea[data-soul-textarea="${CSS.escape(name)}"]`);
  if (ta && ta.dataset.loaded) {
    const raw = ta.value;
    let content = raw;
    try { content = JSON.parse(raw); } catch (_) {}
    await api(`/api/manage/agents/${encodeURIComponent(name)}/soul`, { method: "PUT", body: { content } });
  }
}

function bindAgentForms() {
  document.querySelectorAll("form[data-agent-form]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await submitAgentForm(form.dataset.agentForm, form);
        await loadAgents();
      } catch (err) { alert(err.message || err); }
    });
  });
  document.querySelectorAll("[data-agent-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.agentDelete;
      if (!confirm(`确认删除 agent ${name} 吗？`)) return;
      try {
        await api(`/api/manage/agents/${encodeURIComponent(name)}`, { method: "DELETE" });
        await loadAgents();
      } catch (err) { alert(err.message || err); }
    });
  });
  // 应用 soul 模板：把模板内容覆写到 textarea，不立即保存
  document.querySelectorAll("[data-apply-soul]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.applySoul;
      const form = btn.closest("form[data-agent-form]");
      if (!form) return;
      const soulName = form.elements.soul.value;
      try {
        const data = await api(`/api/manage/souls/${encodeURIComponent(soulName)}`);
        const ta = form.querySelector(`textarea[data-soul-textarea="${CSS.escape(name)}"]`);
        if (ta) {
          const content = data.content;
          ta.value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
          ta.dataset.loaded = "1";
        }
      } catch (err) { alert(err.message || err); }
    });
  });
}

function showNewAgentForm() {
  const el = document.getElementById("agent-list");
  el.innerHTML = `
    <div class="row expanded" data-row="__new__">
      <div class="row-head">
        <span class="row-name">新建 Agent</span>
        <span class="row-caret" style="transform: rotate(90deg);">▶</span>
      </div>
      <div class="row-body">
        <form id="new-agent-form">
          <div class="form-grid">
            <label class="form-field">
              <span>名称</span>
              <input name="name" required />
            </label>
            <label class="form-field">
              <span>Soul</span>
              <select name="soul">
                ${currentSoulNames().map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}
              </select>
            </label>
            <label class="form-field full">
              <span>允许的 MCP</span>
              ${renderCheckboxes(currentMcpOptions(), [])}
            </label>
            <label class="form-field full">
              <span>允许的 Skills</span>
              ${renderCheckboxes(currentSkillNames().map((name) => ({ value: name, label: name })), [])}
            </label>
          </div>
          <div class="toolbar">
            <button type="submit">创建</button>
            <button type="button" class="secondary" id="cancel-new-agent">取消</button>
          </div>
        </form>
      </div>
    </div>
  `;
  document.getElementById("cancel-new-agent").addEventListener("click", () => renderAgents());
  document.getElementById("new-agent-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const mcpOptions = currentMcpOptions();
    const skillOptions = currentSkillNames().map((n) => ({ value: n, label: n }));
    const checkedValues = Array.from(form.querySelectorAll('input[type="checkbox"]:checked')).map((node) => node.value);
    const mcpValues = new Set(mcpOptions.map((item) => item.value));
    const skillValues = new Set(skillOptions.map((item) => item.value));
    const body = {
      name: form.elements.name.value.trim(),
      soul: form.elements.soul.value,
      allowed_mcps: checkedValues.filter((v) => mcpValues.has(v)),
      allowed_skills: checkedValues.filter((v) => skillValues.has(v)),
      enabled: true,
    };
    try {
      await api("/api/manage/agents", { method: "POST", body });
      await loadAgents();
    } catch (err) { alert(err.message || err); }
  });
}

/* ── MCP panel ────────────────────────────────────────────────── */
function renderMcpPanel() {
  const items = state.mcpData?.items || [];
  renderRowList(
    "mcp-server-list",
    items,
    null,
    (item) => escapeHtml(item.name || item.url || item.id),
    (item) => {
      if (item.kind === "local") return "本地工具";
      return `${item.kind === "online" ? "在线" : ""} · ${item.tools?.length || item.tool_count || 0} 个工具`;
    },
    (item) => `
      <div class="meta-row">
        <span class="badge">${item.kind === "local" ? "Local" : "Online"}</span>
        ${item.version ? `<span class="badge">${escapeHtml(item.version)}</span>` : ""}
        ${item.last_refresh_at ? `<span class="badge">最近：${escapeHtml(item.last_refresh_at)}</span>` : ""}
      </div>
      ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}
      ${item.url ? `<pre class="code-block">${escapeHtml(item.url)}</pre>` : ""}
      ${item.last_error ? `<pre class="code-block">${escapeHtml(item.last_error)}</pre>` : ""}
      ${item.tools?.length ? `
        <div>
          <div class="sidebar-title">工具</div>
          <div class="checkbox-grid">
            ${item.tools.map((tool) => `
              <div class="checkbox-item">
                <div>
                  <strong>${escapeHtml(tool.name)}</strong>
                  <p style="margin:2px 0 0;color:var(--muted);font-size:12px;">${escapeHtml(tool.description || "")}</p>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      ` : ""}
    `,
    {
      onToggle: async (key, enabled) => {
        // renderRowList 用 item.name || item.id || item.url 生成 data-row，需用相同逻辑查找
        const item = items.find((x) => (x.name || x.id || x.url || "") === key);
        if (!item) return;
        try {
          if (item.kind === "local") {
            await api("/api/manage/mcps/local/toggle", { method: "PUT", body: { name: item.name, enabled } });
          } else if (item.kind === "online") {
            await api("/api/manage/mcps/online/toggle", { method: "PUT", body: { url: item.url, enabled } });
          }
          await loadMcps();
        } catch (err) { alert(err.message || err); }
      },
    }
  );
}

/* ── Skills panel ─────────────────────────────────────────────── */
function renderSkills() {
  renderRowList(
    "skills-list",
    state.skills,
    null,  // 初始不展开任何行，等用户点击后异步加载
    (item) => escapeHtml(item.name),
    (item) => escapeHtml(item.summary || ""),
    (item) => {
      // body 默认占位，onExpand 触发后会被覆盖
      return `<div class="row-body-loading">点击展开加载 SKILL.md…</div>`;
    },
    {
      onToggle: async (key, enabled) => {
        try {
          await api(`/api/manage/skills/${encodeURIComponent(key)}`, { method: "PUT", body: { enabled } });
          await loadSkills(key);
        } catch (err) { alert(err.message || err); }
      },
      onExpand: async (item, row) => {
        if (!item) return;
        const body = row.querySelector(".row-body");
        if (!body) return;
        body.innerHTML = `<div class="row-body-loading">加载中…</div>`;
        try {
          const detail = await api(`/api/manage/skills/${encodeURIComponent(item.name)}`);
          state.selectedSkill = detail;
          body.innerHTML = `
            ${detail.path ? `<pre class="code-block">${escapeHtml(detail.path)}</pre>` : ""}
            ${detail.content ? `<pre class="code-block">${escapeHtml(detail.content)}</pre>` : '<div class="empty-state">无内容</div>'}
          `;
        } catch (err) {
          body.innerHTML = `<div class="empty-state">加载失败: ${escapeHtml(err.message || String(err))}</div>`;
        }
      },
    }
  );
}

/* ── Souls panel ──────────────────────────────────────────────── */
function renderSouls() {
  renderRowList(
    "soul-list",
    state.souls,
    state.selectedSoul?.name,
    (item) => escapeHtml(item.name),
    (item) => escapeHtml(item.preview || ""),
    (item) => {
      const target = state.selectedSoul?.name === item.name ? state.selectedSoul : item;
      const contentValue = typeof target.content === "string"
        ? target.content
        : JSON.stringify(target.content, null, 2);
      return `
        <form data-soul-form="${escapeHtml(item.name)}">
          <div class="form-grid">
            <label class="form-field full">
              <span>名称</span>
              <input name="name" value="${escapeHtml(target.name || "")}" disabled />
            </label>
            <label class="form-field full">
              <span>内容</span>
              <textarea name="content" rows="14">${escapeHtml(contentValue || "")}</textarea>
            </label>
          </div>
          <div class="toolbar">
            <button type="submit">保存</button>
            <button type="button" class="danger" data-soul-delete="${escapeHtml(item.name)}">删除</button>
          </div>
        </form>
      `;
    }
  );

  document.querySelectorAll('#soul-list .row-head').forEach((head) => {
    head.addEventListener("click", () => {
      const key = head.closest(".row").dataset.row;
      state.selectedSoul = state.souls.find((s) => s.name === key) || state.selectedSoul;
    });
  });

  bindSoulForms();
}

function bindSoulForms() {
  document.querySelectorAll("form[data-soul-form]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = form.dataset.soulForm;
      const raw = form.elements.content.value;
      let content = raw;
      try { content = JSON.parse(raw); } catch (_) {}
      try {
        await api(`/api/manage/souls/${encodeURIComponent(name)}`, { method: "PUT", body: { content } });
        await loadSouls(name);
      } catch (err) { alert(err.message || err); }
    });
  });
  document.querySelectorAll("[data-soul-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.soulDelete;
      if (!confirm(`确认删除 soul ${name} 吗？`)) return;
      try {
        await api(`/api/manage/souls/${encodeURIComponent(name)}`, { method: "DELETE" });
        await loadSouls();
      } catch (err) { alert(err.message || err); }
    });
  });
}

function showNewSoulForm() {
  const el = document.getElementById("soul-list");
  el.innerHTML = `
    <div class="row expanded" data-row="__new__">
      <div class="row-head">
        <span class="row-name">新建 Soul</span>
        <span class="row-caret" style="transform: rotate(90deg);">▶</span>
      </div>
      <div class="row-body">
        <form id="new-soul-form">
          <div class="form-grid">
            <label class="form-field full">
              <span>名称</span>
              <input name="name" required />
            </label>
            <label class="form-field full">
              <span>内容</span>
              <textarea name="content" rows="14"></textarea>
            </label>
          </div>
          <div class="toolbar">
            <button type="submit">创建</button>
            <button type="button" class="secondary" id="cancel-new-soul">取消</button>
          </div>
        </form>
      </div>
    </div>
  `;
  document.getElementById("cancel-new-soul").addEventListener("click", () => renderSouls());
  document.getElementById("new-soul-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const name = form.elements.name.value.trim();
    const raw = form.elements.content.value;
    let content = raw;
    try { content = JSON.parse(raw); } catch (_) {}
    try {
      await api("/api/manage/souls", { method: "POST", body: { name, content } });
      await loadSouls(name);
    } catch (err) { alert(err.message || err); }
  });
}

/* ── Loaders ──────────────────────────────────────────────────── */
async function loadConversations() {
  const data = await api("/api/conversations");
  state.conversations = data.items || [];
  const prevId = state.selectedConversation?.id;
  if (!state.selectedConversation || !state.conversations.some((item) => item.id === prevId)) {
    state.selectedConversation = state.conversations[0] || null;
    if (state.selectedConversation?.id !== prevId) {
      loadChatHistory(state.selectedConversation?.id);
    }
  } else {
    state.selectedConversation = state.conversations.find((item) => item.id === prevId) || null;
  }
  renderConversationList();
  renderConversationMeta();
}

async function loadAgents() {
  const data = await api("/api/manage/agents");
  state.agents = data.items || [];
  renderAgents();
  bindAgentForms();
}

async function loadMcps() {
  state.mcpData = await api("/api/manage/mcps");
  renderMcpPanel();
}

async function loadSkills(selectedName = null) {
  const data = await api("/api/manage/skills");
  state.skills = data.items || [];
  if (selectedName) {
    try {
      state.selectedSkill = await api(`/api/manage/skills/${encodeURIComponent(selectedName)}`);
    } catch (_) { state.selectedSkill = null; }
  }
  // 不预选：避免空 detail 让 row 显示空白 body
  renderSkills();
}

async function loadSouls(selectedName = null) {
  const data = await api("/api/manage/souls");
  state.souls = data.items || [];
  if (selectedName) {
    state.selectedSoul = state.souls.find((item) => item.name === selectedName) || null;
  }
  if (!state.selectedSoul || !state.souls.some((item) => item.name === state.selectedSoul.name)) {
    state.selectedSoul = state.souls[0] || null;
  }
  renderSouls();
}

/* ── Boot ─────────────────────────────────────────────────────── */
async function boot() {
  // 建立全局持久 SSE 流（最先执行）
  connectGlobalStream();

  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.addEventListener("click", () => setActivePanel(button.dataset.panel));
  });

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", autoResize);

  // 团队任务模式切换按钮
  const teamModeBtn = document.getElementById("team-mode-btn");
  teamModeBtn.addEventListener("click", () => {
    state.teamMode = !state.teamMode;
    teamModeBtn.classList.toggle("active", state.teamMode);
    teamModeBtn.setAttribute("aria-pressed", String(state.teamMode));
  });

  document.getElementById("new-single-chat-btn").addEventListener("click", () => createSingleConversation().catch((error) => alert(error.message || error)));
  document.getElementById("new-group-chat-btn").addEventListener("click", () => createGroupConversation().catch((error) => alert(error.message || error)));
  document.getElementById("new-agent-btn").addEventListener("click", () => showNewAgentForm());
  document.getElementById("refresh-agent-btn").addEventListener("click", loadAgents);
  document.getElementById("refresh-mcp-btn").addEventListener("click", async () => {
    await api("/api/manage/mcps/online/refresh", { method: "POST" });
    await loadMcps();
  });
  document.getElementById("add-mcp-btn").addEventListener("click", async () => {
    const url = document.getElementById("new-mcp-url").value.trim();
    if (!url) return;
    try {
      await api("/api/manage/mcps/online", { method: "POST", body: { url } });
      document.getElementById("new-mcp-url").value = "";
      await loadMcps();
    } catch (error) {
      alert(error.message || error);
    }
  });
  document.getElementById("rescan-skills-btn").addEventListener("click", async () => {
    await api("/api/manage/skills/rescan", { method: "POST" });
    await loadSkills();
  });
  document.getElementById("new-soul-btn").addEventListener("click", () => showNewSoulForm());
  document.getElementById("refresh-soul-btn").addEventListener("click", loadSouls);

  // 직렬화: Agent 폼은 Mcps/Skills/Souls 옵션에 의존하므로 먼저 채움
  await loadMcps();
  await loadSkills();
  await loadSouls();
  await loadAgents();
  await loadConversations();
}

boot().catch((error) => {
  console.error(error);
  alert(error.message || error);
});