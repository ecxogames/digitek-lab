/* ───────────────────────── Bridge ───────────────────────── */
  function bridge(payload) {
    if (!window.invokeBridge) return Promise.reject(new Error('Backend bridge not available.'));
    return window.invokeBridge(payload).then(r => {
      if (!r || r.status !== 'ok') throw new Error((r && r.reason) || 'Backend error');
      return r.result;
    });
  }

  /* ───────────────────────── State ───────────────────────── */
  const DEFAULT_MOTION_KEY_MAP = {
    w: { mode:'opposite', target:'s' },
    s: { mode:'opposite', target:'w' },
    a: { mode:'opposite', target:'d' },
    d: { mode:'opposite', target:'a' },
    shift: { mode:'same', target:'' },
    shift_l: { mode:'same', target:'' },
    shift_r: { mode:'same', target:'' },
    ctrl: { mode:'same', target:'' },
    ctrl_l: { mode:'same', target:'' },
    ctrl_r: { mode:'same', target:'' },
    alt: { mode:'same', target:'' },
    alt_l: { mode:'same', target:'' },
    alt_gr: { mode:'same', target:'' },
  };
  function defaultMotionKeyMap() { return JSON.parse(JSON.stringify(DEFAULT_MOTION_KEY_MAP)); }

  const state = {
    execution: { format: 'dgtexec', schema: 1, name: 'Untitled Execution', motionControlled: false, motionKeyMap: defaultMotionKeyMap(), timeline: [] },
    macros: { user: [], core: [] },
    pinnedPluginIds: [],
    appInfo: null,
    playing: false,
    paused: false,
    recording: false,
    recordMotion: false,
    pollTimer: null,
    recTimer: null,
    modalCtx: null,
    dragData: null,
    continuous: false,
    stopRequested: false,
  };

  let uid = 1;
  const newId = () => 'i' + (uid++);
  const PINNED_PLUGINS_KEY = 'dgt_pinned_plugins';

  /* ───────────────────────── Action palette ───────────────────────── */
  // Source of truth is server/core/actions/*.dgtact, loaded at boot via loadActions().
  // The literal below is a fallback used only if the backend is unavailable (e.g. opened
  // in a plain browser). Edit the .dgtact files to change actions, not this object.
  let ACTIONS = {
    keypress:  { icon:'keyboard', label:'Key Press', desc:'Tap a single key',
      def:{ key:'w', holdMs:100 },
      fields:[ {k:'key',label:'Key',type:'text',widget:'key',hint:'Click “Record” then press one key'},
               {k:'holdMs',label:'Hold (ms)',type:'number',hint:'How long the key stays down'} ] },
    keycombo:  { icon:'keyboard_command_key', label:'Key Combo', desc:'Press several keys together',
      def:{ keys:'ctrl_l,c', holdMs:80 },
      fields:[ {k:'keys',label:'Keys',type:'text',widget:'keys',hint:'Click “Record” then press the combo (e.g. Ctrl+C)'},
               {k:'holdMs',label:'Hold (ms)',type:'number'} ] },
    mousemove: { icon:'open_with', label:'Move Cursor', desc:'Jump cursor to a point',
      def:{ x:0.5, y:0.5 }, pick:{ mode:'point' },
      fields:[ {k:'x',label:'X',type:'number',step:'0.01',widget:'coord'}, {k:'y',label:'Y',type:'number',step:'0.01',widget:'coord'} ] },
    mousedrag: { icon:'drag_pan', label:'Mouse Drag', desc:'Smooth drag (camera pan)',
      def:{ fromX:0.4, fromY:0.5, toX:0.6, toY:0.5, durationMs:800, button:'right' }, pick:{ mode:'line' },
      fields:[ {k:'fromX',label:'From X',type:'number',step:'0.01',widget:'coord'}, {k:'fromY',label:'From Y',type:'number',step:'0.01',widget:'coord'},
               {k:'toX',label:'To X',type:'number',step:'0.01',widget:'coord'}, {k:'toY',label:'To Y',type:'number',step:'0.01',widget:'coord'},
               {k:'durationMs',label:'Duration (ms)',type:'number',hint:'Higher = slower, smoother pan'},
               {k:'button',label:'Button',type:'select',widget:'segment',options:['left','right','middle']} ] },
    mouseclick:{ icon:'ads_click', label:'Mouse Click', desc:'Click at a point',
      def:{ x:0.5, y:0.5, button:'left', count:1 }, pick:{ mode:'point' },
      fields:[ {k:'x',label:'X',type:'number',step:'0.01',widget:'coord'}, {k:'y',label:'Y',type:'number',step:'0.01',widget:'coord'},
               {k:'button',label:'Button',type:'select',widget:'segment',options:['left','right','middle']},
               {k:'count',label:'Clicks',type:'number'} ] },
    scroll:    { icon:'mouse', label:'Scroll', desc:'Zoom in/out by notches',
      def:{ amount:-3 },
      fields:[ {k:'amount',label:'Amount (− out / + in)',type:'number',hint:'Negative zooms out, positive zooms in'} ] },
    fov:       { icon:'zoom_in', label:'FOV Preset', desc:'Zoom out to max, then in to a point',
      def:{ targetNotches:6 },
      fields:[ {k:'targetNotches',label:'Zoom-in notches',type:'number',hint:'Scroll-in steps after zooming fully out'} ] },
    controlleraxis: { icon:'sports_esports', label:'Controller Axis', desc:'Hold an Xbox stick or trigger',
      def:{ part:'left_stick', fromX:0, fromY:0, toX:0, toY:0.35, fromValue:0, toValue:0.5 }, editor:'controllerAxis',
      fields:[ {k:'part',label:'Axis',type:'text'}, {k:'fromX',label:'Initial X',type:'number'}, {k:'fromY',label:'Initial Y',type:'number'},
               {k:'toX',label:'Target X',type:'number'}, {k:'toY',label:'Target Y',type:'number'},
               {k:'fromValue',label:'Initial Pull',type:'number'}, {k:'toValue',label:'Target Pull',type:'number'} ] },
    wait:      { icon:'hourglass_empty', label:'Wait', desc:'Pause for a duration',
      def:{ ms:500 },
      fields:[ {k:'ms',label:'Duration (ms)',type:'number'} ] },
  };

  // Load action templates from server/core/actions/*.dgtact and build the ACTIONS map.
  // Each template: { actionType, name, icon, description, order, defaults, fields, pick? }.
  async function loadActions() {
    let list;
    try { list = await bridge({ action:'dgt_list_actions' }); }
    catch (e) { return; }                       // keep the literal fallback
    if (!Array.isArray(list) || !list.length) return;
    const built = {};
    list.forEach(t => {
      built[t.actionType] = {
        icon: t.icon || 'bolt',
        label: t.name || t.actionType,
        desc: t.description || '',
        def: Object.assign({}, t.defaults || {}),
        fields: t.fields || [],
        pick: t.pick || null,
        editor: t.editor || null,
        order: t.order ?? 999,
      };
    });
    ACTIONS = built;                            // backend order is already sorted
  }

  // Rough duration estimate (seconds) for timeline display.
  function estimateActionDuration(type, p) {
    p = p || {};
    switch (type) {
      case 'wait': return (+p.ms || 0) / 1000;
      case 'keypress': return (+p.holdMs || 0) / 1000 + 0.05;
      case 'keycombo': return (+p.holdMs || 0) / 1000 + 0.05;
      case 'mousedrag': return (+p.durationMs || 0) / 1000;
      case 'controlleraxis': return 1.0;
      case 'mouseclick': return 0.06 * (+p.count || 1);
      case 'scroll': return Math.abs(+p.amount || 0) * 0.012;
      case 'fov': return (18 + (+p.targetNotches || 0)) * 0.012 + 0.05;
      default: return 0.1;
    }
  }

  // Multi-track timeline config + selection.
  const TL = { pxPerSec: 90, laneH: 48, clipH: 40, minLen: 0.1, minView: 6, layers: 1, defaultDur: 1.0, snap: true, dragGhost: null, draggingId: null };
  // Actions whose playback length is the clip length (no in-modal hold/duration).
  const HELD_ACTIONS = ['keypress', 'keycombo', 'mousedrag', 'controlleraxis', 'wait'];
  const isHeldItem = (it) => it.kind === 'action' && HELD_ACTIONS.includes(it.actionType);
  let selectedClipId = null;

  // Natural (content) length of an item in seconds.
  function intrinsicDuration(item) {
    if (item.kind === 'action') return estimateActionDuration(item.actionType, item.params);
    return +item.intrinsic || +item.duration || 0.5;
  }
  // Clip length (how long it occupies the timeline).
  function clipDuration(item) {
    const d = +item.duration;
    return Math.max(TL.minLen, d > 0 ? d : intrinsicDuration(item));
  }
  // Snap a time (s) to a light grid for tidy editing (no-op when snapping is off).
  function snap(t) { return TL.snap ? Math.round(t / 0.05) * 0.05 : t; }

  // Snap-to-other-clips: returns the nearest start/end edge of any other clip (or 0)
  // within a small pixel threshold, else the original value.
  const SNAP_PX = 7;
  function snapToClips(value, excludeId) {
    if (!TL.snap) return { t: value, snapped: false, raw: value };
    const thr = SNAP_PX / TL.pxPerSec;
    let best = value, bestD = thr, snapped = false;
    const consider = (t) => { const d = Math.abs(value - t); if (d <= bestD) { bestD = d; best = t; snapped = true; } };
    consider(0);
    state.execution.timeline.forEach(it => {
      if (it.id === excludeId) return;
      const s = it.start || 0;
      consider(s);
      consider(s + clipDuration(it));
    });
    return { t: snapped ? best : snap(value), snapped, raw: best };
  }

  // A dashed guide line at a snapped time (or hidden when time is null). Re-added each
  // frame because renderTimeline() rebuilds the lanes.
  function showSnapGuide(time) {
    const lanes = document.getElementById('tlxLanes');
    const existing = document.getElementById('tlxSnap');
    if (existing) existing.remove();
    if (time == null || !lanes) return;
    const g = document.createElement('div');
    g.id = 'tlxSnap';
    g.className = 'tlx-snapline';
    g.style.left = (time * TL.pxPerSec) + 'px';
    lanes.appendChild(g);
  }
  // End time of the last clip on a layer (for append-on-click).
  function layerEnd(L) {
    let end = 0;
    state.execution.timeline.forEach(it => { if ((it.layer || 0) === L) end = Math.max(end, (it.start || 0) + clipDuration(it)); });
    return end;
  }
  // Give legacy / freshly-loaded executions clip fields (layer/start/duration/trimStart).
  function migrateTimeline() {
    const tl = state.execution.timeline || [];
    let acc = 0, maxLayer = 0;
    tl.forEach(it => {
      if (it.id === undefined) it.id = newId();
      if (it.intrinsic === undefined) it.intrinsic = intrinsicDuration(it);
      if (!(+it.duration > 0)) it.duration = it.intrinsic;
      if (it.trimStart === undefined) it.trimStart = 0;
      if (it.start === undefined) { it.start = acc; acc += clipDuration(it); }
      if (it.layer === undefined) it.layer = 0;
      maxLayer = Math.max(maxLayer, it.layer || 0);
    });
    TL.layers = Math.max(TL.layers, maxLayer + 1);
  }

  /* ───────────────────────── Rendering ───────────────────────── */
  function render() {
    renderTimeline();
    renderActionList();
  }

  // Format seconds for the ruler / cards (e.g. "2.4s" or "1:05.0").
  function fmtTime(s) {
    s = Math.max(0, s);
    if (s >= 60) { const m = Math.floor(s / 60); return m + ':' + (s % 60).toFixed(1).padStart(4, '0'); }
    return s.toFixed(1) + 's';
  }
  // Seconds between ruler ticks so they land roughly every ~64px at the current zoom.
  function niceStep(px) {
    const cands = [0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60];
    for (const s of cands) if (s * px >= 64) return s;
    return 120;
  }
  function zoomTimeline(dir) {
    TL.pxPerSec = Math.max(20, Math.min(400, Math.round(TL.pxPerSec * (dir > 0 ? 1.25 : 0.8))));
    renderTimeline();
  }
  function addLayer() { TL.layers++; renderTimeline(); }

  // Snapping on/off toggle (timeline header button).
  function toggleSnap() {
    TL.snap = !TL.snap;
    const b = document.getElementById('snapBtn');
    if (b) {
      b.classList.toggle('active', TL.snap);
      b.title = TL.snap ? 'Snapping on — click to disable' : 'Snapping off — click to enable';
    }
    toast('info', TL.snap ? 'Snapping enabled.' : 'Snapping disabled.');
  }

  function renderTimeline() {
    migrateTimeline();
    const lanes = document.getElementById('tlxLanes');
    const ruler = document.getElementById('tlxRuler');
    const heads = document.getElementById('tlxHeadsInner');
    if (!lanes || !ruler) return;
    const tl = state.execution.timeline;
    const px = TL.pxPerSec;

    // Layer count: items' max layer + a spare empty lane to drop into.
    let maxLayer = 0;
    tl.forEach(it => { maxLayer = Math.max(maxLayer, it.layer || 0); });
    const laneCount = Math.max(TL.layers, maxLayer + 1, 1) + (tl.length ? 1 : 1);

    // Total time + content width. The timeline always fills the full panel width;
    // when content is longer than the view it grows past it and scrolls.
    let total = 0;
    tl.forEach(it => { total = Math.max(total, (it.start || 0) + clipDuration(it)); });
    const scroll = document.getElementById('tlxScroll');
    const minW = scroll ? scroll.clientWidth : 0;
    const viewSec = Math.max(total + 1.5, TL.minView);
    const width = Math.max(minW, Math.round(viewSec * px) + 20);

    // Ruler.
    ruler.style.width = width + 'px';
    ruler.innerHTML = '';
    const step = niceStep(px);
    for (let s = 0; s <= viewSec + 1e-6; s += step) {
      const tick = document.createElement('div');
      tick.className = 'tlx-tick';
      tick.style.left = (s * px) + 'px';
      tick.textContent = fmtTime(s);
      ruler.appendChild(tick);
    }

    // Track-head column (one "Layer" row + circle toggle per lane).
    if (heads) {
      heads.innerHTML = '';
      for (let L = 0; L < laneCount; L++) {
        const h = document.createElement('div');
        h.className = 'tlx-head';
        h.style.height = TL.laneH + 'px';
        h.innerHTML = `<span class="tlx-head-label">Layer</span>
          <button class="tlx-head-toggle" title="Enable / mute layer"
            onclick="this.classList.toggle('on');this.querySelector('.material-symbols-outlined').textContent=this.classList.contains('on')?'radio_button_unchecked':'radio_button_checked'">
            <span class="material-symbols-outlined">radio_button_unchecked</span></button>`;
        heads.appendChild(h);
      }
    }

    // Lanes container — keep the playhead element, rebuild everything else.
    const playhead = document.getElementById('tlxPlayhead');
    lanes.style.width = width + 'px';
    lanes.style.height = (laneCount * TL.laneH) + 'px';
    lanes.innerHTML = '';
    lanes.appendChild(playhead);

    for (let L = 0; L < laneCount; L++) {
      const lane = document.createElement('div');
      lane.className = 'tlx-lane';
      lane.style.top = (L * TL.laneH) + 'px';
      lane.style.height = TL.laneH + 'px';
      lanes.appendChild(lane);
    }

    // Clips.
    tl.forEach(item => {
      const dur = clipDuration(item);
      const left = (item.start || 0) * px;
      const w = Math.max(20, dur * px);
      const top = (item.layer || 0) * TL.laneH + (TL.laneH - TL.clipH) / 2;
      const el = document.createElement('div');
      el.className = 'tlx-clip kind-' + item.kind + (item.id === selectedClipId ? ' selected' : '') + (item.id === TL.draggingId ? ' dragging' : '');
      el.style.left = left + 'px';
      el.style.top = top + 'px';
      el.style.width = w + 'px';
      el.dataset.id = item.id;

      const info = ACTIONS[item.actionType];
      const icon = item.kind === 'action' ? (info ? info.icon : 'bolt')
                 : item.kind === 'core' ? 'bolt' : 'movie';
      const contentSec = isHeldItem(item) ? dur : Math.max(0, Math.min(dur, intrinsicDuration(item) - (item.trimStart || 0)));
      el.innerHTML = `
        <div class="tlx-handle l"></div><div class="tlx-handle r"></div>
        <button class="tlx-clip-x" title="Remove"><span class="material-symbols-outlined">close</span></button>
        <button class="tlx-clip-rename" title="Rename"><span class="material-symbols-outlined">edit</span></button>
        <div class="tlx-clip-name"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">${icon}</span> ${escapeHtml(item.name)}</div>
        <div class="tlx-clip-sub">${fmtTime(item.start || 0)} · ${dur.toFixed(2)}s${(item.trimStart || 0) > 0 ? ' ✂' : ''}</div>
        <div class="tlx-clip-content" style="width:${Math.round(contentSec * px)}px;"></div>`;
      attachClipHandlers(el, item);
      lanes.appendChild(el);
    });
    renderTimelineGhost(lanes);

    document.getElementById('timelineMeta').textContent =
      `${tl.length} clip${tl.length === 1 ? '' : 's'}`;
    document.getElementById('tlxZoomLabel').textContent = Math.round(px / 90 * 100) + '%';
    if (!state.playing) updateTimecode(selectedClipId ? (tl.find(c => c.id === selectedClipId)?.start || 0) : 0);
    if (state.playing) positionPlayhead(state._elapsed || 0);
    syncTimelineScroll();
  }

  // ── Timecode display (MM:SS:CS) ──
  function updateTimecode(sec) {
    const el = document.getElementById('timecode');
    if (!el) return;
    sec = Math.max(0, sec || 0);
    const m = Math.floor(sec / 60), s = Math.floor(sec % 60), cs = Math.floor((sec * 100) % 100);
    const p = (n) => String(n).padStart(2, '0');
    el.textContent = `${p(m)}:${p(s)}:${p(cs)}`;
  }

  // ── Keep track-head column (vertical) and ruler (horizontal) aligned with the lanes scroll ──
  function syncTimelineScroll() {
    const scroll = document.getElementById('tlxScroll');
    const headsInner = document.getElementById('tlxHeadsInner');
    const ruler = document.getElementById('tlxRuler');
    if (!scroll) return;
    if (headsInner) headsInner.style.transform = `translateY(${-scroll.scrollTop}px)`;
    if (ruler) ruler.style.transform = `translateX(${-scroll.scrollLeft}px)`;
  }

  // ── Select the previous/next/first/last clip and bring it into view ──
  function focusAdjacentClip(where) {
    const tl = [...state.execution.timeline].sort((a, b) => (a.start || 0) - (b.start || 0));
    if (!tl.length) return;
    let idx = tl.findIndex(c => c.id === selectedClipId);
    if (where === 'start') idx = 0;
    else if (where === 'end') idx = tl.length - 1;
    else if (where === 'prev') idx = idx < 0 ? 0 : Math.max(0, idx - 1);
    else if (where === 'next') idx = idx < 0 ? 0 : Math.min(tl.length - 1, idx + 1);
    const item = tl[idx];
    selectedClipId = item.id;
    renderTimeline();
    const scroll = document.getElementById('tlxScroll');
    if (scroll) {
      const left = (item.start || 0) * TL.pxPerSec;
      if (left < scroll.scrollLeft || left > scroll.scrollLeft + scroll.clientWidth - 80) {
        scroll.scrollLeft = Math.max(0, left - 40);
      }
    }
  }

  // ── Delete the currently selected clip (toolbar trash button) ──
  function deleteSelectedClip() {
    if (!selectedClipId) return toast('info', 'Select a clip first, then delete it.');
    removeClip(selectedClipId);
  }

  /* ── Undo / redo (timeline snapshots) ── */
  const HIST = { past: [], future: [], max: 60 };
  function snapshot() { return JSON.stringify({ tl: state.execution.timeline, layers: TL.layers }); }
  function recordHistory(snap) {
    HIST.past.push(snap);
    if (HIST.past.length > HIST.max) HIST.past.shift();
    HIST.future.length = 0;
    refreshUndoButtons();
  }
  function pushHistory() { recordHistory(snapshot()); }
  function applySnapshot(snap) {
    const data = JSON.parse(snap);
    state.execution.timeline = data.tl;
    TL.layers = data.layers || 1;
    selectedClipId = null;
    renderTimeline();
  }
  function undo() {
    if (!HIST.past.length) return;
    HIST.future.push(snapshot());
    applySnapshot(HIST.past.pop());
    refreshUndoButtons();
  }
  function redo() {
    if (!HIST.future.length) return;
    HIST.past.push(snapshot());
    applySnapshot(HIST.future.pop());
    refreshUndoButtons();
  }
  function refreshUndoButtons() {
    const u = document.getElementById('undoBtn'), r = document.getElementById('redoBtn');
    if (u) u.disabled = !HIST.past.length;
    if (r) r.disabled = !HIST.future.length;
  }

  /* ── Clip interactions ── */
  function attachClipHandlers(el, item) {
    el.querySelector('.tlx-clip-x').onclick = (e) => { e.stopPropagation(); removeClip(item.id); };
    el.querySelector('.tlx-clip-rename').onclick = (e) => { e.stopPropagation(); renameClip(item); };
    el.querySelector('.tlx-handle.l').addEventListener('pointerdown', (e) => startResize(e, item, 'l'));
    el.querySelector('.tlx-handle.r').addEventListener('pointerdown', (e) => startResize(e, item, 'r'));
    el.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.tlx-handle') || e.target.closest('.tlx-clip-x') || e.target.closest('.tlx-clip-rename')) return;
      startMove(e, item);
    });
  }

  function renderTimelineGhost(lanes) {
    if (!lanes) lanes = document.getElementById('tlxLanes');
    if (!lanes) return;
    lanes.querySelectorAll('.tlx-drag-ghost').forEach(el => el.remove());
    const g = TL.dragGhost;
    if (!g) return;
    const el = document.createElement('div');
    const dur = Math.max(TL.minLen, +g.duration || TL.defaultDur);
    const start = Math.max(0, +g.start || 0);
    const layer = Math.max(0, +g.layer || 0);
    const kind = g.kind || 'macro';
    el.className = 'tlx-drag-ghost kind-' + kind;
    el.style.left = (start * TL.pxPerSec) + 'px';
    el.style.top = (layer * TL.laneH + (TL.laneH - TL.clipH) / 2) + 'px';
    el.style.width = Math.max(20, dur * TL.pxPerSec) + 'px';
    el.innerHTML = `<div class="tlx-drag-ghost-name">${escapeHtml(g.name || 'Clip')}</div>
      <div class="tlx-drag-ghost-sub">${fmtTime(start)} · ${dur.toFixed(2)}s</div>`;
    lanes.appendChild(el);
  }

  function clearTimelineDragGhost() {
    TL.dragGhost = null;
    TL.draggingId = null;
    const lanes = document.getElementById('tlxLanes');
    if (lanes) {
      lanes.classList.remove('dragover');
      lanes.querySelectorAll('.tlx-drag-ghost').forEach(el => el.remove());
    }
  }

  async function renameClip(item) {
    const name = await nativePrompt({
      title: 'Rename clip', tbLabel: 'Rename', message: 'Enter a new name for this clip:',
      placeholder: 'Clip name', default: item.name, confirmLabel: 'Rename',
    });
    if (name === null) return;
    pushHistory();
    item.name = name || item.name;
    renderTimeline();
  }

  function startMove(e, item) {
    e.preventDefault();
    const startX = e.clientX, startY = e.clientY;
    const origStart = item.start || 0, origLayer = item.layer || 0;
    const before = snapshot();
    let moved = false;
    const dur = clipDuration(item);
    TL.draggingId = item.id;
    TL.dragGhost = { kind:item.kind, name:item.name, start:origStart, layer:origLayer, duration:dur };
    const onMove = (ev) => {
      const dx = ev.clientX - startX, dy = ev.clientY - startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true;
      const ns = Math.max(0, origStart + dx / TL.pxPerSec);
      // Snap whichever edge (start or end) is closer to another clip's edge.
      const snS = snapToClips(ns, item.id);
      const snE = snapToClips(ns + dur, item.id);
      let guide = null;
      if (snS.snapped && (!snE.snapped || Math.abs(ns - snS.t) <= Math.abs((ns + dur) - snE.t))) {
        item.start = Math.max(0, snS.t); guide = snS.t;
      } else if (snE.snapped) {
        item.start = Math.max(0, snE.t - dur); guide = snE.t;
      } else {
        item.start = snS.t;   // light grid snap
      }
      item.layer = Math.max(0, origLayer + Math.round(dy / TL.laneH));
      TL.dragGhost = { kind:item.kind, name:item.name, start:item.start || 0, layer:item.layer || 0, duration:dur };
      renderTimeline();
      showSnapGuide(guide);
    };
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      showSnapGuide(null);
      TL.dragGhost = null;
      TL.draggingId = null;
      if (!moved) selectClip(item);
      else { recordHistory(before); TL.layers = Math.max(TL.layers, (item.layer || 0) + 1); renderTimeline(); }
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  function startResize(e, item, side) {
    e.preventDefault(); e.stopPropagation();
    selectedClipId = item.id;
    const startX = e.clientX;
    const before = snapshot();
    let changed = false;
    const o = { start: item.start || 0, duration: clipDuration(item), trim: item.trimStart || 0 };
    const onMove = (ev) => {
      const dt = (ev.clientX - startX) / TL.pxPerSec;
      if (Math.abs(dt) > 1e-3) changed = true;
      let guide = null;
      if (side === 'r') {
        // The dragged edge is the clip END; snap it to other clips' edges.
        const sn = snapToClips(o.start + o.duration + dt, item.id);
        item.duration = Math.max(TL.minLen, sn.t - o.start);
        guide = sn.snapped ? sn.t : null;
      } else {
        // The dragged edge is the clip START; snap it, then clamp the head trim.
        const sn = snapToClips(o.start + dt, item.id);
        let delta = sn.t - o.start;
        delta = Math.max(delta, -o.trim, -o.start);
        delta = Math.min(delta, o.duration - TL.minLen);
        item.start = o.start + delta;
        item.trimStart = o.trim + delta;
        item.duration = o.duration - delta;
        guide = (sn.snapped && Math.abs(item.start - sn.t) < 1e-6) ? sn.t : null;
      }
      renderTimeline();
      showSnapGuide(guide);
    };
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      showSnapGuide(null);
      if (changed) recordHistory(before);
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  function selectClip(item) {
    selectedClipId = item.id;
    renderTimeline();
    if (item.kind === 'action') editAction(item);
  }

  function editAction(item) {
    const a = ACTIONS[item.actionType];
    if (!a) return;
    openParamModal({
      title: 'Edit ' + a.label, icon: a.icon, okLabel: 'Save', fields: a.fields, pick: a.pick, editor: a.editor,
      values: paramsToForm(item.actionType, item.params),
      onOk: (vals) => { item.params = coerceParams(item.actionType, vals); item.intrinsic = estimateActionDuration(item.actionType, item.params); renderTimeline(); },
    });
  }

  function removeClip(id) {
    const i = state.execution.timeline.findIndex(it => it.id === id);
    if (i < 0) return;
    pushHistory();
    state.execution.timeline.splice(i, 1);
    if (selectedClipId === id) selectedClipId = null;
    renderTimeline();
  }

  function renderActionList() {
    const body = document.getElementById('actionListBody');
    body.innerHTML = '';

    // Actions palette
    body.appendChild(sectionHead('bolt', 'Actions'));
    Object.keys(ACTIONS).forEach(type => {
      const a = ACTIONS[type];
      const row = paletteItem('green', a.icon, a.label, a.desc);
      row.draggable = true;
      row.ondragstart = (e) => { state.dragData = { source:'action', actionType:type }; e.dataTransfer.setData('text/plain','action'); };
      row.onclick = () => addAction(type);
      body.appendChild(row);
    });

    // Saved macros
    body.appendChild(sectionHead('movie', 'Saved Macros'));
    if (!state.macros.user.length) {
      body.appendChild(emptyHint('No saved macros yet. Hit Record to make one.'));
    } else {
      state.macros.user.forEach(m => {
        const desc = `${m.kind==='motion_control'?'Motion · ':''}${m.duration.toFixed(1)}s · ${m.events} events`;
        const row = paletteItem('', 'movie', m.name, desc);
        row.draggable = true;
        row.ondragstart = (e) => { state.dragData = { source:'macro', ref:m.ref, name:m.name, duration:m.duration }; e.dataTransfer.setData('text/plain','macro'); };
        row.onclick = () => addMacro(m);
        const actions = document.createElement('div');
        actions.className = 'al-row-actions';
        actions.innerHTML =
          `<button class="al-mini" title="Export" onclick="event.stopPropagation();exportMacro('${m.ref}')"><span class="material-symbols-outlined">ios_share</span></button>
           <button class="al-mini danger" title="Delete" onclick="event.stopPropagation();deleteMacro('${m.ref}','${escapeHtml(m.name)}')"><span class="material-symbols-outlined">delete</span></button>`;
        row.querySelector('.al-add').replaceWith(actions);
        body.appendChild(row);
      });
    }

    // Core engine macros
    body.appendChild(sectionHead('settings_suggest', 'Core Engine Macros'));
    state.macros.core.forEach(m => {
      const row = paletteItem('amber', 'bolt', m.name, m.description || 'Engine macro');
      row.draggable = true;
      row.ondragstart = (e) => { state.dragData = { source:'core', ref:m.ref, name:m.name, duration:m.duration }; e.dataTransfer.setData('text/plain','core'); };
      row.onclick = () => addCore(m);
      body.appendChild(row);
    });
  }

  function sectionHead(icon, label) {
    const h = document.createElement('div');
    h.className = 'al-section-head';
    h.innerHTML = `<span class="material-symbols-outlined">${icon}</span>${label}`;
    return h;
  }
  function paletteItem(iconClass, icon, name, desc) {
    const row = document.createElement('div');
    row.className = 'al-item';
    row.innerHTML = `
      <div class="al-ico ${iconClass}"><span class="material-symbols-outlined">${icon}</span></div>
      <div class="al-text"><div class="al-name">${escapeHtml(name)}</div><div class="al-desc">${escapeHtml(desc)}</div></div>
      <span class="al-add"><span class="material-symbols-outlined">add_circle</span></span>`;
    return row;
  }
  function emptyHint(text) {
    const d = document.createElement('div');
    d.className = 'al-desc';
    d.style.cssText = 'padding:6px 10px 10px;color:rgba(0,0,0,0.3);font-size:12px;';
    d.textContent = text;
    return d;
  }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  /* ───────────────────────── Timeline mutation ───────────────────────── */
  // pos (optional) = { layer, start } from a drop; otherwise the clip is appended
  // to the end of layer 0.
  function addMacro(m, pos) { insertClip({ id:newId(), kind:'macro', ref:m.ref, name:m.name, intrinsic:+m.duration||0.5 }, pos); }
  function addCore(m, pos)  { insertClip({ id:newId(), kind:'core', ref:m.ref, name:m.name, intrinsic:+m.duration||0.5 }, pos); }

  function addAction(type, pos) {
    // Open the param editor for a new action before inserting.
    const a = ACTIONS[type];
    openParamModal({
      title: a.label, icon: a.icon, okLabel: 'Add', fields: a.fields, pick: a.pick, editor: a.editor,
      values: Object.assign({}, a.def),
      onOk: (vals) => {
        const params = coerceParams(type, vals);
        insertClip({ id:newId(), kind:'action', actionType:type, name:a.label, params, intrinsic:estimateActionDuration(type, params) }, pos);
      },
    });
  }

  function insertClip(item, pos) {
    pushHistory();
    if (pos && typeof pos.start === 'number') { item.layer = Math.max(0, pos.layer || 0); item.start = Math.max(0, pos.start); }
    else { item.layer = 0; item.start = layerEnd(0); }
    item.duration = TL.defaultDur;          // every new clip defaults to 1 second
    item.trimStart = 0;
    state.execution.timeline.push(item);
    TL.layers = Math.max(TL.layers, (item.layer || 0) + 1);
    selectedClipId = item.id;
    renderTimeline();
  }

  // Convert stored params → form-friendly values (e.g. keys array → comma string)
  function paramsToForm(type, p) {
    const v = Object.assign({}, p);
    if (type === 'keycombo' && Array.isArray(v.keys)) v.keys = v.keys.join(',');
    return v;
  }
  // Convert form values → typed params
  function coerceParams(type, vals) {
    if (type === 'controlleraxis') return normalizeControllerAxisParams(vals);
    const a = ACTIONS[type];
    const out = {};
    a.fields.forEach(f => {
      let v = vals[f.k];
      if (f.type === 'number') v = parseFloat(v);
      if (type === 'keycombo' && f.k === 'keys') v = String(vals[f.k]||'').split(',').map(s=>s.trim()).filter(Boolean);
      out[f.k] = v;
    });
    return out;
  }

  /* ── Inline Controller Axis Editor ── */
  const AXIS_PARTS = {
    left_stick:  { label:'Left Stick',    icon:'sports_esports',     axes:[0,1], kind:'stick'   },
    right_stick: { label:'Right Stick',   icon:'sports_esports',     axes:[2,3], kind:'stick'   },
    left_trigger:  { label:'Left Trigger',  icon:'vertical_align_bottom', button:6, axis:6, kind:'trigger' },
    right_trigger: { label:'Right Trigger', icon:'vertical_align_bottom', button:7, axis:7, kind:'trigger' },
  };

  function normalizeControllerAxisParams(vals) {
    vals = vals || {};
    const part = ['left_stick','right_stick','left_trigger','right_trigger'].includes(vals.part) ? vals.part : 'left_stick';
    const clamp = (n, min, max) => Math.max(min, Math.min(max, Number.isFinite(+n) ? +n : 0));
    return {
      part,
      fromX: clamp(vals.fromX, -1, 1),
      fromY: clamp(vals.fromY, -1, 1),
      toX: clamp(vals.toX ?? vals.x, -1, 1),
      toY: clamp(vals.toY ?? vals.y, -1, 1),
      fromValue: clamp(vals.fromValue, 0, 1),
      toValue: clamp(vals.toValue ?? vals.value, 0, 1),
    };
  }

  /* ───────────────────────── Drop from the Action List onto a lane ───────────────────────── */
  function ghostFromDragData(d, layer, start) {
    if (!d) return null;
    if (d.source === 'action') {
      const a = ACTIONS[d.actionType] || {};
      return { kind:'action', name:a.label || 'Action', duration:TL.defaultDur, layer, start };
    }
    return { kind:d.source === 'core' ? 'core' : 'macro', name:d.name || 'Macro', duration:TL.defaultDur, layer, start };
  }

  function onLanesDragOver(e) {
    e.preventDefault();
    const lanes = document.getElementById('tlxLanes');
    if (!lanes) return;
    lanes.classList.add('dragover');
    const rect = lanes.getBoundingClientRect();
    const layer = Math.max(0, Math.floor((e.clientY - rect.top) / TL.laneH));
    const start = Math.max(0, snap((e.clientX - rect.left) / TL.pxPerSec));
    TL.dragGhost = ghostFromDragData(state.dragData, layer, start);
    renderTimelineGhost(lanes);
  }
  function onLanesDragLeave(e) {
    const lanes = document.getElementById('tlxLanes');
    if (lanes && e.relatedTarget && lanes.contains(e.relatedTarget)) return;
    clearTimelineDragGhost();
  }
  function onLanesDrop(e) {
    e.preventDefault();
    const lanes = document.getElementById('tlxLanes');
    lanes.classList.remove('dragover');
    const rect = lanes.getBoundingClientRect();
    const layer = Math.max(0, Math.floor((e.clientY - rect.top) / TL.laneH));
    const start = Math.max(0, snap((e.clientX - rect.left) / TL.pxPerSec));
    const pos = { layer, start };
    const d = state.dragData; state.dragData = null;
    clearTimelineDragGhost();
    if (!d) return;
    if (d.source === 'action') addAction(d.actionType, pos);
    else if (d.source === 'macro') addMacro({ ref:d.ref, name:d.name, duration:d.duration }, pos);
    else if (d.source === 'core') addCore({ ref:d.ref, name:d.name, duration:d.duration }, pos);
  }

  /* ───────────────────────── Param modal ───────────────────────── */
  function openParamModal(ctx) {
    state.modalCtx = ctx;
    document.querySelector('#modal .modal-card')?.classList.toggle('wide', ctx.editor === 'controllerAxis' || ctx.customWide);
    document.getElementById('modalTitle').textContent = ctx.title;
    document.getElementById('modalIcon').textContent = ctx.icon || 'tune';
    document.getElementById('modalOk').textContent = ctx.okLabel || 'OK';
    const body = document.getElementById('modalBody');
    body.innerHTML = '';
    document.getElementById('modalOk').style.display = '';

    if (ctx.editor === 'controllerAxis') {
      renderControllerAxisEditor(ctx.values || {});
      document.getElementById('modal').classList.add('show');
      return;
    }
    if (typeof ctx.render === 'function') {
      ctx.render(body);
      document.getElementById('modalOk').style.display = ctx.hideOk ? 'none' : '';
      document.getElementById('modalFoot').style.display = ctx.hideFoot ? 'none' : '';
      document.getElementById('modal').classList.add('show');
      return;
    }

    // "Pick on screen" shortcut for actions with coordinates.
    if (ctx.pick) {
      const pb = document.createElement('button');
      pb.type = 'button';
      pb.className = 'GTextBtn primary pick-btn';
      pb.innerHTML = `<span class="material-symbols-outlined">my_location</span>${ctx.pick.mode==='line'?'Draw the drag on screen':'Pick the point on screen'}`;
      pb.onclick = () => pickOnScreen(ctx.pick);
      body.appendChild(pb);
    }

    (ctx.fields || []).forEach(f => {
      const wrap = document.createElement('div');
      wrap.className = 'field';
      const cur = ctx.values[f.k];
      let control;

      if (f.widget === 'coord') {
        const v = (cur ?? 0.5);
        control =
          `<div class="coord-row">
             <input type="range" min="0" max="1" step="0.01" id="rng_${f.k}" value="${v}" oninput="syncCoord('${f.k}','rng')">
             <input type="number" min="0" max="1" step="${f.step||'0.01'}" id="f_${f.k}" value="${v}" oninput="syncCoord('${f.k}','num')">
           </div>`;
      } else if (f.widget === 'segment') {
        control =
          `<div class="seg" id="seg_${f.k}">${f.options.map(o =>
             `<button type="button" class="seg-btn ${cur===o?'active':''}" data-v="${o}" onclick="pickSeg('${f.k}','${o}')">
                <span class="material-symbols-outlined">mouse</span>${o}</button>`).join('')}</div>
           <input type="hidden" id="f_${f.k}" value="${cur ?? f.options[0]}">`;
      } else if (f.widget === 'key' || f.widget === 'keys') {
        const multi = f.widget === 'keys';
        control =
          `<div class="keyrec">
             <div class="key-chips" id="chips_${f.k}"></div>
             <div class="keyrec-actions">
               <button type="button" class="keyrec-btn" id="rec_${f.k}" onclick="startKeyRecord('${f.k}',${multi})">
                 <span class="material-symbols-outlined">keyboard</span>Record ${multi?'combo':'key'}</button>
               <button type="button" class="keyrec-btn" onclick="clearKeys('${f.k}')">
                 <span class="material-symbols-outlined">backspace</span>Clear</button>
             </div>
             <input type="hidden" id="f_${f.k}" value="${cur ?? ''}">
           </div>`;
      } else if (f.type === 'select') {
        control = `<select id="f_${f.k}">${f.options.map(o=>{
          const value = typeof o === 'object' ? o.value : o;
          const label = typeof o === 'object' ? (o.label || o.value) : o;
          return `<option value="${escapeHtml(value)}" ${cur===value?'selected':''}>${escapeHtml(label)}</option>`;
        }).join('')}</select>`;
      } else {
        const step = f.step ? `step="${f.step}"` : '';
        control = `<input id="f_${f.k}" type="${f.type}" ${step} value="${cur ?? ''}">`;
      }

      wrap.innerHTML = `<label>${f.label}</label>${control}${f.hint?`<span class="hint">${f.hint}</span>`:''}`;
      body.appendChild(wrap);

      // Initial chip render for key widgets.
      if (f.widget === 'key' || f.widget === 'keys') {
        renderKeyChips(f.k, String(cur ?? '').split(',').map(s=>s.trim()).filter(Boolean));
      }
    });

    if ((!ctx.fields || !ctx.fields.length) && !ctx.pick) body.innerHTML = '<div class="al-desc">No options.</div>';
    document.getElementById('modal').classList.add('show');
  }

  /* ── Editor widget helpers ── */
  function syncCoord(k, src) {
    const rng = document.getElementById('rng_' + k);
    const num = document.getElementById('f_' + k);
    if (!rng || !num) return;
    if (src === 'rng') num.value = rng.value; else rng.value = num.value;
  }
  function pickSeg(k, v) {
    document.getElementById('f_' + k).value = v;
    const seg = document.getElementById('seg_' + k);
    if (seg) seg.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.dataset.v === v));
  }
  function clearKeys(k) { document.getElementById('f_' + k).value = ''; renderKeyChips(k, []); }

  // Friendly label for a stored pynput key name.
  function keyChipLabel(name) {
    const m = { ctrl_l:'Ctrl', ctrl_r:'Ctrl', shift_l:'Shift', shift_r:'Shift', alt_l:'Alt',
      alt_gr:'AltGr', cmd:'Win', cmd_r:'Win', space:'Space', enter:'Enter', tab:'Tab',
      backspace:'Bksp', esc:'Esc', caps_lock:'Caps', up:'↑', down:'↓', left:'←', right:'→' };
    return m[name] || (name.length === 1 ? name.toUpperCase() : name);
  }
  function renderKeyChips(k, names) {
    const box = document.getElementById('chips_' + k);
    if (!box) return;
    box.innerHTML = names.length
      ? names.map(n => `<span class="key-cap">${escapeHtml(keyChipLabel(n))}</span>`).join('<span class="key-plus">+</span>')
      : '<span class="empty">No keys set — click Record</span>';
  }

  // Map a JS keyboard event → a pynput-compatible key name (see input_driver.name_to_key).
  function jsKeyToName(e) {
    const codeMap = {
      ControlLeft:'ctrl_l', ControlRight:'ctrl_r', ShiftLeft:'shift_l', ShiftRight:'shift_r',
      AltLeft:'alt_l', AltRight:'alt_gr', MetaLeft:'cmd', MetaRight:'cmd_r',
      Space:'space', Enter:'enter', Tab:'tab', Backspace:'backspace', Escape:'esc',
      CapsLock:'caps_lock', Delete:'delete', Insert:'insert', Home:'home', End:'end',
      PageUp:'page_up', PageDown:'page_down',
      ArrowUp:'up', ArrowDown:'down', ArrowLeft:'left', ArrowRight:'right',
    };
    if (codeMap[e.code]) return codeMap[e.code];
    if (/^F\d{1,2}$/.test(e.key)) return e.key.toLowerCase();      // F1..F12
    if (/^Key[A-Z]$/.test(e.code)) return e.code.slice(3).toLowerCase();
    if (/^Digit\d$/.test(e.code)) return e.code.slice(5);          // top-row numbers
    if (/^Numpad\d$/.test(e.code)) return e.code.slice(6);
    if (e.key && e.key.length === 1) return e.key.toLowerCase();
    return (e.key || '').toLowerCase();
  }

  function startKeyRecord(k, multi) {
    if (state.keyRecActive) return;
    state.keyRecActive = true;
    const btn = document.getElementById('rec_' + k);
    const hidden = document.getElementById('f_' + k);
    const pressed = new Set();
    const order = [];
    btn.classList.add('recording');
    btn.innerHTML = '<span class="material-symbols-outlined">fiber_manual_record</span>Recording…';

    const commit = () => { hidden.value = order.join(','); };
    const onDown = (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      const name = jsKeyToName(ev);
      if (!name) return;
      if (!pressed.has(name)) { pressed.add(name); order.push(name); }
      renderKeyChips(k, order);
      commit();
      if (!multi) finish();           // single key → done on first press
    };
    const onUp = (ev) => {
      ev.preventDefault();
      pressed.delete(jsKeyToName(ev));
      if (multi && pressed.size === 0 && order.length) finish();
    };
    function finish() {
      document.removeEventListener('keydown', onDown, true);
      document.removeEventListener('keyup', onUp, true);
      state.keyRecActive = false;
      btn.classList.remove('recording');
      btn.innerHTML = `<span class="material-symbols-outlined">keyboard</span>Record ${multi?'combo':'key'}`;
      commit();
    }
    document.addEventListener('keydown', onDown, true);
    document.addEventListener('keyup', onUp, true);
  }

  async function pickOnScreen(pick) {
    const res = await inPagePick(pick.mode);
    if (!res || typeof res !== 'object') return;   // cancelled
    Object.keys(res).forEach(rk => {
      const num = document.getElementById('f_' + rk);
      const rng = document.getElementById('rng_' + rk);
      const v = Math.max(0, Math.min(1, +res[rk])).toFixed(3);
      if (num) num.value = v;
      if (rng) rng.value = v;
    });
    toast('ok', pick.mode === 'line' ? 'Drag path captured.' : 'Point captured.');
  }

  // In-page fallback picker — a full-screen overlay inside the app window.
  // Returns {x,y} (point) or {fromX,fromY,toX,toY} (line), normalized 0..1, or null.
  function inPagePick(mode) {
    return new Promise(resolve => {
      const ov = document.createElement('div');
      ov.style.cssText = 'position:fixed;inset:0;z-index:80;cursor:crosshair;user-select:none;' +
        'background:radial-gradient(ellipse at center, rgba(10,12,30,0.12), rgba(10,12,30,0.34));';
      ov.innerHTML =
        `<div style="position:absolute;top:22px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:10px;` +
        `padding:11px 18px;border-radius:100px;background:rgba(255,255,255,0.62);backdrop-filter:blur(20px);` +
        `border:1px solid rgba(255,255,255,0.65);box-shadow:0 12px 40px rgba(0,0,0,0.25);font-size:13px;font-weight:600;color:rgba(0,0,0,0.82);">` +
        `<span style="width:9px;height:9px;border-radius:50%;background:rgba(99,102,241,1);"></span>` +
        `${mode === 'line' ? 'Drag from start to end' : 'Click the target point'}` +
        `<span style="font-weight:400;color:rgba(0,0,0,0.45);border-left:1px solid rgba(0,0,0,0.15);padding-left:8px;">Esc to cancel</span></div>` +
        `<svg style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;">` +
        `<line id="_ipline" stroke="rgba(99,102,241,0.9)" stroke-width="2" stroke-dasharray="6 5" style="display:none;"/></svg>`;
      document.body.appendChild(ov);
      const line = ov.querySelector('#_ipline');
      const norm = (e) => ({ x: Math.max(0, Math.min(1, e.clientX / window.innerWidth)), y: Math.max(0, Math.min(1, e.clientY / window.innerHeight)) });
      const r4 = (n) => +n.toFixed(4);
      let start = null, dragging = false;
      const cleanup = (val) => { ov.remove(); document.removeEventListener('keydown', onKey); resolve(val); };
      const onKey = (e) => { if (e.key === 'Escape') cleanup(null); };
      document.addEventListener('keydown', onKey);
      if (mode === 'line') {
        ov.addEventListener('pointerdown', (e) => { dragging = true; start = norm(e); line.setAttribute('x1', e.clientX); line.setAttribute('y1', e.clientY); line.setAttribute('x2', e.clientX); line.setAttribute('y2', e.clientY); line.style.display = ''; });
        ov.addEventListener('pointermove', (e) => { if (dragging) { line.setAttribute('x2', e.clientX); line.setAttribute('y2', e.clientY); } });
        ov.addEventListener('pointerup', (e) => { if (!dragging) return; dragging = false; const end = norm(e); cleanup({ fromX: r4(start.x), fromY: r4(start.y), toX: r4(end.x), toY: r4(end.y) }); });
      } else {
        ov.addEventListener('click', (e) => { const n = norm(e); cleanup({ x: r4(n.x), y: r4(n.y) }); });
      }
    });
  }

  function timelineNeedsControllerSupport() {
    return (state.execution.timeline || []).some(it => it.kind === 'action' && it.actionType === 'controlleraxis');
  }

  function controllerSupportAvailable() {
    return !!(state.appInfo && state.appInfo.controllerAvailable);
  }

  async function refreshControllerSupportStatus() {
    try {
      const st = await bridge({ action:'dgt_controller_support_status' });
      state.appInfo = Object.assign({}, state.appInfo || {}, st);
      renderControllerSupportRow();
      return st;
    } catch (e) {
      return state.appInfo || {};
    }
  }

  async function reinstallControllerSupportFlow() {
    return await runControllerSupportJob('reinstall');
  }

  async function installControllerSupportFlow() {
    return await reinstallControllerSupportFlow();
  }

  async function uninstallControllerSupportFlow(options) {
    options = options || {};
    if (!options.skipConfirm) {
      const ok = await nativeConfirm({
        title:'Uninstall Controller Support',
        tbLabel:'Controller Support',
        message:'This will remove the vgamepad Python package and ask Windows to uninstall the ViGEmBus virtual gamepad driver. Other apps that use ViGEmBus may stop creating virtual controllers until it is installed again.',
        confirmLabel:'Uninstall',
        danger:true,
      });
      if (!ok) return false;
    }
    await runControllerSupportJob('uninstall');
    return true;
  }

  function showControllerSupportProgress(kind) {
    document.getElementById('supportOverlay').classList.add('show');
    document.getElementById('supportCloseBtn').style.display = 'none';
    const logPanel = document.getElementById('supportLogPanel');
    const logToggle = document.getElementById('supportLogToggle');
    logPanel.classList.remove('show');
    logPanel.textContent = 'Waiting for installer output...';
    logToggle.classList.remove('active');
    logToggle.title = 'Show installer log';
    logToggle.setAttribute('aria-label', 'Show installer log');
    document.getElementById('supportIcon').textContent = kind === 'uninstall' ? 'delete' : 'download';
    document.getElementById('supportTitle').textContent = kind === 'uninstall' ? 'Removing controller support' : (kind === 'reinstall' ? 'Reinstalling controller support' : 'Setting up controller support');
    document.getElementById('supportSub').textContent = kind === 'uninstall'
      ? 'DigiTek Lab is removing vgamepad and the ViGEmBus virtual controller driver.'
      : (kind === 'reinstall'
        ? 'DigiTek Lab is reinstalling vgamepad and checking the ViGEmBus virtual controller driver.'
        : 'DigiTek Lab is installing vgamepad and checking the ViGEmBus virtual controller driver.');
    updateControllerSupportProgress({ progress:0, phase:'Starting', message:'Starting...', detail:'' });
  }

  function hideControllerSupportProgress() {
    document.getElementById('supportOverlay').classList.remove('show');
    document.getElementById('supportLogPanel').classList.remove('show');
    document.getElementById('supportLogToggle').classList.remove('active');
  }

  function toggleControllerSupportLog() {
    const panel = document.getElementById('supportLogPanel');
    const toggle = document.getElementById('supportLogToggle');
    const visible = panel.classList.toggle('show');
    toggle.classList.toggle('active', visible);
    toggle.title = visible ? 'Hide installer log' : 'Show installer log';
    toggle.setAttribute('aria-label', toggle.title);
    if (visible) panel.scrollTop = panel.scrollHeight;
  }

  function updateControllerSupportProgress(st) {
    const pct = Math.max(0, Math.min(100, Math.round(st.progress || 0)));
    document.getElementById('supportProgressFill').style.width = pct + '%';
    document.getElementById('supportPercent').textContent = pct + '%';
    document.getElementById('supportPhase').textContent = st.phase || 'Working';
    const detail = st.detail || st.message || 'Working...';
    document.getElementById('supportDetail').textContent = detail;
    const logPanel = document.getElementById('supportLogPanel');
    const logLines = Array.isArray(st.log) ? st.log : [];
    logPanel.textContent = logLines.length ? logLines.join('\n') : 'Waiting for installer output...';
    if (logPanel.classList.contains('show')) logPanel.scrollTop = logPanel.scrollHeight;
    if (st.message) setStatus(st.message, st.kind === 'uninstall' ? 'delete' : 'download');
  }

  async function runControllerSupportJob(kind) {
    showControllerSupportProgress(kind);
    try {
      await bridge({ action:'dgt_controller_support_job_start', kind });
      while (true) {
        const st = await bridge({ action:'dgt_controller_support_job_status' });
        updateControllerSupportProgress(st);
        if (st.done || !st.running) {
          state.appInfo = Object.assign({}, state.appInfo || {}, {
            controllerAvailable: !!st.controllerAvailable,
            controllerError: st.controllerError || st.error,
          });
          renderControllerSupportRow();
          document.getElementById('supportCloseBtn').style.display = '';
          setStatus('Ready', 'check_circle');
          if ((kind === 'install' || kind === 'reinstall') && st.controllerAvailable) {
            toast('ok', 'Controller Axis support is ready.');
            setTimeout(hideControllerSupportProgress, 900);
            return true;
          }
          if (kind === 'uninstall' && st.ok) {
            toast('ok', 'Controller support uninstall finished.');
            return true;
          }
          toast('err', st.error || st.controllerError || 'Controller support setup did not complete.');
          return false;
        }
        await new Promise(r => setTimeout(r, 350));
      }
    } catch (e) {
      document.getElementById('supportCloseBtn').style.display = '';
      setStatus('Ready', 'check_circle');
      toast('err', e.message);
      return false;
    }
  }

  function renderControllerSupportRow() {
    const row = document.getElementById('axisSupportRow');
    if (!row) return;
    const ready = controllerSupportAvailable();
    row.innerHTML = ready
      ? `<span>Controller support ready.</span><button type="button" onclick="reinstallControllerSupportFlow()">Reinstall drivers</button><button type="button" class="danger" onclick="uninstallControllerSupportFlow()">Uninstall drivers</button>`
      : `<span>Controller support missing.</span><button type="button" onclick="reinstallControllerSupportFlow()">Reinstall drivers</button><button type="button" class="danger" onclick="uninstallControllerSupportFlow()">Uninstall drivers</button>`;
  }

  function renderControllerAxisEditor(values) {
    state.axisComponentValue = normalizeControllerAxisParams(values);
    const body = document.getElementById('modalBody');
    body.innerHTML =
      `<div class="axis-editor">
        <div class="axis-controller" aria-label="Controller axis picker">
          <button type="button" class="axis-control-item" data-axis-part="left_stick"><span class="axis-control-glyph"><span class="material-symbols-outlined">sports_esports</span></span><span class="axis-control-main"><span class="axis-control-name">Left Stick</span><span class="axis-control-desc">Analog movement axis</span></span><span class="axis-control-side"><span class="axis-control-icon stick" data-axis-icon="left_stick"></span></span></button>
          <button type="button" class="axis-control-item" data-axis-part="right_stick"><span class="axis-control-glyph"><span class="material-symbols-outlined">sports_esports</span></span><span class="axis-control-main"><span class="axis-control-name">Right Stick</span><span class="axis-control-desc">Analog camera/look axis</span></span><span class="axis-control-side"><span class="axis-control-icon stick" data-axis-icon="right_stick"></span></span></button>
          <button type="button" class="axis-control-item" data-axis-part="left_trigger"><span class="axis-control-glyph"><span class="material-symbols-outlined">vertical_align_bottom</span></span><span class="axis-control-main"><span class="axis-control-name">Left Trigger</span><span class="axis-control-desc">Analog pull amount</span></span><span class="axis-control-side"><span class="axis-control-icon trigger" data-axis-icon="left_trigger"></span></span></button>
          <button type="button" class="axis-control-item" data-axis-part="right_trigger"><span class="axis-control-glyph"><span class="material-symbols-outlined">vertical_align_bottom</span></span><span class="axis-control-main"><span class="axis-control-name">Right Trigger</span><span class="axis-control-desc">Analog pull amount</span></span><span class="axis-control-side"><span class="axis-control-icon trigger" data-axis-icon="right_trigger"></span></span></button>
        </div>
        <div class="axis-panel">
          <div class="axis-panel-head"><span class="material-symbols-outlined" id="axis-part-icon">sports_esports</span><span id="axis-part-title">Left Stick</span></div>
          <div class="axis-point-tabs">
            <button type="button" class="axis-point-tab" id="axis-initial-tab"><span class="axis-dot"></span>Initial</button>
            <button type="button" class="axis-point-tab" id="axis-target-tab"><span class="axis-dot target"></span>Target</button>
          </div>
          <div id="axis-stick-tools">
            <div class="axis-stick-pad" id="axis-stick-pad"><div class="axis-stick-path" id="axis-stick-path"></div><div class="axis-stick-ghost" id="axis-stick-ghost"></div><div class="axis-stick-thumb" id="axis-stick-thumb"></div></div>
            <div class="axis-slider-row"><span>X</span><input type="range" min="-1" max="1" step="0.01" id="axis-x-range"><input type="number" min="-1" max="1" step="0.01" id="axis-x-num"></div>
            <div class="axis-slider-row"><span>Y</span><input type="range" min="-1" max="1" step="0.01" id="axis-y-range"><input type="number" min="-1" max="1" step="0.01" id="axis-y-num"></div>
          </div>
          <div id="axis-trigger-tools" style="display:none">
            <div class="axis-trigger-press" id="axis-trigger-press"><div class="axis-trigger-cap" id="axis-trigger-cap"></div></div>
            <div class="axis-slider-row"><span>Pull</span><input type="range" min="0" max="1" step="0.01" id="axis-value-range"><input type="number" min="0" max="1" step="0.01" id="axis-value-num"></div>
          </div>
          <div class="axis-record-row"><button type="button" class="GTextBtn primary" id="axis-record-btn"><span class="material-symbols-outlined">fiber_manual_record</span>Record controller</button><button type="button" class="GTextBtn ghost" id="axis-center-btn"><span class="material-symbols-outlined">restart_alt</span>Center</button></div>
          <div class="axis-readout" id="axis-readout"></div>
          <div class="axis-support-row" id="axisSupportRow"></div>
        </div>
      </div>`;
    axisEdInit(state.axisComponentValue);
  }

  function axisEdInit(params) {
    state.axisEdParams = normalizeControllerAxisParams(params);
    state.axisEdEditPoint = 'target';
    const $id = id => document.getElementById(id);
    document.querySelectorAll('[data-axis-part]').forEach(btn =>
      btn.addEventListener('click', () => axisEdSelectPart(btn.dataset.axisPart)));
    $id('axis-initial-tab').addEventListener('click', () => axisEdSetEditPoint('initial'));
    $id('axis-target-tab').addEventListener('click', () => axisEdSetEditPoint('target'));
    $id('axis-x-range').addEventListener('input', e => axisEdSetComponent('x', e.target.value));
    $id('axis-x-num').addEventListener('input', e => axisEdSetComponent('x', e.target.value));
    $id('axis-y-range').addEventListener('input', e => axisEdSetComponent('y', e.target.value));
    $id('axis-y-num').addEventListener('input', e => axisEdSetComponent('y', e.target.value));
    $id('axis-value-range').addEventListener('input', e => axisEdSetComponent('value', e.target.value));
    $id('axis-value-num').addEventListener('input', e => axisEdSetComponent('value', e.target.value));
    $id('axis-stick-pad').addEventListener('pointerdown', axisEdStartStickDrag);
    $id('axis-trigger-press').addEventListener('pointerdown', axisEdStartTriggerDrag);
    $id('axis-center-btn').addEventListener('click', axisEdResetValue);
    $id('axis-record-btn').addEventListener('click', axisEdToggleRecord);
    axisEdUpdateUi();
    renderControllerSupportRow();
  }

  function axisEdSelectPart(part) {
    if (!AXIS_PARTS[part]) return;
    state.axisEdParams.part = part;
    state.axisComponentValue = normalizeControllerAxisParams(state.axisEdParams);
    axisEdUpdateUi();
  }

  function axisEdSetEditPoint(point) {
    state.axisEdEditPoint = point === 'initial' ? 'initial' : 'target';
    axisEdUpdateUi();
  }

  function axisEdPatch(values) {
    state.axisEdParams = normalizeControllerAxisParams(Object.assign({}, state.axisEdParams, values));
    state.axisComponentValue = state.axisEdParams;
    axisEdUpdateUi();
  }

  function axisEdActiveValues() {
    const p = state.axisEdParams;
    return state.axisEdEditPoint === 'initial'
      ? { x: p.fromX, y: p.fromY, value: p.fromValue }
      : { x: p.toX,   y: p.toY,   value: p.toValue   };
  }

  function axisEdSetComponent(name, raw) {
    const clamp = (n, min, max) => Math.max(min, Math.min(max, Number.isFinite(+n) ? +n : 0));
    const value = clamp(raw, name === 'value' ? 0 : -1, 1);
    if (state.axisEdEditPoint === 'initial') {
      if (name === 'x') state.axisEdParams.fromX = value;
      if (name === 'y') state.axisEdParams.fromY = value;
      if (name === 'value') state.axisEdParams.fromValue = value;
    } else {
      if (name === 'x') state.axisEdParams.toX = value;
      if (name === 'y') state.axisEdParams.toY = value;
      if (name === 'value') state.axisEdParams.toValue = value;
    }
    state.axisComponentValue = normalizeControllerAxisParams(state.axisEdParams);
    axisEdUpdateUi();
  }

  function axisEdUpdateUi() {
    const p = state.axisEdParams;
    if (!p) return;
    const $id = id => document.getElementById(id);
    const part = AXIS_PARTS[p.part] || AXIS_PARTS.left_stick;
    document.querySelectorAll('[data-axis-part]').forEach(b =>
      b.classList.toggle('active', b.dataset.axisPart === p.part));
    const titleEl = $id('axis-part-title'); if (titleEl) titleEl.textContent = part.label;
    const iconEl  = $id('axis-part-icon');  if (iconEl)  iconEl.textContent  = part.icon;
    const stickTools = $id('axis-stick-tools');   if (stickTools) stickTools.style.display   = part.kind === 'stick'   ? '' : 'none';
    const trigTools  = $id('axis-trigger-tools'); if (trigTools)  trigTools.style.display    = part.kind === 'trigger' ? '' : 'none';
    const initTab = $id('axis-initial-tab'); if (initTab) initTab.classList.toggle('active', state.axisEdEditPoint === 'initial');
    const tgtTab  = $id('axis-target-tab');  if (tgtTab)  tgtTab.classList.toggle('active',  state.axisEdEditPoint !== 'initial');
    const a = axisEdActiveValues();
    const xRange = $id('axis-x-range');     if (xRange)   xRange.value   = a.x;
    const xNum   = $id('axis-x-num');       if (xNum)     xNum.value     = a.x.toFixed(2);
    const yRange = $id('axis-y-range');     if (yRange)   yRange.value   = a.y;
    const yNum   = $id('axis-y-num');       if (yNum)     yNum.value     = a.y.toFixed(2);
    const valRange = $id('axis-value-range'); if (valRange) valRange.value = a.value;
    const valNum   = $id('axis-value-num');   if (valNum)   valNum.value   = a.value.toFixed(2);
    const sx = p.fromX * 59, sy = p.fromY * 59, tx = p.toX * 59, ty = p.toY * 59;
    const ghost = $id('axis-stick-ghost');
    if (ghost) { ghost.style.transform = `translate(${sx}px,${sy}px)`; ghost.style.opacity = state.axisEdEditPoint === 'initial' ? '1' : '.58'; }
    const thumb = $id('axis-stick-thumb');
    if (thumb) { thumb.style.transform = `translate(${tx}px,${ty}px)`; thumb.style.opacity = state.axisEdEditPoint === 'initial' ? '.72' : '1'; }
    const dx = tx - sx, dy = ty - sy;
    const path = $id('axis-stick-path');
    if (path) { path.style.transform = `translate(${sx}px,${sy}px) rotate(${Math.atan2(dy,dx)}rad)`; path.style.width = Math.hypot(dx,dy) + 'px'; }
    document.querySelectorAll('.axis-control-icon.stick').forEach(el => { el.style.setProperty('--stick-to-x','0px'); el.style.setProperty('--stick-to-y','0px'); });
    document.querySelectorAll('.axis-control-icon.trigger').forEach(el => el.style.setProperty('--trigger-to','0'));
    const icon = document.querySelector(`[data-axis-icon="${p.part}"]`);
    if (icon && part.kind === 'stick')   { icon.style.setProperty('--stick-to-x',(p.toX*7)+'px'); icon.style.setProperty('--stick-to-y',(p.toY*7)+'px'); }
    if (icon && part.kind === 'trigger')   icon.style.setProperty('--trigger-to', p.toValue);
    const tp = $id('axis-trigger-press');
    if (tp) { tp.style.setProperty('--from', p.fromValue); tp.style.setProperty('--to', p.toValue); tp.style.setProperty('--cap', a.value); }
    const readout = $id('axis-readout');
    if (readout) readout.textContent = part.kind === 'stick'
      ? `${part.label}  ${state.axisEdEditPoint === 'initial' ? 'Initial' : 'Target'} X ${a.x.toFixed(2)}  Y ${a.y.toFixed(2)}`
      : `${part.label}  ${state.axisEdEditPoint === 'initial' ? 'Initial' : 'Target'} pull ${a.value.toFixed(2)}`;
  }

  function axisEdStartStickDrag(e) {
    e.preventDefault();
    const pad = document.getElementById('axis-stick-pad');
    pad.setPointerCapture(e.pointerId);
    const move = ev => {
      const r = pad.getBoundingClientRect();
      const cx = r.left + r.width/2, cy = r.top + r.height/2, max = r.width/2;
      let x = (ev.clientX - cx)/max, y = (ev.clientY - cy)/max;
      const len = Math.hypot(x, y); if (len > 1) { x /= len; y /= len; }
      axisEdPatch(state.axisEdEditPoint === 'initial' ? {fromX:x,fromY:y} : {toX:x,toY:y});
    };
    const up = () => { pad.removeEventListener('pointermove',move); pad.removeEventListener('pointerup',up); pad.removeEventListener('pointercancel',up); };
    pad.addEventListener('pointermove', move); pad.addEventListener('pointerup', up); pad.addEventListener('pointercancel', up);
    move(e);
  }

  function axisEdStartTriggerDrag(e) {
    e.preventDefault();
    const press = document.getElementById('axis-trigger-press');
    press.setPointerCapture(e.pointerId);
    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    const move = ev => {
      const r = press.getBoundingClientRect();
      axisEdPatch(state.axisEdEditPoint === 'initial'
        ? { fromValue: clamp(1 - ((ev.clientY - r.top) / r.height), 0, 1) }
        : { toValue:   clamp(1 - ((ev.clientY - r.top) / r.height), 0, 1) });
    };
    const up = () => { press.removeEventListener('pointermove',move); press.removeEventListener('pointerup',up); press.removeEventListener('pointercancel',up); };
    press.addEventListener('pointermove', move); press.addEventListener('pointerup', up); press.addEventListener('pointercancel', up);
    move(e);
  }

  function axisEdResetValue() {
    axisEdPatch(state.axisEdEditPoint === 'initial' ? {fromX:0,fromY:0,fromValue:0} : {toX:0,toY:0,toValue:0});
  }

  function axisEdToggleRecord() {
    const btn = document.getElementById('axis-record-btn');
    if (state.axisRecTimer) {
      clearInterval(state.axisRecTimer); state.axisRecTimer = null;
      btn.classList.remove('recording');
      btn.innerHTML = '<span class="material-symbols-outlined">fiber_manual_record</span>Record controller';
      return;
    }
    if (!navigator.getGamepads) { toast('err', 'Gamepad recording is not available in this browser.'); return; }
    btn.classList.add('recording');
    btn.innerHTML = '<span class="material-symbols-outlined">stop</span>Stop recording';
    state.axisRecTimer = setInterval(() => {
      const gp = Array.from(navigator.getGamepads()).find(Boolean);
      const readout = document.getElementById('axis-readout');
      if (!gp) { if (readout) readout.textContent = 'Connect or move a controller to record.'; return; }
      const part = AXIS_PARTS[state.axisEdParams.part];
      if (part.kind === 'stick') {
        const x = gp.axes[part.axes[0]] || 0, y = gp.axes[part.axes[1]] || 0;
        axisEdPatch(state.axisEdEditPoint === 'initial'
          ? { fromX: Math.abs(x)<.03?0:x, fromY: Math.abs(y)<.03?0:y }
          : { toX:   Math.abs(x)<.03?0:x, toY:   Math.abs(y)<.03?0:y });
      } else {
        const fromButton = gp.buttons[part.button] ? gp.buttons[part.button].value : 0;
        const fromAxis   = typeof gp.axes[part.axis] === 'number' ? (gp.axes[part.axis]+1)/2 : 0;
        axisEdPatch(state.axisEdEditPoint === 'initial'
          ? { fromValue: Math.max(fromButton, fromAxis) }
          : { toValue:   Math.max(fromButton, fromAxis) });
      }
    }, 80);
  }

  function getControllerAxisParamsFromEditor() {
    return normalizeControllerAxisParams(state.axisComponentValue || {});
  }



  function onModalOk() {
    const ctx = state.modalCtx;
    if (!ctx) return closeAppModal();
    if (ctx.motionSettings) return saveMotionSettings();
    let vals = {};
    if (ctx.editor === 'controllerAxis') vals = getControllerAxisParamsFromEditor();
    else (ctx.fields || []).forEach(f => { vals[f.k] = document.getElementById('f_' + f.k).value; });
    closeAppModal();
    if (ctx.onOk) ctx.onOk(vals);
  }
  function closeAppModal() {
    if (state.axisRecTimer) { clearInterval(state.axisRecTimer); state.axisRecTimer = null; }
    document.querySelector('#modal .modal-card')?.classList.remove('wide');
    document.getElementById('modalOk').style.display = '';
    document.getElementById('modal').classList.remove('show');
    state.modalCtx = null;
  }

  function bindModalCancelOnce(onCancel) {
    let done = false;
    const cancel = () => {
      if (done) return;
      done = true;
      onCancel();
    };
    document.querySelector('#modal .x')?.addEventListener('click', cancel, { once:true });
    document.querySelector('#modal .modal-foot .ghost')?.addEventListener('click', cancel, { once:true });
  }

  // Simple text prompt built on the same modal
  function promptModal(title, label, value, okLabel) {
    return new Promise(resolve => {
      openParamModal({
        title, icon:'edit', okLabel: okLabel || 'OK',
        fields:[ {k:'value', label, type:'text'} ],
        values:{ value: value || '' },
        onOk: (v) => resolve((v.value || '').trim()),
      });
      bindModalCancelOnce(() => resolve(null));
    });
  }

  /* ── Motion Controlled key-map editor ── */
  function normalizeMotionKeyName(name) { return String(name || '').trim().toLowerCase(); }
  function motionMapRowsFromState() {
    const map = state.execution.motionKeyMap || defaultMotionKeyMap();
    return Object.keys(map).sort().map(key => ({
      key,
      mode: map[key]?.mode || 'opposite',
      target: map[key]?.target || '',
    }));
  }
  function ensureMotionKeyMap() {
    if (!state.execution.motionKeyMap || typeof state.execution.motionKeyMap !== 'object')
      state.execution.motionKeyMap = defaultMotionKeyMap();
  }
  function openMotionSettings(event) {
    if (event) event.stopPropagation();
    ensureMotionKeyMap();
    state.modalCtx = { motionSettings:true };
    document.querySelector('#modal .modal-card')?.classList.remove('wide');
    document.getElementById('modalTitle').textContent = 'Motion Controlled';
    document.getElementById('modalIcon').textContent = 'control_camera';
    document.getElementById('modalOk').textContent = 'Save';
    renderMotionSettingsBody(motionMapRowsFromState());
    document.getElementById('modal').classList.add('show');
  }
  function renderMotionSettingsBody(rows) {
    const body = document.getElementById('modalBody');
    body.innerHTML =
      `<div class="motion-map-actions">
         <button type="button" class="GTextBtn primary" onclick="addMotionMapRow()"><span class="material-symbols-outlined">add</span>Add</button>
         <button type="button" class="GTextBtn ghost" onclick="resetMotionMapDefaults()"><span class="material-symbols-outlined">restart_alt</span>Defaults</button>
       </div>
       <div class="motion-map" id="motionMapRows">
         <div class="motion-map-head"><span>Key</span><span>Reverse</span><span>Opposite</span><span></span></div>
         ${rows.map((r, i) => motionMapRowHtml(r, i)).join('')}
       </div>`;
  }
  function motionMapRowHtml(row, i) {
    const mode = ['opposite','same','disabled'].includes(row.mode) ? row.mode : 'opposite';
    return `<div class="motion-map-row" data-motion-row="${i}">
      <input id="motion_key_${i}" value="${escapeHtml(row.key)}" placeholder="w">
      <select id="motion_mode_${i}">
        <option value="opposite" ${mode==='opposite'?'selected':''}>Opposite</option>
        <option value="same" ${mode==='same'?'selected':''}>Same key</option>
        <option value="disabled" ${mode==='disabled'?'selected':''}>Disabled</option>
      </select>
      <input id="motion_target_${i}" value="${escapeHtml(row.target)}" placeholder="s">
      <button type="button" class="motion-map-del" title="Remove" onclick="removeMotionMapRow(${i})"><span class="material-symbols-outlined">delete</span></button>
    </div>`;
  }
  function readMotionMapRows() {
    const rows = [];
    document.querySelectorAll('[data-motion-row]').forEach((row, i) => {
      rows.push({
        key: normalizeMotionKeyName(document.getElementById('motion_key_' + i)?.value),
        mode: document.getElementById('motion_mode_' + i)?.value || 'opposite',
        target: normalizeMotionKeyName(document.getElementById('motion_target_' + i)?.value),
      });
    });
    return rows.filter(r => r.key);
  }
  function addMotionMapRow() {
    const rows = readMotionMapRows();
    rows.push({ key:'', mode:'opposite', target:'' });
    renderMotionSettingsBody(rows);
  }
  function removeMotionMapRow(i) {
    const rows = readMotionMapRows();
    rows.splice(i, 1);
    renderMotionSettingsBody(rows);
  }
  function resetMotionMapDefaults() {
    renderMotionSettingsBody(Object.keys(DEFAULT_MOTION_KEY_MAP).sort().map(key => Object.assign({ key }, DEFAULT_MOTION_KEY_MAP[key])));
  }
  function saveMotionSettings() {
    const map = {};
    readMotionMapRows().forEach(r => {
      const mode = ['opposite','same','disabled'].includes(r.mode) ? r.mode : 'opposite';
      map[r.key] = { mode, target: mode === 'opposite' ? r.target : '' };
    });
    state.execution.motionKeyMap = map;
    closeAppModal();
    toast('ok', 'Motion Controlled key map saved.');
  }

  async function nativeConfirm(opts) {
    opts = opts || {};
    return new Promise(resolve => {
      openParamModal({
        title: opts.title || 'Confirm',
        icon: opts.danger ? 'warning' : (opts.icon || 'help'),
        hideOk: true,
        hideFoot: true,
        render: (body) => {
          const wrap = document.createElement('div');
          wrap.className = 'dom-confirm';
          wrap.innerHTML = `<p>${escapeHtml(opts.message || 'Are you sure?')}</p>`;
          const actions = document.createElement('div');
          actions.className = 'dom-modal-actions';
          actions.innerHTML = `
            <button type="button" class="GTextBtn ghost" data-action="cancel">Cancel</button>
            <button type="button" class="GTextBtn ${opts.danger ? 'danger' : 'primary'}" data-action="ok">${escapeHtml(opts.confirmLabel || 'OK')}</button>
          `;
          wrap.appendChild(actions);
          body.appendChild(wrap);
          actions.querySelector('[data-action="cancel"]').onclick = () => { closeAppModal(); resolve(false); };
          actions.querySelector('[data-action="ok"]').onclick = () => { closeAppModal(); resolve(true); };
        },
      });
      bindModalCancelOnce(() => resolve(false));
    });
  }
  async function nativePrompt(opts) {
    return promptModal(opts.title, opts.message || '', opts.default || '', opts.confirmLabel);
  }
  async function nativePick(opts) {
    return new Promise(resolve => {
      openParamModal({
        title: opts.title, icon:'folder_open', okLabel: opts.confirmLabel || 'OK',
        fields:[ {k:'value', label: opts.message || 'Select', type:'select',
                  options:(opts.options||[]).map(o => typeof o === 'object' ? { value:o.value, label:o.label || o.value } : o)} ],
        values:{ value: (opts.options && opts.options[0]) ? (typeof opts.options[0]==='object'?opts.options[0].value:opts.options[0]) : '' },
        onOk: (v) => resolve(v.value || null),
      });
      bindModalCancelOnce(() => resolve(null));
    });
  }

  /* ───────────────────────── Record flow ───────────────────────── */
  async function onRecord() {
    if (state.recording) { finishRecording(); return; }
    if (state.appInfo && !state.appInfo.inputAvailable) { toast('err', state.appInfo.inputError || 'Input unavailable'); return; }
    await runCountdown('Switch to Roblox…');
    try {
      await bridge({ action:'dgt_record_start', motionControlled: state.execution.motionControlled });
      state.recording = true;
      state.recordMotion = state.execution.motionControlled;
      document.getElementById('recordBtn').classList.add('recording');
      document.getElementById('recordBtn').innerHTML = '<span class="material-symbols-outlined">stop</span>';
      document.getElementById('recBanner').classList.add('show');
      setStatus('Recording…', 'fiber_manual_record');
      startRecPolling();
    } catch (e) { toast('err', e.message); }
  }

  function startRecPolling() {
    const t0 = Date.now();
    state.recTimer = setInterval(async () => {
      document.getElementById('recTime').textContent = ((Date.now()-t0)/1000).toFixed(1) + 's';
      try {
        const st = await bridge({ action:'dgt_record_status' });
        if (st.stoppedByHotkey) finishRecording();
      } catch (e) {}
    }, 250);
  }

  async function finishRecording() {
    if (!state.recording) return;
    clearInterval(state.recTimer);
    state.recording = false;
    document.getElementById('recBanner').classList.remove('show');
    document.getElementById('recordBtn').classList.remove('recording');
    document.getElementById('recordBtn').innerHTML = '<span class="material-symbols-outlined">fiber_manual_record</span>';
    setStatus('Ready', 'check_circle');
    let result;
    try { result = await bridge({ action:'dgt_record_stop' }); }
    catch (e) { toast('err', e.message); return; }
    if (!result || !result.ok || !result.events.length) { toast('info', 'Nothing was recorded.'); return; }

    const name = await nativePrompt({
      title:'Save Macro', tbLabel:'Save Macro',
      message:`Name this ${result.duration.toFixed(1)}s macro:`,
      placeholder:'Macro name', default:'New Macro', confirmLabel:'Save',
    });
    if (name === null) { toast('info', 'Recording discarded.'); return; }
    try {
      await bridge({ action:'dgt_save_macro', data: {
        name: name || 'New Macro', kind: result.kind, motionControlled: result.motionControlled,
        duration: result.duration, events: result.events,
      }});
      toast('ok', `Saved “${name||'New Macro'}” (${result.duration.toFixed(1)}s)`);
      await refreshMacros();
    } catch (e) { toast('err', e.message); }
  }

  function runCountdown(sub) {
    return new Promise(resolve => {
      const el = document.getElementById('countdown');
      const num = document.getElementById('countdownNum');
      document.getElementById('countdownSub').textContent = sub || '';
      let n = 3; num.textContent = n; el.classList.add('show');
      const t = setInterval(() => {
        n--;
        if (n <= 0) { clearInterval(t); el.classList.remove('show'); resolve(); }
        else num.textContent = n;
      }, 700);
    });
  }

  /* ───────────────────────── Play flow ───────────────────────── */
  async function onPlayPause() {
    if (state.playing) {
      if (state.paused) { await bridge({ action:'dgt_resume' }).catch(()=>{}); state.paused = false; setPlayIcon('pause'); setStatus(state.continuous?'Playing (continuous)…':'Playing…','play_arrow'); }
      else { await bridge({ action:'dgt_pause' }).catch(()=>{}); state.paused = true; setPlayIcon('play_arrow'); setStatus('Paused','pause'); }
      return;
    }
    if (!state.execution.timeline.length) { toast('info', 'Add some items to the timeline first.'); return; }
    if (state.appInfo && !state.appInfo.inputAvailable) { toast('err', state.appInfo.inputError || 'Input unavailable'); return; }
    if (timelineNeedsControllerSupport()) {
      const st = await refreshControllerSupportStatus();
      if (!st.controllerAvailable) {
        const installed = await installControllerSupportFlow();
        if (!installed) return;
      }
    }
    await runCountdown('Switch to Roblox…');
    try {
      state.stopRequested = false; state.restarting = false;
      await bridge({ action:'dgt_play', execution: state.execution });
      state.playing = true; state.paused = false;
      setPlayIcon('pause');
      setStatus(state.continuous ? 'Playing (continuous)…' : 'Playing…', 'play_arrow');
      document.getElementById('playBtn')?.classList.add('busy');
      document.getElementById('titlePlayBtn')?.classList.add('busy');
      positionPlayhead(0);
      startPlayPolling();
    } catch (e) { toast('err', e.message); }
  }

  async function onStop() {
    state.stopRequested = true;            // prevent continuous mode from relooping
    await bridge({ action:'dgt_stop' }).catch(()=>{});
    endPlayback();
  }

  function startPlayPolling() {
    state.pollTimer = setInterval(async () => {
      let st;
      try { st = await bridge({ action:'dgt_playback_status' }); } catch (e) { return; }

      if (st.phase === 'rewind') {
        setStatus('Playing backward to start…', 'fast_rewind');
        positionPlayhead(st.elapsed || 0);
        highlightPlayingTime(st.elapsed || 0);
      } else if (st.phase === 'timeline') {
        positionPlayhead(st.elapsed || 0);
        highlightPlayingTime(st.elapsed || 0);
        if (!state.paused) setStatus(state.continuous ? 'Playing (continuous)…' : 'Playing…', 'play_arrow');
      }

      if (!st.playing) {
        if (st.error) { toast('err', 'Playback error: ' + st.error); endPlayback(); return; }
        // Continuous mode: loop the execution again instead of ending.
        if (state.continuous && !state.stopRequested) {
          if (state.restarting) return;      // a restart is already in flight
          state.restarting = true;
          try { await bridge({ action:'dgt_play', execution: state.execution }); positionPlayhead(0); }
          catch (e) { toast('err', e.message); state.restarting = false; endPlayback(); }
          return;                            // cleared once playing is observed again
        }
        toast('ok', 'Playback finished.');
        endPlayback();
        return;
      }
      // Playback confirmed running → a pending continuous restart has taken effect.
      if (state.restarting) state.restarting = false;
    }, 100);
  }

  function positionPlayhead(elapsed) {
    state._elapsed = elapsed;
    updateTimecode(elapsed);
    const ph = document.getElementById('tlxPlayhead');
    if (!ph) return;
    ph.style.left = (elapsed * TL.pxPerSec) + 'px';
    ph.classList.add('show');
  }

  function highlightPlayingTime(elapsed) {
    document.querySelectorAll('.tlx-clip').forEach(el => {
      const item = state.execution.timeline.find(it => it.id === el.dataset.id);
      if (!item) return;
      const s = item.start || 0, e = s + clipDuration(item);
      el.classList.toggle('playing', elapsed >= s && elapsed < e);
    });
  }

  function endPlayback() {
    clearInterval(state.pollTimer);
    state.playing = false; state.paused = false; state.restarting = false; state._elapsed = 0;
    setPlayIcon('play_arrow');
    setStatus('Ready', 'check_circle');
    document.getElementById('playBtn')?.classList.remove('busy');
    document.getElementById('titlePlayBtn')?.classList.remove('busy');
    updateTimecode(0);
    document.querySelectorAll('.tlx-clip.playing').forEach(el => el.classList.remove('playing'));
    setTimeout(() => { const ph = document.getElementById('tlxPlayhead'); if (ph) { ph.classList.remove('show'); ph.style.left = '0px'; } }, 500);
  }

  function setPlayIcon(name) {
    document.getElementById('playIcon').textContent = name;
    const titleIcon = document.getElementById('titlePlayIcon');
    if (titleIcon) titleIcon.textContent = name;
  }

  // Titlebar status pill — update the value text + colour the dot for the current state.
  function setStatus(text, icon) {
    const el = document.getElementById('statusMsg');
    if (el) el.textContent = text;
    const dot = document.getElementById('statusDot');
    if (dot) {
      const danger = icon === 'fiber_manual_record' || icon === 'delete';
      const busy = icon === 'play_arrow' || icon === 'pause' || icon === 'fast_rewind' || icon === 'download';
      dot.style.background = danger ? 'var(--color-danger)' : busy ? 'var(--accent-color)' : 'var(--color-success)';
    }
  }

  // Continuous Playback toggle.
  function toggleContinuous() {
    state.continuous = !state.continuous;
    document.getElementById('continuousBtn')?.classList.toggle('active', state.continuous);
    document.getElementById('continuousStatus').style.display = state.continuous ? 'flex' : 'none';
    toast('info', state.continuous ? 'Continuous playback on — loops until you stop.' : 'Continuous playback off.');
    if (state.playing && !state.paused) setStatus(state.continuous ? 'Playing (continuous)…' : 'Playing…', 'play_arrow');
  }

  /* ───────────────────────── Execution save / load / export ───────────────────────── */
  // Reflect the current execution name in the status bar (replaces the old toolbar input).
  function setExecNameLabel(name) {
    const el = document.getElementById('execNameLabel');
    if (el) el.textContent = name || 'Untitled Execution';
  }
  // Keep the Motion Controlled toolbar button's pressed state in sync with the checkbox.
  function syncMotionBtn() {
    const cb = document.getElementById('motionToggle');
    document.getElementById('motionBtn')?.classList.toggle('active', !!(cb && cb.checked));
  }
  function onMotionToggle() {
    const cb = document.getElementById('motionToggle');
    cb.checked = !cb.checked;            // invoked from the toolbar button
    syncMotionBtn();
    state.execution.motionControlled = cb.checked;
    if (state.execution.motionControlled)
      toast('info', 'Motion Control on — when the execution finishes it plays backward, retracing the camera and any controller axis inputs to their starting positions so you can film a clean plate of the same move.');
    else
      toast('info', 'Motion Control off — the camera stays where the execution ends.');
  }

  function onNewExecution() {
    state.execution = { format:'dgtexec', schema:1, name:'Untitled Execution', motionControlled:false, motionKeyMap:defaultMotionKeyMap(), timeline:[] };
    setExecNameLabel(state.execution.name);
    document.getElementById('motionToggle').checked = false;
    syncMotionBtn();
    TL.layers = 1; selectedClipId = null;
    render();
    toast('info', 'New execution started.');
  }

  async function onSaveExecution() {
    // Always let the user choose a name; saving under an existing name overwrites it.
    const name = await nativePrompt({
      title:'Save Execution', tbLabel:'Save Execution',
      message:'Choose a name for this execution (saving over an existing name overwrites it):',
      placeholder:'Execution name', default: state.execution.name || 'Untitled Execution', confirmLabel:'Save',
    });
    if (name === null) return;
    state.execution.name = name || 'Untitled Execution';
    setExecNameLabel(state.execution.name);
    try {
      const r = await bridge({ action:'dgt_save_execution', name: state.execution.name, data: state.execution });
      state.execution.ref = r.ref;
      toast('ok', `Saved execution “${r.name}”.`);
    } catch (e) { toast('err', e.message); }
  }

  async function onDeleteExecution() {
    let list;
    try { list = await bridge({ action:'dgt_list_executions' }); } catch (e) { return toast('err', e.message); }
    if (!list.length) return toast('info', 'No saved executions to delete.');
    const ref = await nativePick({
      title:'Delete Execution', tbLabel:'Delete Execution', message:'Choose an execution to delete:',
      confirmLabel:'Continue…',
      options: list.map(x => ({ value:x.ref, label:`${x.name} (${x.items} item${x.items===1?'':'s'})` })),
    });
    if (!ref) return;
    const meta = list.find(x => x.ref === ref);
    const ok = await nativeConfirm({
      title:'Delete execution?', tbLabel:'Delete Execution',
      message:`“${meta ? meta.name : ref}” will be permanently deleted. This can’t be undone.`,
      confirmLabel:'Delete', danger:true,
    });
    if (!ok) return;
    try {
      await bridge({ action:'dgt_delete_execution', ref });
      if (state.execution.ref === ref) state.execution.ref = undefined;
      toast('ok', 'Execution deleted.');
    } catch (e) { toast('err', e.message); }
  }

  async function onOpenExecution() {
    let list;
    try { list = await bridge({ action:'dgt_list_executions' }); } catch (e) { return toast('err', e.message); }
    if (!list.length) return toast('info', 'No saved executions yet.');
    const ref = await nativePick({
      title:'Open Execution', tbLabel:'Open Execution', message:'Choose a saved execution:',
      confirmLabel:'Open',
      options: list.map(x => ({ value:x.ref, label:`${x.name} (${x.items} item${x.items===1?'':'s'})` })),
    });
    if (!ref) return;
    try {
      const data = await bridge({ action:'dgt_load_execution', ref });
      loadExecutionData(data);
      state.execution.ref = ref;
      toast('ok', `Opened “${data.name}”.`);
    } catch (e) { toast('err', e.message); }
  }

  function loadExecutionData(data) {
    state.execution = Object.assign({ timeline:[] }, data);
    ensureMotionKeyMap();
    TL.layers = 1; selectedClipId = null;
    migrateTimeline();                       // give legacy items clip fields + size layers
    setExecNameLabel(state.execution.name || 'Untitled Execution');
    document.getElementById('motionToggle').checked = !!state.execution.motionControlled;
    syncMotionBtn();
    render();
  }

  async function onExportExecution() {
    try {
      const r = await bridge({ action:'dgt_export_execution', data: state.execution });
      if (r.cancelled) return;
      toast('ok', 'Exported execution.');
    } catch (e) { toast('err', e.message); }
  }

  /* ───────────────────────── Macro list ops ───────────────────────── */
  async function refreshMacros() {
    try {
      state.macros = await bridge({ action:'dgt_list_macros' });
      renderActionList();
    } catch (e) { /* backend may be warming up */ }
  }
  async function exportMacro(ref) {
    try { const r = await bridge({ action:'dgt_export_macro', ref, kind:'macro' }); if (!r.cancelled) toast('ok', 'Macro exported.'); }
    catch (e) { toast('err', e.message); }
  }
  async function deleteMacro(ref, name) {
    const ok = await nativeConfirm({
      title:'Delete macro?', tbLabel:'Delete Macro',
      message:`“${name}” will be permanently deleted. This can’t be undone.`,
      confirmLabel:'Delete', danger:true,
    });
    if (!ok) return;
    try { await bridge({ action:'dgt_delete_macro', ref }); toast('ok', 'Macro deleted.'); refreshMacros(); }
    catch (e) { toast('err', e.message); }
  }
  async function onImportMacro() {
    try { const r = await bridge({ action:'dgt_import_macro' }); if (r.cancelled) return; toast('ok', `Imported “${r.name}”.`); refreshMacros(); }
    catch (e) { toast('err', e.message); }
  }

  /* ───────────────────────── Themes ───────────────────────── */
  function applyTheme(theme) {
    const style = document.getElementById('activeThemeStyle');
    if (style) style.textContent = (theme && theme.css) || '';
    document.documentElement.dataset.theme = (theme && theme.id) || 'default';
  }

  async function loadActiveTheme() {
    try { applyTheme(await bridge({ action:'dgt_active_theme' })); }
    catch (_e) { applyTheme(null); }
  }

  async function onImportTheme() {
    try {
      const r = await bridge({ action:'dgt_import_theme' });
      if (r.cancelled) return;
      await loadActiveTheme();
      toast('ok', `Imported theme “${r.name}”.`);
      openThemeManager();
    } catch (e) { toast('err', e.message); }
  }

  async function openThemeManager() {
    let themes = [];
    let active = {};
    try {
      themes = await bridge({ action:'dgt_list_themes' });
      active = await bridge({ action:'dgt_active_theme' });
    } catch (e) { return toast('err', e.message); }
    const activeId = active.id || '';
    const rows = [{ id:'', name:'Default', description:'Use DigiTek Lab built-in styling.', builtin:true, active:!activeId }].concat(themes);
    openParamModal({
      title:'Manage Themes', icon:'palette', hideOk:true, customWide:true,
      render: (body) => {
        const wrap = document.createElement('div');
        wrap.className = 'plugin-manager';
        wrap.innerHTML = rows.map(t => `
          <div class="plugin-card">
            <div class="plugin-card-icon"><span class="material-symbols-outlined">${t.active || t.id === activeId ? 'radio_button_checked' : 'palette'}</span></div>
            <div>
              <div class="plugin-name">${escapeHtml(t.name || t.id)}</div>
              <div class="plugin-meta">${escapeHtml([t.builtin ? 'Built in' : 'Installed theme', t.description || ''].filter(Boolean).join(' · '))}</div>
            </div>
            <div class="plugin-actions">
              <button class="al-mini ${t.active || t.id === activeId ? 'success' : ''}" title="Apply theme" onclick="setTheme('${escapeHtml(t.id)}')"><span class="material-symbols-outlined">check</span></button>
              ${t.builtin ? '' : `<button class="al-mini danger" title="Remove theme" onclick="removeTheme('${escapeHtml(t.id)}', decodeURIComponent('${encodeURIComponent(t.name || t.id)}'))"><span class="material-symbols-outlined">delete</span></button>`}
            </div>
          </div>
        `).join('');
        body.appendChild(wrap);
      },
    });
  }

  async function setTheme(themeId) {
    try {
      const theme = await bridge({ action:'dgt_set_theme', themeId });
      applyTheme(theme);
      toast('ok', theme.id ? `Applied “${theme.name}”.` : 'Applied default theme.');
      openThemeManager();
    } catch (e) { toast('err', e.message); }
  }

  async function removeTheme(themeId, name) {
    const ok = await nativeConfirm({
      title:'Remove theme?', tbLabel:'Remove Theme',
      message:`“${name}” will be removed from DigiTek Lab.`,
      confirmLabel:'Remove', danger:true,
    });
    if (!ok) return;
    try {
      await bridge({ action:'dgt_remove_theme', themeId });
      await loadActiveTheme();
      toast('ok', 'Theme removed.');
      openThemeManager();
    } catch (e) { toast('err', e.message); }
  }

  /* ───────────────────────── Plugins ───────────────────────── */
  async function onImportPlugin() {
    const progress = openPluginInstallProgress('Importing Plugin', 'Waiting for file selection...');
    try {
      progress.set(18, 'Selecting plugin package...');
      const r = await bridge({ action:'dgt_import_plugin' });
      progress.done();
      if (r.cancelled) return;
      toast('ok', `Imported plugin “${r.name}”.`);
      refreshPinnedPlugins();
      openPluginManager();
    } catch (e) {
      progress.fail(e.message);
      toast('err', e.message);
    }
  }

  async function openPluginsFolder() {
    try {
      const r = await bridge({ action:'dgt_open_plugins_folder' });
      toast('ok', `Opened plugins folder: ${r.path}`);
    } catch (e) { toast('err', e.message); }
  }

  async function openPluginManager() {
    let plugins = [];
    let updates = {};
    try { plugins = await bridge({ action:'dgt_list_plugins' }); }
    catch (e) { return toast('err', e.message); }
    try { updates = await bridge({ action:'dgt_plugin_update_status' }); }
    catch (_e) { updates = {}; }
    const pinned = new Set(await fetchPinnedPluginIds());
    openParamModal({
      title:'Manage Plugins', icon:'extension', hideOk:true, customWide:true,
      render: (body) => {
        const wrap = document.createElement('div');
        wrap.className = 'plugin-manager';
        if (!plugins.length) {
          wrap.innerHTML = '<div class="plugin-empty">No plugins installed yet.</div>';
        } else {
          wrap.innerHTML = plugins.map(p => `
            <div class="plugin-card">
              <div class="plugin-card-icon">${pluginIconHtml(p)}</div>
              <div>
                <div class="plugin-name">${escapeHtml(p.name || p.id)}</div>
                <div class="plugin-meta">${escapeHtml(pluginMetaText(p, updates[p.id]))}</div>
              </div>
              <div class="plugin-actions">
                <button class="al-mini ${pinned.has(p.id) ? 'success' : ''}" title="${pinned.has(p.id) ? 'Unpin from toolbar' : 'Pin to toolbar'}" onclick="togglePluginPin('${escapeHtml(p.id)}')"><span class="material-symbols-outlined">${pinned.has(p.id) ? 'keep_off' : 'keep'}</span></button>
                ${updates[p.id] && updates[p.id].updateAvailable ? `<button class="al-mini success" title="Update plugin" onclick="updateInstalledPlugin('${escapeHtml(p.id)}', 'manager')"><span class="material-symbols-outlined">upgrade</span></button>` : ''}
                <button class="al-mini" title="Open plugin" onclick="openInstalledPlugin('${escapeHtml(p.id)}')"><span class="material-symbols-outlined">open_in_new</span></button>
                <button class="al-mini danger" title="Remove plugin" onclick="removeInstalledPlugin('${escapeHtml(p.id)}', decodeURIComponent('${encodeURIComponent(p.name || p.id)}'), 'manager')"><span class="material-symbols-outlined">delete</span></button>
              </div>
            </div>`).join('');
        }
        body.appendChild(wrap);
      },
    });
  }

  async function openPluginMarketplace(refreshed) {
    let plugins = [];
    try { plugins = await bridge({ action:'dgt_marketplace_plugins' }); }
    catch (e) { return toast('err', e.message); }
    if (refreshed) toast('ok', 'Plugin marketplace refreshed.');
    openParamModal({
      title:'Plugin Marketplace', icon:'storefront', hideOk:true, customWide:true,
      render: (body) => {
        const shell = document.createElement('div');
        shell.className = 'plugin-marketplace-shell';
        const header = document.createElement('div');
        header.className = 'plugin-marketplace-tools';
        header.innerHTML = `
          <div class="plugin-marketplace-count">${plugins.length} plugin${plugins.length === 1 ? '' : 's'}</div>
          <button class="al-mini" title="Refresh marketplace" onclick="openPluginMarketplace(true)">
            <span class="material-symbols-outlined">refresh</span>
          </button>`;
        const wrap = document.createElement('div');
        wrap.className = 'plugin-manager';
        if (!plugins.length) {
          wrap.innerHTML = '<div class="plugin-empty">Marketplace is empty.</div>';
        } else {
          wrap.innerHTML = plugins.map(p => `
            <div class="plugin-card">
              <div class="plugin-card-icon"><span class="material-symbols-outlined">extension</span></div>
              <div>
                <div class="plugin-name">${escapeHtml(p.name || p.id)}</div>
                <div class="plugin-meta">${escapeHtml(marketplaceMetaText(p))}</div>
              </div>
              <div class="plugin-actions">
                <button class="GTextBtn ${p.installed && !p.updateAvailable ? 'danger' : 'primary'}" onclick="${p.updateAvailable ? 'updateInstalledPlugin' : p.installed ? 'removeInstalledPlugin' : 'installMarketplacePlugin'}('${escapeHtml(p.id)}'${p.updateAvailable ? ", 'marketplace'" : p.installed ? `, decodeURIComponent('${encodeURIComponent(p.name || p.id)}'), 'marketplace'` : ''})">
                  <span class="material-symbols-outlined">${p.updateAvailable ? 'upgrade' : p.installed ? 'delete' : 'download'}</span>${p.updateAvailable ? 'Update' : p.installed ? 'Uninstall' : 'Install'}
                </button>
              </div>
            </div>`).join('');
        }
        shell.appendChild(header);
        shell.appendChild(wrap);
        body.appendChild(shell);
      },
    });
  }

  async function installMarketplacePlugin(pluginId) {
    const progress = openPluginInstallProgress('Installing Plugin', 'Downloading plugin package...');
    try {
      progress.set(24, 'Downloading plugin package...');
      const r = await bridge({ action:'dgt_install_marketplace_plugin', pluginId });
      progress.done('Plugin installed.');
      toast('ok', `Installed “${r.name}”.`);
      await refreshPinnedPlugins();
      openPluginMarketplace();
    } catch (e) {
      progress.fail(e.message);
      toast('err', e.message);
    }
  }

  async function updateInstalledPlugin(pluginId, refreshView) {
    const progress = openPluginInstallProgress('Updating Plugin', 'Downloading latest plugin package...');
    try {
      progress.set(24, 'Downloading latest plugin package...');
      const r = await bridge({ action:'dgt_update_plugin', pluginId });
      progress.done('Plugin updated.');
      toast('ok', `Updated “${r.name}” to v${r.version}.`);
      await refreshPinnedPlugins();
      if (refreshView === 'marketplace') openPluginMarketplace();
      else if (refreshView !== false) openPluginManager();
    } catch (e) {
      progress.fail(e.message);
      toast('err', e.message);
    }
  }

  function openPluginInstallProgress(title, message) {
    let pct = 8;
    let stopped = false;
    openParamModal({
      title, icon:'download', hideOk:true, customWide:false,
      render: (body) => {
        body.innerHTML = `
          <div class="plugin-install-progress">
            <div class="support-phase">
              <span id="pluginInstallPhase">${escapeHtml(message || 'Preparing...')}</span>
            </div>
            <div class="support-progress"><div class="support-progress-fill" id="pluginInstallFill" style="width:${pct}%"></div></div>
          </div>`;
      },
    });
    const update = (value, text, detail) => {
      pct = Math.max(0, Math.min(100, Math.round(value)));
      const fill = document.getElementById('pluginInstallFill');
      const phase = document.getElementById('pluginInstallPhase');
      if (fill) fill.style.width = pct + '%';
      if (phase && text) phase.textContent = text;
    };
    const timer = setInterval(() => {
      if (stopped) return;
      const next = pct < 38 ? pct + 4 : pct < 74 ? pct + 2 : pct < 92 ? pct + 1 : pct;
      const label = next < 36 ? 'Downloading plugin package...' : next < 72 ? 'Checking Python and requirements...' : 'Installing required packages...';
      update(next, label);
    }, 420);
    return {
      set: update,
      done(text) {
        stopped = true;
        clearInterval(timer);
        update(100, text || 'Complete.', 'Finished.');
        setTimeout(() => closeAppModal(), 450);
      },
      fail(text) {
        stopped = true;
        clearInterval(timer);
        update(100, 'Installation failed.', text || 'Unable to install plugin.');
      },
    };
  }

  function pluginMetaText(plugin, update) {
    const base = [plugin.version ? 'v' + plugin.version : '', plugin.author || '', plugin.description || ''].filter(Boolean);
    if (update && update.updateAvailable) base.unshift(`Update available: v${update.latestVersion}`);
    return base.join(' · ');
  }

  function marketplaceMetaText(plugin) {
    const base = [plugin.version ? 'v' + plugin.version : '', plugin.author || '', plugin.category || plugin.topic || '', plugin.description || ''].filter(Boolean);
    if (plugin.updateAvailable) base.unshift(`Installed v${plugin.installedVersion}`);
    return base.join(' · ');
  }

  async function removeInstalledPlugin(pluginId, name, refreshView) {
    const ok = await nativeConfirm({
      title:'Remove plugin?', tbLabel:'Remove Plugin',
      message:`“${name}” will be removed from DigiTek Lab. You can import it again later.`,
      confirmLabel:'Remove', danger:true,
    });
    if (!ok) return;
    try {
      await bridge({ action:'dgt_remove_plugin', pluginId });
      await refreshPinnedPlugins();
      toast('ok', 'Plugin removed.');
      if (refreshView === 'marketplace') openPluginMarketplace();
      else if (refreshView !== false) openPluginManager();
    } catch (e) { toast('err', e.message); }
  }

  function normalizePinnedPluginIds(ids) {
    const seen = new Set();
    return (ids || []).map(id => String(id || '').trim().toLowerCase()).filter(id => {
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  function loadPinnedPluginIds() {
    try {
      const raw = localStorage.getItem(PINNED_PLUGINS_KEY);
      const ids = JSON.parse(raw || '[]');
      state.pinnedPluginIds = Array.isArray(ids) ? normalizePinnedPluginIds(ids) : [];
    } catch (_e) {
      state.pinnedPluginIds = [];
    }
    return state.pinnedPluginIds;
  }

  async function fetchPinnedPluginIds() {
    try {
      const ids = await bridge({ action:'dgt_get_pinned_plugins' });
      state.pinnedPluginIds = normalizePinnedPluginIds(ids);
      try { localStorage.setItem(PINNED_PLUGINS_KEY, JSON.stringify(state.pinnedPluginIds)); } catch (_e) {}
      return state.pinnedPluginIds;
    } catch (_e) {
      return loadPinnedPluginIds();
    }
  }

  async function savePinnedPluginIds(ids) {
    state.pinnedPluginIds = normalizePinnedPluginIds(ids);
    try { localStorage.setItem(PINNED_PLUGINS_KEY, JSON.stringify(state.pinnedPluginIds)); } catch (_e) {}
    try { state.pinnedPluginIds = normalizePinnedPluginIds(await bridge({ action:'dgt_set_pinned_plugins', pluginIds: state.pinnedPluginIds })); }
    catch (_e) {}
    return state.pinnedPluginIds;
  }

  async function unpinPluginId(pluginId) {
    const id = String(pluginId || '');
    await savePinnedPluginIds((await fetchPinnedPluginIds()).filter(p => p !== id));
  }

  async function togglePluginPin(pluginId) {
    const id = String(pluginId || '').trim().toLowerCase();
    if (!id) return;
    const ids = await fetchPinnedPluginIds();
    if (ids.includes(id)) {
      await savePinnedPluginIds(ids.filter(p => p !== id));
      toast('ok', 'Plugin unpinned.');
    } else {
      await savePinnedPluginIds(ids.concat(id));
      toast('ok', 'Plugin pinned to toolbar.');
    }
    await refreshPinnedPlugins();
    openPluginManager();
  }

  function pluginIconHtml(plugin) {
    if (plugin && plugin.iconDataUri) {
      return `<img src="${escapeHtml(plugin.iconDataUri)}" alt="">`;
    }
    return '<span class="material-symbols-outlined">extension</span>';
  }

  async function refreshPinnedPlugins() {
    const wrap = document.getElementById('pinnedPlugins');
    const divider = document.getElementById('pluginPinDivider');
    if (!wrap) return;
    const ids = await fetchPinnedPluginIds();
    if (!ids.length) {
      wrap.innerHTML = '';
      if (divider) divider.hidden = true;
      return;
    }
    let plugins = [];
    try { plugins = await bridge({ action:'dgt_list_plugins' }); }
    catch (_e) {
      wrap.innerHTML = '';
      if (divider) divider.hidden = true;
      return;
    }
    const byId = new Map(plugins.map(p => [p.id, p]));
    const validIds = ids.filter(id => byId.has(id));
    const pinned = validIds.map(id => byId.get(id));
    wrap.innerHTML = pinned.map(p => `
      <button class="ToolBtn plugin-pin" title="${escapeHtml(p.name || p.id)}" onclick="openInstalledPlugin('${escapeHtml(p.id)}')">
        ${pluginIconHtml(p)}
      </button>
    `).join('');
    if (divider) divider.hidden = !pinned.length;
  }

  async function openInstalledPlugin(pluginId) {
    const canOpen = await promptPluginUpdateIfNeeded(pluginId);
    if (!canOpen) return;
    let loaded;
    try {
      await bridge({ action:'dgt_clear_plugin_cache', pluginId });
      loaded = await bridge({ action:'dgt_load_plugin_ui', pluginId });
    }
    catch (e) { return toast('err', e.message); }
    const plugin = loaded.plugin || { id:pluginId, name:pluginId };
    plugin.cacheBust = loaded.cacheBust || Date.now();
    if (openNativePluginWindow(plugin, loaded.html || '')) return;
    openPluginPopupFallback(plugin, loaded.html || '');
  }

  async function promptPluginUpdateIfNeeded(pluginId) {
    let status = null;
    try { status = await bridge({ action:'dgt_plugin_update_status', pluginId }); }
    catch (_e) { return true; }
    if (!status || !status.updateAvailable) return true;
    const ok = await nativeConfirm({
      title:'Plugin update available',
      tbLabel:'Update Plugin',
      message:`${status.name || pluginId} has an update available (${status.installedVersion || 'installed'} -> ${status.latestVersion}). Update before opening?`,
      confirmLabel:'Update',
    });
    if (!ok) return true;
    try {
      const r = await bridge({ action:'dgt_update_plugin', pluginId });
      toast('ok', `Updated “${r.name}” to v${r.version}.`);
      await refreshPinnedPlugins();
      return true;
    } catch (e) {
      toast('err', e.message);
      return false;
    }
  }

  function openNativePluginWindow(plugin, html) {
    const payload = {
      pluginId: plugin.id,
      plugin,
      windowTitle: plugin.name || plugin.id || 'Plugin',
      windowIconPath: plugin.iconPath || '',
      cacheBust: plugin.cacheBust || Date.now(),
      htmlBase64: encodePluginHtml(html),
    };
    if (typeof window._openModalSetPayload === 'function' && typeof window._openModalNative === 'function') {
      window._openModalSetPayload(payload);
      window._openModalNative('plugin');
      return true;
    }
    return false;
  }

  function encodePluginHtml(html) {
    return btoa(unescape(encodeURIComponent(html || '')));
  }

  function openPluginPopupFallback(plugin, html) {
    const popup = window.open('', 'dgt_plugin_' + plugin.id, 'width=385,height=536,resizable=no,scrollbars=no');
    if (!popup) {
      toast('err', 'Plugin window was blocked by the browser.');
      return;
    }
    popup.document.open();
    popup.document.write(injectPluginPopupBridge(html, plugin.id));
    popup.document.close();
    popup.document.title = plugin.name || plugin.id;
  }

  function injectPluginPopupBridge(html, pluginId) {
    const boot = `<script>
      document.addEventListener('contextmenu', event => event.preventDefault());
      document.addEventListener('keydown', event => {
        const key = String(event.key || '').toLowerCase();
        const blocked = key === 'f12' || (event.ctrlKey && event.shiftKey && ['i', 'j', 'c'].includes(key));
        if (blocked) {
          event.preventDefault();
          event.stopPropagation();
        }
      }, true);
      window.DIGITEK_PLUGIN_ID = ${JSON.stringify(pluginId)};
      window.pluginInvoke = function(payload) {
        if (!window.opener || !window.opener.__dgtPluginBridge) {
          return Promise.reject(new Error('DigiTek plugin bridge is unavailable.'));
        }
        return window.opener.__dgtPluginBridge(${JSON.stringify(pluginId)}, payload || {});
      };
    <\/script>`;
    return /<head[^>]*>/i.test(html)
      ? html.replace(/<head[^>]*>/i, m => m + boot)
      : boot + html;
  }

  window.__dgtPluginBridge = async function(pluginId, payload) {
    const result = await bridge({ action:'dgt_plugin_call', pluginId, payload });
    return unwrapPluginResult(result);
  };

  function unwrapPluginResult(result) {
    if (typeof result !== 'string') return result;
    try {
      const parsed = JSON.parse(result);
      if (parsed && parsed.status === 'error') throw new Error(parsed.reason || 'Plugin backend error');
      if (parsed && parsed.status === 'ok') return parsed.result;
    } catch (err) {
      if (err && err.message !== result) throw err;
    }
    return result;
  }

  /* ───────────────────────── Toast ───────────────────────── */
  function toast(kind, text) {
    const wrap = document.getElementById('toastWrap');
    const el = document.createElement('div');
    el.className = 'toast ' + kind;
    const icon = kind==='ok'?'check_circle':kind==='err'?'error':'info';
    el.innerHTML = `<span class="material-symbols-outlined">${icon}</span><span>${escapeHtml(text)}</span>`;
    wrap.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; setTimeout(()=>el.remove(), 250); }, 3200);
  }

  function openTutorial() {
    openParamModal({
      title:'Tutorial', icon:'smart_display', hideOk:true, customWide:true,
      render: (body) => {
        const video = document.createElement('video');
        video.className = 'tutorial-video';
        video.controls = true;
        video.preload = 'metadata';
        video.src = '../assets/tutorial.mp4';
        video.onerror = () => {
          body.innerHTML = '<div class="tutorial-missing">Tutorial video not found.<br>Place it at <code>ui/assets/tutorial.mp4</code>.</div>';
        };
        body.appendChild(video);
      },
    });
  }

  window.addEventListener('resize', () => { renderTimeline(); });

  /* ───────────────────────── Boot ───────────────────────── */
  async function boot() {
    await loadActiveTheme();
    setExecNameLabel(state.execution.name);
    syncMotionBtn();
    render();
    // appInfo may need a moment while the Python backend warms up.
    for (let i = 0; i < 25; i++) {
      try { state.appInfo = await bridge({ action:'dgt_app_info' }); break; }
      catch (e) { await new Promise(r => setTimeout(r, 200)); }
    }
    if (state.appInfo) {
      const hk = state.appInfo.hotkeys || {};
      document.getElementById('hotkeyHint').textContent = `Stop rec: ${(hk.stopRecord||'F8').toUpperCase()} · Stop play: ${(hk.stopPlayback||'F9').toUpperCase()}`;
      if (!state.appInfo.inputAvailable) {
        const w = document.getElementById('inputWarning');
        document.getElementById('inputWarningText').textContent =
          (state.appInfo.inputError || 'Input backend unavailable.') + ' Recording and playback are disabled.';
        w.classList.add('show');
      }
    }
    await loadActions();
    await refreshMacros();
    await refreshPinnedPlugins();
  }

  // Keep the track-head column and ruler aligned while scrolling the lanes.
  document.getElementById('tlxScroll')?.addEventListener('scroll', syncTimelineScroll);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeAppModal(); return; }
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    // Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) → undo / redo.
    if (e.ctrlKey && !typing && (e.key === 'z' || e.key === 'Z' || e.key === 'y' || e.key === 'Y')) {
      e.preventDefault();
      if (e.key === 'y' || e.key === 'Y' || e.shiftKey) redo(); else undo();
      return;
    }
    // Ctrl + / Ctrl - → zoom the timeline.
    if (e.ctrlKey && (e.key === '=' || e.key === '+' || e.key === '-' || e.key === '_')) {
      if (typing) return;
      e.preventDefault();
      zoomTimeline((e.key === '-' || e.key === '_') ? -1 : 1);
      return;
    }
    // Delete the selected clip — ignore while typing or a modal is open.
    if (e.key === 'Delete' && selectedClipId) {
      const modalOpen = document.getElementById('modal').classList.contains('show');
      if (!modalOpen && !typing) { e.preventDefault(); removeClip(selectedClipId); }
    }
  });

  // Ctrl + mouse wheel over the timeline → zoom in/out.
  (function () {
    const sc = document.getElementById('tlxScroll');
    if (sc) sc.addEventListener('wheel', (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      zoomTimeline(e.deltaY < 0 ? 1 : -1);
    }, { passive: false });
  })();

  Object.assign(window, {
    addLayer, addMotionMapRow,
    clearKeys, closeAppModal, deleteMacro, deleteSelectedClip, exportMacro, finishRecording,
    focusAdjacentClip, installMarketplacePlugin,
    onDeleteExecution, onExportExecution, onImportMacro, onImportPlugin, onMotionToggle,
    onModalOk, onNewExecution, onOpenExecution, onPlayPause, onRecord, onSaveExecution, onStop,
    openInstalledPlugin, openMotionSettings, openPluginManager, openPluginMarketplace,
    openPluginsFolder, openThemeManager, openTutorial, pickSeg, redo, removeInstalledPlugin,
    removeMotionMapRow, removeTheme, resetMotionMapDefaults, saveMotionSettings,
    setTheme, startKeyRecord, syncCoord, toggleContinuous, togglePluginPin,
    toggleControllerSupportLog, toggleSnap, uninstallControllerSupportFlow, updateInstalledPlugin,
    undo, zoomTimeline,
  });

  window.addEventListener('DOMContentLoaded', boot);
