/* JARVIS — Personal AI · frontend
   Talks to the local Python backend over:
     - GET  /events        Server-Sent-Events state + conversation stream
     - GET  /api/settings  current settings
     - GET  /api/history   persisted conversation
     - POST /api/command   submit a typed command
     - POST /api/stop      interrupt JARVIS while speaking
     - POST /api/listen    toggle continuous microphone capture
   No external libraries. The neural core is a canvas that adapts its quality
   to keep the UI smooth on slow machines. */

'use strict';

const $ = (sel) => document.querySelector(sel);

/* ------------------------------------------------------------------ */
/* Element refs                                                        */
/* ------------------------------------------------------------------ */
const body = document.body;
const coreVisual = $('#coreVisual');
const stateText = $('#stateText');
const stateDetail = $('#stateDetail');
const coreStateLabel = $('#coreStateLabel');
const micButton = $('#micButton');
const micButtonLabel = $('#micButtonLabel');
const stopButton = $('#stopButton');
const messagesEl = $('#messages');
const commandForm = $('#commandForm');
const commandInput = $('#commandInput');
const backendLabel = $('#backendLabel');
const backendChip = $('#backendChip');
const micLabel = $('#micLabel');
const waveform = $('#waveform');
const historyDrawer = $('#historyDrawer');
const settingsDrawer = $('#settingsDrawer');
const historyMessages = $('#historyMessages');
const toastEl = $('#toast');

/* ------------------------------------------------------------------ */
/* UI state                                                            */
/* ------------------------------------------------------------------ */
const app = {
  state: 'offline',        // mirror of backend state
  connected: false,        // are we receiving events right now?
  online: true,            // navigator.onLine
  autoListen: true,
  ttsActive: false,        // voice output currently playing (drives brain "talking")
  talk: 0,                 // smoothed speech-envelope level 0..1
  activeMsgId: null,       // id of the assistant message being streamed
  historyVisible: false,
};

const STATE_COPY = {
  idle:        { title: 'How can I help?',  detail: 'I’m right here when you need me.',        label: 'Ready' },
  listening:   { title: 'Listening',        detail: 'Go ahead — I’m all ears.',                label: 'Listening…' },
  understanding: { title: 'Understanding…', detail: 'Let me figure out what you need.',       label: 'Understanding…' },
  planning:    { title: 'Planning…',        detail: 'Working out the best way to help.',       label: 'Planning…' },
  executing:   { title: 'On it…',           detail: 'Taking care of that for you.',            label: 'Executing…' },
  processing:  { title: 'Thinking…',        detail: 'Just a moment.',                          label: 'Processing…' },
  speaking:    { title: 'Speaking',         detail: 'I’m with you.',                           label: 'Speaking…' },
  waiting_confirmation: { title: 'Your call', detail: 'Should I go ahead?',                   label: 'Waiting…' },
  interrupted: { title: 'Interrupted',      detail: 'I stopped. What were you saying?',        label: 'Listening…' },
  error:       { title: 'Something went wrong', detail: 'Try that again when you’re ready.',   label: 'Error' },
  offline:     { title: 'Offline',          detail: 'Reconnecting to the local JARVIS…',       label: 'Offline' },
};

/* Drive the neural activity level from the current state. */
const STATE_ACTIVITY = {
  idle: 0.18, listening: 0.55, understanding: 0.7, planning: 0.85,
  executing: 0.95, processing: 0.9, speaking: 0.7, waiting_confirmation: 0.4,
  interrupted: 0.6, error: 0.1, offline: 0.05,
};

let animating = true;

/* ------------------------------------------------------------------ */
/* Basic utilities                                                     */
/* ------------------------------------------------------------------ */
function timestamp() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function setBodyState(state) {
  app.state = state;
  body.dataset.state = state;
  const copy = STATE_COPY[state] || STATE_COPY.idle;
  stateText.textContent = copy.title;
  stateDetail.textContent = copy.detail;
  coreStateLabel.textContent = copy.label;
  coreVisual.dataset.state = state;
  micButtonLabel.textContent =
    state === 'idle' ? 'Start listening' :
    state === 'listening' ? (app.autoListen ? 'Listening' : 'Tap to listen') :
    state === 'processing' ? 'Working' :
    state === 'speaking' ? 'Speaking' : 'Start listening';
  body.dataset.autolisten = app.autoListen ? 'on' : 'off';
  const active = state === 'listening' || state === 'speaking' || state === 'processing' || state === 'interrupted';
  waveform.classList.toggle('active', active);
  stopButton.hidden = !(state === 'speaking' || state === 'processing');\n  activityIndicator.hidden = !(state === 'planning' || state === 'executing' || state === 'understanding');\n  if (!activityIndicator.hidden) { activityText.textContent = copy.title; }
  micButton.classList.toggle('muted', !app.autoListen);
}

