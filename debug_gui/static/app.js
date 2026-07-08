const state = {
  host: "",
  port: 8899,
  data: null,
  expanded: new Set(),
  statusMap: loadStatusMap(),
  busy: false,
  pollTimer: null,
  generation: -1,
};

const el = {
  deviceName: document.querySelector("#deviceName"),
  statusDot: document.querySelector("#statusDot"),
  host: document.querySelector("#hostInput"),
  port: document.querySelector("#portInput"),
  subnet: document.querySelector("#subnetInput"),
  connect: document.querySelector("#connectBtn"),
  scan: document.querySelector("#scanBtn"),
  refresh: document.querySelector("#refreshBtn"),
  zones: document.querySelector("#zones"),
  message: document.querySelector("#message"),
  mapping: document.querySelector("#mapping"),
  scanResults: document.querySelector("#scanResults"),
  debug: document.querySelector("#debugText"),
};

async function init() {
  try {
    const res = await fetch("/api/defaults");
    const defaults = await res.json();
    el.subnet.value = defaults.subnet || "";
    el.port.value = defaults.port || 8899;
  } catch {
    el.subnet.value = "192.168.1.0/24";
  }

  const savedHost = localStorage.getItem("dax88-host");
  if (savedHost) el.host.value = savedHost;

  el.connect.addEventListener("click", query);
  el.refresh.addEventListener("click", query);
  el.scan.addEventListener("click", scan);
  el.host.addEventListener("keydown", (event) => {
    if (event.key === "Enter") query();
  });
  renderMapping();
}

function setMessage(text, error = false) {
  el.message.textContent = text;
  el.message.classList.toggle("error", error);
  el.message.classList.toggle("hidden", !text);
}

function setBusy(busy) {
  state.busy = busy;
  el.connect.disabled = busy;
  el.scan.disabled = busy;
  el.refresh.disabled = busy;
}

function connection() {
  return {
    host: el.host.value.trim(),
    port: Number(el.port.value || 8899),
  };
}

async function connectState(host, port) {
  const res = await fetch(`/api/connect?host=${encodeURIComponent(host)}&port=${port}`);
  const payload = await res.json();
  if (!payload.ok) throw new Error(payload.error || "Connect failed");
  return payload;
}

async function fetchSubscriptionState(host, port) {
  const res = await fetch(`/api/state?host=${encodeURIComponent(host)}&port=${port}`);
  const payload = await res.json();
  if (!payload.ok) throw new Error(payload.error || "State refresh failed");
  return payload;
}

async function query() {
  const { host, port } = connection();
  if (!host) {
    setMessage("Enter a DAX88 host/IP first.", true);
    return;
  }

  setBusy(true);
  setMessage("Querying DAX88...");
  try {
    state.host = host;
    state.port = port;
    const payload = await connectState(host, port);
    if (!payload.state) throw new Error(payload.last_error || "No subscription state received yet");
    state.data = payload.state;
    state.generation = payload.generation;
    localStorage.setItem("dax88-host", host);
    startStatePoll();
    render();
    setMessage(`Subscribed to ${state.data.device_name || host}.`);
  } catch (err) {
    state.data = null;
    render();
    setMessage(err.message, true);
  } finally {
    setBusy(false);
  }
}

function startStatePoll() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refreshSubscriptionState, 600);
}

async function refreshSubscriptionState() {
  if (!state.host || state.busy) return;
  try {
    const payload = await fetchSubscriptionState(state.host, state.port);
    if (payload.generation !== state.generation && payload.state) {
      state.generation = payload.generation;
      state.data = payload.state;
      render();
      if (payload.last_event) {
        setMessage(`Event: ${payload.last_event.command} zone ${payload.last_event.zones.join(",") || "?"}`);
      }
    }
  } catch (err) {
    setMessage(err.message, true);
  }
}

