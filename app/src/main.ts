// Main window — six panels (Timeline, Search, Digest, Commitments, People, Settings).
// Vanilla TS routing via data-tab attributes; each panel is a tiny render
// function bound to its DOM root. No SPA framework.

import "./styles.css";
import { api } from "./api";
import type { AuditEntry, Commitment, Event, Hit, StatusResponse } from "./api";

// ---------- shared helpers ----------
const $ = (sel: string) => document.querySelector<HTMLElement>(sel)!;
const $$ = (sel: string) => Array.from(document.querySelectorAll<HTMLElement>(sel));

const pad = (n: number) => String(n).padStart(2, "0");
const isoDate = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fmtTime = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const escapeHtml = (s: string) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

function toast(msg: string, kind: "info" | "err" = "info", ms = 2200) {
  const mount = document.getElementById("toast-mount")!;
  const el = document.createElement("div");
  el.className = `toast ${kind === "err" ? "err" : ""}`;
  el.textContent = msg;
  mount.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ---------- routing ----------
type TabName = "timeline" | "search" | "digest" | "commitments" | "people" | "settings";

let currentTab: TabName = "timeline";

function showTab(name: TabName) {
  currentTab = name;
  $$("button.tab").forEach((b) =>
    b.setAttribute("data-active", String(b.dataset.tab === name)),
  );
  $$(".panel").forEach((p) =>
    p.setAttribute("data-active", String(p.dataset.panel === name)),
  );
  switch (name) {
    case "timeline": loadTimeline(); break;
    case "search":   $("#search-input")?.focus(); break;
    case "digest":   loadDigest(); break;
    case "commitments": loadCommitments(); break;
    case "people":   $("#people-input")?.focus(); break;
    case "settings": loadSettings(); break;
  }
}

$$(".tab").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab as TabName)),
);

// ---------- TIMELINE ----------
let timelineDate = new Date();
let timelineEvents: Event[] = [];
let timelineFilter = "";
// Hour window scoping: [startHour, endHour] inclusive, both 0–23. Null = full day.
let timelineHourScope: [number, number] | null = null;

function fmtRelDay(d: Date) {
  const today = new Date();
  if (isoDate(d) === isoDate(today)) return `today · ${isoDate(d)}`;
  const yest = new Date(today); yest.setDate(today.getDate() - 1);
  if (isoDate(d) === isoDate(yest)) return `yesterday · ${isoDate(d)}`;
  return isoDate(d);
}

