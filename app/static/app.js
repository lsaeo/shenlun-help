/* 公考申论素材助手 — 前端逻辑（原生 JS，无依赖） */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const STATE = {
  tab: "hotspots",
  filters: { position: "", theme: "", technique: "", collected: false },
  themes: [],
  modal: { kind: "", id: null },
};

/* ---------- 工具 ---------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 2200);
}
async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) {
    let msg = `请求失败 (${resp.status})`;
    try { msg = (await resp.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return resp.status === 204 ? null : resp.json();
}
function statusTag(s) {
  return `<span class="tag ${s === "草稿" ? "draft" : "published"}">${esc(s)}</span>`;
}
function fmtList(items) {
  if (!items || !items.length) return "";
  return "<ul>" + items.map((i) => `<li>${esc(i)}</li>`).join("") + "</ul>";
}

/* ---------- 概览 ---------- */
async function refreshOverview() {
  try {
    const o = await api("/api/overview");
    $("#overview").innerHTML =
      `<span class="badge">热点 ${o.hotspots_total}</span>` +
      (o.hotspots_draft ? `<span class="badge warn">待审热点 ${o.hotspots_draft}</span>` : "") +
      `<span class="badge">话题卡 ${o.cards_total}</span>` +
      (o.cards_draft ? `<span class="badge warn">待审卡 ${o.cards_draft}</span>` : "") +
      `<span class="badge">语段 ${o.phrases_total}</span>` +
      `<span class="badge">更新至 ${o.last_update_date || "—"}</span>`;
  } catch (e) { /* 服务未就绪时静默 */ }
}

