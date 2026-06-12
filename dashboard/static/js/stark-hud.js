/* stark-hud.js — the Stark HUD layer. Animation-first: state choreography,
   ambient lab, UI sound wiring. Driven entirely by edith:state events and the
   public window.EDITH surface — zero business logic, zero engine reads beyond
   source_freshness for the (honest) radar.
   Performance law: transforms/opacity CSS, ONE canvas here (shards+bars share
   it; edith's wave strip is hidden in Stark mode), everything pauses when the
   tab hides, ambient throttles during heavy renders. */
(function() {
  'use strict';

  function lsGet(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ── THE INTENSITY SYSTEM (Phase 5): Stark default, Focus strips back ──
  function starkOn() {
    if (reduced) return false;                       // reduced-motion → Focus
    return lsGet('edith-stark', '1') === '1';
  }
  function applyMode() {
    document.body.classList.toggle('stark-mode', starkOn());
    document.body.classList.toggle('focus-mode', !starkOn());
  }
  function toggleMode() {
    lsSet('edith-stark', starkOn() ? '0' : '1');
    applyMode();
    if (window.EDITH) window.EDITH.audio.uiConfirm();
  }
  document.addEventListener('keydown', function(e) {
    var tag = (document.activeElement || {}).tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    if (e.key === 'S' && e.shiftKey && !e.metaKey && !e.ctrlKey) toggleMode();
  });

  var hidden = false;
  document.addEventListener('visibilitychange', function() { hidden = document.hidden; });

  // ═════════════════════════════════════════════════════════
  //  PHASE 1 — THE THINKING STATE
  // ═════════════════════════════════════════════════════════

  // 1) Processing reactor: 3 counter-rotating segmented arcs around the orb
  var reactorEl = null;
  function buildReactor() {
    reactorEl = document.createElement('div');
    reactorEl.id = 'stark-reactor';
    reactorEl.className = 'stark-reactor';
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 180 180');
    // three segmented rings (dasharray = segments), built once
    [[78, '40 12', 'sr-ring sr-a'], [64, '18 9', 'sr-ring sr-b'], [50, '8 7', 'sr-ring sr-c']].forEach(function(spec) {
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', '90'); c.setAttribute('cy', '90'); c.setAttribute('r', String(spec[0]));
      c.setAttribute('fill', 'none');
      c.setAttribute('stroke-dasharray', spec[1]);
      c.setAttribute('class', spec[2]);
      svg.appendChild(c);
    });
    // tick marks ring
    for (var i = 0; i < 36; i++) {
      var t = document.createElementNS(NS, 'line');
      var a = (i / 36) * Math.PI * 2;
      var r1 = 84, r2 = i % 9 === 0 ? 74 : 80;
      t.setAttribute('x1', String(90 + Math.cos(a) * r1));
      t.setAttribute('y1', String(90 + Math.sin(a) * r1));
      t.setAttribute('x2', String(90 + Math.cos(a) * r2));
      t.setAttribute('y2', String(90 + Math.sin(a) * r2));
      t.setAttribute('class', 'sr-tick');
      svg.appendChild(t);
    }
    // orbiting bright sweep highlight
    var orbiter = document.createElementNS(NS, 'circle');
    orbiter.setAttribute('cx', '90'); orbiter.setAttribute('cy', '12'); orbiter.setAttribute('r', '3.2');
    orbiter.setAttribute('class', 'sr-orbiter');
    var orbitGroup = document.createElementNS(NS, 'g');
    orbitGroup.setAttribute('class', 'sr-orbit-group');
    orbitGroup.appendChild(orbiter);
    svg.appendChild(orbitGroup);
    reactorEl.appendChild(svg);
    document.body.appendChild(reactorEl);
  }

  // 2+SPEAKING bars) one canvas, two draw modes: data shards (thinking),
  //    vertical analyser bars (speaking)
  var fxCanvas = null, fxCtx = null, fxRAF = null, fxMode = null;
  var shards = [];
  var GLYPHS = '01▮▯·–◇△913847AFE'.split('');

  function buildCanvas() {
    fxCanvas = document.createElement('canvas');
    fxCanvas.id = 'stark-canvas';
    fxCanvas.className = 'stark-canvas';
    fxCanvas.width = 280; fxCanvas.height = 340;
    document.body.appendChild(fxCanvas);
    fxCtx = fxCanvas.getContext('2d');
  }

  function startShards() {
    if (!starkOn() || !fxCtx) return;
    fxMode = 'shards';
    fxCanvas.classList.add('show');
    shards = [];
    for (var i = 0; i < 46; i++) {
      shards.push({
        x: 60 + Math.random() * 180, y: 340 - Math.random() * 80,
        vy: 0.6 + Math.random() * 1.6, vx: (Math.random() - 0.5) * 0.7,
        g: GLYPHS[(Math.random() * GLYPHS.length) | 0],
        a: 0, life: Math.random(),
      });
    }
    runFx();
  }

  function startBars() {
    if (!starkOn() || !fxCtx) return;
    fxMode = 'bars';
    fxCanvas.classList.add('show');
    runFx();
  }

  function stopFx() {
    fxMode = null;
    if (fxRAF) cancelAnimationFrame(fxRAF);
    fxRAF = null;
    if (fxCtx) fxCtx.clearRect(0, 0, 280, 340);
    if (fxCanvas) fxCanvas.classList.remove('show');
  }

  var barBuf = new Uint8Array(64);
  function runFx() {
    if (fxRAF) cancelAnimationFrame(fxRAF);
    (function loop() {
      if (!fxMode || hidden) { if (fxMode) fxRAF = requestAnimationFrame(loop); return; }
      _perfTick();
      fxCtx.clearRect(0, 0, 280, 340);
      if (fxMode === 'shards') {
        for (var i = 0; i < shards.length; i++) {
          var s = shards[i];
          s.y -= s.vy; s.x += s.vx;
          s.life += 0.02;
          s.a = Math.max(0, Math.sin(s.life * Math.PI) * 0.85);
          if (s.y < 0 || s.a <= 0.01 && s.life > 1) {
            s.y = 340 - Math.random() * 40; s.x = 60 + Math.random() * 180;
            s.life = 0; s.g = GLYPHS[(Math.random() * GLYPHS.length) | 0];
          }
          fxCtx.globalAlpha = s.a * (0.35 + Math.random() * 0.25);  // flicker
          fxCtx.fillStyle = '#5B9BD0';
          fxCtx.font = '10px Menlo, monospace';
          fxCtx.fillText(s.g, s.x, s.y);
        }
        fxCtx.globalAlpha = 1;
      } else if (fxMode === 'bars') {
        var an = window.EDITH && window.EDITH.analyser();
        if (an) {
          an.getByteFrequencyData(barBuf);
          var n = 24;
          for (var b = 0; b < n; b++) {
            var v = barBuf[Math.floor(b * barBuf.length / n)] / 255;
            var h = 4 + v * 90;
            fxCtx.fillStyle = 'rgba(91,155,208,' + (0.35 + v * 0.55) + ')';
            fxCtx.fillRect(34 + b * 9, 330 - h, 5, h);
          }
        }
      }
      fxRAF = requestAnimationFrame(loop);
    })();
  }

  // 3) scan beam — one sweep, 600ms
  var beamEl = null;
  function scanBeam() {
    if (!starkOn()) return;
    if (!beamEl) {
      beamEl = document.createElement('div');
      beamEl.className = 'stark-beam';
      document.body.appendChild(beamEl);
    }
    beamEl.classList.remove('run');
    void beamEl.offsetWidth;   // restart the animation
    beamEl.classList.add('run');
  }

  // 4) status ticker — REAL pipeline stages only
  var tickerEl = null, tickerTimer = null, tickerStageTimer = null;
  function buildTicker() {
    tickerEl = document.createElement('div');
    tickerEl.id = 'stark-ticker';
    tickerEl.className = 'stark-ticker';
    document.body.appendChild(tickerEl);
  }
  function tickerType(text) {
    if (!tickerEl) return;
    clearInterval(tickerTimer);
    tickerEl.classList.add('show');
    var i = 0;
    tickerEl.textContent = '';
    tickerTimer = setInterval(function() {
      tickerEl.textContent = text.slice(0, ++i) + (i < text.length ? '▌' : '');
      if (i >= text.length) clearInterval(tickerTimer);
    }, 22);
  }
  function tickerHide() {
    clearInterval(tickerTimer);
    clearTimeout(tickerStageTimer);
    if (tickerEl) tickerEl.classList.remove('show');
  }

  // ── thinking state assembly/teardown ──
  var hudThinking = false;
  function enterThinking() {
    if (!starkOn()) return;
    hudThinking = true;
    document.body.classList.add('stark-thinking');
    if (reactorEl) reactorEl.classList.add('run');
    if (bigRingEl) bigRingEl.classList.add('run');
    startShards();
    scanBeam();
    tickerType('ROUTING QUERY…');                       // real: request sent
    clearTimeout(tickerStageTimer);
    tickerStageTimer = setTimeout(function() {
      if (hudThinking) tickerType('ANALYSING ENGINES…'); // real: model working
    }, 1400);
    if (window.EDITH) window.EDITH.audio.startHum();
  }
  function exitThinking() {
    hudThinking = false;
    document.body.classList.remove('stark-thinking');
    if (reactorEl) reactorEl.classList.remove('run');
    if (bigRingEl) bigRingEl.classList.remove('run');
    if (fxMode === 'shards') stopFx();
    if (window.EDITH) window.EDITH.audio.stopHum();
  }

  // ═════════════════════════════════════════════════════════
  //  PHASE 2 — LISTENING & SPEAKING CHOREOGRAPHY
  // ═════════════════════════════════════════════════════════
  var listenRAF = null, lastRingAt = 0, edgeEl = null;

  function enterListening() {
    if (!starkOn()) return;
    document.body.classList.add('stark-listening');
    if (!edgeEl) {
      edgeEl = document.createElement('div');
      edgeEl.className = 'stark-edge';
      document.body.appendChild(edgeEl);
    }
    (function loop() {
      if (!window.EDITH || window.EDITH.getState() !== 'listening' || hidden) {
        if (window.EDITH && window.EDITH.getState() === 'listening') { listenRAF = requestAnimationFrame(loop); }
        return;
      }
      _perfTick();
      var level = window.EDITH.micRMS();
      edgeEl.style.opacity = Math.min(level * 5, 0.85);
      // each voice peak emits an expanding ring from the orb
      if (level > 0.07 && performance.now() - lastRingAt > 260) {
        lastRingAt = performance.now();
        var ring = document.createElement('div');
        ring.className = 'stark-pulse-ring';
        document.body.appendChild(ring);
        setTimeout(function() { ring.remove(); }, 1100);
      }
      listenRAF = requestAnimationFrame(loop);
    })();
  }
  function exitListening() {
    document.body.classList.remove('stark-listening');
    if (listenRAF) cancelAnimationFrame(listenRAF);
    listenRAF = null;
    if (edgeEl) edgeEl.style.opacity = 0;
  }

  function enterSpeaking() {
    if (!starkOn()) return;
    document.body.classList.add('stark-speaking');
    startBars();
  }
  function exitSpeaking() {
    document.body.classList.remove('stark-speaking');
    if (fxMode === 'bars') stopFx();
    if (window.EDITH) window.EDITH.audio.uiComplete();
  }

  // ═════════════════════════════════════════════════════════
  //  PHASE 3 — AMBIENT HUD (always-on in Stark)
  // ═════════════════════════════════════════════════════════

  // 2) systems radar: real engines, freshness-honest blips
  var radarEl = null;
  var RADAR_ENGINES = [
    { key: 'CASH', src: 'xero' }, { key: 'MRR', src: 'sheets' },
    { key: 'FUNNEL', src: 'sales' }, { key: 'TEAM', src: 'team_roster' },
    { key: 'PIPELINE', src: 'ghl' },
  ];
  function buildRadar() {
    radarEl = document.createElement('div');
    radarEl.id = 'stark-radar';
    radarEl.className = 'stark-radar';
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 120 120');
    [54, 38, 22].forEach(function(r) {
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', '60'); c.setAttribute('cy', '60'); c.setAttribute('r', String(r));
      c.setAttribute('class', 'radar-ring');
      svg.appendChild(c);
    });
    var sweep = document.createElementNS(NS, 'path');
    sweep.setAttribute('d', 'M60,60 L60,6 A54,54 0 0,1 88,12 Z');
    sweep.setAttribute('class', 'radar-sweep');
    svg.appendChild(sweep);
    RADAR_ENGINES.forEach(function(eng, i) {
      var a = (i / RADAR_ENGINES.length) * Math.PI * 2 - Math.PI / 2;
      var b = document.createElementNS(NS, 'circle');
      b.setAttribute('cx', String(60 + Math.cos(a) * 40));
      b.setAttribute('cy', String(60 + Math.sin(a) * 40));
      b.setAttribute('r', '3');
      b.setAttribute('class', 'radar-blip');
      b.dataset.engine = eng.key;
      var title = document.createElementNS(NS, 'title');
      title.textContent = eng.key;
      b.appendChild(title);
      svg.appendChild(b);
    });
    radarEl.appendChild(svg);
    document.body.appendChild(radarEl);
    refreshRadar();
  }
  function refreshRadar() {
    if (!radarEl) return;
    var snap = window.__CURRENT_SNAP__ || window.__SNAP__ || {};
    var fresh = snap.source_freshness || {};
    radarEl.querySelectorAll('.radar-blip').forEach(function(b) {
      var eng = RADAR_ENGINES.find(function(x) { return x.key === b.dataset.engine; });
      var ts = eng && fresh[eng.src];
      b.classList.toggle('stale', !ts);
      var t = b.querySelector('title');
      if (t) t.textContent = b.dataset.engine + (ts ? ' · updated ' + String(ts).slice(0, 16).replace('T', ' ') : ' · no data');
    });
  }

  // 3) grid whisper with scroll parallax
  var gridEl = null, scrollRAF = null;
  function buildGrid() {
    gridEl = document.createElement('div');
    gridEl.className = 'stark-grid';
    document.body.appendChild(gridEl);
    var pending = false;
    window.addEventListener('scroll', function() {
      if (pending || !starkOn()) return;
      pending = true;
      scrollRAF = requestAnimationFrame(function() {
        pending = false;
        if (gridEl) gridEl.style.transform = 'translateY(' + (window.scrollY * -0.04) + 'px)';
      });
    }, { passive: true });
  }

  // 4) periodic sweep every ~25s
  setInterval(function() {
    if (!starkOn() || hidden) return;
    var st = window.EDITH && window.EDITH.getState();
    if (st === 'idle' || st === 'listening') scanBeam();
  }, 25000);

  // 6) transitions: nav sweep, window-toggle reprojection, refresh radial
  function wireTransitions() {
    document.addEventListener('click', function(e) {
      var nav = e.target.closest && e.target.closest('.nav-link');
      if (nav && starkOn()) {
        scanBeam();
        if (window.EDITH) window.EDITH.audio.uiTick();
        return;
      }
      var winBtn = e.target.closest && e.target.closest('.global-window-btn, .window-tab');
      if (winBtn && starkOn()) {
        var main = document.getElementById('main');
        if (main) {
          main.classList.remove('stark-reproject');
          void main.offsetWidth;
          main.classList.add('stark-reproject');
          setTimeout(function() { main.classList.remove('stark-reproject'); }, 700);
        }
        if (window.EDITH) window.EDITH.audio.uiConfirm();
        return;
      }
      var refresh = e.target.closest && e.target.closest('#btn-refresh');
      if (refresh && starkOn()) {
        var radial = document.createElement('div');
        radial.className = 'stark-radial';
        document.body.appendChild(radial);
        setTimeout(function() { radial.remove(); }, 900);
      }
    }, true);

    // hover ticks: nav + primary buttons only, felt not heard
    document.addEventListener('mouseover', function(e) {
      if (!starkOn()) return;
      var t = e.target.closest && e.target.closest('.nav-link, .icon-btn');
      if (t && !t._tickedAt || (t && performance.now() - t._tickedAt > 400)) {
        if (t) { t._tickedAt = performance.now(); window.EDITH && window.EDITH.audio.uiTick(); }
      }
    }, true);
  }

  // 5) card life on data refresh
  window.addEventListener('edith:data', function() {
    refreshRadar();
    if (!starkOn()) return;
    document.querySelectorAll('.panel, .kpi-strip').forEach(function(p, i) {
      if (i > 24) return;
      p.classList.remove('data-pulse');
      void p.offsetWidth;
      p.classList.add('data-pulse');
    });
    setTimeout(function() {
      document.querySelectorAll('.data-pulse').forEach(function(p) { p.classList.remove('data-pulse'); });
    }, 1400);
  });

  // ═════════════════════════════════════════════════════════
  //  STATE ROUTER
  // ═════════════════════════════════════════════════════════
  window.addEventListener('edith:state', function(e) {
    var from = e.detail.from, to = e.detail.to;
    if (from === 'thinking') exitThinking();
    if (from === 'listening') exitListening();
    if (from === 'speaking') exitSpeaking();
    if (to === 'thinking') enterThinking();
    if (to === 'listening') enterListening();
    if (to === 'speaking') { exitThinking(); enterSpeaking(); }
  });

  // typed chat drives the same choreography (voice OR text — the spec's law)
  window.addEventListener('edith:chat', function(e) {
    var st = window.EDITH && window.EDITH.getState();
    if (e.detail.phase === 'sent' && (st === 'idle' || !st)) enterThinking();
    if (e.detail.phase === 'reply') exitThinking();
    if (e.detail.phase === 'error') { exitThinking(); window.EDITH && window.EDITH.audio.uiError(); }
  });

  window.addEventListener('edith:tts', function(e) {
    if (e.detail.phase === 'synth') tickerType('VOCALISING…');   // real: TTS request out
    if (e.detail.phase === 'playing') tickerHide();              // real: audio arriving
  });

  // ═════════════════════════════════════════════════════════
  //  PERF SAMPLER (Phase 5/6): frame times during animated states
  // ═════════════════════════════════════════════════════════
  var _frames = [];
  var _lastFrame = 0;
  function _perfTick() {
    var now = performance.now();
    if (_lastFrame) {
      _frames.push(now - _lastFrame);
      if (_frames.length > 600) _frames.shift();
    }
    _lastFrame = now;
  }
  window.__STARK_PERF__ = function() {
    if (!_frames.length) return null;
    var sorted = _frames.slice().sort(function(a, b) { return a - b; });
    var avg = _frames.reduce(function(a, b) { return a + b; }, 0) / _frames.length;
    return {
      samples: _frames.length,
      avg_ms: Math.round(avg * 100) / 100,
      p95_ms: Math.round(sorted[Math.floor(sorted.length * 0.95)] * 100) / 100,
      approx_fps: Math.round(1000 / avg),
    };
  };

  // the full-frame computing ring: large, centered, behind content
  var bigRingEl = null;
  function buildBigRing() {
    bigRingEl = document.createElement('div');
    bigRingEl.id = 'stark-bigring';
    bigRingEl.className = 'stark-bigring';
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 480 480');
    [[222, '90 28', 'sbr-a'], [196, '40 18', 'sbr-b'], [160, '14 11', 'sbr-c']].forEach(function(spec) {
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', '240'); c.setAttribute('cy', '240'); c.setAttribute('r', String(spec[0]));
      c.setAttribute('fill', 'none');
      c.setAttribute('stroke-dasharray', spec[1]);
      c.setAttribute('class', 'sbr-ring ' + spec[2]);
      svg.appendChild(c);
    });
    for (var i = 0; i < 48; i++) {
      var t = document.createElementNS(NS, 'line');
      var a = (i / 48) * Math.PI * 2;
      t.setAttribute('x1', String(240 + Math.cos(a) * 234));
      t.setAttribute('y1', String(240 + Math.sin(a) * 234));
      t.setAttribute('x2', String(240 + Math.cos(a) * (i % 12 === 0 ? 224 : 229)));
      t.setAttribute('y2', String(240 + Math.sin(a) * (i % 12 === 0 ? 224 : 229)));
      t.setAttribute('class', 'sbr-tick');
      svg.appendChild(t);
    }
    bigRingEl.appendChild(svg);
    document.body.appendChild(bigRingEl);
  }

  // header data-stream: constant subtle motion saying "live system"
  function buildHeaderStream() {
    var el = document.createElement('div');
    el.className = 'stark-header-stream';
    document.body.appendChild(el);
  }

  // ── init ─────────────────────────────────────────────────
  applyMode();
  buildBigRing();
  buildHeaderStream();
  buildReactor();
  buildCanvas();
  buildTicker();
  buildRadar();
  buildGrid();
  wireTransitions();
})();