function commitmentish(text: string) {
  return /\b(i'?ll|i will|we will|by\s+(monday|tuesday|wednesday|thursday|friday)|deadline|due)\b/i.test(text);
}

function appHint(text: string) {
  const m = text.match(/^([A-Z][\w]+):/);
  return m ? m[1].toLowerCase() : "memory";
}

function timelineRow(ev: Event) {
  const time = fmtTime(ev.valid_from);
  const app = appHint(ev.content);
  const imp = ev.importance.toFixed(1);
  return `
    <div class="row" data-has-commitment="${commitmentish(ev.content)}" data-id="${escapeHtml(ev.memory_id)}">
      <div class="time">${time} · ${imp}</div>
      <div class="app">${escapeHtml(app)}</div>
      <div class="body">${escapeHtml(ev.content)}</div>
    </div>
  `;
}

function eventHour(ev: Event): number | null {
  if (!ev.valid_from) return null;
  const d = new Date(ev.valid_from);
  return isNaN(d.getTime()) ? null : d.getHours();
}

function renderTimeline() {
  $("#timeline-date").textContent = fmtRelDay(timelineDate);
  let list = timelineEvents;
  if (timelineHourScope) {
    const [a, b] = timelineHourScope;
    list = list.filter((e) => {
      const h = eventHour(e);
      return h !== null && h >= a && h <= b;
    });
  }
  if (timelineFilter) {
    list = list.filter((e) =>
      e.content.toLowerCase().includes(timelineFilter.toLowerCase()));
  }
  const body = $("#timeline-body");
  const scopeLabel = timelineHourScope
    ? ` · ${timelineHourScope[0].toString().padStart(2, "0")}:00–${(timelineHourScope[1] + 1).toString().padStart(2, "0")}:00`
    : "";
  body.innerHTML = list.length
    ? list.map(timelineRow).join("")
    : `<div class="empty">no captures ${timelineFilter ? `match "${escapeHtml(timelineFilter)}"` : `for this${scopeLabel ? " hour window" : " day"}`}</div>`;
  $("#timeline-meta").textContent =
    `${list.length} of ${timelineEvents.length} entries${scopeLabel}`;
  $("#tab-count-timeline").textContent = String(timelineEvents.length);
  drawScrubber();
}

// ---------- TIMELINE SCRUBBER (canvas) ----------
function hourBuckets(events: Event[]): number[] {
  const b = new Array(24).fill(0);
  for (const e of events) {
    const h = eventHour(e);
    if (h !== null) b[h]++;
  }
  return b;
}

function drawScrubber() {
  const canvas = document.getElementById("timeline-scrubber") as HTMLCanvasElement | null;
  if (!canvas) return;
  // Match canvas internal size to its CSS-rendered size for crisp bars.
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(200, Math.floor(rect.width));
  const h = canvas.height;
  if (canvas.width !== w) canvas.width = w;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, w, h);

  const buckets = hourBuckets(timelineEvents);
  const max = Math.max(1, ...buckets);
  const barW = w / 24;
  const pad = 2;

  for (let i = 0; i < 24; i++) {
    const fill = buckets[i] / max;
    const barH = Math.max(2, Math.round(fill * (h - 6)));
    const x = Math.floor(i * barW + pad);
    const y = h - barH - 3;
    const inScope =
      !timelineHourScope ||
      (i >= timelineHourScope[0] && i <= timelineHourScope[1]);
    ctx.fillStyle = inScope ? "#fbbf24" : "rgba(251, 191, 36, 0.18)";
    ctx.fillRect(x, y, Math.max(1, Math.floor(barW - pad * 2)), barH);
  }

  // Scope overlay: dim the out-of-scope edges.
  if (timelineHourScope) {
    const [a, b] = timelineHourScope;
    ctx.fillStyle = "rgba(9, 9, 11, 0.55)";
    if (a > 0) ctx.fillRect(0, 0, a * barW, h);
    if (b < 23) ctx.fillRect((b + 1) * barW, 0, w - (b + 1) * barW, h);
    // Scope edges (1px lines)
    ctx.strokeStyle = "rgba(251, 191, 36, 0.9)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(a * barW + 0.5, 0); ctx.lineTo(a * barW + 0.5, h);
    ctx.moveTo((b + 1) * barW - 0.5, 0); ctx.lineTo((b + 1) * barW - 0.5, h);
    ctx.stroke();
  }
}

function ensureScrubberInteraction() {
  const canvas = document.getElementById("timeline-scrubber") as HTMLCanvasElement | null;
  if (!canvas || (canvas as any).__sb_wired__) return;
  (canvas as any).__sb_wired__ = true;

  const axis = document.getElementById("scrubber-axis")!;
  axis.innerHTML = Array.from({ length: 24 }, (_, i) =>
    `<span>${i.toString().padStart(2, "0")}</span>`).join("");

  let dragStart: number | null = null;

  const hourAtEvent = (e: MouseEvent): number => {
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width - 1, e.clientX - rect.left));
    return Math.max(0, Math.min(23, Math.floor((x / rect.width) * 24)));
  };

  canvas.addEventListener("mousedown", (e) => {
    dragStart = hourAtEvent(e);
  });
  canvas.addEventListener("mousemove", (e) => {
    if (dragStart === null) return;
    const cur = hourAtEvent(e);
    const a = Math.min(dragStart, cur);
    const b = Math.max(dragStart, cur);
    timelineHourScope = [a, b];
    renderTimeline();
  });
  window.addEventListener("mouseup", () => { dragStart = null; });
  canvas.addEventListener("click", (e) => {
    // Pure click (no drag) → scope to exactly that hour.
    if (dragStart === null) {
      const h = hourAtEvent(e);
      timelineHourScope = [h, h];
      renderTimeline();
    }
  });
  canvas.addEventListener("dblclick", () => {
    timelineHourScope = null;
    renderTimeline();
  });
  window.addEventListener("resize", () => drawScrubber());
}

async function loadTimeline() {
  const start = new Date(timelineDate); start.setHours(0, 0, 0, 0);
  const end = new Date(timelineDate); end.setHours(23, 59, 59, 999);
  $("#timeline-body").innerHTML = `<div class="empty">loading…</div>`;
  // Reset scope when switching days — leaving a previous day's hour window
  // applied is confusing.
  timelineHourScope = null;
  try {
    const { events } = await api.timeline(start.toISOString(), end.toISOString());
    timelineEvents = events.slice().sort((a, b) =>
      (b.valid_from ?? "").localeCompare(a.valid_from ?? ""));
    ensureScrubberInteraction();
    renderTimeline();
  } catch (e) {
    $("#timeline-body").innerHTML =
      `<div class="empty">gateway unreachable — is the daemon running?</div>`;
    toast(`timeline: ${(e as Error).message}`, "err");
  }
}