/* ---------- 标签页 ---------- */
function switchTab(tab) {
  STATE.tab = tab;
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${tab}`));
  if (tab === "hotspots") loadHotspots();
  if (tab === "cards") loadCards();
  if (tab === "phrases") loadPhrases();
  if (tab === "settings") loadSettings();
}

/* ================= 今日热点 ================= */
async function loadHotspots() {
  const q = $("#hs-q").value.trim();
  const date = $("#hs-date").value;
  const status = $("#hs-status").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (date) params.set("date", date); // 后端 list_items 未按 date 过滤，前端过滤兜底
  if (status) params.set("status", status);
  const { items } = await api(`/api/hotspots?${params}`);
  const filtered = date ? items.filter((it) => it.date === date) : items;
  renderHotspots(filtered);
}
function renderHotspots(items) {
  const box = $("#hs-list");
  if (!items.length) {
    box.innerHTML = `<div class="empty">暂无热点。点击「⚡ 立即生成今日」或「＋ 手动录入」。</div>`;
    return;
  }
  box.innerHTML = items.map((it) => `
    <div class="item ${it.status === "草稿" ? "draft" : "published"}">
      <div class="item-head">
        <div class="item-title">${esc(it.title)}</div>
        ${statusTag(it.status)}
      </div>
      <div class="item-meta">
        <span>📅 ${esc(it.date)}</span>
        <span>🏷 ${esc(it.source || "—")}</span>
        ${it.url ? `<a href="${esc(it.url)}" target="_blank">原文链接</a>` : ""}
      </div>
      ${it.summary ? `<div class="item-body"><div class="field"><span class="field-label">摘要</span>${esc(it.summary)}</div></div>` : ""}
      ${it.意义 ? `<div class="item-body"><div class="field"><span class="field-label">意义</span>${esc(it.意义)}</div></div>` : ""}
      ${it.角度?.length ? `<div class="item-body"><div class="field"><span class="field-label">角度</span>${fmtList(it.角度)}</div></div>` : ""}
      ${it.对策?.length ? `<div class="item-body"><div class="field"><span class="field-label">对策</span>${fmtList(it.对策)}</div></div>` : ""}
      ${it.金句 ? `<div class="item-body"><div class="field"><span class="field-label">金句</span>${esc(it.金句)}</div></div>` : ""}
      <div class="item-actions">
        ${it.status === "草稿"
          ? `<button class="btn primary small" data-act="publish" data-id="${it.id}">✔ 入库</button>
             <button class="btn small" data-act="edit" data-id="${it.id}">编辑</button>
             <button class="btn danger small" data-act="delete" data-id="${it.id}">删除</button>`
          : `<button class="btn small" data-act="edit" data-id="${it.id}">编辑</button>
             <button class="btn danger small" data-act="delete" data-id="${it.id}">删除</button>`}
      </div>
    </div>`).join("");
}
async function actHotspot(act, id) {
  if (act === "delete") {
    if (!confirm("确定删除这条热点？")) return;
    await api(`/api/hotspots/${id}`, { method: "DELETE" });
    toast("已删除");
  } else if (act === "publish") {
    await api(`/api/hotspots/${id}/review`, { method: "POST", body: JSON.stringify({ action: "publish" }) });
    toast("已入库 ✔");
  } else if (act === "edit") {
    openHotspotModal(id);
  }
  await loadHotspots();
  refreshOverview();
}
function openHotspotModal(id = null) {
  STATE.modal = { kind: "hotspot", id };
  $("#modal-title").textContent = id ? "编辑热点" : "手动录入热点";
  const d = new Date().toISOString().slice(0, 10);
  let it = { date: d, title: "", source: "", url: "", summary: "", 意义: "", 角度: [], 对策: [], 金句: "" };
  if (id) {
    api(`/api/hotspots/${id}`).then((r) => { it = r; buildHotspotForm(it); });
    return;
  }
  buildHotspotForm(it);
}
function buildHotspotForm(it) {
  $("#modal-body").innerHTML = `
    <label>日期 <input id="f-date" type="date" value="${esc(it.date)}"></label>
    <label>标题 <input id="f-title" type="text" value="${esc(it.title)}" placeholder="新闻标题"></label>
    <div class="row2">
      <label>来源 <input id="f-source" type="text" value="${esc(it.source || "")}" placeholder="如：新华网"></label>
      <label>原文链接 <input id="f-url" type="text" value="${esc(it.url || "")}"></label>
    </div>
    <label>摘要 <textarea id="f-summary" placeholder="新闻内容摘要（可留空）">${esc(it.summary || "")}</textarea></label>
    <label>意义（该事件为何重要、对应申论主题）<textarea id="f-meaning">${esc(it.意义 || "")}</textarea></label>
    <label>角度（每行一个论述切入点）<textarea id="f-angles" placeholder="角度1\n角度2">${esc((it.角度 || []).join("\n"))}</textarea></label>
    <label>对策（每行一条）<textarea id="f-measures" placeholder="对策1\n对策2">${esc((it.对策 || []).join("\n"))}</textarea></label>
    <label>金句 <textarea id="f-quote">${esc(it.金句 || "")}</textarea></label>`;
  showModal();
}
async function saveHotspotModal() {
  const data = {
    date: $("#f-date").value,
    title: $("#f-title").value.trim(),
    source: $("#f-source").value.trim(),
    url: $("#f-url").value.trim(),
    summary: $("#f-summary").value.trim(),
    意义: $("#f-meaning").value.trim(),
    角度: $("#f-angles").value.split("\n").map((s) => s.trim()).filter(Boolean),
    对策: $("#f-measures").value.split("\n").map((s) => s.trim()).filter(Boolean),
    金句: $("#f-quote").value.trim(),
  };
  if (!data.title) { toast("标题不能为空"); return; }
  const id = STATE.modal.id;
  if (id) await api(`/api/hotspots/${id}`, { method: "PUT", body: JSON.stringify({ data }) });
  else await api("/api/hotspots", { method: "POST", body: JSON.stringify({ data }) });
  hideModal();
  toast("已保存");
  await loadHotspots();
  refreshOverview();
}

/* ================= 话题卡 ================= */
async function loadThemes() {
  if (STATE.themes.length) return;
  try {
    const { themes } = await api("/api/themes");
    STATE.themes = themes;
    $("#tc-theme").innerHTML = `<option value="">全部主题</option>` +
      themes.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  } catch (e) { /* ignore */ }
}
async function loadCards() {
  const q = $("#tc-q").value.trim();
  const theme = $("#tc-theme").value;
  const status = $("#tc-status").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  const { items } = await api(`/api/topic_cards?${params}`);
  const filtered = theme ? items.filter((it) => it.theme === theme) : items;
  renderCards(filtered);
}
function renderCards(items) {
  const box = $("#tc-list");
  if (!items.length) {
    box.innerHTML = `<div class="empty">暂无话题卡。点击「⚡ 立即生成今日」生成，或「＋ 手动录入」。</div>`;
    return;
  }
  box.innerHTML = items.map((it) => `
    <div class="item ${it.status === "草稿" ? "draft" : "published"}">
      <div class="item-head">
        <div class="item-title">${esc(it.topic)}</div>
        <span class="tag">${esc(it.theme)}</span>
        ${statusTag(it.status)}
      </div>
      <div class="item-meta"><span>📅 ${esc(it.date)}</span></div>
      <div class="item-body">
        ${it.背景 ? `<div class="field"><span class="field-label">背景</span>${esc(it.背景)}</div>` : ""}
        ${it.意义 ? `<div class="field"><span class="field-label">意义</span>${esc(it.意义)}</div>` : ""}
        ${it.问题 ? `<div class="field"><span class="field-label">问题</span>${esc(it.问题)}</div>` : ""}
        ${it.对策?.length ? `<div class="field"><span class="field-label">对策</span>${fmtList(it.对策)}</div>` : ""}
        ${it.金句 ? `<div class="field"><span class="field-label">金句</span>${esc(it.金句)}</div>` : ""}
      </div>
      <div class="item-actions">
        ${it.status === "草稿"
          ? `<button class="btn primary small" data-act="publish" data-id="${it.id}">✔ 入库</button>
             <button class="btn small" data-act="edit" data-id="${it.id}">编辑</button>
             <button class="btn danger small" data-act="delete" data-id="${it.id}">删除</button>`
          : `<button class="btn small" data-act="edit" data-id="${it.id}">编辑</button>
             <button class="btn danger small" data-act="delete" data-id="${it.id}">删除</button>`}
      </div>
    </div>`).join("");
}
async function actCard(act, id) {
  if (act === "delete") {
    if (!confirm("确定删除这张话题卡？")) return;
    await api(`/api/topic_cards/${id}`, { method: "DELETE" });
    toast("已删除");
  } else if (act === "publish") {
    await api(`/api/topic_cards/${id}/review`, { method: "POST", body: JSON.stringify({ action: "publish" }) });
    toast("已入库 ✔");
  } else if (act === "edit") {
    openCardModal(id);
  }
  await loadCards();
  refreshOverview();
}
function openCardModal(id = null) {
  STATE.modal = { kind: "card", id };
  $("#modal-title").textContent = id ? "编辑话题卡" : "手动录入话题卡";
  const d = new Date().toISOString().slice(0, 10);
  let it = { date: d, theme: STATE.themes[0] || "", topic: "", 背景: "", 意义: "", 问题: "", 对策: [], 金句: "" };
  if (id) {
    api(`/api/topic_cards/${id}`).then((r) => { it = r; buildCardForm(it); });
    return;
  }
  buildCardForm(it);
}
function buildCardForm(it) {
  $("#modal-body").innerHTML = `
    <label>日期 <input id="f-date" type="date" value="${esc(it.date)}"></label>
    <div class="row2">
      <label>主题
        <select id="f-theme">${STATE.themes.map((t) =>
          `<option value="${esc(t)}" ${t === it.theme ? "selected" : ""}>${esc(t)}</option>`).join("")}
        </select>
      </label>
      <label>话题名 <input id="f-topic" type="text" value="${esc(it.topic)}"></label>
    </div>
    <label>背景 <textarea id="f-bg">${esc(it.背景 || "")}</textarea></label>
    <label>意义 <textarea id="f-meaning">${esc(it.意义 || "")}</textarea></label>
    <label>问题 <textarea id="f-problems">${esc(it.问题 || "")}</textarea></label>
    <label>对策（每行一条）<textarea id="f-measures">${esc((it.对策 || []).join("\n"))}</textarea></label>
    <label>金句 <textarea id="f-quote">${esc(it.金句 || "")}</textarea></label>`;
  showModal();
}
async function saveCardModal() {
  const data = {
    date: $("#f-date").value,
    theme: $("#f-theme").value,
    topic: $("#f-topic").value.trim(),
    背景: $("#f-bg").value.trim(),
    意义: $("#f-meaning").value.trim(),
    问题: $("#f-problems").value.trim(),
    对策: $("#f-measures").value.split("\n").map((s) => s.trim()).filter(Boolean),
    金句: $("#f-quote").value.trim(),
  };
  if (!data.topic) { toast("话题名不能为空"); return; }
  const id = STATE.modal.id;
  if (id) await api(`/api/topic_cards/${id}`, { method: "PUT", body: JSON.stringify({ data }) });
  else await api("/api/topic_cards", { method: "POST", body: JSON.stringify({ data }) });
  hideModal();
  toast("已保存");
  await loadCards();
  refreshOverview();
}

/* ================= 语段库 ================= */
function renderFilterBar() {
  const groups = {
    "f-position": ["开头", "结尾", "过渡", "论证"],
    "f-theme": STATE.themes,
    "f-technique": ["排比", "对仗", "引用", "比喻", "设问", "递进"],
  };
  for (const [gid, opts] of Object.entries(groups)) {
    const g = $(`#${gid}`);
    if (!g) continue;
    g.innerHTML = `<span class="fg-label">${gid === "f-position" ? "位置" : gid === "f-theme" ? "主题" : "手法"}</span>` +
      opts.map((o) => `<button class="chip" data-group="${gid}" data-val="${esc(o)}">${esc(o)}</button>`).join("");
  }
  applyChipState();
}
function applyChipState() {
  $$(".chip").forEach((c) => {
    const key = c.dataset.group.replace("f-", "");
    c.classList.toggle("on", STATE.filters[key] === c.dataset.val);
  });
}
async function loadPhrases() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(STATE.filters)) if (v) p.set(k, v);
  const q = $("#ph-q").value.trim();
  if (q) p.set("q", q);
  const { items } = await api(`/api/phrases/filter?${p}`);
  renderPhrases(items);
}
function renderPhrases(items) {
  const box = $("#ph-list");
  if (!items.length) {
    box.innerHTML = `<div class="empty">暂无匹配语段。调整筛选条件或「＋ 新增语段」。</div>`;
    return;
  }
  box.innerHTML = items.map((it) => `
    <div class="item">
      <div class="phrase-text">${esc(it.text)}</div>
      ${it.template ? `<div class="phrase-template">框架：${esc(it.template)}</div>` : ""}
      ${(it.examples || []).length ? `
        <div class="phrase-examples">
          <div class="pe-label">改写例句</div>
          ${it.examples.map((e) => `<div class="pe-item">${esc(e)}</div>`).join("")}
        </div>` : ""}
      <div class="tags-row">
        ${(it.position || []).map((t) => `<span class="tag">位·${esc(t)}</span>`).join("")}
        ${(it.theme || []).map((t) => `<span class="tag">题·${esc(t)}</span>`).join("")}
        ${(it.technique || []).map((t) => `<span class="tag">法·${esc(t)}</span>`).join("")}
      </div>
      ${it.usage ? `<div class="usage">💡 ${esc(it.usage)}</div>` : ""}
      <div class="item-actions">
        <button class="btn primary small" data-act="copy" data-id="${it.id}">📋 复制</button>
        ${it.template ? `<button class="btn small" data-act="copy-template" data-id="${it.id}">📋 复制框架</button>` : ""}
        <button class="btn small ${it.collected ? "collected" : ""}" data-act="collect" data-id="${it.id}">
          ${it.collected ? "★ 已收藏" : "☆ 收藏"}
        </button>
        <button class="btn small" data-act="edit" data-id="${it.id}">编辑</button>
        <button class="btn danger small" data-act="delete" data-id="${it.id}">删除</button>
        <span class="used">已用 ${it.used_count || 0} 次</span>
      </div>
    </div>`).join("");
}
async function actPhrase(act, id) {
  if (act === "copy" || act === "copy-template") {
    const it = await api(`/api/phrases/${id}`);
    await copyText(act === "copy-template" ? (it.template || it.text) : it.text);
    await api(`/api/phrases/${id}/copy`, { method: "POST" });
    toast(act === "copy-template" ? "已复制框架模板" : "已复制到剪贴板");
    await loadPhrases();
  } else if (act === "collect") {
    await api(`/api/phrases/${id}/toggle-collect`, { method: "POST" });
    await loadPhrases();
  } else if (act === "delete") {
    if (!confirm("确定删除这条语段？")) return;
    await api(`/api/phrases/${id}`, { method: "DELETE" });
    toast("已删除");
    await loadPhrases();
  } else if (act === "edit") {
    openPhraseModal(id);
  }
  refreshOverview();
}
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}
function openPhraseModal(id = null) {
  STATE.modal = { kind: "phrase", id };
  $("#modal-title").textContent = id ? "编辑语段" : "新增语段";
  let it = { text: "", template: "", examples: [], position: [], theme: [], technique: [], usage: "" };
  if (id) {
    api(`/api/phrases/${id}`).then((r) => { it = r; buildPhraseForm(it); });
    return;
  }
  buildPhraseForm(it);
}
function buildPhraseForm(it) {
  const opts = {
    position: ["开头", "结尾", "过渡", "论证"],
    theme: STATE.themes,
    technique: ["排比", "对仗", "引用", "比喻", "设问", "递进"],
  };
  $("#modal-body").innerHTML = `
    <label>语段正文
      <textarea id="f-text" style="min-height:110px" placeholder="粘贴或输入语段…">${esc(it.text || "")}</textarea>
    </label>
    <label>填空框架（把具体内容替换为 ____，保留句式骨架，可空）
      <textarea id="f-template" placeholder="例：民之所忧，我必念之；民之所盼，我必行之。从____到____，民生无小事…">${esc(it.template || "")}</textarea>
    </label>
    <label>改写例句（每行一个示例，演示框架怎么套用到别处）
      <textarea id="f-examples" style="min-height:60px" placeholder="例：从“米袋子”“菜篮子”到“钱袋子”…">${esc((it.examples || []).join("\n"))}</textarea>
    </label>
    ${Object.entries(opts).map(([k, list]) => `
      <label>${k === "position" ? "功能位置" : k === "theme" ? "主题" : "手法"}（可多选）
        <div class="check-grid">
          ${list.map((o) => {
            const on = (it[k] || []).includes(o);
            return `<label class="check"><input type="checkbox" data-cat="${k}" value="${esc(o)}" ${on ? "checked" : ""}> ${esc(o)}</label>`;
          }).join("")}
        </div>
      </label>`).join("")}
    <label>适用场景 / 使用提示
      <textarea id="f-usage" placeholder="如：适合放在开头亮明观点；主题词可替换…">${esc(it.usage || "")}</textarea>
    </label>`;
  showModal();
}
async function savePhraseModal() {
  const text = $("#f-text").value.trim();
  if (!text) { toast("语段正文不能为空"); return; }
  const data = { text };
  data.template = $("#f-template").value.trim();
  data.examples = $("#f-examples").value.split("\n").map((s) => s.trim()).filter(Boolean);
  for (const cat of ["position", "theme", "technique"]) {
    data[cat] = $$(`input[data-cat="${cat}"]:checked`).map((c) => c.value);
  }
  data.usage = $("#f-usage").value.trim();
  const id = STATE.modal.id;
  if (id) await api(`/api/phrases/${id}`, { method: "PUT", body: JSON.stringify({ data }) });
  else await api("/api/phrases", { method: "POST", body: JSON.stringify({ data }) });
  hideModal();
  toast("已保存");
  await loadPhrases();
  refreshOverview();
}

