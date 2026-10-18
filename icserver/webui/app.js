// Infinite Crisis companion app (icserver/webapp.py serves the data).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const tex = (did, size = 0) => did ? `/tex/${did.replace(/^0x/i, "")}.png${size ? "?s=" + size : ""}` : "";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = async (path, body) => {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  return r.json();
};
const toast = (text) => {
  const t = $("#toast"); t.textContent = text; t.classList.add("on");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 2800);
};
const img = (did, size, alt = "") => did ? `<img loading="lazy" src="${tex(did, size)}" alt="${esc(alt)}" onerror="this.style.visibility='hidden'">` : "";
// a background picture from the first texture that exists (the install may lack some packs)
function setArt(el, ids, size = 1024) {
  const list = ids.filter(Boolean);
  if (el.dataset.art === list.join(",")) return;
  el.dataset.art = list.join(",");
  const next = (i) => {
    if (i >= list.length) { el.style.backgroundImage = ""; return; }
    const probe = new Image();
    probe.onload = () => (el.style.backgroundImage = `url(${probe.src})`);
    probe.onerror = () => next(i + 1);
    probe.src = location.origin + tex(list[i], size);
  };
  next(0);
}
// the full-screen art behind the whole client (two layers that cross-fade)
const BD = { on: "a", key: "" };
function setBackdrop(ids) {
  const list = ids.filter(Boolean), key = list.join(",");
  if (!list.length || key === BD.key) return;
  BD.key = key;
  const next = (i) => {
    if (i >= list.length) return;
    const probe = new Image();
    probe.onload = () => {
      if (BD.key !== key) return;
      const show = BD.on === "a" ? "b" : "a", hide = BD.on;
      $("#bd-" + show).style.backgroundImage = `url(${probe.src})`;
      $("#bd-" + show).classList.add("on"); $("#bd-" + hide).classList.remove("on");
      BD.on = show;
    };
    probe.onerror = () => next(i + 1);
    probe.src = location.origin + tex(list[i], 1024);
  };
  next(0);
}
const batmanArt = () => { const b = batman(); return b ? [b.art, b.wallpaper] : []; };
const pretty = (name) => String(name || "").replace(/\s+--\s+/g, " – ");
const chips = (parts) => parts.filter(Boolean).map((p) => `<span class="stat">${esc(p)}</span>`).join("");

const S = { state: null, champs: null, cos: null, items: null, enc: null, slot: 0, sub: "champions", tab: "amplifiers",
  brand: "", mode: "Training", queue: null, queuedAt: 0 };
const load = async () => {
  [S.champs, S.enc, S.cos] = await Promise.all([S.champs ?? api("/api/champions"), S.enc ?? api("/api/encounters"),
    S.cos ?? api("/api/cosmetics")]);
};
const batman = () => S.champs?.find((c) => c.name === "Gaslight Batman");
const iconPic = (id) => (S.cos?.icons.find((i) => i.id.toLowerCase() === (id || "").toLowerCase()) || {}).picture;
const header = () => (S.state?.profile_icons?.length ? S.state.profile_icons : S.cos?.header) || [];

// ---- navigation ------------------------------------------------------------------
const VIEWS = ["home", "collection", "arsenal", "profile"];
async function show(view) {
  view = VIEWS.includes(view) ? view : "home";
  $("#champ-page").hidden = true;
  $("#main").classList.remove("detail");
  $$(".view").forEach((v) => (v.hidden = v.id !== "view-" + view));
  $$(".tabs-main a").forEach((a) => a.classList.toggle("on", a.dataset.view === view));
  await load();
  renderStatus();
  if (view === "collection" || view === "arsenal") setBackdrop(batmanArt());
  ({ home: renderHome, collection: renderCollection, arsenal: renderArsenal, profile: renderProfile })[view]();
  $("#main").scrollTop = 0;
}
window.addEventListener("hashchange", () => show(location.hash.slice(1)));

// ---- status (top bar, social column, queue pill) -----------------------------------
const PHASES = { MENU: "In the menus", QUEUED: "In queue", REFERRED: "Match found", LOBBY: "Loading", GAME_CONNECTED: "Loading",
  LOADING: "Loading", IN_WORLD: "In a match", PLAYING: "In a match" };