$("#timeline-filter")!.addEventListener("input", (e) => {
  timelineFilter = (e.target as HTMLInputElement).value.trim();
  renderTimeline();
});
$("#prev-day")!.addEventListener("click", () => {
  timelineDate.setDate(timelineDate.getDate() - 1);
  loadTimeline();
});
$("#next-day")!.addEventListener("click", () => {
  timelineDate.setDate(timelineDate.getDate() + 1);
  loadTimeline();
});
$("#today-btn")!.addEventListener("click", () => {
  timelineDate = new Date();
  loadTimeline();
});

// Right-click on a row → forget
$("#timeline-body")!.addEventListener("contextmenu", async (e) => {
  const target = (e.target as HTMLElement).closest<HTMLElement>(".row");
  if (!target) return;
  e.preventDefault();
  const id = target.dataset.id;
  if (!id) return;
  const reason = prompt(`Forget this memory? (give a reason for the audit log)`, "user-requested");
  if (!reason) return;
  try {
    const r = await api.forget(id, reason);
    toast(`deleted ${r.deleted} node(s)`);
    loadTimeline();
  } catch (err) {
    toast(`forget failed: ${(err as Error).message}`, "err");
  }
});

// ---------- SEARCH (in-page) ----------
let searchHits: Hit[] = [];
let searchActiveIdx = 0;
let searchTimer: number | null = null;
const searchInput = $("#search-input") as HTMLInputElement;

function highlight(snippet: string, query: string): string {
  const esc = escapeHtml(snippet);
  const tokens = query.split(/\s+/).filter((t) => t.length >= 2)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!tokens.length) return esc;
  const re = new RegExp(`(${tokens.join("|")})`, "ig");
  return esc.replace(re, "<mark>$1</mark>");
}

function renderSearch(q: string) {
  const body = $("#search-body");
  if (!searchHits.length) {
    body.innerHTML = `<div class="empty">${q ? "no matches" : "type a query to search your memory"}</div>`;
    $("#search-meta").textContent = q ? "0 results" : "—";
    return;
  }
  body.innerHTML = searchHits.map((h, i) => `
    <div class="row" data-active="${i === searchActiveIdx}" data-id="${escapeHtml(h.capture_id)}" data-idx="${i}">
      <div class="time">rrf ${h.rrf_score.toFixed(4)}</div>
      <div class="app">${escapeHtml(h.capture_id.slice(0,8))}</div>
      <div class="body">${highlight(h.snippet, q)}</div>
    </div>
  `).join("");
  $("#search-meta").textContent = `${searchHits.length} result${searchHits.length === 1 ? "" : "s"}`;
}

async function runSearch(q: string) {
  if (!q.trim()) { searchHits = []; renderSearch(""); return; }
  try {
    const { hits } = await api.search(q, 30);
    searchHits = hits;
    searchActiveIdx = 0;
    renderSearch(q);
  } catch (e) {
    toast(`search failed: ${(e as Error).message}`, "err");
  }
}

searchInput.addEventListener("input", () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => runSearch(searchInput.value), 110);
});
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { searchInput.value = ""; runSearch(""); }
  if (!searchHits.length) return;
  if (e.key === "ArrowDown") { e.preventDefault(); searchActiveIdx = (searchActiveIdx + 1) % searchHits.length; renderSearch(searchInput.value); }
  if (e.key === "ArrowUp") { e.preventDefault(); searchActiveIdx = (searchActiveIdx - 1 + searchHits.length) % searchHits.length; renderSearch(searchInput.value); }
});

// ---------- DIGEST ----------
let digestPeriod: "day" | "week" | "month" = "day";
let digestUseLLM = false;