/* ================= 设置 ================= */
async function loadSettings() {
  const cfg = await api("/api/config");
  $("#cfg-key").value = cfg.api_key || "";
  $("#cfg-base").value = cfg.api_base || "https://api.deepseek.com";
  $("#cfg-model").value = cfg.model || "deepseek-chat";
  $("#cfg-time").value = cfg.update_time || "07:00";
  $("#cfg-hot").value = cfg.daily_hotspots || 5;
  $("#cfg-cards").value = cfg.daily_cards || 5;
  $("#cfg-phrases").value = cfg.daily_phrases ?? 3;
  $("#cfg-catchup").value = cfg.catchup_limit ?? 3;
  $("#cfg-hint").textContent = `最近更新：${cfg.last_update_date || "从未"}；语段素材源：${(cfg.phrase_sources || []).map(s => s.name).join("、") || "未配置"}`;
}
async function saveSettings() {
  const data = {
    api_key: $("#cfg-key").value.trim(),
    api_base: $("#cfg-base").value.trim() || "https://api.deepseek.com",
    model: $("#cfg-model").value.trim() || "deepseek-chat",
    update_time: $("#cfg-time").value || "07:00",
    daily_hotspots: Math.max(1, Math.min(20, Number($("#cfg-hot").value) || 5)),
    daily_cards: Math.max(1, Math.min(20, Number($("#cfg-cards").value) || 5)),
    daily_phrases: Math.max(0, Math.min(10, Number($("#cfg-phrases").value) || 0)),
    catchup_limit: Math.max(0, Math.min(7, Number($("#cfg-catchup").value) || 3)),
  };
  await api("/api/config", { method: "PUT", body: JSON.stringify({ data }) });
  toast("设置已保存");
  refreshOverview();
}