const QUEUE_PHASES = new Set(["QUEUED", "REFERRED", "LOBBY", "GAME_CONNECTED", "LOADING"]);
async function poll() {
  const t0 = performance.now();
  try { S.state = await api("/api/state"); S.slow = performance.now() - t0 > 1500; } catch { S.state = null; }
  renderStatus();
}
// server light: red = no answer, yellow = answering but busy (game starting /
// loading / queued, or a slow answer), green = ready (menus or in a match)
function serverLight(st) {
  if (!st) return ["red", "Server offline", "The server is not answering. Start it with python ic.py app."];
  const busy = st.pending || QUEUE_PHASES.has(st.phase) || S.slow;
  const game = st.online ? PHASES[st.phase] || "Online" : st.pending ? "Starting the game" : "Game closed";
  if (busy) return ["yellow", "Server busy", `${game}. ${S.slow ? "The server is answering slowly." : "Please wait."}`];
  return ["green", "Server online", `Server ready. ${game}.`];
}
function renderStatus() {
  const st = S.state;
  const [color, label, tip] = serverLight(st);
  $("#srv").className = "srv " + color;
  $("#srv-label").textContent = label;
  $("#srv-tip").textContent = tip;
  $("#srv").setAttribute("aria-label", `${label}. ${tip}`);
  $("#me-status").textContent = !st ? "Offline" : st.online ? PHASES[st.phase] || "Online" : SOC.status === "online" ? "Online" : SOC.status[0].toUpperCase() + SOC.status.slice(1);
  $("#me-status").className = "pres-" + (!st ? "offline" : st.online ? "ingame" : SOC.status);
  if (st) {
    $("#me-name").textContent = $("#soc-name").textContent = st.player;
    $("#me-level").textContent = st.level;
    const pic = iconPic(header()[0]);
    for (const el of [$("#me-icon"), $("#soc-icon")]) if (pic && !el.src.endsWith(tex(pic))) el.src = tex(pic);
  }
  // queue pill: waiting for the game to log in, or queued / loading
  const waiting = st && (st.pending || QUEUE_PHASES.has(st.phase));
  if (waiting && !S.queuedAt) S.queuedAt = Date.now();
  if (!waiting) S.queuedAt = 0;
  $("#queue-pill").hidden = !waiting;
  $("#queue-title").textContent = !st ? "" : st.pending && !st.online ? "Starting the game" : PHASES[st.phase] || "In queue";
  $("#play-btn").classList.toggle("busy", !!(st?.online && !["MENU", ""].includes(st.phase)));
}
setInterval(() => {
  if (!S.queuedAt) return;
  const s = Math.floor((Date.now() - S.queuedAt) / 1000);
  $("#queue-time").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}, 500);

// ---- home ---------------------------------------------------------------------------
function renderHome() {
  const b = batman();
  setBackdrop(batmanArt());
  const ready = S.enc.find((e) => e.playable);
  const done = new Set((S.state?.completed || []).map((d) => d.toLowerCase()));
  if (ready) {
    const isDone = done.has(ready.id.toLowerCase());
    $("#feature-title").textContent = pretty(ready.name);
    $("#feature-sub").textContent = isDone
      ? "Completed. Play it again any time; Gaslight Batman is already yours."
      : "Learn the basics on the streets of Gotham. Finish it to unlock Gaslight Batman.";
    $("#feature-play").dataset.play = ready.id;
    $("#feature-play").textContent = isDone ? "Play again" : "Play now";
  }
  const fresh = S.champs.filter((c) => c.new);
  $("#tile-champs-sub").textContent = fresh.length ? `${fresh.length} added from your install` : "Browse every champion";
  const mosaic = $("#tile-champs-art");
  if (!mosaic.childElementCount) {
    mosaic.className = "tile-art mosaic";
    mosaic.innerHTML = (fresh.length ? fresh : S.champs).slice(0, 9).map((c) => img(c.portrait, 0, "")).join("");
  }
  $("#tile-icons-sub").textContent = `${S.cos.icons.length} icons to choose from`;
  const icons = $("#tile-icons-art");
  if (!icons.childElementCount) icons.innerHTML = S.cos.icons.slice(0, 12).map((i) => img(i.picture, 0, "")).join("");
}