async function loadDigest() {
  const body = $("#digest-body");
  body.innerHTML = `<div class="empty">${digestUseLLM ? "thinking…" : "loading…"}</div>`;
  $("#digest-subtitle").textContent = `${digestPeriod} · ${isoDate(new Date())} · ${digestUseLLM ? "LLM" : "heuristic"}`;
  try {
    const d = await api.digest(isoDate(new Date()), digestPeriod);
    body.innerHTML = `
      <div class="card">
        <h2>Themes</h2>
        <div class="body">
          ${d.themes.length
            ? d.themes.map((t) => `<div class="line">${escapeHtml(t)}</div>`).join("")
            : '<div class="muted">no themes yet</div>'}
        </div>
      </div>
      <div class="card">
        <h2>Broken promises</h2>
        <div class="body">
          ${d.broken_promises.length
            ? d.broken_promises.map((b) => `<div class="line"><span class="pill broken">past due</span> ${escapeHtml(b)}</div>`).join("")
            : '<div class="muted">none — well done</div>'}
        </div>
      </div>
      <div class="card">
        <h2>Suggested follow-ups</h2>
        <div class="body">
          ${d.suggested_followups.length
            ? d.suggested_followups.map((f) => `<div class="line">${escapeHtml(f)}</div>`).join("")
            : '<div class="muted">no follow-ups</div>'}
        </div>
      </div>
      <div class="card">
        <h2>Importance roll-up</h2>
        <div class="body muted">sum = ${d.importance_sum.toFixed(1)} · cites ${d.cited.length} memories</div>
      </div>
    `;
    $("#digest-meta").textContent = `Σ ${d.importance_sum.toFixed(1)}`;
    $("#tab-count-digest").textContent = String(d.cited.length);
  } catch (e) {
    body.innerHTML = `<div class="empty">digest unavailable</div>`;
    toast(`digest: ${(e as Error).message}`, "err");
  }
}

$$("#digest-period button").forEach((b) =>
  b.addEventListener("click", () => {
    digestPeriod = b.dataset.period as any;
    $$("#digest-period button").forEach((x) =>
      x.setAttribute("data-active", String(x.dataset.period === digestPeriod)));
    loadDigest();
  }));
$("#digest-llm-toggle")!.addEventListener("click", () => {
  digestUseLLM = !digestUseLLM;
  $("#digest-llm-toggle").setAttribute("data-active", String(digestUseLLM));
  // NOTE: the gateway's /digest doesn't yet accept use_llm; the toggle is
  // forward-compat for when we wire it. Today it just changes the label.
  loadDigest();
});

// ---------- COMMITMENTS ----------
let commStatus: "open" | "done" | "broken" = "open";

async function loadCommitments() {
  const body = $("#commitments-body");
  body.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const { commitments } = await api.commitments(commStatus);
    body.innerHTML = commitments.length
      ? commitments.map((c) => commitmentRow(c)).join("")
      : `<div class="empty">no ${commStatus} commitments</div>`;
    $("#commitments-meta").textContent = `${commitments.length} ${commStatus}`;
    $("#tab-count-commitments").textContent = String(commitments.length);
  } catch (e) {
    body.innerHTML = `<div class="empty">commitments unavailable</div>`;
    toast(`commitments: ${(e as Error).message}`, "err");
  }
}

function commitmentRow(c: Commitment) {
  const due = c.due_at ? new Date(c.due_at).toLocaleString() : "no deadline";
  const owner = c.owner_pid ? c.owner_pid.replace(/^person:/, "") : "—";
  return `
    <div class="row" data-id="${escapeHtml(c.id)}">
      <div class="time">${escapeHtml(due)}</div>
      <div class="app">
        <span class="pill ${c.status}">${c.status}</span>
        ${owner === "—" ? "" : `<span style="margin-left:6px;color:var(--text-muted);">${escapeHtml(owner)}</span>`}
      </div>
      <div class="body">${escapeHtml(c.content)}</div>
    </div>
  `;
}

$$("#commitments-status button").forEach((b) =>
  b.addEventListener("click", () => {
    commStatus = b.dataset.status as any;
    $$("#commitments-status button").forEach((x) =>
      x.setAttribute("data-active", String(x.dataset.status === commStatus)));
    loadCommitments();
  }));

// ---------- PEOPLE ----------
const peopleInput = $("#people-input") as HTMLInputElement;
let peopleTimer: number | null = null;

