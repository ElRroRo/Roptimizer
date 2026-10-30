// Chart modules (spec section 4): every folder in app/charts/ with a module.json is a panel. The server lists them
// (/api/charts); each one's panel.js registers itself with registerPanel (room.js) and joins every slot's menu.
// Loaded while the page is parsed, so the modules are in the registry before the room is first drawn.
(function () {
  let mods = [];
  try { mods = API.get("/api/charts").items; } catch (e) { console.error("chart modules:", e.message); }
  window.CHART_MODULES = mods;
  mods.forEach((m) => document.write(`<script src="/charts/${encodeURIComponent(m.name)}/panel.js"><\/script>`));
})();