// ---- play: mode select ------------------------------------------------------------------
const MODE_ICONS = {
  Training: '<path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/><path d="M9 12l2 2 4-4"/>',
  PvP: '<path d="M5 19L19 5M14 5h5v5M19 19L5 5M5 10V5h5"/>',
  Other: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
};
function modes() {
  const out = {};
  for (const e of S.enc) (out[e.mode || "Other"] ??= []).push(e);
  return out;
}
async function openLobby() {
  await load();
  const m = modes();
  if (!m[S.mode]) S.mode = Object.keys(m)[0];
  $("#lobby-modes").innerHTML = Object.entries(m).map(([name, list]) => {
    const n = list.filter((e) => e.playable).length;
    return `<button role="tab" class="mode-tab ${name === S.mode ? "on" : ""}" data-mode="${esc(name)}" aria-selected="${name === S.mode}">
      <svg viewBox="0 0 24 24">${MODE_ICONS[name] || MODE_ICONS.Other}</svg>${esc(name)}
      <small>${n ? `${n} ready` : "Coming later"}</small></button>`;
  }).join("");
  const list = m[S.mode];
  if (!S.queue || !list.some((e) => e.id === S.queue)) S.queue = (list.find((e) => e.playable) || list[0]).id;
  $("#lobby-queues").innerHTML = list.map((e) => `<li><button data-queue="${e.id}" class="${e.id === S.queue ? "on" : ""}"
      ${e.playable ? "" : "disabled"}><i></i>${esc(pretty(e.name))}${e.playable ? "" : "<small>Later</small>"}</button></li>`).join("");
  const e = list.find((x) => x.id === S.queue);
  $("#lobby-map").textContent = pretty(e.name);
  $("#lobby-desc").textContent = e.playable
    ? "Gotham, Gaslight era. Learn to move, attack and use your abilities as Gaslight Batman."
    : "This mode is not available on this server yet.";
  const b = batman();
  if (e.playable && b) setArt($("#lobby-art"), [b.art, b.wallpaper]);
  else { $("#lobby-art").style.backgroundImage = ""; delete $("#lobby-art").dataset.art; }
  $("#lobby-confirm").disabled = !e.playable;
  $("#lobby").hidden = false;
}
const closeLobby = () => ($("#lobby").hidden = true);
$("#play-btn").addEventListener("click", openLobby);
$("#lobby").addEventListener("click", (ev) => {
  const m = ev.target.closest("[data-mode]"); if (m) { S.mode = m.dataset.mode; S.queue = null; openLobby(); }
  const q = ev.target.closest("[data-queue]"); if (q && !q.disabled) { S.queue = q.dataset.queue; openLobby(); }
  if (ev.target.closest("[data-lobby-close]") || ev.target === $("#lobby")) closeLobby();
});
$("#lobby-confirm").addEventListener("click", () => play(S.queue, $("#lobby-confirm")));
async function play(encounter, button) {
  if (button) button.disabled = true;
  const r = await api("/api/play", { encounter });
  if (button) button.disabled = false;
  if (!r.ok) return toast(r.error || "Could not start the match");
  closeLobby();
  toast(r.queued ? "Queued. The match is loading in the game." : r.launched
    ? "Starting the game. Log in and the match loads by itself." : "Log in to the game and the match loads by itself.");
  poll();
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("#feature-play"); if (b) play(b.dataset.play, b);
});