async function loadPerson(name: string) {
  if (!name.trim()) {
    $("#people-body").innerHTML =
      `<div class="empty">type a name above to see their card</div>`;
    $("#people-meta").textContent = "—";
    return;
  }
  $("#people-body").innerHTML = `<div class="empty">looking up ${escapeHtml(name)}…</div>`;
  try {
    const r = await api.who(name);
    const facts = r.facts ?? [];
    $("#people-body").innerHTML = `
      <div class="card">
        <h2>${escapeHtml(name)} <span class="muted">(${escapeHtml(r.person_id)})</span></h2>
        <div class="body muted">${facts.length} memories mentioning this person</div>
      </div>
      ${facts.length ? facts.map((f: Event) => timelineRow(f)).join("") : '<div class="empty">no memories yet</div>'}
    `;
    $("#people-meta").textContent = `${facts.length} memories`;
  } catch (e) {
    $("#people-body").innerHTML = `<div class="empty">person not found</div>`;
    toast(`who: ${(e as Error).message}`, "err");
  }
}

peopleInput.addEventListener("input", () => {
  if (peopleTimer) clearTimeout(peopleTimer);
  peopleTimer = window.setTimeout(() => loadPerson(peopleInput.value), 200);
});

// ---------- SETTINGS ----------
async function loadSettings() {
  const body = $("#settings-body");
  body.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const [llm, audit] = await Promise.all([api.llmConfig(), api.auditLog(50)]);
    const sdk = llm.sdk_state || "unknown";
    const sdkClass = sdk.startsWith("ok") ? "open" : "broken";
    body.innerHTML = `
      <div class="card">
        <h2>BYO-LLM</h2>
        <div class="body">
          <div class="line">provider · <b>${escapeHtml(llm.provider ?? "ollama (default)")}</b></div>
          <div class="line">model · <b>${escapeHtml(llm.model ?? "(provider default)")}</b></div>
          <div class="line">base url · <b>${escapeHtml(llm.base_url ?? "(provider default)")}</b></div>
          <div class="line">api key · ${llm.api_key_set ? "<b>set</b>" : '<span class="muted">not set</span>'}</div>
          <div class="line">sdk · <span class="pill ${sdkClass}">${escapeHtml(sdk)}</span></div>
        </div>
        <div class="muted" style="margin-top:10px;">
          configure via env: <code>SECONDBRAIN_LLM_PROVIDER</code>, <code>_MODEL</code>, <code>_BASE_URL</code>, <code>_API_KEY</code>
        </div>
      </div>
      <div class="card">
        <h2>Audit log</h2>
        <div class="body">
          ${audit.entries.length
            ? audit.entries.map((e: AuditEntry) => auditRow(e)).join("")
            : '<div class="muted">no audit rows yet</div>'}
        </div>
      </div>
      <div class="card">
        <h2>Local-first promises</h2>
        <div class="body">
          <div class="line">captures · <b>local disk</b> · encrypted SQLite</div>
          <div class="line">embeddings · <b>local LanceDB</b> · never sent over the wire</div>
          <div class="line">knowledge graph · <b>local Kùzu</b> · bi-temporal</div>
          <div class="line">LLM · <b>${llm.provider === "ollama" || !llm.provider ? "local Ollama" : "hosted provider you opted into"}</b></div>
          <div class="line muted">when a hosted LLM is configured, only prompted text egresses — and only because you opted in</div>
        </div>
      </div>
    `;
    $("#settings-meta").textContent =
      `${audit.entries.length} audit rows · sdk ${sdk}`;
  } catch (e) {
    body.innerHTML = `<div class="empty">settings unavailable</div>`;
    toast(`settings: ${(e as Error).message}`, "err");
  }
}

function auditRow(e: AuditEntry) {
  const when = new Date(e.ts * 1000).toLocaleString();
  return `
    <div class="line">
      <span class="muted">${when} · ${escapeHtml(e.actor)}</span>
      · <b>${escapeHtml(e.action)}</b>
      ${e.query ? ` · ${escapeHtml(e.query)}` : ""}
      ${e.cited.length ? ` · <span class="muted">${e.cited.length} cited</span>` : ""}
    </div>
  `;
}

$("#settings-refresh")!.addEventListener("click", loadSettings);

// Theme toggle — persists to localStorage so it survives reloads.
const themeToggle = document.getElementById("theme-toggle");
function applyTheme(theme: "dark" | "light") {
  document.body.setAttribute("data-theme", theme);
  try { localStorage.setItem("sb-theme", theme); } catch {}
}
themeToggle?.addEventListener("click", () => {
  const cur = (document.body.getAttribute("data-theme") || "dark") as "dark" | "light";
  applyTheme(cur === "dark" ? "light" : "dark");
});
try {
  const saved = localStorage.getItem("sb-theme");
  if (saved === "dark" || saved === "light") applyTheme(saved);
} catch {}

