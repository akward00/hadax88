const state = {
  host: "",
  port: 8899,
  data: null,
  snapshot: null,
  expanded: new Set(),
  statusMap: loadStatusMap(),
  busy: false,
  pollTimer: null,
  generation: -1,
  lastUnknownPayload: "",
  pendingEvent: null,
  lastStatusData: null,
  statusTracking: localStorage.getItem("dax88-status-tracking") === "1",
  statusLog: [],
  lastTrackedSeq: 0,
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
  statusTracking: document.querySelector("#statusTrackingInput"),
  statusTrackerPanel: document.querySelector("#statusTrackerPanel"),
  statusTrackerLog: document.querySelector("#statusTrackerLog"),
  statusTrackerCount: document.querySelector("#statusTrackerCount"),
  statusTrackerClear: document.querySelector("#statusTrackerClear"),
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
  el.statusTracking.checked = state.statusTracking;
  el.statusTracking.addEventListener("change", () => {
    state.statusTracking = el.statusTracking.checked;
    localStorage.setItem("dax88-status-tracking", state.statusTracking ? "1" : "0");
    renderStatusTracker();
  });
  el.statusTrackerClear.addEventListener("click", () => {
    state.statusLog = [];
    renderStatusTracker();
  });
  el.host.addEventListener("keydown", (event) => {
    if (event.key === "Enter") query();
  });
  renderMapping();
  renderStatusTracker();
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
    state.snapshot = payload;
    state.generation = payload.generation;
    state.pendingEvent = null;
    state.lastStatusData = cloneState(payload.state);
    appendReceivedFrames(payload, "connect");
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
      const update = payload.last_update || {};
      let learned = "";

      if (update.type === "event" && update.event?.zones?.length) {
        state.pendingEvent = {
          event: update.event,
          baseline: cloneState(state.lastStatusData || state.data),
        };
      } else if (update.type === "status") {
        if (state.pendingEvent) {
          learned = learnStatusMapFromEvent(state.pendingEvent.event, state.pendingEvent.baseline, payload.state);
          state.pendingEvent = null;
        }
        state.lastStatusData = cloneState(payload.state);
      }

      state.generation = payload.generation;
      state.data = payload.state;
      state.snapshot = payload;
      appendReceivedFrames(payload, "push");
      render();

      if (payload.last_unknown && payload.last_unknown.raw_payload_hex !== state.lastUnknownPayload) {
        state.lastUnknownPayload = payload.last_unknown.raw_payload_hex;
        setMessage(`Unknown frame: ${payload.last_unknown.reason || "unrecognized"}`, true);
      } else if (learned) {
        setMessage(`Learned ${learned}.`);
      } else if (update.type === "event" && update.event) {
        setMessage(`Event: ${update.event.command} zone ${update.event.zones.join(",") || "?"}`);
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

function appendReceivedFrames(payload, source) {
  if (!state.statusTracking) return;
  const updates = Array.isArray(payload.update_log) ? payload.update_log : [payload.last_update || {}];
  const fresh = updates.filter((update) => {
    if (!update || !update.type) return false;
    if (update.seq == null) return update !== payload.last_update || payload.generation !== state.generation;
    return update.seq > state.lastTrackedSeq;
  });
  if (!fresh.length) return;

  for (const update of fresh) {
    if (update.seq != null) state.lastTrackedSeq = Math.max(state.lastTrackedSeq, update.seq);
    state.statusLog.unshift({
      at: update.rx ? new Date(update.rx * 1000).toLocaleTimeString() : new Date().toLocaleTimeString(),
      source,
      generation: payload.generation,
      seq: update.seq,
      type: update.type,
      raw: update.raw_payload_hex || "",
      event: update.event || null,
      config: update.config || null,
      reason: update.reason || "",
      interpretation: update.type === "status" && payload.state ? summarizeStatus(payload.state) : null,
    });
  }
  state.statusLog = state.statusLog.slice(0, 100);
  renderStatusTracker();
}

function summarizeStatus(data) {
  return (data.zones || []).map((zone) => ({
    zone: zone.zone,
    name: zone.name,
    source: zone.source,
    volume: zone.volume,
    treble: zone.treble,
    bass: zone.bass,
    balance: zone.balance,
    power_on: zone.power_on,
    muted: zone.muted,
    raw: {
      source: zone.source_raw,
      volume: zone.volume_raw,
      treble: zone.treble_raw,
      bass: zone.bass_raw,
      balance: zone.balance_raw,
      power: zone.power_raw,
      mute: zone.mute_raw,
    },
  }));
}

function renderStatusTracker() {
  el.statusTrackerPanel.classList.toggle("hidden", !state.statusTracking);
  el.statusTrackerCount.textContent = `${state.statusLog.length} frame${state.statusLog.length === 1 ? "" : "s"}`;
  if (!state.statusLog.length) {
    el.statusTrackerLog.textContent = "No frames captured yet.";
    return;
  }
  el.statusTrackerLog.textContent = state.statusLog.map(formatStatusEntry).join("\n\n");
}

function formatStatusEntry(entry) {
  const header = `[${entry.at}] ${entry.source} ${entry.type} frame${entry.seq ? ` #${entry.seq}` : ""} generation ${entry.generation}`;
  const raw = `Actual bytes received:\n  ${entry.raw || "(none)"}`;
  if (entry.type === "event" && entry.event) {
    return `${header}\n${raw}\nOur interpretation:\n  event command=${entry.event.command} value=${entry.event.value} raw=${entry.event.value_raw} zones=${(entry.event.zones || []).join(",") || "?"}`;
  }
  if (entry.type === "config" && entry.config) {
    return `${header}\n${raw}\nOur interpretation:\n  config device=${entry.config.device_name || "?"} zones=${(entry.config.zones || []).join(" | ")} sources=${(entry.config.sources || []).join(" | ")}`;
  }
  if (entry.type === "unknown") {
    return `${header}\n${raw}\nOur interpretation:\n  unknown ${entry.reason || "unrecognized frame"}`;
  }
  const zones = (entry.interpretation || []).map((zone) => (
    `  Z${zone.zone} ${zone.name}: power=${zone.power_on ? "on" : "off"} mute=${zone.muted ? "on" : "off"} src=${zone.source} vol=${zone.volume} tr=${zone.treble} bs=${zone.bass} bal=${zone.balance} raw=[src:${zone.raw.source} vol:${zone.raw.volume} tr:${zone.raw.treble} bs:${zone.raw.bass} bal:${zone.raw.balance} pwr:${zone.raw.power} mute:${zone.raw.mute}]`
  )).join("\n");
  return `${header}\n${raw}\nOur interpretation:\n${zones || "  no parsed zone state"}`;
}
function render() {
  const data = state.data;
  el.statusDot.classList.toggle("online", Boolean(data));
  el.deviceName.textContent = data?.device_name || "DAX88 Debug Control";
  el.debug.textContent = data ? JSON.stringify({ statusMap: state.statusMap, snapshot: state.snapshot, raw: data }, null, 2) : "No query yet.";
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
  const explicitPowerSlot = state.statusMap.power?.[String(logicalZoneNumber)];
  const powerKnown = explicitPowerSlot != null;
  const power = statusFor(data, logicalZoneNumber, "power");
  const defaultPowerSlotClaimedBy = claimedPowerSlots[String(logicalZoneNumber)];
  const hasPowerConflict = !powerKnown && defaultPowerSlotClaimedBy && defaultPowerSlotClaimedBy !== logicalZoneNumber;
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
    power_known: powerKnown && !hasPowerConflict,
    status_conflict: !powerKnown ? "Power status is uncalibrated; use On/Off until this zone is observed changing." : (hasPowerConflict ? `Power status slot ${logicalZoneNumber} is claimed by zone ${defaultPowerSlotClaimedBy}; this zone still needs calibration.` : ""),
  };
}

function zoneTemplate(zone, sources, expanded) {
  const sourceCount = Math.max(8, sources.length, Number(zone.source || 0));
  const sourceOptions = Array.from({ length: sourceCount }, (_, index) => {
    const source = index + 1;
    return `<option value="${source}" ${source === zone.source ? "selected" : ""}>${escapeHtml(sourceLabel(sources, source))}</option>`;
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
        <button class="toggle ${zone.power_known && zone.power_on ? "on" : ""}" type="button" data-command="power" title="${zone.power_known ? "Power" : "Power state unknown; use On/Off"}" ${zone.power_known ? "" : "disabled"}></button>
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

function sourceLabel(sources, source) {
  return sources[source - 1] || (source === 8 ? "Wi-Fi" : `Source ${source}`);
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
    const update = payload.last_update || {};
    if (payload.state) {
      if (update.type === "event" && update.event?.zones?.length) {
        state.pendingEvent = {
          event: update.event,
          baseline: cloneState(state.lastStatusData || state.data),
        };
      } else if (update.type === "status") {
        state.lastStatusData = cloneState(payload.state);
      }
      state.generation = payload.generation;
      state.data = payload.state;
      state.snapshot = payload;
      appendReceivedFrames(payload, "send");
      render();
    }
    if (update.type === "event" && update.event) {
      setMessage(`Echoed ${update.event.command} event for zone ${update.event.zones.join(",") || zone}.`);
    } else {
      setMessage(`Sent ${command} to zone ${zone}; waiting for pushed confirmation.`);
    }
  } catch (err) {
    setMessage(err.message, true);
  } finally {
    setBusy(false);
  }
}

function learnStatusMapFromEvent(event, before, after) {
  if (!event?.command || !event.zones?.length || !before?.zones?.length || !after?.zones?.length) return "";
  const logicalZoneNumber = Number(event.zones[0]);
  const command = event.command;
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
  if (!field) return "";

  const changed = [];
  for (const afterZone of after.zones) {
    const beforeZone = before.zones.find((zone) => zone.zone === afterZone.zone);
    if (!beforeZone) continue;
    if (beforeZone[field] !== afterZone[field]) {
      if (event.value_raw == null || afterZone[field] === event.value_raw) {
        changed.push(afterZone.zone);
      }
    }
  }

  if (changed.length !== 1) return "";
  state.statusMap[command] = state.statusMap[command] || {};
  state.statusMap[command][String(logicalZoneNumber)] = changed[0];
  if (changed[0] === logicalZoneNumber) {
    saveStatusMap();
    renderMapping();
    return `${command} for zone ${logicalZoneNumber} reads its own status slot`;
  }
  saveStatusMap();
  renderMapping();
  return `${command} for zone ${logicalZoneNumber} reads status slot ${changed[0]}`;
}

function cloneState(value) {
  return value ? JSON.parse(JSON.stringify(value)) : null;
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

  if (changed.length === 1) {
    state.statusMap[command] = state.statusMap[command] || {};
    state.statusMap[command][String(logicalZoneNumber)] = changed[0];
    saveStatusMap();
    renderMapping();
    if (changed[0] === logicalZoneNumber) return `${command} for zone ${logicalZoneNumber} reads its own status slot`;
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