// ---- collection: champions and icons ------------------------------------------------------
function renderCollection() {
  $$("#view-collection .subtab").forEach((t) => t.classList.toggle("on", t.dataset.sub === S.sub));
  $("#champ-tools").hidden = S.sub !== "champions";
  $("#champ-grid").hidden = S.sub !== "champions";
  $("#icon-pane").hidden = S.sub !== "icons";
  return S.sub === "champions" ? renderChampions() : renderIcons();
}
function renderChampions() {
  const q = $("#champ-search").value.trim().toLowerCase();
  const f = $("#champ-filter").value;
  const list = S.champs.filter((c) => (!q || c.name.toLowerCase().includes(q))
    && (f === "all" || (f === "new" && c.new) || (f === "playable" && c.playable)));
  $("#champ-owned").textContent = `${S.champs.length} owned`;
  $("#champ-grid").innerHTML = list.length ? list.map((c) => `
    <button class="champ" data-champ="${c.id}">${c.unreleased ? '<i class="flag rare">Unreleased</i>' : c.new ? '<i class="flag">New</i>' : c.playable ? '<i class="flag play">Tutorial</i>' : ""}
      ${img(c.portrait, 0, "")}<span class="name">${esc(c.name)}</span></button>`).join("")
    : `<p class="empty">No champion matches “${esc(q)}”.</p>`;
}
$("#champ-search").addEventListener("input", renderChampions);
$("#champ-filter").addEventListener("change", renderChampions);
$("#view-collection .subtabs").addEventListener("click", (ev) => {
  const t = ev.target.closest(".subtab"); if (!t) return;
  S.sub = t.dataset.sub; renderCollection();
});
function slotsHtml() {
  return [0, 1, 2, 3, 4].map((i) => `<button class="slot ${i === S.slot ? "on" : ""}" data-slot="${i}"
      aria-label="Slot ${i + 1}">${img(iconPic(header()[i]), 0)}</button>`).join("");
}
function renderIcons() {
  $("#col-slots").innerHTML = slotsHtml();
  const used = new Set(header().map((h) => h.toLowerCase()));
  $("#icon-grid").innerHTML = S.cos.icons.map((i) => `<button data-icon="${i.id}" title="${esc(i.name)}"
      class="${used.has(i.id.toLowerCase()) ? "used" : ""}">${img(i.picture, 0, i.name)}</button>`).join("");
}
document.addEventListener("click", async (ev) => {
  const s = ev.target.closest("[data-slot]");
  if (s) { S.slot = +s.dataset.slot; $$(".slot").forEach((x) => x.classList.toggle("on", +x.dataset.slot === S.slot)); }
  const i = ev.target.closest("[data-icon]");
  if (i) {
    const r = await api("/api/profile/icon", { slot: S.slot, icon: i.dataset.icon });
    if (!r.ok) return toast(r.error || "Could not set the icon");
    await poll();
    toast(`Icon set in slot ${S.slot + 1}`);
    if (!$("#icon-pane").hidden) renderIcons();
    if (!$("#view-profile").hidden) renderProfile();
  }
});