/* ================= 流水线 ================= */
async function runPipelineNow() {
  const btn = $("#hs-run");
  btn.disabled = true;
  btn.textContent = "⏳ 生成中（约 1-3 分钟）…";
  toast("开始生成今日内容，请耐心等待…");
  try {
    const r = await api("/api/pipeline/run", { method: "POST" });
    if (r.ok) toast(`已生成：热点 ${r.hotspots} 条 / 话题卡 ${r.cards} 张（待审核）`);
    else toast("生成部分失败：" + (r.errors || []).join("；").slice(0, 80));
  } catch (e) {
    toast("生成失败：" + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ 立即生成今日";
    await loadHotspots();
    await loadCards();
    refreshOverview();
  }
}
async function runCatchup() {
  toast("开始补拉缺失天数…");
  try {
    const r = await api("/api/pipeline/catchup", { method: "POST" });
    toast(`补拉完成：${(r.caught_up || []).join(", ") || "无缺失"}`);
  } catch (e) {
    toast("补拉失败：" + e.message);
  }
  refreshOverview();
}

/* ================= 弹窗 ================= */
function showModal() { $("#modal-mask").classList.remove("hidden"); }
function hideModal() {
  $("#modal-mask").classList.add("hidden");
  STATE.modal = { kind: "", id: null };
}

/* ================= 事件绑定 ================= */
function bindEvents() {
  $$(".tab").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

  // 热点
  $("#hs-refresh").addEventListener("click", loadHotspots);
  $("#hs-add").addEventListener("click", () => openHotspotModal());
  $("#hs-run").addEventListener("click", runPipelineNow);
  $("#hs-q").addEventListener("input", debounce(loadHotspots, 300));
  $("#hs-date").addEventListener("change", loadHotspots);
  $("#hs-status").addEventListener("change", loadHotspots);
  $("#hs-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) actHotspot(btn.dataset.act, btn.dataset.id);
  });

  // 话题卡
  $("#tc-refresh").addEventListener("click", loadCards);
  $("#tc-add").addEventListener("click", () => openCardModal());
  $("#tc-q").addEventListener("input", debounce(loadCards, 300));
  $("#tc-theme").addEventListener("change", loadCards);
  $("#tc-status").addEventListener("change", loadCards);
  $("#tc-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) actCard(btn.dataset.act, btn.dataset.id);
  });

  // 语段库
  $("#ph-refresh").addEventListener("click", loadPhrases);
  $("#ph-add").addEventListener("click", () => openPhraseModal());
  $("#ph-q").addEventListener("input", debounce(loadPhrases, 300));
  $("#ph-collected").addEventListener("change", (e) => {
    STATE.filters.collected = e.target.checked ? "1" : "";
    loadPhrases();
  });
  $("#ph-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) actPhrase(btn.dataset.act, btn.dataset.id);
  });
  $$(".filters").forEach((g) => g.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const key = chip.dataset.group.replace("f-", "");
    STATE.filters[key] = STATE.filters[key] === chip.dataset.val ? "" : chip.dataset.val;
    applyChipState();
    loadPhrases();
  }));

  // 设置
  $("#cfg-save").addEventListener("click", saveSettings);
  $("#cfg-catch-run").addEventListener("click", runCatchup);

  // 弹窗
  $("#modal-close").addEventListener("click", hideModal);
  $("#modal-cancel").addEventListener("click", hideModal);
  $("#modal-save").addEventListener("click", () => {
    const k = STATE.modal.kind;
    if (k === "hotspot") saveHotspotModal();
    else if (k === "card") saveCardModal();
    else if (k === "phrase") savePhraseModal();
  });
  $("#modal-mask").addEventListener("click", (e) => { if (e.target.id === "modal-mask") hideModal(); });
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ================= 启动 ================= */
(async function init() {
  bindEvents();
  renderFilterBar();
  await loadThemes();
  await refreshOverview();
  switchTab("hotspots");
  setInterval(refreshOverview, 30000);
})();