// Sidebar search shortcut → switch to search tab.
document.getElementById("sidebar-search")?.addEventListener("click", () => {
  showTab("search");
});

// ---------- STATUS POLL ----------
const dot = $("#status-dot");
const statusText = $("#status-text");
const statusToday = $("#status-today");
const pauseToggle = $("#pause-toggle") as HTMLButtonElement;

async function pollStatus() {
  try {
    const s: StatusResponse = await api.status();
    if (s.running) {
      const paused = !!s.metrics?.paused;
      dot.setAttribute("data-state", paused ? "paused" : "capturing");
      statusText.textContent = paused ? "paused" : "capturing";
      statusToday.textContent = String(s.metrics?.persisted ?? 0);
      pauseToggle.textContent = paused ? "Resume" : "Pause";
      pauseToggle.dataset.state = paused ? "paused" : "running";
    } else {
      dot.setAttribute("data-state", "paused");
      statusText.textContent = "offline";
      statusToday.textContent = "0";
      pauseToggle.textContent = "Daemon offline";
      pauseToggle.disabled = true;
    }
  } catch {
    dot.setAttribute("data-state", "paused");
    statusText.textContent = "gateway?";
  }
}

pauseToggle.addEventListener("click", async () => {
  const wantsPause = pauseToggle.dataset.state !== "paused";
  try {
    await api.daemonControl(wantsPause ? "pause" : "resume");
    pollStatus();
  } catch (e) {
    toast(`daemon control: ${(e as Error).message}`, "err");
  }
});

// ---------- GLOBAL HOTKEYS ----------
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    showTab("search");
  }
  if (e.key === "Escape" && currentTab === "search") {
    searchInput.value = "";
    runSearch("");
  }
});

// ---------- boot ----------
(window as any).__sb_apply_tab__ = (t: string) => {
  const allowed: TabName[] = ["timeline", "search", "digest", "commitments", "people", "settings"];
  if (allowed.includes(t as TabName) && currentTab !== t) {
    showTab(t as TabName);
  }
};

// Optional pre-fill values (also injected by the Tauri shell when set):
(window as any).__sb_apply_query__ = (q: string) => {
  searchInput.value = q;
  runSearch(q);
};
(window as any).__sb_apply_person__ = (name: string) => {
  peopleInput.value = name;
  loadPerson(name);
};

const injected = (window as any).__SB_DEFAULT_TAB__ as TabName | undefined;
const params = new URLSearchParams(location.search);
const fromQuery = params.get("tab") as TabName | null;
const prefillQuery = params.get("q") || (window as any).__SB_DEFAULT_QUERY__;
const prefillPerson = params.get("person") || (window as any).__SB_DEFAULT_PERSON__;
const initialTab: TabName = (injected || fromQuery || "timeline") as TabName;
showTab(initialTab);
// Wait two animation frames so showTab has finished its DOM swap before we
// trigger the search/person fetch — otherwise the async fetch result lands
// in a hidden panel and the row body height is zero.
requestAnimationFrame(() => requestAnimationFrame(() => {
  if (prefillQuery) (window as any).__sb_apply_query__(prefillQuery);
  if (prefillPerson) (window as any).__sb_apply_person__(prefillPerson);
}));
pollStatus();
setInterval(pollStatus, 3000);

// ---------- Tauri event subscriptions ----------
// The Rust tray emits these when /daemon control or /status polling sees
// trouble. Surface them in the webview as toasts so the user doesn't have
// to tail stderr to know what's wrong.
async function wireTauriEvents() {
  try {
    const { listen } = await import("@tauri-apps/api/event");
    await listen<{ error: string }>("daemon-control-error", (e) => {
      toast(`pause/resume failed: ${e.payload.error}`, "err", 4000);
    });
    await listen<{ url: string; consecutive_misses: number }>(
      "gateway-unreachable",
      (e) => {
        toast(
          `gateway unreachable at ${e.payload.url} — daemon may be down`,
          "err",
          5000,
        );
      },
    );
    await listen<{ ok: boolean; state: string }>("daemon-control", (e) => {
      if (e.payload.ok) {
        toast(`daemon ${e.payload.state}`, "info", 1600);
      }
    });
  } catch {
    // Not running inside Tauri (e.g. `vite dev` browser tab) — no events to wire.
  }
}
wireTauriEvents();