// champion page
const SLOT_NAMES = { 0: "Basic", 1: "Q", 2: "W", 3: "E", 4: "R", 5: "Passive" };
const STAT = { 3: "Cost", 5: "Damage", 15: "Cooldown", 18: "Range" };
function statParts(stats) {
  return (stats || "").split(" ").map((p) => {
    const m = p.match(/^(\d+)=(.*)$/); if (!m || !STAT[m[1]]) return "";
    let v = m[2]; if (m[1] === "3") v = v.replace(/^-/, "").replace(/\(-/, "(");
    return `${STAT[m[1]]} ${v}${m[1] === "15" ? " s" : ""}`;
  }).filter(Boolean);
}
function openChampion(id) {
  const c = S.champs.find((x) => x.id === id); if (!c) return;
  setBackdrop([c.art, c.wallpaper, c.portrait]);
  $("#cp-tag").textContent = c.playable ? "Playable in Tutorial 1" : c.unreleased ? "Never released: found in your install"
    : c.new ? "Added from your install" : "Champion";
  $("#cp-name").textContent = c.name;
  $("#cp-abilities").innerHTML = c.skills.map((s, k) => `<button class="ability ${k === 0 ? "on" : ""}" data-ability="${k}"
      aria-label="${esc(s.name)}">${img(s.icon, 0, "")}<i>${esc(SLOT_NAMES[s.slot] ?? s.key)}</i></button>`).join("");
  S.cpSkills = c.skills;
  showAbility(0);
  $("#cp-skins-title").hidden = !c.skins.length;
  $("#cp-skins").innerHTML = c.skins.map((s) => img(s.wallpaper || s.portrait, 256, c.name + " skin")).join("");
  $("#champ-page").hidden = false;
  $("#main").classList.add("detail");
  $("#main").scrollTop = 0;
  $(".champ-page .close").focus();
}
function closeChampion() {
  if ($("#champ-page").hidden) return;
  $("#champ-page").hidden = true;
  $("#main").classList.remove("detail");
  setBackdrop(batmanArt());
}
function showAbility(k) {
  const s = S.cpSkills[k];
  $$(".ability").forEach((b) => b.classList.toggle("on", +b.dataset.ability === k));
  $("#cp-info").innerHTML = s ? `<b>${esc(s.name)}</b><div class="stats">${chips(statParts(s.stats))}</div>`
    : `<p class="empty">This champion's abilities aren't in the catalog yet.</p>`;
}
document.addEventListener("click", (ev) => {
  const c = ev.target.closest("[data-champ]"); if (c) openChampion(c.dataset.champ);
  const a = ev.target.closest("[data-ability]"); if (a) showAbility(+a.dataset.ability);
  if (ev.target.closest("[data-close]")) closeChampion();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  if (!$("#lobby").hidden) closeLobby(); else closeChampion();
});

// ---- profile -----------------------------------------------------------------------------
function renderProfile() {
  const b = batman();
  setBackdrop(batmanArt());
  const st = S.state || { player: "Player", level: 30, completed: [], champions: S.champs.length };
  $("#profile-name").textContent = st.player;
  $("#profile-level").textContent = st.level;
  $("#profile-sub").textContent = `${st.champions} champions`;
  const pic = iconPic(header()[0]);
  if (pic) $("#profile-icon").src = tex(pic);
  $("#slots").innerHTML = slotsHtml();
  const done = new Set(st.completed.map((d) => d.toLowerCase()));
  $("#progress").innerHTML = S.enc.filter((e) => e.mode === "Training").map((e) => {
    const ok = done.has(e.id.toLowerCase());
    return `<li class="${ok ? "done" : ""}"><b>${esc(pretty(e.name))}</b><small>${ok ? "Completed" : e.playable ? "Not completed" : "Coming later"}</small></li>`;
  }).join("");
}

// ---- arsenal -----------------------------------------------------------------------------
const initials = (b) => (b || "?").replace(/[^A-Za-z ]/g, "").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2);
const brandKey = (b) => (b || "").toLowerCase().replace(/[^a-z]/g, "");
function ampName(a) {
  let n = a.name || "";
  if (a.brand && n.startsWith(a.brand)) n = n.slice(a.brand.length).trim();
  const m = n.match(/^Augment Codename:\s*(.+)$/i);
  if (m) return m[1].charAt(0) + m[1].slice(1).toLowerCase();
  return n.replace(/^Mod\s+/, "");
}
// "Attack Speed +%0.0269" -> "Attack Speed +2.69%"
const ampStats = (s) => (s || "").split(/;\s*/).filter(Boolean)
  .map((p) => p.replace(/([+-])%(\d*\.?\d+)/, (_, sg, v) => `${sg}${+(v * 100).toFixed(2)}%`));