/* ------------------------------------------------------------------ */
/* Neural core visualisation — rotating AI brain (canvas, adaptive)    */
/* ------------------------------------------------------------------ */
const canvas = $('#neuralCanvas');
const ctx = canvas.getContext('2d');
const N = {
  nodes: [], edges: [], signals: [], projected: [],
  width: 0, height: 0, dpr: 1, last: performance.now(), frames: 0,
  frameTime: 16, quality: 'medium', rotY: 0, breath: 0, phase: 0,
  activity: 0.2, target: 0.2, corePulse: 0,
};
const RUN_PROFILE = {
  idle: { speed: 0.5, activity: 10 }, listening: { speed: 1.0, activity: 34 },
  processing: { speed: 1.6, activity: 60 }, speaking: { speed: 1.1, activity: 40 },
  interrupted: { speed: 1.2, activity: 44 }, error: { speed: 0.3, activity: 4 },
  offline: { speed: 0.2, activity: 3 },
};
const QUALITY = {
  high: { nodeStride: 1, edgeStride: 1, signalFactor: 1, shadowBlur: 5 },
  medium: { nodeStride: 1, edgeStride: 2, signalFactor: 0.6, shadowBlur: 3 },
  low: { nodeStride: 2, edgeStride: 3, signalFactor: 0.35, shadowBlur: 0 },
};

function resizeCore() {
  const rect = canvas.getBoundingClientRect();
  N.dpr = Math.min(window.devicePixelRatio || 1, 1.5);
  N.width = Math.max(1, rect.width);
  N.height = Math.max(1, rect.height);
  canvas.width = Math.round(N.width * N.dpr);
  canvas.height = Math.round(N.height * N.dpr);
  ctx.setTransform(N.dpr, 0, 0, N.dpr, 0, 0);
}

