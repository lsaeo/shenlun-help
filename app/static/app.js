/* 公考申论素材助手 V2 — 前端逻辑（原生 JS，无依赖） */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const STATE = {
  tab: "hotspots",
  filters: { position: "", theme: "", technique: "", collected: false },
  exFilters: { kind: "", theme: "", collected: false },
  themes: [],
  modal: { kind: "", id: null },
  fwTheme: "",
  inReview: {},      // "type:id" -> true
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
function anglesTags(it) {
  const a = it?.angles || [];
  if (!a.length) return "";
  return `<div class="angles-row">${a.map((x) =>
    `<button class="angle-chip" data-angle="${esc(x)}">${esc(x)}</button>`).join("")}</div>`;
}
function reviewBtn(type, id) {
  const key = `${type}:${id}`;
  if (STATE.inReview[key]) {
    return `<span class="tag published">📌 已入复习池</span>`;
  }
  return `<button class="btn accent small" data-act="review-add" data-type="${type}" data-id="${id}">✔ 背完了</button>`;
}
function hl(text) {
  /* 重点内容高亮（可背金句/要点） */
  return `<span class="hl-em">${esc(text)}</span>`;
}

/* ---------- 概览 ---------- */
async function refreshOverview() {
  try {
    const o = await api("/api/overview");
    $("#overview").innerHTML =
      `<span class="badge">热点 ${o.hotspots_total}</span>` +
      (o.hotspots_draft ? `<span class="badge warn">待审热点 ${o.hotspots_draft}</span>` : "") +
      `<span class="badge">话题卡 ${o.cards_total}</span>` +
      `<span class="badge">语段 ${o.phrases_total}</span>` +
      `<span class="badge">表达 ${o.expressions_total}</span>` +
      `<span class="badge">复习池 ${o.review_pool}</span>` +
      (o.review_due ? `<span class="badge warn">今日待复习 ${o.review_due}</span>` : "") +
      `<span class="badge">更新至 ${o.last_update_date || "—"}</span>`;
  } catch (e) { /* 服务未就绪时静默 */ }
}

/* ---------- 复习状态缓存 ---------- */
async function loadReviewState() {
  try {
    const r = await api("/api/review");
    STATE.inReview = {};
    r.items.forEach((it) => { STATE.inReview[`${it.type}:${it.item_id}`] = true; });
  } catch (e) { /* ignore */ }
}

/* ---------- 标签页 ---------- */
function switchTab(tab) {
  STATE.tab = tab;
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${tab}`));
  if (tab === "hotspots") loadHotspots();
  if (tab === "cards") loadCards();
  if (tab === "phrases") loadPhrases();
  if (tab === "expressions") loadExpressions();
  if (tab === "framework") loadFramework();
  if (tab === "review") loadReview();
  if (tab === "settings") loadSettings();
}

/* ================= 今日热点（V2 三层展示） ================= */
async function loadHotspots() {
  const q = $("#hs-q").value.trim();
  const date = $("#hs-date").value;
  const status = $("#hs-status").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
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
        ${it.why ? `<span>💡 ${esc(it.why)}</span>` : ""}
        ${(it.subjects || []).length ? it.subjects.map((s) => `<span class="tag">${esc(s)}</span>`).join("") : ""}
      </div>
      <div class="item-body">
        ${it.可背金句 ? `<div class="field"><span class="field-label">可背金句</span>${hl(it.可背金句)}</div>` : ""}
        ${(it.重点提炼 || []).length ? `
          <div class="field"><span class="field-label">重点提炼</span>
          <ul>${it.重点提炼.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>` : ""}
        ${it.意义 ? `<div class="field"><span class="field-label">意义</span>${esc(it.意义)}</div>` : ""}
        ${it.角度?.length ? `<div class="field"><span class="field-label">角度</span>${fmtList(it.角度)}</div>` : ""}
        ${it.对策?.length ? `<div class="field"><span class="field-label">对策</span>${fmtList(it.对策)}</div>` : ""}
        ${it.金句 ? `<div class="field"><span class="field-label">金句</span>${esc(it.金句)}</div>` : ""}
        ${anglesTags(it)}
      </div>
      ${it.summary ? `
        <details class="collapse">
          <summary>📄 原文摘要（点击展开）</summary>
          <div class="collapse-body">${esc(it.summary)}</div>
        </details>` : ""}
      <div class="item-actions">
        ${reviewBtn("hotspots", it.id)}
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
  let it = { date: d, title: "", source: "", url: "", summary: "", 重点提炼: [], 可背金句: "", 意义: "", 角度: [], 对策: [], 金句: "", angles: [] };
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
      <label>来源 <input id="f-source" type="text" value="${esc(it.source || "")}" placeholder="如：中国政府网"></label>
      <label>原文链接 <input id="f-url" type="text" value="${esc(it.url || "")}"></label>
    </div>
    <label>重点提炼（每行一条核心要点）<textarea id="f-points" style="min-height:60px">${esc((it.重点提炼 || []).join("\n"))}</textarea></label>
    <label>可背金句（一句话，直接背）<textarea id="f-quotable">${esc(it.可背金句 || "")}</textarea></label>
    <label>摘要（折叠区）<textarea id="f-summary" placeholder="新闻内容摘要（可留空）">${esc(it.summary || "")}</textarea></label>
    <label>意义（该事件为何重要、对应申论主题）<textarea id="f-meaning">${esc(it.意义 || "")}</textarea></label>
    <label>角度（每行一个论述切入点）<textarea id="f-angles" placeholder="角度1\n角度2">${esc((it.角度 || []).join("\n"))}</textarea></label>
    <label>对策（每行一条）<textarea id="f-measures" placeholder="对策1\n对策2">${esc((it.对策 || []).join("\n"))}</textarea></label>
    <label>金句 <textarea id="f-quote">${esc(it.金句 || "")}</textarea></label>
    <label>可用方向（每行一个论点，如 共建共治共享）<textarea id="f-useangles">${esc((it.angles || []).join("\n"))}</textarea></label>`;
  showModal();
}
async function saveHotspotModal() {
  const data = {
    date: $("#f-date").value,
    title: $("#f-title").value.trim(),
    source: $("#f-source").value.trim(),
    url: $("#f-url").value.trim(),
    summary: $("#f-summary").value.trim(),
    重点提炼: $("#f-points").value.split("\n").map((s) => s.trim()).filter(Boolean),
    可背金句: $("#f-quotable").value.trim(),
    意义: $("#f-meaning").value.trim(),
    角度: $("#f-angles").value.split("\n").map((s) => s.trim()).filter(Boolean),
    对策: $("#f-measures").value.split("\n").map((s) => s.trim()).filter(Boolean),
    金句: $("#f-quote").value.trim(),
    angles: $("#f-useangles").value.split("\n").map((s) => s.trim()).filter(Boolean),
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
        ${it.金句 ? `<div class="field"><span class="field-label">金句</span>${hl(it.金句)}</div>` : ""}
        ${anglesTags(it)}
      </div>
      <div class="item-actions">
        ${reviewBtn("topic_cards", it.id)}
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
  let it = { date: d, theme: STATE.themes[0] || "", topic: "", 背景: "", 意义: "", 问题: "", 对策: [], 金句: "", angles: [] };
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
    <label>金句 <textarea id="f-quote">${esc(it.金句 || "")}</textarea></label>
    <label>可用方向（每行一个）<textarea id="f-useangles">${esc((it.angles || []).join("\n"))}</textarea></label>`;
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
    angles: $("#f-useangles").value.split("\n").map((s) => s.trim()).filter(Boolean),
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
      ${anglesTags(it)}
      ${it.usage ? `<div class="usage">💡 ${esc(it.usage)}</div>` : ""}
      <div class="item-actions">
        ${reviewBtn("phrases", it.id)}
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
  let it = { text: "", template: "", examples: [], position: [], theme: [], technique: [], usage: "", angles: [] };
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
    <label>可用方向（每行一个论点，如 共建共治共享）<textarea id="f-useangles">${esc((it.angles || []).join("\n"))}</textarea></label>
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
  data.angles = $("#f-useangles").value.split("\n").map((s) => s.trim()).filter(Boolean);
  data.usage = $("#f-usage").value.trim();
  const id = STATE.modal.id;
  if (id) await api(`/api/phrases/${id}`, { method: "PUT", body: JSON.stringify({ data }) });
  else await api("/api/phrases", { method: "POST", body: JSON.stringify({ data }) });
  hideModal();
  toast("已保存");
  await loadPhrases();
  refreshOverview();
}

/* ================= 表达库 ================= */
function renderExprFilterBar() {
  const groups = {
    "f-kind": ["规范词", "好词", "平易词"],
    "f-extheme": STATE.themes,
  };
  for (const [gid, opts] of Object.entries(groups)) {
    const g = $(`#${gid}`);
    if (!g) continue;
    g.innerHTML = `<span class="fg-label">${gid === "f-kind" ? "类型" : "主题"}</span>` +
      opts.map((o) => `<button class="chip" data-group="${gid}" data-val="${esc(o)}">${esc(o)}</button>`).join("");
  }
  applyExprChipState();
}
function applyExprChipState() {
  $$(".chip[data-group^=f-]").forEach((c) => {
    const gid = c.dataset.group;
    if (gid === "f-kind" || gid === "f-extheme") {
      const key = gid === "f-kind" ? "kind" : "theme";
      c.classList.toggle("on", STATE.exFilters[key] === c.dataset.val);
    }
  });
}
async function loadExpressions() {
  const p = new URLSearchParams();
  if (STATE.exFilters.kind) p.set("kind", STATE.exFilters.kind);
  if (STATE.exFilters.theme) p.set("theme", STATE.exFilters.theme);
  if (STATE.exFilters.collected) p.set("collected", "1");
  const q = $("#ex-q").value.trim();
  if (q) p.set("q", q);
  const { items } = await api(`/api/expressions/filter?${p}`);
  renderExpressions(items);
}
function renderExpressions(items) {
  const box = $("#ex-list");
  if (!items.length) {
    box.innerHTML = `<div class="empty">暂无匹配表达。调整筛选或「＋ 新增表达」。</div>`;
    return;
  }
  box.innerHTML = items.map((it) => `
    <div class="item">
      <div class="expr-text">${esc(it.text)}</div>
      <div class="tags-row">
        ${(it.kind || []).map((k) => `<span class="tag kind-${esc(k)}">${esc(k)}</span>`).join("")}
        ${(it.theme || []).map((t) => `<span class="tag">题·${esc(t)}</span>`).join("")}
      </div>
      ${it.example ? `<div class="usage">✍️ ${esc(it.example)}</div>` : ""}
      <div class="item-actions">
        <button class="btn primary small" data-act="copy" data-id="${it.id}">📋 复制</button>
        <button class="btn small ${it.collected ? "collected" : ""}" data-act="collect" data-id="${it.id}">
          ${it.collected ? "★ 已收藏" : "☆ 收藏"}
        </button>
        <button class="btn small" data-act="edit" data-id="${it.id}">编辑</button>
        <button class="btn danger small" data-act="delete" data-id="${it.id}">删除</button>
      </div>
    </div>`).join("");
}
async function actExpression(act, id) {
  if (act === "copy") {
    const it = await api(`/api/expressions/${id}`);
    await copyText(it.text);
    toast("已复制");
  } else if (act === "collect") {
    await api(`/api/expressions/${id}/toggle-collect`, { method: "POST" });
    await loadExpressions();
  } else if (act === "delete") {
    if (!confirm("确定删除？")) return;
    await api(`/api/expressions/${id}`, { method: "DELETE" });
    toast("已删除");
    await loadExpressions();
  } else if (act === "edit") {
    openExprModal(id);
  }
  refreshOverview();
}
function openExprModal(id = null) {
  STATE.modal = { kind: "expression", id };
  $("#modal-title").textContent = id ? "编辑表达" : "新增表达";
  let it = { text: "", kind: [], theme: [], example: "" };
  if (id) {
    api(`/api/expressions/${id}`).then((r) => { it = r; buildExprForm(it); });
    return;
  }
  buildExprForm(it);
}
function buildExprForm(it) {
  $("#modal-body").innerHTML = `
    <label>表达内容 <input id="f-text" type="text" value="${esc(it.text || "")}" placeholder="如：共建共治共享"></label>
    <label>类型（可多选）
      <div class="check-grid">
        ${["规范词", "好词", "平易词"].map((k) => {
          const on = (it.kind || []).includes(k);
          return `<label class="check"><input type="checkbox" data-cat="kind" value="${esc(k)}" ${on ? "checked" : ""}> ${esc(k)}</label>`;
        }).join("")}
      </div>
    </label>
    <label>主题（可多选）
      <div class="check-grid">
        ${STATE.themes.map((t) => {
          const on = (it.theme || []).includes(t);
          return `<label class="check"><input type="checkbox" data-cat="theme" value="${esc(t)}" ${on ? "checked" : ""}> ${esc(t)}</label>`;
        }).join("")}
      </div>
    </label>
    <label>例句 / 用法 <textarea id="f-example">${esc(it.example || "")}</textarea></label>`;
  showModal();
}
async function saveExprModal() {
  const text = $("#f-text").value.trim();
  if (!text) { toast("内容不能为空"); return; }
  const data = { text, example: $("#f-example").value.trim() };
  for (const cat of ["kind", "theme"]) {
    data[cat] = $$(`input[data-cat="${cat}"]:checked`).map((c) => c.value);
  }
  if (!data.kind.length) { toast("至少选一个类型"); return; }
  const id = STATE.modal.id;
  if (id) await api(`/api/expressions/${id}`, { method: "PUT", body: JSON.stringify({ data }) });
  else await api("/api/expressions", { method: "POST", body: JSON.stringify({ data }) });
  hideModal();
  toast("已保存");
  await loadExpressions();
  refreshOverview();
}

/* ================= 框架（主题树 + 拆解 + 骨架） ================= */
async function loadFramework() {
  const { items } = await api("/api/topics");
  const nav = $("#fw-theme-nav");
  nav.innerHTML = STATE.themes.map((t) =>
    `<button class="fw-theme-btn ${t === STATE.fwTheme ? "on" : ""}" data-theme="${esc(t)}">${esc(t)}</button>`).join("");
  // 默认选中第一个主题
  if (!STATE.fwTheme && STATE.themes.length) STATE.fwTheme = STATE.themes[0];
  if (STATE.fwTheme) renderFrameworkContent(STATE.fwTheme, items);
}
async function renderFrameworkContent(theme, topics) {
  STATE.fwTheme = theme;
  $$(".fw-theme-btn").forEach((b) => b.classList.toggle("on", b.dataset.theme === theme));
  const box = $("#fw-content");
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const topic = (topics || []).find((t) => t.theme === theme) || { theme, dimensions: [] };
  const fw = await api(`/api/framework/${encodeURIComponent(theme)}`);
  const dims = (topic.dimensions || []).map((d, di) => `
    <details class="fw-dim">
      <summary>
        <span class="fw-dim-name">${esc(d.name)}</span>
        ${(d.items || []).map((i) => `<span class="tag">${esc(i)}</span>`).join("")}
      </summary>
      <div class="fw-dim-detail">
        ${d.explain ? `<div class="fw-dim-explain">💡 ${esc(d.explain)}</div>` : ""}
        ${(d.cases || []).length ? `
          <div class="fw-dim-cases"><b>使用案例：</b>
          ${d.cases.map((c) => `<div class="fw-item">· ${esc(c)}</div>`).join("")}</div>` : ""}
      </div>
    </details>`).join("") || `<div class="hint">该主题暂无拆解维度</div>`;
  const tmpls = (fw.templates || []).map((t) => `
    <div class="tmpl-card">
      <div class="tmpl-head">
        <b>${esc(t.title)}</b>
        <span class="tag">${(t.theme || []).join("、")}</span>
        <span class="tmpl-src">${esc(t.source || "")}</span>
      </div>
      <div class="tmpl-structure">
        ${(t.structure || []).map((s) => `
          <div class="tmpl-part">
            <span class="sk-label">${esc(s.part)}</span>
            <div class="tmpl-role">${esc(s.role)}</div>
            <div class="tmpl-how">写法：${esc(s.how)}</div>
            ${s.pattern ? `<div class="tmpl-pattern">句式：${esc(s.pattern)}</div>` : ""}
            ${s.excerpt ? `<div class="tmpl-excerpt">原文：${esc(s.excerpt)}</div>` : ""}
          </div>`).join("")}
      </div>
      ${(t.killer_sentences || []).length ? `
        <div class="tmpl-killers"><b>可背金句：</b>${t.killer_sentences.map((k) => `<div class="hl-em">${esc(k)}</div>`).join("")}</div>` : ""}
      <div class="item-actions">
        <button class="btn small" data-act="tmpl-edit" data-id="${t.id}">编辑</button>
        <button class="btn danger small" data-act="tmpl-delete" data-id="${t.id}">删除</button>
      </div>
    </div>`).join("");
  box.innerHTML = `
    <div class="fw-block">
      <h3>📐 主题拆解（可点击维度看解释）</h3>
      <div class="fw-dims">${dims}</div>
    </div>
    <div class="fw-block">
      <h3>💬 表达库（${fw.expressions.length}）</h3>
      <div class="fw-chips">${fw.expressions.map((e) =>
        `<button class="angle-chip" data-jump="expressions" data-q="${esc(e.text)}">${esc(e.text)}</button>`).join("") || "无"}</div>
    </div>
    <div class="fw-block">
      <h3>📝 语段（${fw.phrases.length}）</h3>
      ${fw.phrases.slice(0, 8).map((p) => `<div class="fw-phrase">${esc(p.text)}</div>`).join("") || "无"}
    </div>
    <div class="fw-block">
      <h3>🔥 相关热点（${fw.hotspots.length}）</h3>
      ${fw.hotspots.slice(0, 6).map((h) => `<div class="fw-item">· ${esc(h.title)}</div>`).join("") || "无"}
    </div>
    <div class="fw-block">
      <h3>🎴 话题卡（${fw.cards.length}）</h3>
      ${fw.cards.slice(0, 6).map((c) => `<div class="fw-item">· [${esc(c.theme)}] ${esc(c.topic)}</div>`).join("") || "无"}
    </div>
    <div class="fw-block">
      <h3>🧩 案例素材（${fw.cases.length}）</h3>
      ${fw.cases.slice(0, 6).map((c) => `<div class="fw-item">· ${esc(c.title)}</div>`).join("") || "无"}
    </div>
    <div class="fw-block">
      <h3>🦴 范文模板库（${fw.templates.length}）</h3>
      ${tmpls || `<div class="hint">暂无模板。点击上方「📄 范文模板」抓取/粘贴范文，确认后 AI 解析成模板。</div>`}
    </div>`;
}
async function actFrameworkJump(e) {
  const btn = e.target.closest("[data-jump]");
  if (!btn) return;
  const q = btn.dataset.q || "";
  // 双向联动：跳到表达库 → 清筛选 → 定位高亮
  STATE.exFilters = { kind: "", theme: "", collected: false };
  applyExprChipState();
  switchTab("expressions");
  $("#ex-q").value = q;
  await loadExpressions();
  // 定位高亮
  try {
    const loc = await api(`/api/expressions/locate?q=${encodeURIComponent(q)}`);
    if (loc.found) {
      const items = $$("#ex-list .expr-text");
      const target = items.find((el) => el.textContent.trim() === q);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.closest(".item").classList.add("locate-flash");
        setTimeout(() => target.closest(".item")?.classList.remove("locate-flash"), 2500);
      }
    }
  } catch (err) { /* ignore */ }
}

/* ================= 复习 ================= */
async function loadReview() {
  const r = await api("/api/review");
  STATE.inReview = {};
  r.items.forEach((it) => { STATE.inReview[`${it.type}:${it.item_id}`] = true; });
  const due = await api("/api/review/due");
  renderReviewDue(due.due);
  renderReviewRandom(due.random);
  renderReviewPool(r.items);
}
function reviewCard(r) {
  const c = r.content;
  const title = c ? (c.title || c.topic || c.text || c.topic || "") : "";
  const short = c ? (c.可背金句 || c.金句 || c.template || (c.text || "").slice(0, 80) || c.背景 || "") : "";
  const typeName = { hotspots: "热点", topic_cards: "话题卡", phrases: "语段" }[r.type] || r.type;
  return `
    <div class="item rv-item">
      <div class="item-head">
        <div class="item-title">[${esc(typeName)}] ${esc(String(title).slice(0, 60))}</div>
        <span class="tag">第${r.stage || 0}级</span>
      </div>
      ${short ? `<div class="item-body"><div class="field"><span class="field-label">回忆点</span>${esc(String(short).slice(0, 120))}</div></div>` : ""}
      <div class="item-actions">
        <button class="btn primary small" data-act="answer" data-type="${r.type}" data-id="${r.item_id}" data-result="remember">😀 记住了</button>
        <button class="btn small" data-act="answer" data-type="${r.type}" data-id="${r.item_id}" data-result="fuzzy">😐 模糊</button>
        <button class="btn small" data-act="answer" data-type="${r.type}" data-id="${r.item_id}" data-result="forget">😵 忘了</button>
        <button class="btn danger small" data-act="rv-remove" data-type="${r.type}" data-id="${r.item_id}">移出</button>
      </div>
    </div>`;
}
function renderReviewDue(due) {
  const box = $("#rv-due");
  box.innerHTML = due.length ? due.map(reviewCard).join("")
    : `<div class="empty">今日无到期复习项 🎉（去各库点「✔ 背完了」加入复习池）</div>`;
}
function renderReviewRandom(items) {
  const box = $("#rv-random");
  $("#rv-random-title").textContent = items.length ? "随机抽查" : "随机抽查（暂无，先去各库加入复习池）";
  box.innerHTML = items.length ? items.map(reviewCard).join("") : "";
}
function renderReviewPool(items) {
  const box = $("#rv-pool");
  if (!items.length) {
    box.innerHTML = `<div class="empty">复习池为空。在热点/话题卡/语段/表达页点「✔ 背完了」加入。</div>`;
    return;
  }
  box.innerHTML = items.map((r) => {
    const c = r.content;
    const title = c ? (c.title || c.topic || c.text || "") : "";
    const typeName = { hotspots: "热点", topic_cards: "话题卡", phrases: "语段" }[r.type] || r.type;
    return `<div class="item">
      <div class="item-head"><div class="item-title">[${esc(typeName)}] ${esc(String(title).slice(0, 50))}</div>
        <span class="tag">下次 ${esc(r.next_review || "—")}</span></div>
      <div class="item-actions">
        <button class="btn small" data-act="rv-remove" data-type="${r.type}" data-id="${r.item_id}">移出复习池</button>
      </div>
    </div>`;
  }).join("");
}
async function actReview(act, el) {
  const type = el.dataset.type, id = el.dataset.id;
  if (act === "answer") {
    await api(`/api/review/${type}/${id}/answer`, { method: "POST", body: JSON.stringify({ data: { result: el.dataset.result } }) });
    toast("已记录");
  } else if (act === "rv-remove") {
    await api(`/api/review/${type}/${id}/remove`, { method: "POST" });
    toast("已移出复习池");
  } else if (act === "review-add") {
    await api(`/api/review/${type}/${id}/add`, { method: "POST" });
    toast("已加入复习池 ✔ 明天开始安排复习");
    // 背完后立即移除当前卡片，列表自动上移（不重新加载整列表，避免滚动位置跳变）
    const card = el.closest(".item");
    if (card) {
      card.style.opacity = "0.3";
      card.style.transition = "opacity 0.2s";
      setTimeout(() => {
        card.remove();
        // 若列表空了显示空态
        const box = card.parentElement;
        if (box && box.querySelectorAll(".item").length === 0 && box.id === "ph-list") {
          box.innerHTML = `<div class="empty">暂无匹配语段。调整筛选条件或「＋ 新增语段」。</div>`;
        }
        if (box && box.querySelectorAll(".item").length === 0 && box.id === "hs-list") {
          box.innerHTML = `<div class="empty">暂无热点。点击「⚡ 立即生成今日」或「＋ 手动录入」。</div>`;
        }
      }, 250);
    }
  }
  await loadReviewState();
  await refreshOverview();
  if (STATE.tab === "review") await loadReview();
}

/* ================= 范文模板区（本地轮转） ================= */
async function toggleFanwenPanel() {
  const panel = $("#fanwen-panel");
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) await loadFanwen();
}
async function loadFanwen() {
  try {
    const r = await api("/api/fanwen/index");
    const s = r.stats || {};
    const files = await api("/api/fanwen/list-files");
    $("#fanwen-stats").innerHTML =
      `📊 本地范文：共 <b>${s.total || 0}</b> 篇 ｜ 待解析 <b class="hl-em">${s.pending || 0}</b> ｜ ` +
      `已解析 ${s.resolved || 0} ｜ 已跳过 ${s.skipped || 0}`;
    // 进度条
    const pct = s.total ? Math.round(((s.resolved + s.skipped) / s.total) * 100) : 0;
    $("#fanwen-progress-bar").style.setProperty("--pct", pct + "%");
    $("#fanwen-progress-text").textContent = `进度 ${pct}%（已解析 ${s.resolved || 0} / ${s.total || 0}）`;
    // 文件列表：in_index=true 灰色不可点（已在轮转队列），false 绿色可点击
    const fl = (files.files || []).map((f) => f.in_index
      ? `<button class="btn small disabled" disabled title="已在每日轮转队列，将自动解析">📄 ${esc(f.name)}</button>`
      : `<button class="btn small new-file" data-act="fanwen-parse-file" data-path="${esc(f.path)}" data-name="${esc(f.name)}">📄 ${esc(f.name)}</button>`).join("");
    $("#fanwen-file-list").innerHTML = fl || `<span class="hint">sucai/ 下暂无可解析文件</span>`;
    // 轮转队列：左=已完成，右=待解析（全部显示，各自滚动）
    const items = r.items || [];
    const done = items.filter((a) => a.status !== "待解析").map((a) =>
      `<div class="fw-item">${statusTag(a.status || "待解析")} ${esc((a.title || "").slice(0, 45))}</div>`).join("");
    const pending = items.filter((a) => a.status === "待解析").map((a) =>
      `<div class="fw-item">${statusTag("待解析")} ${esc((a.title || "").slice(0, 45))}</div>`).join("");
    $("#fanwen-queue-done").innerHTML = done || `<div class="hint">暂无</div>`;
    $("#fanwen-queue-pending").innerHTML = pending || `<div class="hint">全部完成 🎉</div>`;
  } catch (e) {
    $("#fanwen-stats").textContent = "加载失败：" + e.message;
  }
}
async function parseFanwenFile(path, name) {
  toast(`AI 解析「${name}」中（约 1 分钟）…`);
  try {
    const r = await api("/api/fanwen/parse-file", { method: "POST", body: JSON.stringify({ data: { path, title: name } }) });
    toast("✅ 模板已生成，见框架栏模板区");
    if (STATE.fwTheme) loadFramework();
  } catch (e) {
    toast("解析失败：" + e.message);
  }
}

