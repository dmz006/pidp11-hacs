/**
 * PiDP-11 Front Panel — Lovelace custom card.
 *
 * Faithfully replicates the PDP-11/70 front panel layout:
 *   Row 1: Status indicators (PAR ERR, ADRS ERR, RUN, PAUSE, MASTER |
 *                              USER, SUPER, KERNEL, DATA | ADDRESSING 16/18/22)
 *   Row 2: ADDRESS — 22 LEDs under a dark-red segment bar
 *   Row 3: DATA    — PARITY H/L + 16 LEDs under a dark-purple segment bar
 *   Row 4: Switch Register — 22 toggle-style switches, alternating octal groups
 *   Row 5: ADDR SELECT / DATA SELECT rotary position indicators
 *   Footer: System name + control switch buttons
 *
 * Lamp feed. Two Home Assistant events drive the lamps:
 *   pidp11_lamps2  live frames from the add-on: percent-on per lamp, up to the
 *                  fps set in the integration options. Each lamp is drawn with
 *                  brightness proportional to its percent. While frames keep
 *                  arriving the header shows "live".
 *   pidp11_lamps   the older PC/PSW snapshot (EVENT lamps). Drawn as before and
 *                  marked "approximate".
 * With no frame for 5 seconds the card falls back to the entity values (the
 * poll) and shows "approximate". LED updates are coalesced into one
 * requestAnimationFrame per frame, so the card never draws faster than events arrive.
 */