async function renderArsenal() {
  S.items ??= await api("/api/items");
  $$("#view-arsenal .subtab").forEach((t) => t.classList.toggle("on", t.dataset.tab === S.tab));
  const sel = $("#brand-filter");
  if (!sel.options.length) {
    const brands = [...new Set(S.items.amplifiers.map((a) => a.brand).filter(Boolean))].sort();
    sel.innerHTML = `<option value="">All brands</option>` + brands.map((b) => `<option>${esc(b)}</option>`).join("");
  }
  sel.hidden = S.tab !== "amplifiers";
  const q = $("#arsenal-search").value.trim().toLowerCase();
  const hit = (...xs) => !q || xs.join(" ").toLowerCase().includes(q);
  let html = "";
  if (S.tab === "amplifiers") {
    for (const kind of ["augment", "mod"]) {
      const rows = S.items.amplifiers.filter((a) => a.type === kind && (!sel.value || a.brand === sel.value)
        && hit(a.name, a.brand, a.stats, a.targets));
      if (!rows.length) continue;
      html += `<h3 class="group-title">${kind === "augment" ? "Augments" : "Mods"}<span class="count">${rows.length}</span></h3><div class="list">`
        + rows.map((a) => `<div class="item"><div class="ph brand-${brandKey(a.brand)}">${esc(initials(a.brand))}</div><div>
          <b>${esc(ampName(a))}</b><small>${esc(a.brand)}</small>
          <div class="stats">${chips(ampStats(a.stats || a.targets))}</div></div></div>`).join("") + "</div>";
    }
  } else if (S.tab === "artifacts") {
    const rows = S.items.artifacts.filter((a) => hit(a.name, a.category, a.stats));
    html = rows.length ? `<div class="list">` + rows.map((a) => `<div class="item">${img(a.icon, 0, a.name)}<div><b>${esc(a.name)}</b>
      <small>${esc(a.category)} artifact, tier ${esc(a.tier)}, ${esc(a.cost)} credits</small>
      <div class="stats">${chips(ampStats(a.stats))}</div></div></div>`).join("") + "</div>" : "";
  } else {
    const rows = S.items.stolen_powers.filter((p) => hit(p.power, p.champion));
    html = rows.length ? `<div class="list">` + rows.map((p) => `<div class="item">${img(p.icon, 0, p.power)}<div><b>${esc(p.power)}</b>
      <small>${esc(p.champion)}</small></div></div>`).join("") + "</div>" : "";
  }
  $("#arsenal-body").innerHTML = html || `<p class="empty">Nothing matches “${esc(q)}”.</p>`;
}
$("#arsenal-search").addEventListener("input", renderArsenal);
$("#brand-filter").addEventListener("change", renderArsenal);
$("#view-arsenal .subtabs").addEventListener("click", (ev) => {
  const t = ev.target.closest(".subtab"); if (!t) return;
  S.tab = t.dataset.tab; renderArsenal();
});

// ---- friends and chat (icserver/social.py) ----------------------------------------------------
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } } };
const SOC = { status: store.get("ic.status", "online"), data: null, tabs: store.get("ic.chats", []), with: null, min: false,
  log: {}, lastId: {} };