/* ================= 拆解树编辑 ================= */
function openTreeEdit() {
  STATE.modal = { kind: "tree" };
  $("#modal-title").textContent = `编辑拆解：${STATE.fwTheme}`;
  const t = STATE.fwTheme;
  const rows = () => {
    const topic = null;
    return api("/api/topics").then((r) => {
      const found = (r.items || []).find((x) => x.theme === t) || { theme: t, dimensions: [] };
      return (found.dimensions || []).map((d, i) => `
        <div class="tree-dim-row" data-idx="${i}">
          <input type="text" data-f="name" value="${esc(d.name)}" placeholder="维度名">
          <input type="text" data-f="items" value="${esc((d.items || []).join("、"))}" placeholder="素材标签（顿号分隔）">
          <input type="text" data-f="explain" value="${esc(d.explain || "")}" placeholder="解释（是什么/为什么考）">
          <input type="text" data-f="cases" value="${esc((d.cases || []).join("；"))}" placeholder="使用案例（分号分隔）">
          <button class="btn danger small" data-act="tree-dim-del" data-idx="${i}">✕</button>
        </div>`).join("") || `<div class="hint">暂无维度</div>`;
    });
  };
  rows().then((html) => {
    $("#modal-body").innerHTML = `
      <div class="tree-edit-list">${html}</div>
      <button class="btn" id="tree-dim-add">＋ 添加维度</button>
      <p class="hint">每行：维度名 ｜ 素材标签（顿号分隔）｜ 解释 ｜ 使用案例（分号分隔）</p>`;
    $("#tree-dim-add").addEventListener("click", () => {
      const list = $(".tree-edit-list");
      const row = document.createElement("div");
      row.className = "tree-dim-row";
      row.innerHTML = `
        <input type="text" data-f="name" placeholder="维度名">
        <input type="text" data-f="items" placeholder="素材标签（顿号分隔）">
        <input type="text" data-f="explain" placeholder="解释">
        <input type="text" data-f="cases" placeholder="使用案例">
        <button class="btn danger small" data-act="tree-dim-del">✕</button>`;
      list.appendChild(row);
    });
    $(".tree-edit-list").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act=tree-dim-del]");
      if (btn) btn.closest(".tree-dim-row").remove();
    });
  });
  showModal();
}
async function saveTreeEdit() {
  const dims = [];
  $$(".tree-dim-row").forEach((row) => {
    const name = row.querySelector('[data-f="name"]').value.trim();
    if (!name) return;
    const items = row.querySelector('[data-f="items"]').value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean);
    const explain = row.querySelector('[data-f="explain"]').value.trim();
    const cases = row.querySelector('[data-f="cases"]').value.split(/[；;]/).map((s) => s.trim()).filter(Boolean);
    dims.push({ name, items, explain, cases });
  });
  await api(`/api/topics/${encodeURIComponent(STATE.fwTheme)}`, { method: "PUT", body: JSON.stringify({ data: { dimensions: dims } }) });
  hideModal();
  toast("拆解已保存");
  loadFramework();
}

