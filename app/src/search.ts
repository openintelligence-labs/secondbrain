// ⌘+Space search overlay. Frameless, transparent, focus-trapped.
// Talks to /search on the local gateway.

import "./styles.css";
import { api } from "./api";
import type { Hit } from "./api";

const qEl = document.getElementById("q") as HTMLInputElement;
const resultsEl = document.getElementById("results")!;
const metaEl = document.getElementById("meta")!;

let lastHits: Hit[] = [];
let activeIdx = 0;
let pendingTimer: number | null = null;

function escapeHtml(s: string) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Highlight all whole-word query tokens inside a snippet. */
function highlight(snippet: string, query: string): string {
  const esc = escapeHtml(snippet);
  const tokens = query
    .split(/\s+/)
    .filter((t) => t.length >= 2)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!tokens.length) return esc;
  const re = new RegExp(`(${tokens.join("|")})`, "ig");
  return esc.replace(re, "<mark>$1</mark>");
}

function rankBadge(h: Hit): string {
  const parts: string[] = [];
  if (h.bm25_rank != null) parts.push(`bm ${h.bm25_rank}`);
  if (h.dense_rank != null) parts.push(`d ${h.dense_rank}`);
  return parts.join(" · ");
}

function render(query: string) {
  if (!lastHits.length) {
    resultsEl.innerHTML = `<div class="empty">${
      query ? "no matches" : "type to search"
    }</div>`;
    metaEl.textContent = query ? "0 results" : "—";
    return;
  }
  resultsEl.innerHTML = lastHits
    .map((h, i) => {
      const active = i === activeIdx ? "active" : "";
      return `
        <div class="result ${active}" data-idx="${i}" data-cid="${escapeHtml(
        h.capture_id
      )}">
          <div class="meta">${escapeHtml(h.capture_id)}<br/>${rankBadge(h)}</div>
          <div class="body">${highlight(h.snippet, query)}</div>
          <div class="score">${h.rrf_score.toFixed(4)}</div>
        </div>
      `;
    })
    .join("");
  metaEl.textContent = `${lastHits.length} result${lastHits.length === 1 ? "" : "s"}`;
  // Scroll the active row into view.
  const activeEl = resultsEl.querySelector<HTMLDivElement>(".result.active");
  activeEl?.scrollIntoView({ block: "nearest" });
}

async function runSearch(q: string) {
  if (!q.trim()) {
    lastHits = [];
    activeIdx = 0;
    render(q);
    return;
  }
  try {
    const { hits } = await api.search(q, 25);
    lastHits = hits;
    activeIdx = 0;
    render(q);
  } catch (e) {
    resultsEl.innerHTML = `<div class="empty">gateway offline — ${escapeHtml(
      String((e as Error).message ?? e)
    )}</div>`;
  }
}

// Debounced live search.
qEl.addEventListener("input", () => {
  const q = qEl.value;
  if (pendingTimer) clearTimeout(pendingTimer);
  pendingTimer = window.setTimeout(() => runSearch(q), 90);
});

// Keyboard navigation.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    closeWindow();
    return;
  }
  if (!lastHits.length) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    activeIdx = (activeIdx + 1) % lastHits.length;
    render(qEl.value);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    activeIdx = (activeIdx - 1 + lastHits.length) % lastHits.length;
    render(qEl.value);
  } else if (e.key === "Enter") {
    e.preventDefault();
    const hit = lastHits[activeIdx];
    if (hit) openHitInTimeline(hit);
  }
});

// Clicking a row activates it; double-click opens.
resultsEl.addEventListener("click", (e) => {
  const el = (e.target as HTMLElement).closest<HTMLElement>(".result");
  if (!el) return;
  activeIdx = Number(el.dataset.idx ?? 0);
  render(qEl.value);
});

resultsEl.addEventListener("dblclick", (e) => {
  const el = (e.target as HTMLElement).closest<HTMLElement>(".result");
  if (!el) return;
  const hit = lastHits[Number(el.dataset.idx ?? 0)];
  if (hit) openHitInTimeline(hit);
});

async function openHitInTimeline(_hit: Hit) {
  // Future: focus the timeline row for `_hit.capture_id`. For v0.1 we just
  // bring the main window to the front so the user can scroll to it.
  try {
    const mod = await import("@tauri-apps/api/webviewWindow").catch(() => null);
    if (mod) {
      const win = await mod.WebviewWindow.getByLabel("main");
      if (win) {
        await win.show();
        await win.setFocus();
      }
    }
  } catch {
    /* non-tauri preview: no-op */
  }
  closeWindow();
}

async function closeWindow() {
  try {
    const mod = await import("@tauri-apps/api/webviewWindow").catch(() => null);
    if (mod) {
      const cur = mod.getCurrentWebviewWindow();
      await cur.hide();
      return;
    }
  } catch {
    /* fallthrough */
  }
  window.close();
}
