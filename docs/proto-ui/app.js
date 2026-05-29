/* ═══════════════════════════════════════════════════════════════════════
   DroneTraffic Platform — Shared Runtime
   Theme switcher · Debug overlay · Simulated WebSocket data feed
   ═══════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  /* ─── Theme Switcher ─── */
  var THEME_KEY = 'dronetraffic:theme';

  function getTheme() {
    try { return localStorage.getItem(THEME_KEY) || 'cto'; } catch (_) { return 'cto'; }
  }

  function setTheme(t) {
    try { localStorage.setItem(THEME_KEY, t); } catch (_) {}
    applyTheme(t);
  }

  function applyTheme(t) {
    var html = document.documentElement;
    if (t === 'police') {
      html.setAttribute('data-theme', 'police');
    } else {
      html.removeAttribute('data-theme');
    }
    // Update all theme toggle buttons
    var btns = document.querySelectorAll('.theme-toggle');
    for (var i = 0; i < btns.length; i++) {
      var icon = btns[i].querySelector('.theme-icon');
      var label = btns[i].querySelector('.theme-label');
      if (t === 'police') {
        if (icon) icon.textContent = '🚦';
        if (label) label.textContent = '交警模式';
      } else {
        if (icon) icon.textContent = '⚡';
        if (label) label.textContent = 'CTO 模式';
      }
    }
  }

  function toggleTheme() {
    var current = getTheme();
    setTheme(current === 'police' ? 'cto' : 'police');
  }

  // Apply theme on load
  applyTheme(getTheme());

  // Delegate click on .theme-toggle
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.theme-toggle');
    if (btn) {
      e.preventDefault();
      toggleTheme();
    }
  });

  /* ─── Debug Overlay ─── */
  var debugEl = null;

  function ensureDebugOverlay() {
    if (debugEl) return debugEl;
    debugEl = document.createElement('div');
    debugEl.className = 'debug-overlay';
    debugEl.id = 'debug-overlay';
    debugEl.innerHTML = [
      '<div class="debug-header">',
      '  <span class="debug-title">DEBUG OVERLAY · System Telemetry</span>',
      '  <button class="btn btn-ghost btn-sm" onclick="window.__toggleDebug()">关闭 (D)</button>',
      '</div>',
      '<div class="debug-grid" id="debug-grid"></div>',
    ].join('\n');
    document.body.appendChild(debugEl);
    return debugEl;
  }

  var debugMetrics = [
    { label: 'FPS', key: 'fps', unit: '', color: 'var(--accent)', gen: function () { return (27 + Math.random() * 3).toFixed(1); } },
    { label: 'GPU Utilization', key: 'gpu', unit: '%', color: 'var(--accent)', gen: function () { return Math.floor(68 + Math.random() * 12); }, bar: true },
    { label: 'GPU VRAM', key: 'vram', unit: ' MB', color: 'var(--secondary)', gen: function () { return (6100 + Math.floor(Math.random() * 400)); }, sub: '/ 8192 MB' },
    { label: 'GPU Temperature', key: 'temp', unit: '°C', color: 'var(--warn)', gen: function () { return Math.floor(58 + Math.random() * 8); } },
    { label: 'Inference Time', key: 'infer', unit: ' ms', color: 'var(--accent)', gen: function () { return (13 + Math.random() * 4).toFixed(1); } },
    { label: 'Tracking Time', key: 'track', unit: ' ms', color: 'var(--success)', gen: function () { return (2.5 + Math.random() * 2).toFixed(1); } },
    { label: 'Track Buffer', key: 'buf', unit: '', color: 'var(--accent)', gen: function () { return Math.floor(110 + Math.random() * 40); }, sub: '/ 250 max' },
    { label: 'Kafka TPS', key: 'ktps', unit: '', color: 'var(--accent)', gen: function () { return Math.floor(2700 + Math.random() * 300).toLocaleString(); } },
    { label: 'Kafka Consumer Lag', key: 'klag', unit: '', color: 'var(--success)', gen: function () { return Math.floor(Math.random() * 5); } },
    { label: 'WebSocket Latency', key: 'wslat', unit: ' ms', color: 'var(--success)', gen: function () { return Math.floor(8 + Math.random() * 8); } },
    { label: 'Match Rate', key: 'match', unit: '%', color: 'var(--success)', gen: function () { return (94 + Math.random() * 5).toFixed(1); } },
    { label: 'Calibration Quality', key: 'calib', unit: '%', color: 'var(--success)', gen: function () { return (92 + Math.random() * 6).toFixed(1); }, bar: true },
  ];

  function renderDebugGrid() {
    var grid = document.getElementById('debug-grid');
    if (!grid) return;
    var html = '';
    for (var i = 0; i < debugMetrics.length; i++) {
      var m = debugMetrics[i];
      var val = m.gen();
      html += '<div class="debug-metric">';
      html += '  <div class="debug-metric-label">' + m.label + '</div>';
      html += '  <div class="debug-metric-value" style="color:' + m.color + ';" data-debug-key="' + m.key + '">' + val + '<span style="font-size:0.45em;color:var(--fg-muted);">' + m.unit + '</span></div>';
      if (m.sub) {
        html += '  <div class="debug-metric-sub">' + m.sub + '</div>';
      }
      if (m.bar) {
        var pct = typeof val === 'string' ? parseFloat(val) : val;
        html += '  <div class="debug-bar"><div class="debug-bar-fill" style="width:' + Math.min(pct, 100) + '%;background:' + m.color + ';"></div></div>';
      }
      html += '</div>';
    }
    grid.innerHTML = html;
  }

  function updateDebugValues() {
    if (!debugEl || !debugEl.classList.contains('visible')) return;
    for (var i = 0; i < debugMetrics.length; i++) {
      var m = debugMetrics[i];
      var el = debugEl.querySelector('[data-debug-key="' + m.key + '"]');
      if (el) {
        var val = m.gen();
        el.innerHTML = val + '<span style="font-size:0.45em;color:var(--fg-muted);">' + m.unit + '</span>';
        if (m.bar) {
          var pct = typeof val === 'string' ? parseFloat(val) : val;
          var bar = el.parentElement.querySelector('.debug-bar-fill');
          if (bar) bar.style.width = Math.min(pct, 100) + '%';
        }
      }
    }
  }

  var debugVisible = false;

  window.__toggleDebug = function () {
    debugVisible = !debugVisible;
    var overlay = ensureDebugOverlay();
    if (debugVisible) {
      renderDebugGrid();
      overlay.classList.add('visible');
    } else {
      overlay.classList.remove('visible');
    }
  };

  // D key toggles debug
  document.addEventListener('keydown', function (e) {
    if (e.key === 'd' || e.key === 'D') {
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault();
      window.__toggleDebug();
    }
  });

  // Update debug values every 2s
  setInterval(updateDebugValues, 2000);

  /* ─── Simulated WebSocket / Real-time Data ─── */
  var wsListeners = {};

  window.__ws = {
    on: function (event, fn) {
      if (!wsListeners[event]) wsListeners[event] = [];
      wsListeners[event].push(fn);
    },
    emit: function (event, data) {
      var fns = wsListeners[event] || [];
      for (var i = 0; i < fns.length; i++) fns[i](data);
    }
  };

  // Simulate periodic KPI updates
  function simulateKPI() {
    window.__ws.emit('kpi', {
      flow: 184293 + Math.floor(Math.random() * 200),
      congestion: (1.2 + Math.random() * 0.6).toFixed(2),
      anomalies: Math.floor(5 + Math.random() * 5),
      drones_online: 17 + Math.floor(Math.random() * 3),
      gpu_pct: Math.floor(65 + Math.random() * 20),
      latency_ms: Math.floor(35 + Math.random() * 20)
    });
  }

  // Simulate periodic alert feed
  var alertTypes = [
    { type: '逆行事件', severity: 'p1', location: '中山路/解放路' },
    { type: '排队超限预警', severity: 'p2', location: '和平路/光华街' },
    { type: '疑似交通事故', severity: 'p1', location: '人民大道/建设路' },
    { type: '拥堵指数突破阈值', severity: 'p3', location: '文化路/科技大道' },
    { type: '非机动车闯入', severity: 'p2', location: '中山路/解放路' },
    { type: '行人闯红灯', severity: 'p3', location: '滨江路/新华街' },
    { type: '违规变道检测', severity: 'p2', location: '光华街/和平路' },
    { type: '异常停车', severity: 'p2', location: '建设路/人民大道' },
  ];

  function simulateAlert() {
    var a = alertTypes[Math.floor(Math.random() * alertTypes.length)];
    var now = new Date();
    var ts = pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
    window.__ws.emit('alert', {
      time: ts,
      type: a.type,
      severity: a.severity,
      location: a.location
    });
  }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  // Start simulation
  setInterval(simulateKPI, 3000);
  setInterval(simulateAlert, 8000 + Math.random() * 5000);

  /* ─── Tab Switching ─── */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('[data-tab]');
    if (!tab) return;
    e.preventDefault();
    var group = tab.closest('[data-tab-group]');
    if (!group) return;
    var target = tab.getAttribute('data-tab');

    // Update tab buttons
    var tabs = group.querySelectorAll('[data-tab]');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle('active', tabs[i] === tab);
    }
    // Update tab panels
    var panels = group.querySelectorAll('[data-tab-panel]');
    for (var j = 0; j < panels.length; j++) {
      panels[j].style.display = panels[j].getAttribute('data-tab-panel') === target ? '' : 'none';
    }
  });

  /* ─── Clock ─── */
  function updateClock() {
    var els = document.querySelectorAll('[data-clock]');
    if (!els.length) return;
    var now = new Date();
    var str = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) + ' ' +
              pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
    for (var i = 0; i < els.length; i++) {
      els[i].textContent = str;
    }
  }
  setInterval(updateClock, 1000);
  updateClock();

})();