async function scan() {
  const subnet = el.subnet.value.trim();
  const port = Number(el.port.value || 8899);
  if (!subnet) {
    setMessage("Enter a subnet to scan.", true);
    return;
  }

  setBusy(true);
  setMessage(`Scanning ${subnet}...`);
  el.scanResults.classList.add("hidden");
  el.scanResults.innerHTML = "";
  try {
    const res = await fetch(`/api/scan?subnet=${encodeURIComponent(subnet)}&port=${port}`);
    const payload = await res.json();
    if (!payload.ok) throw new Error(payload.error || "Scan failed");
    renderScanResults(payload.devices);
    setMessage(payload.devices.length ? `Found ${payload.devices.length} DAX88 candidate(s).` : "No DAX88 devices found.");
  } catch (err) {
    setMessage(err.message, true);
  } finally {
    setBusy(false);
  }
}

function renderScanResults(devices) {
  el.scanResults.innerHTML = "";
  el.scanResults.classList.toggle("hidden", devices.length === 0);
  for (const device of devices) {
    const item = document.createElement("div");
    item.className = "device-option";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(device.device_name || "DAX88")}</strong>
        <span>${escapeHtml(device.host)} &middot; ${device.zones.length} zones &middot; ${device.sources.length} sources</span>
      </div>
      <button type="button">Use</button>
    `;
    item.querySelector("button").addEventListener("click", () => {
      el.host.value = device.host;
      query();
    });
    el.scanResults.appendChild(item);
  }
}

function render() {
  const data = state.data;
  el.statusDot.classList.toggle("online", Boolean(data));
  el.deviceName.textContent = data?.device_name || "DAX88 Debug Control";
  el.debug.textContent = data ? JSON.stringify({ statusMap: state.statusMap, raw: data }, null, 2) : "No query yet.";
  el.zones.innerHTML = "";
  renderMapping();

  if (!data?.zones?.length) return;

  const claimed = claimedStatusOwners("power");
  for (let zoneNum = 1; zoneNum <= data.zones.length; zoneNum += 1) {
    const zone = logicalZone(data, zoneNum, claimed);
    const card = document.createElement("article");
    const expanded = state.expanded.has(zone.zone);
    card.className = `zone ${expanded ? "" : "collapsed"}`;
    card.innerHTML = zoneTemplate(zone, data.config?.sources || [], expanded);
    bindZone(card, zone);
    el.zones.appendChild(card);
  }
}

function claimedStatusOwners(command) {
  const claimed = {};
  for (const [logical, slot] of Object.entries(state.statusMap[command] || {})) {
    claimed[String(slot)] = Number(logical);
  }
  return claimed;
}

function statusFor(data, logicalZoneNumber, command) {
  const statusSlot = Number(state.statusMap[command]?.[String(logicalZoneNumber)] || logicalZoneNumber);
  return data.zones.find((zone) => zone.zone === statusSlot) || data.zones[logicalZoneNumber - 1];
}

function logicalZone(data, logicalZoneNumber, claimedPowerSlots) {
  const base = data.zones[logicalZoneNumber - 1];
  const source = statusFor(data, logicalZoneNumber, "source");
  const volume = statusFor(data, logicalZoneNumber, "volume");
  const bass = statusFor(data, logicalZoneNumber, "bass");
  const treble = statusFor(data, logicalZoneNumber, "treble");
  const balance = statusFor(data, logicalZoneNumber, "balance");
  const mute = statusFor(data, logicalZoneNumber, "mute");
  const power = statusFor(data, logicalZoneNumber, "power");
  const defaultPowerSlotClaimedBy = claimedPowerSlots[String(logicalZoneNumber)];
  const hasPowerConflict = !state.statusMap.power?.[String(logicalZoneNumber)] && defaultPowerSlotClaimedBy && defaultPowerSlotClaimedBy !== logicalZoneNumber;
  const zoneName = data.config?.zones?.[logicalZoneNumber - 1] || `Zone ${logicalZoneNumber}`;

  return {
    ...base,
    zone: logicalZoneNumber,
    name: zoneName,
    source: source.source,
    source_name: source.source_name,
    source_raw: source.source_raw,
    volume: volume.volume,
    volume_raw: volume.volume_raw,
    bass: bass.bass,
    bass_raw: bass.bass_raw,
    treble: treble.treble,
    treble_raw: treble.treble_raw,
    balance: balance.balance,
    balance_raw: balance.balance_raw,
    muted: mute.muted,
    mute_raw: mute.mute_raw,
    power_on: power.power_on,
    power_raw: power.power_raw,
    power_status_slot: power.zone,
    power_known: !hasPowerConflict,
    status_conflict: hasPowerConflict ? `Power status slot ${logicalZoneNumber} is claimed by zone ${defaultPowerSlotClaimedBy}; this zone still needs calibration.` : "",
  };
}

function zoneTemplate(zone, sources, expanded) {
  const sourceOptions = sources.map((name, index) => {
    const source = index + 1;
    return `<option value="${source}" ${source === zone.source ? "selected" : ""}>${escapeHtml(name)}</option>`;
  }).join("");

  return `
    <div class="zone-header">
      <span class="zone-number">${zone.zone}</span>
      <span class="zone-title">${escapeHtml(zone.name)}</span>
      <button class="expand" type="button" data-action="expand" title="Expand zone">${expanded ? "^" : "v"}</button>
    </div>
    <div class="zone-body">
      <div class="zone-main">
        <select data-command="source">${sourceOptions}</select>
        <button class="toggle ${zone.power_known && zone.power_on ? "on" : ""}" type="button" data-command="power" title="Power"></button>
        <button class="mute" type="button" data-command="mute" title="Mute">${zone.muted ? "&#128263;" : "&#128264;"}</button>
      </div>
      <div class="power-row">
        <button type="button" class="${zone.power_known && zone.power_on ? "active" : ""}" data-power-value="true">On</button>
        <button type="button" class="${zone.power_known && !zone.power_on ? "active" : ""}" data-power-value="false">Off</button>
      </div>
      ${zone.status_conflict ? `<div class="slot-note">${escapeHtml(zone.status_conflict)}</div>` : ""}
      ${zone.power_status_slot !== zone.zone ? `<div class="slot-note">Power reads status slot ${zone.power_status_slot}; commands still send zone ${zone.zone}.</div>` : ""}
      ${slider("volume", "Volume", zone.volume, 0, 38)}
      <div class="advanced">
        ${balance(zone.balance)}
        ${slider("bass", "Bass", zone.bass, -12, 12)}
        ${slider("treble", "Treble", zone.treble, -12, 12)}
      </div>
    </div>
  `;
}

function slider(command, label, value, min, max) {
  return `
    <div class="control">
      <div class="control-label"><span>${label} <strong data-value-for="${command}">(${value})</strong></span></div>
      <div class="range-row">
        <button class="step" type="button" data-step="${command}" data-delta="-1">-</button>
        <input type="range" min="${min}" max="${max}" step="1" value="${value}" data-command="${command}">
        <button class="step" type="button" data-step="${command}" data-delta="1">+</button>
      </div>
    </div>
  `;
}

function balance(value) {
  return `
    <div class="control">
      <div class="control-label"><span>Balance <strong data-value-for="balance">(${value})</strong></span></div>
      <div class="balance-row">
        <span>L</span>
        <input type="range" min="0" max="20" step="1" value="${value}" data-command="balance">
        <span>R</span>
      </div>
    </div>
  `;
}

function bindZone(card, zone) {
  card.querySelector("[data-action='expand']").addEventListener("click", () => {
    if (state.expanded.has(zone.zone)) state.expanded.delete(zone.zone);
    else state.expanded.add(zone.zone);
    render();
  });

  card.querySelector("[data-command='power']").addEventListener("click", () => {
    send(zone.zone, "power", !zone.power_on);
  });

  for (const button of card.querySelectorAll("[data-power-value]")) {
    button.addEventListener("click", () => {
      send(zone.zone, "power", button.dataset.powerValue === "true");
    });
  }

  card.querySelector("[data-command='mute']").addEventListener("click", () => {
    send(zone.zone, "mute", !zone.muted);
  });

  card.querySelector("[data-command='source']").addEventListener("change", (event) => {
    send(zone.zone, "source", Number(event.target.value));
  });

  for (const input of card.querySelectorAll("input[type='range']")) {
    input.addEventListener("input", (event) => {
      const valueEl = card.querySelector(`[data-value-for='${event.target.dataset.command}']`);
      if (valueEl) valueEl.textContent = `(${event.target.value})`;
    });
    input.addEventListener("change", (event) => {
      send(zone.zone, event.target.dataset.command, Number(event.target.value));
    });
  }

  for (const button of card.querySelectorAll("[data-step]")) {
    button.addEventListener("click", () => {
      const command = button.dataset.step;
      const input = card.querySelector(`input[data-command='${command}']`);
      const next = clamp(Number(input.value) + Number(button.dataset.delta), Number(input.min), Number(input.max));
      input.value = next;
      const valueEl = card.querySelector(`[data-value-for='${command}']`);
      if (valueEl) valueEl.textContent = `(${next})`;
      send(zone.zone, command, next);
    });
  }
}

async function send(zone, command, value) {
  if (!state.host) return;
  const before = state.data;
  setBusy(true);
  setMessage(`Sending ${command} to zone ${zone}...`);
  try {
    const res = await fetch("/api/send", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        host: state.host,
        port: state.port,
        zone,
        command,
        value,
      }),
    });
    const payload = await res.json();
    if (!payload.ok) throw new Error(payload.error || "Command failed");
    if (payload.state) {
      const learned = learnStatusMap(zone, command, before, payload.state);
      state.data = payload.state;
      state.generation = payload.generation ?? state.generation;
      render();
      setMessage(learned ? `Sent ${command}; learned ${learned}.` : `Sent ${command} to zone ${zone}; waiting for pushed confirmation.`);
    } else {
      setMessage(`Sent ${command} to zone ${zone}; waiting for pushed confirmation.`);
    }
  } catch (err) {
    setMessage(err.message, true);
  } finally {
    setBusy(false);
  }
}

function learnStatusMap(logicalZoneNumber, command, before, after) {
  const fieldByCommand = {
    power: "power_raw",
    mute: "mute_raw",
    volume: "volume_raw",
    source: "source_raw",
    bass: "bass_raw",
    treble: "treble_raw",
    balance: "balance_raw",
  };
  const field = fieldByCommand[command];
  if (!field || !before?.zones?.length || !after?.zones?.length) return "";

  const changed = [];
  for (const afterZone of after.zones) {
    const beforeZone = before.zones.find((zone) => zone.zone === afterZone.zone);
    if (beforeZone && beforeZone[field] !== afterZone[field]) changed.push(afterZone.zone);
  }

  if (changed.length === 1 && changed[0] !== logicalZoneNumber) {
    state.statusMap[command] = state.statusMap[command] || {};
    state.statusMap[command][String(logicalZoneNumber)] = changed[0];
    saveStatusMap();
    renderMapping();
    return `${command} for zone ${logicalZoneNumber} reads status slot ${changed[0]}`;
  }
  return "";
}

function renderMapping() {
  const entries = [];
  for (const [command, map] of Object.entries(state.statusMap)) {
    for (const [zone, slot] of Object.entries(map || {})) {
      entries.push(`${command} zone ${zone} -> slot ${slot}`);
    }
  }
  el.mapping.classList.toggle("hidden", entries.length === 0);
  if (!entries.length) {
    el.mapping.innerHTML = "";
    return;
  }
  el.mapping.innerHTML = `<span>Status map: ${escapeHtml(entries.join(", "))}</span><button type="button">Reset</button>`;
  el.mapping.querySelector("button").addEventListener("click", () => {
    state.statusMap = emptyStatusMap();
    saveStatusMap();
    render();
  });
}

function emptyStatusMap() {
  return {
    power: {},
    mute: {},
    volume: {},
    source: {},
    bass: {},
    treble: {},
    balance: {},
  };
}

function loadStatusMap() {
  try {
    const raw = JSON.parse(localStorage.getItem("dax88-status-map") || "{}");
    if (raw.power || raw.source || raw.volume) {
      return { ...emptyStatusMap(), ...raw };
    }
    const migrated = emptyStatusMap();
    for (const [zone, slot] of Object.entries(raw)) {
      migrated.power[zone] = slot;
    }
    localStorage.setItem("dax88-status-map", JSON.stringify(migrated));
    return migrated;
  } catch {
    return emptyStatusMap();
  }
}

function saveStatusMap() {
  localStorage.setItem("dax88-status-map", JSON.stringify(state.statusMap));
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

init();