function seedCore() {
  // A stylised brain: two hemispheres separated by a longitudinal fissure,
  // cortical folds approximated by layered sine modulation. Rotates on the
  // Y axis (plus a gentle tilt) to give the classic "AI brain" read.
  const count = 1500;
  const GAP = 0.045;          // hemisphere separation
  N.hemisphere = [];
  N.nodes = [];
  for (let i = 0; i < count; i += 1) {
    const left = i % 2 === 0 ? 1 : -1;
    // Bias sampling toward the shell so the cortex reads as a surface.
    const u = Math.random();
    const r = 0.55 + Math.pow(Math.random(), 0.35) * 0.55;
    const theta = Math.PI * 2 * Math.random();
    const phi = Math.acos(2 * u - 1);
    // Cortical folds: squash vertically, wrinkle with sine bands.
    let x = Math.sin(phi) * Math.cos(theta) * r;
    let y = Math.cos(phi) * r * 0.82;
    let z = Math.sin(phi) * Math.sin(theta) * r;
    const folds = Math.sin(theta * 5 + phi * 4) * 0.055
      + Math.sin(phi * 7 - theta * 2) * 0.04;
    const len = Math.sqrt(x * x + y * y + z * z) || 1;
    x += (x / len) * folds;
    y += (y / len) * folds;
    z += (z / len) * folds;
    x = left * Math.max(Math.abs(x), GAP) ;   // split into hemispheres
    N.nodes.push({
      x, y, z,
      hemi: left,
      isCore: (Math.sqrt(x * x + y * y + z * z) < 0.62),
      size: 0.7 + Math.random() * 1.9,
      energy: Math.random() * 0.3,
      phase: Math.random() * Math.PI * 2,
    });
  }
  // Synapse edges: mostly within a hemisphere, a few bridging the fissure.
  N.edges = [];
  for (let i = 0; i < count; i += 1) {
    const a = N.nodes[i];
    let best = -1, bestD = 0.028;
    for (let j = i + 1; j < count; j += 1) {
      const b = N.nodes[j];
      if (a.hemi !== b.hemi && Math.random() > 0.06) continue;
      const dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
      const d = dx * dx + dy * dy + dz * dz;
      if (d < bestD) { bestD = d; best = j; }
    }
    if (best !== -1) N.edges.push([i, best]);
  }
  N.signals = Array.from({ length: 150 }, () => ({
    from: Math.floor(Math.random() * count),
    to: Math.floor(Math.random() * count),
    p: Math.random(), speed: 0.4 + Math.random() * 1.2, life: 0,
  }));
  N.projected = N.nodes.map(() => ({ x: 0, y: 0, d: 1 }));
}
function coreFrame(time) {
  if (!animating) return;
  const delta = Math.min((time - N.last) / 1000 || 0.016, 0.05);
  N.last = time;
  N.frames += 1;
  N.frameTime = N.frameTime * 0.94 + delta * 1000 * 0.06;
  if (N.frames % 90 === 0) {
    if (N.frameTime > 30) N.quality = 'low';
    else if (N.frameTime > 24) N.quality = 'medium';
    else if (N.frameTime < 17) N.quality = 'high';
  }
  const profile = RUN_PROFILE[app.state] || RUN_PROFILE.idle;
  N.target = (profile.activity / 100) || 0.05;
  N.activity += (N.target - N.activity) * delta * 2.2;
  /* Speech envelope: while voice output is playing, drive a syllable-like
     rhythm (fast layered sines + wander) so the brain visibly "talks". */
  if (app.ttsActive) {
    const t = time / 1000;
    const syllable = Math.abs(Math.sin(t * 9.5) * Math.sin(t * 3.7 + Math.sin(t * 1.3) * 1.4));
    const wobble = 0.55 + 0.45 * Math.sin(t * 23 + Math.sin(t * 6.1) * 2.0);
    const level = Math.min(1, syllable * wobble * 1.5);
    app.talk += (level - app.talk) * Math.min(1, delta * 14);
  } else {
    app.talk += (0 - app.talk) * Math.min(1, delta * 6);
  }
  N.talk = app.talk;
  N.breath += delta * (0.6 + profile.speed + app.talk * 1.2);
  N.phase += delta * (0.4 + profile.speed + app.talk * 0.8);
  N.rotY += delta * 0.2 * (1 + N.activity + app.talk * 0.7);
  N.corePulse += delta * (1.1 + N.activity * 2 + app.talk * 5);

  const w = N.width, h = N.height, cx = w / 2, cy = h / 2;
  const q = QUALITY[N.quality];
  const scale = Math.min(w, h) * 0.5;
  ctx.clearRect(0, 0, w, h);

  const glow = ctx.createRadialGradient(cx, cy, 10, cx, cy, Math.min(w, h) * 0.55);
  glow.addColorStop(0, `rgba(96, 130, 255, ${0.10 + N.activity * 0.10})`);
  glow.addColorStop(0.5, 'rgba(40, 66, 150, 0.05)');
  glow.addColorStop(1, 'rgba(4, 7, 15, 0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  const proj = N.projected;
  const cosY = Math.cos(N.rotY), sinY = Math.sin(N.rotY);
  const tilt = 0.3 + Math.sin(N.phase * 0.5) * 0.08;
  const cosT = Math.cos(tilt), sinT = Math.sin(tilt);
  for (let i = 0; i < N.nodes.length; i += 1) {
    const n = N.nodes[i];
    const dx = n.x + Math.sin(N.breath + n.phase) * 0.04;
    const dy = n.y + Math.cos(N.phase * 1.4 + n.phase) * 0.04;
    const dz = n.z + Math.sin(N.phase + n.phase) * 0.04;
    const rx = dx * cosY - dz * sinY;
    const rz = dx * sinY + dz * cosY;
    const rz2 = rz * cosT + dy * sinT;
    const ry = dy * cosT - rz * sinT;
    const persp = 2.6 / (rz2 + 3.0);
    proj[i].x = rx * persp;
    proj[i].y = ry * persp;
    proj[i].d = persp;
  }

  ctx.lineWidth = 0.9;
  ctx.strokeStyle = `rgba(160, 150, 255, ${0.09 + N.activity * 0.13 + app.talk * 0.1})`;
  ctx.beginPath();
  for (let i = 0; i < N.edges.length; i += q.edgeStride) {
    const e = N.edges[i];
    const a = proj[e[0]], b = proj[e[1]];
    ctx.moveTo(cx + a.x * scale, cy + a.y * scale);
    ctx.lineTo(cx + b.x * scale, cy + b.y * scale);
  }
  ctx.stroke();

  for (let i = 0; i < N.signals.length; i += 1) {
    const s = N.signals[i];
    s.p += delta * s.speed * (1 + N.activity * 1.4);
    if (s.p >= 1) {
      s.p = 0;
      s.from = Math.floor(Math.random() * N.nodes.length);
      s.to = Math.floor(Math.random() * N.nodes.length);
    }
    const a = proj[s.from], b = proj[s.to];
    if (!a || !b) continue;
    const px = a.x + (b.x - a.x) * s.p;
    const py = a.y + (b.y - a.y) * s.p;
    ctx.beginPath();
    ctx.fillStyle = `rgba(190, 165, 255, ${0.2 + N.activity * 0.35})`;
    ctx.arc(cx + px * scale, cy + py * scale, 1.3, 0, Math.PI * 2);
    ctx.fill();
  }

  for (let i = 0; i < N.nodes.length; i += q.nodeStride) {
    const p = proj[i];
    const n = N.nodes[i];
    const flicker = Math.max(0, Math.sin(N.corePulse * 1.7 + n.phase));
    const alpha = Math.min(0.92, 0.18 + (N.activity + flicker * 0.25 + app.talk * 0.4) * 0.6);
    ctx.beginPath();
    if (n.isCore) {
      // Golden-amber neural brain core
      ctx.fillStyle = `rgba(255, ${Math.round(180 + flicker * 40)}, 30, ${alpha * 1.25})`;
      if (q.shadowBlur > 0) {
        ctx.shadowBlur = q.shadowBlur * 1.5;
        ctx.shadowColor = '#ffaa00';
      }
    } else {
      // Electric cyan profile silhouette & contour
      ctx.fillStyle = `rgba(0, 235, 255, ${alpha * 1.1})`;
      if (q.shadowBlur > 0) {
        ctx.shadowBlur = q.shadowBlur;
        ctx.shadowColor = '#00f0ff';
      }
    }
    ctx.arc(cx + p.x * scale, cy + p.y * scale, n.size * p.d * (0.7 + N.activity * 0.6 + app.talk * 0.5), 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  // Voice ring: an equalizer-style ring that dances while JARVIS speaks.
  if (app.talk > 0.02) {
    const bars = 48;
    const baseR = Math.min(w, h) * 0.42;
    for (let i = 0; i < bars; i += 1) {
      const ang = (i / bars) * Math.PI * 2 + N.rotY * 0.5;
      const wobble = Math.abs(Math.sin(i * 1.7 + N.corePulse * 2.1) * Math.cos(i * 0.9 - N.corePulse * 1.3));
      const len = 4 + app.talk * wobble * 26;
      const r1 = baseR, r2 = baseR + len;
      const mix = i / bars;
      ctx.beginPath();
      ctx.strokeStyle = `rgba(${Math.round(255 - mix * 200)}, ${Math.round(180 + mix * 50)}, 255, ${0.2 + app.talk * wobble * 0.65})`;
      ctx.lineWidth = 2;
      ctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
      ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
      ctx.stroke();
    }
  }

  const coreRadius = 28 + Math.sin(N.corePulse) * 5 + N.activity * 8 + app.talk * 14;
  const core = ctx.createRadialGradient(cx, cy, 2, cx, cy, coreRadius * 2.6);
  core.addColorStop(0, `rgba(255, 200, 35, ${0.28 + N.activity * 0.18})`);
  core.addColorStop(0.35, `rgba(255, 120, 10, ${0.12 + N.activity * 0.09})`);
  core.addColorStop(1, 'rgba(0, 210, 255, 0)');
  ctx.beginPath();
  ctx.fillStyle = core;
  ctx.arc(cx, cy, coreRadius * 2.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.strokeStyle = `rgba(0, 230, 255, ${0.25 + N.activity * 0.3})`;
  ctx.lineWidth = 1.4;
  ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2);
  ctx.stroke();

  requestAnimationFrame(coreFrame);
}
/* ------------------------------------------------------------------ */
/* Conversation rendering                                              */
/* ------------------------------------------------------------------ */
function addMessage(role, text, options) {
  const opts = options || {};
  const article = document.createElement('article');
  article.className = 'message ' + (role === 'user' ? 'user' : 'jarvis');
  article.dataset.role = role === 'user' ? 'user' : 'assistant';
  const meta = document.createElement('div');
  meta.className = 'message-meta';
  const label = document.createElement('span');
  label.textContent = role === 'user' ? 'YOU' : 'JARVIS';
  const time = document.createElement('time');
  time.textContent = timestamp();
  meta.append(label, time);
  const body = document.createElement('p');
  body.textContent = text;
  article.append(meta, body);
  if (opts.streaming) article.classList.add('streaming');
  messagesEl.appendChild(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  if (!opts.local) historyMessages.appendChild(article.cloneNode(true));
  return article;
}

function notice(text) {
  const article = document.createElement('article');
  article.className = 'message meta';
  article.textContent = text;
  messagesEl.appendChild(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  historyMessages.appendChild(article.cloneNode(true));
}

let toastTimer = null;
function toast(text, isError) {
  toastEl.textContent = text;
  toastEl.classList.toggle('error', Boolean(isError));
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3200);
}

/** Handle a message event coming from the backend. */
function handleBackendMessage(event) {
  const role = event.role === 'user' ? 'user' : 'assistant';
  const text = (event.text || '').trim();
  if (event.stream && event.status === 'streaming') {
    // Create or update the live assistant bubble.
    if (!app.activeMsgId || !app.activeMsgId.isConnected) {
      app.activeMsgId = addMessage('assistant', text, { streaming: true });
    } else {
      app.activeMsgId.querySelector('p').textContent = text;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
    return;
  }
  if (app.activeMsgId && app.activeMsgId.isConnected && role === 'assistant') {
    app.activeMsgId.classList.remove('streaming');
    app.activeMsgId.querySelector('p').textContent = text || app.activeMsgId.querySelector('p').textContent;
    app.activeMsgId = null;
    historyMessages.appendChild(
      Array.from(messagesEl.children).slice(-1)[0].cloneNode(true));
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return;
  }
  addMessage(role, text);
}

/* ------------------------------------------------------------------ */
/* Backend transport (SSE with automatic reconnect)                    */
/* ------------------------------------------------------------------ */
let eventSource = null;
let reconnectDelay = 1000;

function connectEvents() {
  setBodyState(app.connected ? app.state : 'offline');
  if (eventSource) { eventSource.close(); eventSource = null; }
  eventSource = new EventSource('/events');

  eventSource.onopen = () => {
    app.connected = true;
    reconnectDelay = 1000;
    body.dataset.sse = 'online';
    backendLabel.textContent = 'Online';
    backendChip.dataset.state = 'online';
  };

  eventSource.onerror = () => {
    app.connected = false;
    body.dataset.sse = 'offline';
    backendLabel.textContent = 'Reconnecting…';
    backendChip.dataset.state = 'offline';
    setBodyState('offline');
    eventSource.close();
    eventSource = null;
    // Probe the health endpoint aggressively: if the backend is already up
    // again we reconnect immediately instead of waiting out the backoff.
    const probe = async () => {
      try {
        const data = await getJSON('/api/health');
        if (data && data.ok) { reconnectDelay = 1000; connectEvents(); return; }
      } catch (error) { /* still down */ }
      setTimeout(connectEvents, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    };
    setTimeout(probe, 700);
  };

  eventSource.onmessage = (evt) => {
    let payload;
    try { payload = JSON.parse(evt.data); } catch (error) { return; }
    if (payload.type === 'hello') {
      setBodyState(payload.state || 'idle');
      return;
    }
    if (payload.type === 'state') {
      setBodyState(payload.state);
      return;
    }
    if (payload.type === 'message') {
      handleBackendMessage(payload);
      return;
    }
    
    if (payload.type === 'confirmation_request') {
      confirmDesc.textContent = payload.description || JARVIS wants to execute .;
      confirmModal.hidden = false;
      confirmModal.setAttribute('aria-hidden', 'false');
      return;
    }
    if (payload.type === 'speech') {
      app.ttsActive = Boolean(payload.active);
      if (!app.ttsActive) app.talk = 0;
      return;
    }
    if (payload.type === 'notice') {
      const text = payload.text || '';
      notice(text);
      if (payload.state === 'error' || /unavailable|went wrong|Microphone/i.test(text)) {
        toast(text, true);
        setBodyState('error');
        setTimeout(() => { if (app.state === 'error') setBodyState('idle'); }, 2600);
      } else {
        toast(text, false);
      }
    }
  };
}

/* ------------------------------------------------------------------ */
/* REST helpers                                                        */
/* ------------------------------------------------------------------ */
async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function getJSON(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
/* ------------------------------------------------------------------ */
/* Controls                                                            */
/* ------------------------------------------------------------------ */
let listenToggling = false;
async function toggleListen() {
  if (listenToggling) return;
  listenToggling = true;
  try {
    const next = !app.autoListen;
    await postJSON('/api/listen', { enable: next });
    app.autoListen = next;
    body.dataset.autolisten = next ? 'on' : 'off';
    micLabel.textContent = next ? 'Mic on' : 'Mic paused';
    toast(next ? 'Microphone capture enabled.' : 'Microphone capture paused.');
    if (next && app.state === 'idle') setBodyState('listening');
    if (!next && app.state === 'listening') setBodyState('idle');
  } catch (error) {
    toast('Could not change microphone state.', true);
  } finally {
    listenToggling = false;
  }
}

async function interrupt() {
  try {
    await postJSON('/api/stop');
    setBodyState('interrupted');
    setTimeout(() => { if (app.state === 'interrupted') setBodyState('idle'); }, 900);
  } catch (error) {
    toast('Interrupt failed — backend unreachable.', true);
  }
}

async function sendCommand(text) {
  const clean = (text || '').trim();
  if (!clean) return;
  commandInput.value = '';
  try {
    await postJSON('/api/command', { text: clean });
    if (app.state === 'idle') setBodyState('processing');
  } catch (error) {
    toast('JARVIS is not responding. Check the backend.', true);
    setBodyState('offline');
  }
}

micButton.addEventListener('click', () => {
  if (app.state === 'speaking' || app.state === 'processing') { interrupt(); return; }
  toggleListen();
});
$('#inputMicButton').addEventListener('click', toggleListen);
stopButton.addEventListener('click', interrupt);

commandForm.addEventListener('submit', (event) => {
  event.preventDefault();
  sendCommand(commandInput.value);
});

document.addEventListener('keydown', (event) => {
  if (event.code === 'Space' && document.activeElement.tagName !== 'INPUT'
      && document.activeElement.tagName !== 'TEXTAREA' && !document.activeElement.isContentEditable) {
    event.preventDefault();
    if (app.state === 'speaking' || app.state === 'processing') interrupt(); else toggleListen();
  }
  if (event.key === 'Escape') {
    historyDrawer.classList.remove('open');
    settingsDrawer.classList.remove('open');
  }
});

/* Drawers */
$('#historyButton').addEventListener('click', () => {
  historyDrawer.classList.add('open');
  historyDrawer.setAttribute('aria-hidden', 'false');
  historyMessages.scrollTop = historyMessages.scrollHeight;
});
$('#closeHistory').addEventListener('click', () => {
  historyDrawer.classList.remove('open');
  historyDrawer.setAttribute('aria-hidden', 'true');
});
$('#settingsButton').addEventListener('click', () => {
  settingsDrawer.classList.add('open');
  settingsDrawer.setAttribute('aria-hidden', 'false');
});
$('#closeSettings').addEventListener('click', () => {
  settingsDrawer.classList.remove('open');
  settingsDrawer.setAttribute('aria-hidden', 'true');
});
/* ------------------------------------------------------------------ */
/* Settings wiring (real backend settings)                             */
/* ------------------------------------------------------------------ */
function applySettings(settings) {
  app.autoListen = Boolean(settings.auto_listen);
  $('#setAutoListen').checked = app.autoListen;
  $('#setSensitivity').value = settings.mic_sensitivity;
  $('#setVerbosity').value = settings.response_verbosity;
  $('#setIntensity').value = settings.visual_intensity;
  $('#setBargeIn').checked = Boolean(settings.barge_in);
  body.dataset.autolisten = app.autoListen ? 'on' : 'off';
  micLabel.textContent = app.autoListen ? 'Mic on' : 'Mic paused';
}

async function loadSettings() {
  try {
    const data = await getJSON('/api/settings');
    applySettings(data.settings || {});
  } catch (error) {
    backendLabel.textContent = 'Reconnecting…';
  }
}

function debounce(fn, wait) {
  let timer = null;
  return function debounced(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}

const pushSetting = debounce(async (key, value) => {
  try {
    await postJSON('/api/settings', { key, value });
  } catch (error) {
    toast('Setting could not be saved.', true);
  }
}, 350);

$('#setAutoListen').addEventListener('change', (event) => {
  app.autoListen = event.target.checked;
  body.dataset.autolisten = app.autoListen ? 'on' : 'off';
  micLabel.textContent = app.autoListen ? 'Mic on' : 'Mic paused';
  postJSON('/api/settings', { key: 'auto_listen', value: app.autoListen }).catch(() => {});
});
$('#setSensitivity').addEventListener('input', (event) => {
  pushSetting('mic_sensitivity', Number(event.target.value));
});
$('#setVerbosity').addEventListener('change', (event) => {
  pushSetting('response_verbosity', event.target.value);
});
$('#setIntensity').addEventListener('input', (event) => {
  N.activity = Number(event.target.value);
  pushSetting('visual_intensity', Number(event.target.value));
});
$('#setBargeIn').addEventListener('change', (event) => {
  pushSetting('barge_in', Boolean(event.target.checked));
  toast(event.target.checked
    ? 'Barge-in enabled — speak to interrupt JARVIS.'
    : 'Barge-in disabled — use the Stop button to interrupt.');
});

/* ------------------------------------------------------------------ */
/* History                                                             */
/* ------------------------------------------------------------------ */
async function loadHistory() {
  try {
    const data = await getJSON('/api/history');
    const items = data.history || [];
    if (!items.length) return;
    // Avoid duplicating turns that are already rendered live.
    const existing = new Set(
      Array.from(historyMessages.children).map((node) =>
        (node.dataset.role || '') + '|' + (node.querySelector('p') ? node.querySelector('p').textContent : '')));
    const fresh = items.filter((entry) => !existing.has((entry.role === 'user' ? 'user' : 'assistant') + '|' + (entry.text || '')));
    if (!fresh.length) return;
    historyMessages.textContent = '';
    items.forEach((entry) => {
      const article = document.createElement('article');
      article.className = 'message ' + (entry.role === 'user' ? 'user' : 'jarvis');
      const meta = document.createElement('div');
      meta.className = 'message-meta';
      const label = document.createElement('span');
      label.textContent = entry.role === 'user' ? 'YOU' : 'JARVIS';
      const time = document.createElement('time');
      time.textContent = entry.ts ? String(entry.ts).slice(-8) : '';
      meta.append(label, time);
      const body = document.createElement('p');
      body.textContent = entry.text;
      article.append(meta, body);
      historyMessages.appendChild(article);
    });
  } catch (error) { /* backend not ready; SSE still streams live turns */ }
}

/* ------------------------------------------------------------------ */
/* Waveform bars + init                                                */
/* ------------------------------------------------------------------ */
for (let i = 0; i < 28; i += 1) {
  const bar = document.createElement('i');
  bar.style.setProperty('--i', String(i));
  waveform.appendChild(bar);
}

window.addEventListener('resize', resizeCore);
window.addEventListener('online', () => { app.online = true; connectEvents(); });
window.addEventListener('offline', () => { app.online = false; setBodyState('offline'); });

resizeCore();
seedCore();
requestAnimationFrame(coreFrame);
setBodyState('offline');
micLabel.textContent = 'Mic idle';
connectEvents();
loadSettings();
loadHistory();
setTimeout(loadHistory, 1500);  /* pick up messages streamed during boot */\n
confirmYes.addEventListener('click', async () => {
  confirmModal.hidden = true;
  confirmModal.setAttribute('aria-hidden', 'true');
  setBodyState('processing');
  try {
    await postJSON('/api/confirm', { action: 'confirm' });
  } catch (error) {
    toast('Confirmation failed — backend unreachable.', true);
  }
});
confirmNo.addEventListener('click', async () => {
  confirmModal.hidden = true;
  confirmModal.setAttribute('aria-hidden', 'true');
  try {
    await postJSON('/api/confirm', { action: 'decline' });
  } catch (error) {
    toast('Cancellation failed — backend unreachable.', true);
  }
});