const PRES = { online: "Online", away: "Away", busy: "Busy", ingame: "In game", offline: "Offline" };
const me = () => S.state?.player || "Player";
async function pollSocial() {
  if (!S.state) return;
  try {
    SOC.data = await api(`/api/social?me=${encodeURIComponent(me())}&status=${SOC.status}`);
  } catch { return; }
  renderSocial();
}
function friendRow(f) {
  return `<li><button class="friend" data-chat="${esc(f.name)}"><span class="f-av">${esc(f.name[0].toUpperCase())}<b class="pres-dot ${f.status}"></b></span>
    <span class="f-text"><b>${esc(f.name)}</b><small class="pres-${f.status}" ${f.is_friend_back ? "" : 'title="They have not added you back yet"'}>${PRES[f.status]}</small></span>
    ${f.unread ? `<i class="unread">${f.unread}</i>` : ""}</button>
    <button class="f-remove" data-unfriend="${esc(f.name)}" aria-label="Remove ${esc(f.name)}" title="Remove">×</button></li>`;
}
function renderSocial() {
  const d = SOC.data; if (!d) return;
  $("#soc-status").value = SOC.status;
  $("#soc-dot").className = "pres-dot " + (d.status === "offline" ? SOC.status : d.status);
  const on = d.friends.filter((f) => f.status !== "offline"), off = d.friends.filter((f) => f.status === "offline");
  $("#friends-count").textContent = on.length;
  const unread = d.friends.reduce((n, f) => n + f.unread, 0);
  $("#friends-btn").classList.toggle("has-unread", unread > 0);
  const group = (title, list, open = true) => `<details class="fgroup" ${open ? "open" : ""}><summary>${title}<span>${list.length}</span></summary>
    <ul>${list.map(friendRow).join("") || '<li class="none">Nobody here yet</li>'}</ul></details>`;
  $("#soc-lists").innerHTML =
    (d.requests.length ? `<details class="fgroup" open><summary>Friend requests<span>${d.requests.length}</span></summary><ul>${d.requests.map((n) =>
      `<li class="req"><span class="f-av">${esc(n[0].toUpperCase())}</span><span class="f-text"><b>${esc(n)}</b><small>Added you</small></span>
       <button class="btn-mini" data-accept="${esc(n)}">Accept</button></li>`).join("")}</ul></details>` : "")
    + group("Online", on) + group("Offline", off, on.length < 8)
    + (d.friends.length ? "" : `<p class="soc-empty">Add friends by their player name. When they open this app on your server, they show up here and you can chat.</p>`);
  renderChatTabs();
}
$("#soc-status").addEventListener("change", (e) => { SOC.status = e.target.value; store.set("ic.status", SOC.status); pollSocial(); renderStatus(); });
$("#add-friend").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#add-name").value.trim(); if (!name) return;
  const r = await api("/api/social/friend", { me: me(), name });
  if (!r.ok) return toast(r.error || "Could not add the friend");
  $("#add-name").value = ""; toast(`${name} added to your friends`); pollSocial();
});
document.addEventListener("click", async (ev) => {
  const acc = ev.target.closest("[data-accept]");
  if (acc) { await api("/api/social/friend", { me: me(), name: acc.dataset.accept }); toast(`${acc.dataset.accept} is now your friend`); pollSocial(); }
  const rm = ev.target.closest("[data-unfriend]");
  if (rm) { await api("/api/social/friend", { me: me(), name: rm.dataset.unfriend, remove: true }); toast(`${rm.dataset.unfriend} removed`); pollSocial(); }
  const c = ev.target.closest("[data-chat]"); if (c) openChat(c.dataset.chat);
  const t = ev.target.closest("[data-tab-chat]"); if (t) openChat(t.dataset.tabChat);
});
// friends panel open / closed (remembered per browser)
function setSocialOpen(open) {
  $(".client").classList.toggle("social-closed", !open);
  $("#friends-btn").setAttribute("aria-pressed", String(open));
  store.set("ic.social", open);
}
$("#friends-btn").addEventListener("click", () => setSocialOpen($(".client").classList.contains("social-closed")));
setSocialOpen(store.get("ic.social", window.innerWidth > 1100));