(function () {
  "use strict";

  if (customElements.get("pidp11-panel-card")) return;

  // ── Bit helpers ────────────────────────────────────────────────────────────

  function octalToInt(s) { return s ? parseInt(s, 8) : 0; }

  // Entity ids come from the integration's device "PiDP-11": HA slugs it to
  // pidp_11 (pidp11 on installs made with the older slug). The defaults below
  // use pidp_11. A configured or default id that is not in hass.states is
  // resolved by suffix under either device prefix, so "_2" duplicates and
  // renamed entities still work.
  var DEVICE_OBJECT_RE = /^pidp_?11_/;

  // A live frame older than this is no longer live (the card shows "approximate").
  var STALE_MS = 5000;
  // How often the card checks whether the live feed has gone quiet.
  var LIVE_TICK_MS = 1000;
  var EVENT_OLD = "pidp11_lamps";
  var EVENT_LIVE = "pidp11_lamps2";

  // Domain and object-id suffix of each single-entity option.
  var SINGLE_ENTITY = {
    state_entity:    ["sensor", "cpu_state"],
    pc_entity:       ["sensor", "pc"],
    psw_entity:      ["sensor", "psw"],
    system_entity:   ["sensor", "system"],
    cpu_mode_entity: ["sensor", "cpu_mode"],
  };

  function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  // Lamp names are compared without case, punctuation or underscores, so
  // "P.PHY", "P_PHY" and "PPHY" are the same selector lamp.
  function normLamp(s) { return String(s).toUpperCase().replace(/[^A-Z0-9]/g, ""); }

  // Smallest entity id in `states` of `domain` whose object id is under the device
  // prefix and ends in "_<suffix>", optionally followed by "_<n>". One pass, no
  // sort, so it stays cheap on every hass update. Returns null when there is none.
  function findDeviceEntity(states, domain, suffix) {
    var tail = new RegExp("_" + escapeRegExp(suffix) + "(_\\d+)?$");
    var head = domain + ".";
    var keys = Object.keys(states);
    var best = null;
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      if (key.indexOf(head) !== 0) continue;
      var obj = key.slice(head.length);
      if (!DEVICE_OBJECT_RE.test(obj) || !tail.test(obj)) continue;
      if (best === null || key < best) best = key;
    }
    return best;
  }

  function intToBits(n, len) {
    var bits = [];
    for (var i = len - 1; i >= 0; i--) bits.push((n >>> i) & 1);
    return bits;
  }

  // LED row. cls = type class ('adr' or 'dat') used by _paintLamps. prefix names
  // the lamps: the leftmost LED is the highest bit (ADDRESS21 .. ADDRESS0).
  function ledRow(bits, groups, cls, prefix) {
    var html = '<div class="leds">';
    var idx = 0;
    var total = bits.length;
    groups.forEach(function (count, gi) {
      if (gi > 0) html += '<span class="sep"></span>';
      for (var k = 0; k < count; k++, idx++) {
        html += '<span class="led lit ' + cls + '" data-lamp="' + prefix +
                (total - 1 - idx) + '" data-fb="' + (bits[idx] ? 1 : 0) + '"></span>';
      }
    });
    return html + '</div>';
  }

  // SR toggle-switch row. Groups alternate two colors (octal-digit bands).
  function swRow(bits, groups) {
    var html = '<div class="swrow">';
    var idx = 0;
    groups.forEach(function (count, gi) {
      if (gi > 0) html += '<span class="sep"></span>';
      var gc = (gi % 2 === 0) ? 'ga' : 'gb';
      for (var k = 0; k < count; k++, idx++) {
        html += '<span class="sw ' + gc + ' ' + (bits[idx] ? 'on' : 'off') + '"></span>';
      }
    });
    return html + '</div>';
  }

  // Bit-number labels above the SR switch row (all 22 numbers shown).
  function bitNums(totalBits, groups) {
    var html = '<div class="bitnums">';
    var idx = 0;
    groups.forEach(function (count, gi) {
      if (gi > 0) html += '<span class="bnsep"></span>';
      for (var k = 0; k < count; k++, idx++) {
        html += '<span class="bitnum">' + (totalBits - 1 - idx) + '</span>';
      }
    });
    return html + '</div>';
  }

  // Single status-indicator LED with label below. lamp is the add-on's lamp name.
  function si(lamp, on, lbl) {
    return '<div class="si"><div class="sdot lit" data-lamp="' + lamp +
           '" data-fb="' + (on ? 1 : 0) + '"></div><div class="slbl">' + lbl + '</div></div>';
  }

  // Rotary selector row. prefix is ADDR_SEL_ or DATA_SEL_; each position's lamp is
  // the prefix plus the position label (see normLamp).
  function selRow(hdr, prefix, modes) {
    var dots = modes.map(function (m) {
      return '<div class="selitem"><div class="seldot lit" data-lamp="' + prefix + normLamp(m.label) +
             '" data-fb="' + (m.active ? 1 : 0) + '"></div><div class="sellbl' + (m.active ? ' act' : '') + '">' +
             m.label + '</div></div>';
    }).join('');
    return '<div class="selrow"><span class="selhdr">' + hdr +
           '</span><div class="selmodes">' + dots + '</div></div>';
  }

  // ── CSS ────────────────────────────────────────────────────────────────────

  var CSS = [
    ':host{display:block}',

    '.card{',
      'background:#1a0d0d;',
      'border-radius:8px;',
      'overflow:hidden;',
      "font-family:'Helvetica Neue',Arial,sans-serif;",
      'box-shadow:0 6px 28px rgba(0,0,0,.75),0 0 0 1px rgba(80,10,10,.35);',
      'user-select:none',
    '}',

    /* Header */
    '.hdr{',
      'padding:10px 16px 8px;',
      'display:flex;',
      'justify-content:space-between;',
      'align-items:center;',
      'border-bottom:1px solid #2d0f0f'
    + '}',
    '.logo{font-size:17px;font-style:italic;font-weight:300;color:#d8d0d0;letter-spacing:1px}',
    '.logo strong{font-style:normal;font-weight:700;color:#ffffff}',
    '.hdr-r{display:flex;flex-direction:column;align-items:flex-end;gap:1px}',
    '.sysval{font-size:12px;color:#ff5520;font-family:"Courier New",monospace;letter-spacing:1px}',
    '.cpustate{font-size:6.5px;letter-spacing:2px;text-transform:uppercase}',
    '.cpustate.run{color:#dd4400}',
    '.cpustate.halt{color:#886060}',
    '.cpustate.off{color:#664444}',
    /* Lamp feed marker: "live" while live frames arrive, "approximate" otherwise */
    '.lmode{font-size:5.5px;letter-spacing:1.2px;text-transform:uppercase;color:#886060;margin-top:1px}',
    '.lmode[data-mode="live"]{color:#ff7040}',

    /* Faceplate body */
    '.face{padding:10px 16px 14px;display:flex;flex-direction:column;gap:9px}',

    /* Status indicator row */
    '.statrow{display:flex;align-items:flex-end;gap:0}',
    '.sigrp{display:flex;align-items:flex-end;gap:5px}',
    '.sigrp+.sigrp{margin-left:8px;padding-left:8px;border-left:1px solid #2d0f0f}',
    '.si{display:flex;flex-direction:column;align-items:center;gap:3px}',
    '.sdot{width:8px;height:8px;border-radius:50%;border:1px solid #2a0808;background:#3d1010}',
    '.slbl{font-size:5.5px;color:#c8b8b8;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap}',
    /* Addressing sub-group (label above) */
    '.amgrp{display:flex;flex-direction:column;align-items:center}',
    '.amlbl{font-size:4.5px;color:#b0a0a0;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}',
    '.aminner{display:flex;gap:5px}',

    /* Segment bars */
    '.segbar{height:5px;border-radius:1px;margin-bottom:3px}',
    '.segbar.addr{background:#7e1e1e}',
    '.segbar.data{background:#42185a}',

    /* Register rows */
    '.regrow{display:flex;flex-direction:column}',
    '.reginner{display:flex;align-items:center;gap:8px}',
    '.regright{display:flex;flex-direction:column;align-items:flex-end;margin-left:auto;flex-shrink:0;gap:1px}',
    '.rlbl{font-size:7px;color:#d0c0c0;text-transform:uppercase;letter-spacing:2px}',
    '.rval{font-size:10px;font-family:"Courier New",monospace;color:#ff5520;letter-spacing:1px}',

    /* LEDs. The well is always dark; a lit overlay on top carries the brightness
       in --lv (0 to 1), which is the lamp's percent on the live feed. */
    '.leds{display:flex;align-items:center;gap:3px}',
    '.led{display:inline-block;width:9px;height:9px;border-radius:50%;border:1px solid #1a0606;flex-shrink:0;background:#3d1010}',
    '.lit{position:relative}',
    '.lit::after{content:"";position:absolute;inset:0;border-radius:50%;',
      'background:radial-gradient(circle at 33% 33%,#ff7050,#ff2e00);',
      'box-shadow:0 0 5px #ff2e00,0 0 10px rgba(255,46,0,.28);',
      'opacity:var(--lv,0);pointer-events:none}',
    '.sep{display:inline-block;width:5px;flex-shrink:0}',

    /* Parity group (DATA row, far left) */
    '.pargrp{display:flex;flex-direction:column;align-items:center;gap:2px;flex-shrink:0}',
    '.pardots{display:flex;gap:3px}',
    '.pardot{width:7px;height:7px;border-radius:50%;background:#2a0a0a;border:1px solid #1a0606}',
    '.parhl{display:flex;gap:3px}',
    '.parhl span{font-size:4.5px;color:#b0a0a0;width:7px;text-align:center}',
    '.parlbl{font-size:5px;color:#b0a0a0;text-transform:uppercase;letter-spacing:.5px}',

    /* SR switch section */
    '.srsec{display:flex;flex-direction:column;gap:2px}',
    /* Bit-number labels */
    '.bitnums{display:flex;align-items:center;gap:3px}',
    '.bitnum{display:inline-block;width:8px;font-size:5px;color:#c0b0b0;',
            'text-align:center;flex-shrink:0;font-family:"Courier New",monospace}',
    '.bnsep{display:inline-block;width:5px;flex-shrink:0}',
    /* Toggle switches */
    '.swrow{display:flex;align-items:center;gap:3px}',
    '.sw{display:inline-block;width:8px;height:18px;border-radius:2px 2px 1px 1px;',
        'position:relative;flex-shrink:0}',
    '.sw::after{content:"";position:absolute;left:1px;width:6px;height:4px;',
               'border-radius:1px;background:rgba(228,192,180,.55)}',
    '.sw.on::after{top:1px}',
    '.sw.off::after{bottom:1px}',
    '.sw.ga{background:linear-gradient(to bottom,#c83020,#781010)}',
    '.sw.ga.off{background:linear-gradient(to bottom,#601010,#380808)}',
    '.sw.gb{background:linear-gradient(to bottom,#8a1018,#4e080c)}',
    '.sw.gb.off{background:linear-gradient(to bottom,#440810,#280406)}',

    /* Rotary selector indicators */
    '.selsec{display:flex;flex-direction:column;gap:5px}',
    '.selrow{display:flex;align-items:flex-start;gap:5px}',
    '.selhdr{font-size:6px;color:#c0b0b0;text-transform:uppercase;letter-spacing:.5px;',
            'min-width:28px;padding-top:4px;flex-shrink:0}',
    '.selmodes{display:flex;gap:4px;flex-wrap:wrap}',
    '.selitem{display:flex;flex-direction:column;align-items:center;gap:2px}',
    '.seldot{width:6px;height:6px;border-radius:50%;background:#2a0808;border:1px solid #1a0606}',
    '.sellbl{font-size:5.5px;color:#b0a0a0;text-transform:uppercase;white-space:nowrap}',
    '.sellbl.act{color:#ff6040}',

    /* Footer bar */
    '.bar{background:#110808;border-top:1px solid #2d0f0f;padding:8px 16px;',
         'display:flex;align-items:center;gap:10px}',
    '.barsys{display:flex;flex-direction:column;gap:1px;flex-shrink:0}',
    '.barsyslbl{font-size:6px;color:#c0b0b0;text-transform:uppercase;letter-spacing:1px}',
    '.barsysval{font-size:12px;color:#ff5520;font-family:"Courier New",monospace}',
    '.ctrlrow{display:flex;gap:3px;align-items:center;margin-left:auto;flex-wrap:wrap;justify-content:flex-end}',
    '.cbtn{font-size:5.5px;color:#d8c0c0;text-transform:uppercase;letter-spacing:.4px;',
          'padding:2px 4px;border-radius:2px;background:#5a1010;white-space:nowrap}',
    '.cbtn.act{background:#b01808;color:#fff}',
  ].join('');

  // ── Card element ───────────────────────────────────────────────────────────

  // Lovelace creates the card with document.createElement, so it must be a real
  // custom element: a class that extends HTMLElement and calls super(). A
  // constructor function that never runs the HTMLElement constructor gets no
  // setConfig/hass wiring, and the card never renders.
  class PiDP11PanelCard extends HTMLElement {

    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._cfg     = null;
      this._hass    = null;
      this._found   = {};
      this._livePC  = 0;
      this._livePSW = 0;
      this._lampSubs = null;   // the two event subscriptions (promises of unsubscribe)
      this._frame    = null;   // latest live frame: normalized lamp name -> percent
      this._frameAt  = 0;      // Date.now() of that frame
      this._wasLive  = false;  // mode at the last paint, for the staleness tick
      this._liveTimer = null;
      this._rafId   = null;
    }

    setConfig(config) {
      this._cfg = {
        state_entity:    config.state_entity    || "sensor.pidp_11_cpu_state",
        pc_entity:       config.pc_entity       || "sensor.pidp_11_pc",
        psw_entity:      config.psw_entity      || "sensor.pidp_11_psw",
        system_entity:   config.system_entity   || "sensor.pidp_11_system",
        sr_prefix:       config.sr_prefix       || "binary_sensor.pidp_11_sr",
        cpu_mode_entity: config.cpu_mode_entity || "sensor.pidp_11_cpu_mode",
      };
    }

    getCardSize() { return 6; }

    set hass(hass) {
      this._hass = hass;
      if (!this._cfg) this.setConfig({});
      this._subscribeLamps();
      var pcOct  = this._st(this._entity("pc_entity"));
      var pswOct = this._st(this._entity("psw_entity"));
      if (pcOct  !== null) this._livePC  = octalToInt(pcOct);
      if (pswOct !== null) this._livePSW = octalToInt(pswOct);
      this._update();
    }

    connectedCallback() {
      // Lamp feed is released on disconnect; re-attach it when the card returns.
      this._subscribeLamps();
    }

    disconnectedCallback() {
      this._unsubscribeLamps();
      if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }
    }

    _subscribeLamps() {
      if (this._lampSubs || !this._hass || !this.isConnected) return;
      var self = this;
      this._lampSubs = [EVENT_OLD, EVENT_LIVE].map(function (type) {
        return self._hass.connection.subscribeEvents(function (ev) {
          if (type === EVENT_LIVE) self._onLampFrame(ev); else self._onLamp(ev);
        }, type);
      });
      this._startLiveTimer();
    }

    _unsubscribeLamps() {
      if (!this._lampSubs) return;
      this._lampSubs.forEach(function (sub) {
        Promise.resolve(sub).then(function (u) { try { u && u(); } catch (e) {} });
      });
      this._lampSubs = null;
      this._stopLiveTimer();
    }

    _startLiveTimer() {
      if (this._liveTimer) return;
      var self = this;
      this._liveTimer = setInterval(function () { self._tickLive(); }, LIVE_TICK_MS);
    }

    _stopLiveTimer() {
      if (this._liveTimer) { clearInterval(this._liveTimer); this._liveTimer = null; }
    }

    // Repaints only when the feed goes live or quiet; nothing is drawn otherwise.
    _tickLive() {
      if (this._isLive() !== this._wasLive) this._schedulePaint();
    }

    _isLive() {
      return this._frame !== null && Date.now() - this._frameAt < STALE_MS;
    }

    _st(id) {
      return this._hass && this._hass.states[id] ? this._hass.states[id].state : null;
    }

    // Entity id for a single-entity option (state_entity, pc_entity, ...).
    _entity(key) {
      var kind = SINGLE_ENTITY[key];
      return this._resolveId(this._cfg[key], kind[0], kind[1]);
    }

    // Entity id for SR bit `bit`: sr_prefix + bit, or the device's sr<bit>.
    _srEntity(bit) {
      return this._resolveId(this._cfg.sr_prefix + bit, "binary_sensor", "sr" + bit);
    }

    // Configured id if it exists; otherwise the device entity with this suffix.
    // A found id is cached until it leaves hass.states.
    _resolveId(configured, domain, suffix) {
      var states = this._hass ? this._hass.states : {};
      if (states[configured]) return configured;
      var cacheKey = domain + "." + suffix;
      var cached = this._found[cacheKey];
      if (cached && states[cached]) return cached;
      var found = findDeviceEntity(states, domain, suffix);
      if (found) { this._found[cacheKey] = found; return found; }
      return configured;
    }

    // Old format: PC/PSW snapshot. Values are kept; the lamps are drawn from them
    // while no live frame is current.
    _onLamp(ev) {
      var d = ev.data;
      if (!d) return;
      var pc  = d.address !== undefined ? parseInt(d.address, 8) : this._livePC;
      var ps  = d.data    !== undefined ? parseInt(d.data,    8) : this._livePSW;
      if (isNaN(pc)) pc = this._livePC;
      if (isNaN(ps)) ps = this._livePSW;
      if (pc === this._livePC && ps === this._livePSW) return;
      this._livePC  = pc;
      this._livePSW = ps;
      this._schedulePaint();
    }

    // Live frame: {"seq": n, "leds": {"ADDRESS21": 0-100, ...}}. Only numeric
    // values are kept; a lamp missing from the frame keeps its entity value.
    _onLampFrame(ev) {
      var d = ev && ev.data;
      if (!d || typeof d !== "object" || !d.leds || typeof d.leds !== "object") return;
      var map = {};
      var names = Object.keys(d.leds);
      for (var i = 0; i < names.length; i++) {
        var v = d.leds[names[i]];
        if (typeof v !== "number" || !isFinite(v)) continue;
        map[normLamp(names[i])] = Math.min(100, Math.max(0, v));
      }
      this._frame   = map;
      this._frameAt = Date.now();
      this._schedulePaint();
    }

    // One paint per animation frame at most; events only mark the lamps dirty.
    _schedulePaint() {
      if (this._rafId) return;
      var self = this;
      this._rafId = requestAnimationFrame(function () {
        self._rafId = null;
        self._paintLamps();
      });
    }

    // Sets --lv on every lamp: from the live frame when it is current, otherwise
    // from the entity values (the old behaviour). Also refreshes the readouts and
    // the live/approximate marker.
    _paintLamps() {
      var root = this.shadowRoot;
      if (!root) return;
      var live  = this._isLive();
      var frame = live ? this._frame : null;
      this._wasLive = live;

      var pcB  = intToBits(this._livePC,  22);
      var pswB = intToBits(this._livePSW, 16);
      var i;
      var adr = root.querySelectorAll(".adr");
      for (i = 0; i < adr.length; i++) paintLamp(adr[i], pcB[i], frame);
      var dat = root.querySelectorAll(".dat");
      for (i = 0; i < dat.length; i++) paintLamp(dat[i], pswB[i], frame);
      var rest = root.querySelectorAll(".lit:not(.adr):not(.dat)");
      for (i = 0; i < rest.length; i++) {
        paintLamp(rest[i], rest[i].getAttribute("data-fb") === "1" ? 1 : 0, frame);
      }

      var ep = root.querySelector(".rv-pc");
      var ed = root.querySelector(".rv-ps");
      if (ep) ep.textContent = this._livePC.toString(8).padStart(6, "0");
      if (ed) ed.textContent = this._livePSW.toString(8).padStart(6, "0");

      var mode = root.querySelector(".lmode");
      if (mode) {
        mode.textContent = live ? "live" : "approximate";
        mode.setAttribute("data-mode", live ? "live" : "approximate");
      }
    }

    // Full DOM rebuild — runs on every hass update (entity state change).
    _update() {
      if (!this._cfg || !this._hass) return;

      var cpu     = this._st(this._entity("state_entity")) || "offline";
      var sys     = this._st(this._entity("system_entity")) || "—";
      var mode    = this._st(this._entity("cpu_mode_entity"));

      var running = cpu === "running";
      var offline = cpu === "offline" || cpu === "unavailable" || cpu === "unknown";

      var stLbl = offline ? "OFFLINE" : running ? "RUNNING" : "HALTED";
      var stCls = offline ? "off"     : running ? "run"     : "halt";

      var pcB   = intToBits(this._livePC,  22);
      var pswB  = intToBits(this._livePSW, 16);
      var pcD   = this._livePC.toString(8).padStart(6, "0");
      var pswD  = this._livePSW.toString(8).padStart(6, "0");

      // SR: bit 21 (MSB) = left, bit 0 (LSB) = right
      var srB = [];
      for (var b = 21; b >= 0; b--) {
        var sv = this._st(this._srEntity(b));
        srB.push(sv === "on" ? 1 : 0);
      }
      var srHas = !!this._hass.states[this._srEntity(0)];

      // Groups: [1,3,3,3,3,3,3,3] = 22 bits in "octal+1" grouping
      var G22 = [1, 3, 3, 3, 3, 3, 3, 3];
      var G16 = [4, 4, 4, 4];

      // ADDR SELECT: always PROG PHY (we always EXAMINE PC = program virtual addr)
      var addrModes = [
        { label:"P.PHY", active:true  }, { label:"K.I",   active:false },
        { label:"S.I",   active:false }, { label:"U.I",   active:false },
        { label:"C.PHY", active:false }, { label:"K.D",   active:false },
        { label:"S.D",   active:false }, { label:"U.D",   active:false },
      ];
      // DATA SELECT: always DISPLAY REGISTER (we always EXAMINE PSW)
      var dataModes = [
        { label:"D/P",  active:false }, { label:"BUS",  active:false },
        { label:"FPP",  active:false }, { label:"DSP",  active:true  },
      ];

      this.shadowRoot.innerHTML =
        "<style>" + CSS + "</style>" +
        '<div class="card">' +

        // ── Header ──
        '<div class="hdr">' +
          '<div class="logo"><em>pdp</em><strong>11</strong><em>/70</em></div>' +
          '<div class="hdr-r">' +
            '<div class="sysval">' + sys + '</div>' +
            '<div class="cpustate ' + stCls + '">' + stLbl + '</div>' +
            '<div class="lmode" data-mode="approximate">approximate</div>' +
          '</div>' +
        '</div>' +

        // ── Faceplate ──
        '<div class="face">' +

          // Row 1: Status indicators
          '<div class="statrow">' +
            // Group 1 — system/CPU state
            '<div class="sigrp">' +
              si('PAR_ERR', false, 'PAR ERR') +
              si('ADRS_ERR', false, 'ADRS ERR') +
              si('RUN', running, 'RUN') +
              si('PAUSE', false, 'PAUSE') +
              si('MASTER', false, 'MASTER') +
            '</div>' +
            // Group 2 — privilege mode
            '<div class="sigrp">' +
              si('USER', mode === 'user', 'USER') +
              si('SUPER', mode === 'supervisor', 'SUPER') +
              si('KERNEL', mode === 'kernel', 'KERNEL') +
              si('DATA_SPACE', false, 'DATA') +
            '</div>' +
            // Group 3 — addressing mode (PDP-11/70 always uses 22-bit)
            '<div class="sigrp">' +
              '<div class="amgrp">' +
                '<div class="amlbl">ADDRESSING</div>' +
                '<div class="aminner">' +
                  si('ADDRESSING_16', false, '16') +
                  si('ADDRESSING_18', false, '18') +
                  si('ADDRESSING_22', !offline, '22') +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +

          // Row 2: ADDRESS register (22 LEDs, dark-red segment bar)
          '<div class="regrow">' +
            '<div class="segbar addr"></div>' +
            '<div class="reginner">' +
              ledRow(pcB, G22, 'adr', 'ADDRESS') +
              '<div class="regright">' +
                '<span class="rlbl">ADDRESS</span>' +
                '<span class="rval rv-pc">' + pcD + '</span>' +
              '</div>' +
            '</div>' +
          '</div>' +

          // Row 3: DATA register (PARITY H/L + 16 LEDs, dark-purple segment bar)
          '<div class="regrow">' +
            '<div class="segbar data"></div>' +
            '<div class="reginner">' +
              '<div class="pargrp">' +
                '<div class="pardots">' +
                  '<div class="pardot lit" data-lamp="PARITY_HIGH" data-fb="0"></div>' +
                  '<div class="pardot lit" data-lamp="PARITY_LOW" data-fb="0"></div>' +
                '</div>' +
                '<div class="parhl"><span>H</span><span>L</span></div>' +
                '<div class="parlbl">PAR</div>' +
              '</div>' +
              ledRow(pswB, G16, 'dat', 'DATA') +
              '<div class="regright">' +
                '<span class="rlbl">DATA</span>' +
                '<span class="rval rv-ps">' + pswD + '</span>' +
              '</div>' +
            '</div>' +
          '</div>' +

          // Row 4: Switch Register (SR21..SR0, toggle style)
          (srHas
            ? '<div class="srsec">' +
                bitNums(22, G22) +
                swRow(srB, G22) +
              '</div>'
            : '') +

          // Row 5: Rotary selector indicators
          '<div class="selsec">' +
            selRow('ADDR', 'ADDR_SEL_', addrModes) +
            selRow('DATA', 'DATA_SEL_', dataModes) +
          '</div>' +

        '</div>' +

        // ── Footer bar ──
        '<div class="bar">' +
          '<div class="barsys">' +
            '<div class="barsyslbl">System</div>' +
            '<div class="barsysval">' + sys + '</div>' +
          '</div>' +
          '<div class="ctrlrow">' +
            '<span class="cbtn">LOAD ADRS</span>' +
            '<span class="cbtn">EXAM</span>' +
            '<span class="cbtn">DEP</span>' +
            '<span class="cbtn">CONT</span>' +
            '<span class="cbtn ' + (running ? 'act' : '') + '">' +
              (running ? 'ENABLE' : 'HALT') + '</span>' +
            '<span class="cbtn">S INST</span>' +
            '<span class="cbtn">START</span>' +
          '</div>' +
        '</div>' +

        '</div>';

      this._paintLamps();
    }
  }

  // One lamp: brightness is the live percent when the frame has the lamp, otherwise
  // the fallback bit (0 or 1) from the entity values.
  function paintLamp(el, fallbackBit, frame) {
    var v = fallbackBit ? 1 : 0;
    var name = el.getAttribute("data-lamp");
    if (frame && name) {
      var pct = frame[normLamp(name)];
      if (pct !== undefined) v = pct / 100;
    }
    el.style.setProperty("--lv", String(v));
  }

  customElements.define("pidp11-panel-card", PiDP11PanelCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type:             "pidp11-panel-card",
    name:             "PiDP-11 Front Panel",
    description:      "Faithful PDP-11/70 front panel — 22 ADDRESS LEDs, status row, SR toggles, rotary selectors, live lamp feed.",
    preview:          true,
    documentationURL: "https://github.com/dmz006/pidp11-hacs",
  });
}());