/* ================= 模板编辑 ================= */
async function openTemplateEdit(id) {
  STATE.modal = { kind: "template", id };
  const it = await api(`/api/templates/${id}`);
  $("#modal-title").textContent = "编辑模板";
  $("#modal-body").innerHTML = `
    <label>标题 <input id="f-title" type="text" value="${esc(it.title || "")}"></label>
    <label>适用主题（顿号分隔）<input id="f-theme" type="text" value="${esc((it.theme || []).join("、"))}"></label>
    <label>可背金句（每行一句）<textarea id="f-killers" style="min-height:60px">${esc((it.killer_sentences || []).join("\n"))}</textarea></label>
    <label>结构解析（每行一段：段落名｜作用｜写法｜可套用句式）
      <textarea id="f-structure" style="min-height:160px">${esc((it.structure || []).map((s) =>
        [s.part, s.role, s.how, s.pattern].join("｜")).join("\n"))}</textarea></label>`;
  showModal();
}
async function saveTemplateEdit() {
  const data = {
    title: $("#f-title").value.trim(),
    theme: $("#f-theme").value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean),
    killer_sentences: $("#f-killers").value.split("\n").map((s) => s.trim()).filter(Boolean),
    structure: $("#f-structure").value.split("\n").map((line) => {
      const [part, role, how, pattern] = line.split("｜").map((s) => (s || "").trim());
      return { part, role, how, pattern, excerpt: "" };
    }).filter((s) => s.part),
  };
  await api(`/api/templates/${STATE.modal.id}`, { method: "PUT", body: JSON.stringify({ data }) });
  hideModal();
  toast("模板已保存");
  loadFramework();
}