// chat dock
function openChat(name) {
  if (!SOC.tabs.includes(name)) SOC.tabs = [...SOC.tabs, name].slice(-5);
  SOC.with = name; SOC.min = false; store.set("ic.chats", SOC.tabs);
  SOC.log[name] ??= []; SOC.lastId[name] ??= 0;
  $("#chat").hidden = false; $("#chat").classList.remove("min");
  renderChatTabs(); renderChatLog(); pollChat(); $("#chat-input").focus();
}
function renderChatTabs() {
  if (!SOC.tabs.length) { $("#chat").hidden = true; return; }
  const by = Object.fromEntries((SOC.data?.friends || []).map((f) => [f.name.toLowerCase(), f]));
  $("#chat-tabs").innerHTML = SOC.tabs.map((n) => {
    const f = by[n.toLowerCase()] || { status: "offline", unread: 0 };
    return `<button role="tab" class="chat-tab ${n === SOC.with && !SOC.min ? "on" : ""}" data-tab-chat="${esc(n)}" aria-selected="${n === SOC.with}">
      <b class="pres-dot ${f.status}"></b>${esc(n)}${f.unread && n !== SOC.with ? `<i class="unread">${f.unread}</i>` : ""}</button>`;
  }).join("");
  if (SOC.with) {
    const f = by[SOC.with.toLowerCase()];
    $("#chat-with").textContent = SOC.with;
    $("#chat-pres").textContent = f ? PRES[f.status] : "Not in your friends";
  }
}
const hhmm = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function renderChatLog() {
  const log = SOC.log[SOC.with] || [];
  $("#chat-log").innerHTML = log.length ? log.map((m) => `<li class="${m.from.toLowerCase() === me().toLowerCase() ? "mine" : ""}">
      <p>${esc(m.text)}</p><time>${hhmm(m.t)}</time></li>`).join("")
    : `<li class="chat-empty">Say hi to ${esc(SOC.with)}. Messages wait here until they come online.</li>`;
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}
async function pollChat() {
  const w = SOC.with; if (!w || SOC.min || $("#chat").hidden || !S.state) return;
  try {
    const r = await api(`/api/chat?me=${encodeURIComponent(me())}&with=${encodeURIComponent(w)}&since=${SOC.lastId[w] || 0}`);
    if (r.messages.length) {
      SOC.log[w] = [...SOC.log[w], ...r.messages]; SOC.lastId[w] = r.messages[r.messages.length - 1].id;
      if (w === SOC.with) renderChatLog();
      if (r.messages.some((m) => m.from.toLowerCase() !== me().toLowerCase())) pollSocial();
    }
  } catch { /* server offline: the light shows it */ }
}
$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#chat-input").value.trim(); if (!text || !SOC.with) return;
  $("#chat-input").value = "";
  const r = await api("/api/chat", { me: me(), to: SOC.with, text });
  if (!r.ok) return toast(r.error || "Message not sent");
  pollChat();
});
$("#chat-min").addEventListener("click", () => { SOC.min = !SOC.min; $("#chat").classList.toggle("min", SOC.min); renderChatTabs(); });
$("#chat-close").addEventListener("click", () => {
  SOC.tabs = SOC.tabs.filter((n) => n !== SOC.with); store.set("ic.chats", SOC.tabs);
  SOC.with = SOC.tabs[SOC.tabs.length - 1] || null;
  if (SOC.with) { renderChatTabs(); renderChatLog(); pollChat(); } else $("#chat").hidden = true;
});
if (SOC.tabs.length) { SOC.with = SOC.tabs[SOC.tabs.length - 1]; SOC.min = true; $("#chat").hidden = false; $("#chat").classList.add("min"); SOC.log[SOC.with] = []; }
setInterval(pollSocial, 4000);
setInterval(pollChat, 2000);

// ---- settings: interface switch (icserver/interface.py) ------------------------------------
async function openSettings() {
  let ui = { mode: "new", hotkey: "ctrl+shift+u", can_switch: false };
  try { ui = await api("/api/interface"); } catch { /* offline */ }
  const key = (ui.hotkey || "").split("+").map((k) => k.length === 1 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1)).join("+");
  $("#ui-note").textContent = `From the game, press ${key} to come back to this launcher.`
    + (ui.return_after_match ? " After each match this launcher comes back by itself." : "");
  $("#to-legacy").disabled = !ui.can_switch;
  if (!ui.can_switch) $("#ui-note").textContent += " (Start with python ic.py play to switch from here.)";
  $("#settings").hidden = false;
}
$("#settings-btn").addEventListener("click", openSettings);
$("#to-legacy").addEventListener("click", () => { $("#settings").hidden = true; $("#confirm").hidden = false; $("#confirm-yes").focus(); });
$("#confirm-yes").addEventListener("click", async () => {
  $("#confirm").hidden = true;
  const r = await api("/api/interface", { mode: "legacy" });
  if (!r.ok) return toast(r.error || "Could not switch");
  $("#restarting").hidden = false;
  setTimeout(() => { try { window.close(); } catch { /* the server closes the window */ } }, 1500);
});
document.addEventListener("click", (ev) => {
  if (ev.target.closest("[data-settings-close]") || ev.target === $("#settings")) $("#settings").hidden = true;
  if (ev.target.closest("[data-confirm-close]") || ev.target === $("#confirm")) $("#confirm").hidden = true;
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { $("#settings").hidden = true; $("#confirm").hidden = true; } });

poll().then(() => { show(location.hash.slice(1)); pollSocial(); });
setInterval(poll, 3000);