/* ================= AI 拆解弹窗 ================= */
function openDecompose() {
  $("#decompose-mask").classList.remove("hidden");
  $("#dc-desc").value = "";
  $("#dc-result").innerHTML = "";
}
function closeDecompose() {
  $("#decompose-mask").classList.add("hidden");
}
async function runDecompose() {
  const desc = $("#dc-desc").value.trim();
  if (!desc) { toast("请先粘贴现象描述"); return; }
  const btn = $("#dc-run");
  btn.disabled = true;
  btn.textContent = "⏳ 拆解中…";
  try {
    const r = await api("/api/cases/decompose", { method: "POST", body: JSON.stringify({ data: { description: desc } }) });
    $("#dc-result").innerHTML = `
      <div class="dc-block"><b>标题：</b>${esc(r.title || "—")}</div>
      <div class="dc-block"><b>背景：</b>${esc(r.background || "—")}</div>
      <div class="dc-block"><b>问题：</b><ul>${(r.problems || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="dc-block"><b>对策：</b><ul>${(r.measures || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="dc-block"><b>可用方向：</b>${(r.angles || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>
      <div class="dc-block"><b>主题：</b>${esc(r.theme || "—")}</div>
      <button class="btn primary" id="dc-save">存入案例库（草稿）</button>`;
    window.__DC_RESULT__ = r;
    $("#dc-save").addEventListener("click", async () => {
      const data = { title: window.__DC_RESULT__.title || desc.slice(0, 15), description: desc,
        background: window.__DC_RESULT__.background || "", problems: window.__DC_RESULT__.problems || [],
        measures: window.__DC_RESULT__.measures || [], angles: window.__DC_RESULT__.angles || [],
        theme: window.__DC_RESULT__.theme || "", date: new Date().toISOString().slice(0, 10) };
      await api("/api/cases", { method: "POST", body: JSON.stringify({ data }) });
      toast("已存入案例库（草稿）");
      closeDecompose();
    });
  } catch (e) {
    $("#dc-result").innerHTML = `<div class="dc-block">拆解失败：${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "🤖 开始拆解";
  }
}

/* ================= 设置 ================= */
async function loadSettings() {
  const cfg = await api("/api/config");
  $("#cfg-provider").value = cfg.ai_provider || "deepseek";
  $("#cfg-key").value = cfg.api_key || "";
  $("#cfg-base").value = cfg.api_base || "https://api.deepseek.com";
  $("#cfg-model").value = cfg.model || "deepseek-v4-flash";
  $("#cfg-gemini-key").value = cfg.gemini_api_key || "";
  $("#cfg-gemini-model").value = cfg.gemini_model || "gemini-2.0-flash";
  $("#cfg-custom-base").value = cfg.custom_api_base || "https://api.gemai.cc/v1";
  $("#cfg-custom-key").value = cfg.custom_api_key || "";
  $("#cfg-custom-model").value = cfg.custom_model || "[福利]gemini-3.5-flash";
  toggleProviderConfig();
  $("#cfg-time").value = cfg.update_time || "07:00";
  $("#cfg-hot").value = cfg.daily_hotspots || 5;
  $("#cfg-cards").value = cfg.daily_cards || 5;
  $("#cfg-phrases").value = cfg.daily_phrases ?? 3;
  $("#cfg-expr").value = cfg.daily_expressions ?? 3;
  $("#cfg-cases").value = cfg.daily_cases ?? 2;
  $("#cfg-fanwen").value = cfg.fanwen_interval_days ?? 3;
  $("#cfg-random").value = cfg.daily_random ?? 3;
  $("#cfg-catchup").value = cfg.catchup_limit ?? 3;
  $("#cfg-font-base").value = cfg.font_base ?? 14;
  $("#cfg-font-emph").value = cfg.font_emphasis ?? 16;
  $("#cfg-hint").textContent = `最近更新：${cfg.last_update_date || "从未"}；语段素材源：${(cfg.phrase_sources || []).map(s => s.name).join("、") || "未配置"}`;
}
function toggleProviderConfig() {
  const p = $("#cfg-provider").value;
  $("#cfg-block-deepseek").classList.toggle("hidden", p !== "deepseek");
  $("#cfg-block-gemini").classList.toggle("hidden", p !== "gemini");
  $("#cfg-block-custom").classList.toggle("hidden", p !== "custom");
}
async function saveSettings() {
  const data = {
    ai_provider: $("#cfg-provider").value || "deepseek",
    api_key: $("#cfg-key").value.trim(),
    api_base: $("#cfg-base").value.trim() || "https://api.deepseek.com",
    model: $("#cfg-model").value.trim() || "deepseek-v4-flash",
    gemini_api_key: $("#cfg-gemini-key").value.trim(),
    gemini_model: $("#cfg-gemini-model").value.trim() || "gemini-2.0-flash",
    custom_api_base: $("#cfg-custom-base").value.trim() || "https://api.gemai.cc/v1",
    custom_api_key: $("#cfg-custom-key").value.trim(),
    custom_model: $("#cfg-custom-model").value.trim() || "[福利]gemini-3.5-flash",
    update_time: $("#cfg-time").value || "07:00",
    daily_hotspots: Math.max(1, Math.min(20, Number($("#cfg-hot").value) || 5)),
    daily_cards: Math.max(1, Math.min(20, Number($("#cfg-cards").value) || 5)),
    daily_phrases: Math.max(0, Math.min(10, Number($("#cfg-phrases").value) || 0)),
    daily_expressions: Math.max(0, Math.min(10, Number($("#cfg-expr").value) || 0)),
    daily_cases: Math.max(0, Math.min(10, Number($("#cfg-cases").value) || 0)),
    fanwen_interval_days: Math.max(1, Math.min(30, Number($("#cfg-fanwen").value) || 3)),
    daily_random: Math.max(0, Math.min(20, Number($("#cfg-random").value) || 0)),
    catchup_limit: Math.max(0, Math.min(7, Number($("#cfg-catchup").value) || 3)),
    font_base: Math.max(13, Math.min(18, Number($("#cfg-font-base").value) || 14)),
    font_emphasis: Math.max(14, Math.min(22, Number($("#cfg-font-emph").value) || 16)),
  };
  await api("/api/config", { method: "PUT", body: JSON.stringify({ data }) });
  applyFonts();
  toast("设置已保存");
  refreshOverview();
}

/* ---------- 字体应用 ---------- */
async function applyFonts() {
  try {
    const cfg = await api("/api/config");
    const base = cfg.font_base || 14, emph = cfg.font_emphasis || 16;
    document.documentElement.style.setProperty("--font-base", base + "px");
    document.documentElement.style.setProperty("--font-emph", emph + "px");
  } catch (e) { /* ignore */ }
}

/* ================= 流水线（异步 + 进度） ================= */
let _ppTimer = null;
let _ppStart = 0;

function ppShow() {
  const el = $("#pipeline-progress");
  el.classList.remove("hidden");
  _ppStart = Date.now();
}
function ppHide() {
  const el = $("#pipeline-progress");
  el.classList.add("hidden");
  if (_ppTimer) { clearInterval(_ppTimer); _ppTimer = null; }
}
function ppRender(st) {
  const step = st.step || "";
  const msg = st.message || "";
  const done = st.done || 0, total = st.total || 0;
  $("#pp-step").textContent = step;
  $("#pp-msg").textContent = msg;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  $("#pp-bar").style.width = pct + "%";
  const secs = Math.round((Date.now() - _ppStart) / 1000);
  $("#pp-time").textContent = `⏱ ${Math.floor(secs / 60)}分${secs % 60}秒`;
  // 熔断/失败 → 显示重跑按钮
  const acts = $("#pp-actions");
  if (st.state === "stopped" || st.state === "failed") {
    acts.innerHTML = `
      <div class="pp-warn">⚠️ ${st.state === "stopped" ? "API 不可用，流水线已停止" : "流水线失败"}</div>
      <div class="pp-warn-msg">${esc(st.message || "")}</div>
      <button class="btn accent" id="pp-go-settings">⚙️ 去设置换 API</button>
      <button class="btn primary" id="pp-rerun">🔄 重跑全部任务</button>`;
    $("#pp-go-settings").addEventListener("click", () => { switchTab("settings"); ppHide(); });
    $("#pp-rerun").addEventListener("click", () => { ppHide(); runPipelineNow(); });
  } else if (st.state === "done" || st.state === "partial") {
    acts.innerHTML = `<div class="pp-ok">✅ ${st.state === "done" ? "全部完成" : "部分完成"}：${esc(st.message || "")}</div>
      <button class="btn small" id="pp-close">关闭</button>`;
    $("#pp-close").addEventListener("click", async () => {
      ppHide();
      await api("/api/pipeline/reset-status", { method: "POST" });
    });
  }
}
async function pollPipelineStatus() {
  const st = await api("/api/pipeline/status");
  if (st.state === "running") {
    ppShow();
    ppRender(st);
    _ppTimer = setInterval(async () => {
      try {
        const s2 = await api("/api/pipeline/status");
        ppRender(s2);
        if (s2.state !== "running") {
          clearInterval(_ppTimer); _ppTimer = null;
          await refreshOverview();
          loadHotspots(); loadCards();
        }
      } catch (e) { /* ignore */ }
    }, 1500);
  } else if (st.state === "stopped" || st.state === "failed") {
    ppShow();
    ppRender(st);
  }
}
async function runPipelineNow() {
  try {
    await api("/api/pipeline/run", { method: "POST" });
    toast("流水线已启动，可在下方看实时进度");
    ppShow();
    ppRender({ state: "running", step: "启动中", message: "正在准备…", done: 0, total: 6 });
    _ppTimer = setInterval(async () => {
      try {
        const st = await api("/api/pipeline/status");
        ppRender(st);
        if (st.state !== "running") {
          clearInterval(_ppTimer); _ppTimer = null;
          await refreshOverview();
          loadHotspots(); loadCards();
        }
      } catch (e) { /* ignore */ }
    }, 1500);
  } catch (e) {
    toast("启动失败：" + e.message);
    ppHide();
  }
}
async function runCatchup() {
  try {
    await api("/api/pipeline/catchup", { method: "POST" });
    toast("补拉已启动");
  } catch (e) {
    toast("补拉失败：" + e.message);
  }
}

/* ================= 一键入库 ================= */
async function publishAll(apiBase, refreshFn) {
  if (!confirm("确定将本库全部草稿入库？")) return;
  try {
    const r = await api(`${apiBase}/publish-all`, { method: "POST" });
    toast(`已入库 ${r.published} 条`);
  } catch (e) {
    toast("入库失败：" + e.message);
  }
  await refreshFn();
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
  $("#hs-publish-all").addEventListener("click", () => publishAll("/api/hotspots", loadHotspots));
  $("#hs-add").addEventListener("click", () => openHotspotModal());
  $("#hs-run").addEventListener("click", runPipelineNow);
  $("#hs-q").addEventListener("input", debounce(loadHotspots, 300));
  $("#hs-date").addEventListener("change", loadHotspots);
  $("#hs-status").addEventListener("change", loadHotspots);
  $("#hs-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) {
      if (btn.dataset.act === "review-add") actReview("review-add", btn);
      else actHotspot(btn.dataset.act, btn.dataset.id);
    }
  });

  // 话题卡
  $("#tc-refresh").addEventListener("click", loadCards);
  $("#tc-publish-all").addEventListener("click", () => publishAll("/api/topic_cards", loadCards));
  $("#tc-add").addEventListener("click", () => openCardModal());
  $("#tc-q").addEventListener("input", debounce(loadCards, 300));
  $("#tc-theme").addEventListener("change", loadCards);
  $("#tc-status").addEventListener("change", loadCards);
  $("#tc-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) {
      if (btn.dataset.act === "review-add") actReview("review-add", btn);
      else actCard(btn.dataset.act, btn.dataset.id);
    }
  });

  // 语段库
  $("#ph-refresh").addEventListener("click", loadPhrases);
  $("#ph-publish-all").addEventListener("click", () => publishAll("/api/phrases", loadPhrases));
  $("#ph-add").addEventListener("click", () => openPhraseModal());
  $("#ph-q").addEventListener("input", debounce(loadPhrases, 300));
  $("#ph-collected").addEventListener("change", (e) => {
    STATE.filters.collected = e.target.checked ? "1" : "";
    loadPhrases();
  });
  $("#ph-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) {
      if (btn.dataset.act === "review-add") actReview("review-add", btn);
      else actPhrase(btn.dataset.act, btn.dataset.id);
    }
  });
  $$(".filters").forEach((g) => g.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const gid = chip.dataset.group;
    if (gid === "f-kind" || gid === "f-extheme") return; // 表达库筛选单独处理
    const key = gid.replace("f-", "");
    STATE.filters[key] = STATE.filters[key] === chip.dataset.val ? "" : chip.dataset.val;
    applyChipState();
    loadPhrases();
  }));

  // 表达库
  $("#ex-refresh").addEventListener("click", loadExpressions);
  $("#ex-publish-all").addEventListener("click", () => publishAll("/api/expressions", loadExpressions));
  $("#ex-add").addEventListener("click", () => openExprModal());
  $("#ex-q").addEventListener("input", debounce(loadExpressions, 300));
  $("#ex-collected").addEventListener("change", (e) => {
    STATE.exFilters.collected = e.target.checked ? "1" : "";
    loadExpressions();
  });
  $("#ex-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) actExpression(btn.dataset.act, btn.dataset.id);
  });
  $("#f-kind").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    STATE.exFilters.kind = STATE.exFilters.kind === chip.dataset.val ? "" : chip.dataset.val;
    applyExprChipState();
    loadExpressions();
  });
  $("#f-extheme").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    STATE.exFilters.theme = STATE.exFilters.theme === chip.dataset.val ? "" : chip.dataset.val;
    applyExprChipState();
    loadExpressions();
  });

  // 框架
  $("#fw-theme-nav").addEventListener("click", (e) => {
    const btn = e.target.closest(".fw-theme-btn");
    if (btn) {
      STATE.fwTheme = btn.dataset.theme;
      loadFramework();
    }
  });
  $("#fw-decompose").addEventListener("click", openDecompose);
  $("#fw-edit-tree").addEventListener("click", openTreeEdit);
  $("#fw-fanwen").addEventListener("click", toggleFanwenPanel);
  $("#fw-fanwen-refresh").addEventListener("click", loadFanwen);
  $("#fanwen-file-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act=fanwen-parse-file]");
    if (btn) parseFanwenFile(btn.dataset.path, btn.dataset.name);
  });
  $("#fw-content").addEventListener("click", (e) => {
    if (e.target.closest("[data-jump]")) actFrameworkJump(e);
    else if (e.target.closest("[data-act=tmpl-edit]")) {
      openTemplateEdit(e.target.closest("[data-act=tmpl-edit]").dataset.id);
    } else if (e.target.closest("[data-act=tmpl-delete]")) {
      const id = e.target.closest("[data-act=tmpl-delete]").dataset.id;
      if (confirm("删除这个模板？")) {
        api(`/api/templates/${id}`, { method: "DELETE" }).then(() => { toast("已删除"); loadFramework(); });
      }
    }
  });

  // 复习
  $("#rv-refresh").addEventListener("click", loadReview);
  $("#rv-due").addEventListener("click", reviewClickHandler);
  $("#rv-random").addEventListener("click", reviewClickHandler);
  $("#rv-pool").addEventListener("click", reviewClickHandler);

  // AI 拆解弹窗
  $("#decompose-close").addEventListener("click", closeDecompose);
  $("#dc-run").addEventListener("click", runDecompose);

  // 设置
  $("#cfg-save").addEventListener("click", saveSettings);
  $("#cfg-catch-run").addEventListener("click", runCatchup);
  $("#cfg-rerun").addEventListener("click", () => { switchTab("hotspots"); runPipelineNow(); });

  // 弹窗
  $("#modal-close").addEventListener("click", hideModal);
  $("#modal-cancel").addEventListener("click", hideModal);
  $("#modal-save").addEventListener("click", () => {
    const k = STATE.modal.kind;
    if (k === "hotspot") saveHotspotModal();
    else if (k === "card") saveCardModal();
    else if (k === "phrase") savePhraseModal();
    else if (k === "expression") saveExprModal();
    else if (k === "tree") saveTreeEdit();
    else if (k === "template") saveTemplateEdit();
  });
  $("#modal-mask").addEventListener("click", (e) => { if (e.target.id === "modal-mask") hideModal(); });
}
function reviewClickHandler(e) {
  const btn = e.target.closest("button[data-act]");
  if (btn) actReview(btn.dataset.act, btn);
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ================= 启动 ================= */
(async function init() {
  bindEvents();
  renderFilterBar();
  renderExprFilterBar();
  await applyFonts();
  await loadThemes();
  await loadReviewState();
  await refreshOverview();
  switchTab("hotspots");
  pollPipelineStatus();  // 恢复遗留的 running/stopped 状态（重启后仍显示）
  setInterval(refreshOverview, 30000);
})();
