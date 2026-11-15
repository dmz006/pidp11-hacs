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
 * Live animation at 20 Hz via pidp11_lamps HA events (lamp watch port 2226).
 * LED updates use requestAnimationFrame without rebuilding innerHTML.
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

  // Domain and object-id suffix of each single-entity option.
  var SINGLE_ENTITY = {
    state_entity:    ["sensor", "cpu_state"],
    pc_entity:       ["sensor", "pc"],
    psw_entity:      ["sensor", "psw"],
    system_entity:   ["sensor", "system"],
    cpu_mode_entity: ["sensor", "cpu_mode"],
  };

  function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

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

  // LED row. cls = type class ('adr' or 'dat') used by _updateLeds querySelectorAll.
  function ledRow(bits, groups, cls) {
    var html = '<div class="leds">';
    var idx = 0;
    groups.forEach(function (count, gi) {
      if (gi > 0) html += '<span class="sep"></span>';
      for (var k = 0; k < count; k++, idx++) {
        html += '<span class="led ' + cls + ' ' + (bits[idx] ? 'on' : 'off') + '"></span>';
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

  // Single status-indicator LED with label below.
  function si(on, lbl) {
    return '<div class="si"><div class="sdot ' + (on ? 'on' : 'off') +
           '"></div><div class="slbl">' + lbl + '</div></div>';
  }

  // Rotary selector row.
  function selRow(hdr, modes) {
    var dots = modes.map(function (m) {
      return '<div class="selitem"><div class="seldot' + (m.active ? ' on' : '') +
             '"></div><div class="sellbl' + (m.active ? ' act' : '') + '">' +
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
      'border-bottom:1px solid #2d0f0f',
    '}',
    '.logo{font-size:17px;font-style:italic;font-weight:300;color:#d8d0d0;letter-spacing:1px}',
    '.logo strong{font-style:normal;font-weight:700;color:#ffffff}',
    '.hdr-r{display:flex;flex-direction:column;align-items:flex-end;gap:1px}',
    '.sysval{font-size:12px;color:#ff5520;font-family:"Courier New",monospace;letter-spacing:1px}',
    '.cpustate{font-size:6.5px;letter-spacing:2px;text-transform:uppercase}',
    '.cpustate.run{color:#dd4400}',
    '.cpustate.halt{color:#886060}',
    '.cpustate.off{color:#664444}',

    /* Faceplate body */
    '.face{padding:10px 16px 14px;display:flex;flex-direction:column;gap:9px}',

    /* Status indicator row */
    '.statrow{display:flex;align-items:flex-end;gap:0}',
    '.sigrp{display:flex;align-items:flex-end;gap:5px}',
    '.sigrp+.sigrp{margin-left:8px;padding-left:8px;border-left:1px solid #2d0f0f}',
    '.si{display:flex;flex-direction:column;align-items:center;gap:3px}',
    '.sdot{width:8px;height:8px;border-radius:50%;border:1px solid #2a0808}',
    '.sdot.on{background:radial-gradient(circle at 35% 35%,#ff7040,#ff2e00);',
             'box-shadow:0 0 4px #ff2e00,0 0 8px rgba(255,46,0,.35)}',
    '.sdot.off{background:#3d1010}',
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

    /* LEDs */
    '.leds{display:flex;align-items:center;gap:3px}',
    '.led{display:inline-block;width:9px;height:9px;border-radius:50%;border:1px solid #1a0606;flex-shrink:0}',
    '.led.on{background:radial-gradient(circle at 33% 33%,#ff7050,#ff2e00);',
            'box-shadow:0 0 5px #ff2e00,0 0 10px rgba(255,46,0,.28)}',
    '.led.off{background:#3d1010}',
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
    '.seldot.on{background:#ff2e00;box-shadow:0 0 3px #ff2e00}',
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
      this._lampSub = null;
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
      if (this._lampSub || !this._hass || !this.isConnected) return;
      var self = this;
      this._lampSub = this._hass.connection.subscribeEvents(
        function (ev) { self._onLamp(ev); }, "pidp11_lamps"
      );
    }

    _unsubscribeLamps() {
      if (!this._lampSub) return;
      Promise.resolve(this._lampSub).then(function (u) { try { u && u(); } catch (e) {} });
      this._lampSub = null;
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

    // Fast path — only update LED class names and octal value text.
    // ADDRESS row uses 22 bits (PC zero-extended to PROG PHY 22-bit).
    _updateLeds() {
      var root = this.shadowRoot;
      if (!root) return;
      var adr  = root.querySelectorAll(".adr");
      var dat  = root.querySelectorAll(".dat");
      var pcB  = intToBits(this._livePC,  22);
      var pswB = intToBits(this._livePSW, 16);
      for (var i = 0; i < adr.length;  i++) adr[i].className  = "led adr "  + (pcB[i]  ? "on" : "off");
      for (var j = 0; j < dat.length;  j++) dat[j].className  = "led dat "  + (pswB[j] ? "on" : "off");
      var ep = root.querySelector(".rv-pc");
      var ed = root.querySelector(".rv-ps");
      if (ep) ep.textContent = this._livePC.toString(8).padStart(6, "0");
      if (ed) ed.textContent = this._livePSW.toString(8).padStart(6, "0");
    }

    _onLamp(ev) {
      var d = ev.data;
      if (!d) return;
      var pc  = d.address !== undefined ? parseInt(d.address, 8) : this._livePC;
      var ps  = d.data    !== undefined ? parseInt(d.data,    8) : this._livePSW;
      if (pc === this._livePC && ps === this._livePSW) return;
      this._livePC  = pc;
      this._livePSW = ps;
      if (this._rafId) return;
      var self = this;
      this._rafId = requestAnimationFrame(function () { self._rafId = null; self._updateLeds(); });
    }

    // Full DOM rebuild — runs at 5 s entity-update cadence.
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
          '</div>' +
        '</div>' +

        // ── Faceplate ──
        '<div class="face">' +

          // Row 1: Status indicators
          '<div class="statrow">' +
            // Group 1 — system/CPU state
            '<div class="sigrp">' +
              si(false, 'PAR ERR') +
              si(false, 'ADRS ERR') +
              si(running, 'RUN') +
              si(false, 'PAUSE') +
              si(false, 'MASTER') +
            '</div>' +
            // Group 2 — privilege mode
            '<div class="sigrp">' +
              si(mode === 'user',       'USER') +
              si(mode === 'supervisor', 'SUPER') +
              si(mode === 'kernel',     'KERNEL') +
              si(false, 'DATA') +
            '</div>' +
            // Group 3 — addressing mode (PDP-11/70 always uses 22-bit)
            '<div class="sigrp">' +
              '<div class="amgrp">' +
                '<div class="amlbl">ADDRESSING</div>' +
                '<div class="aminner">' +
                  si(false,    '16') +
                  si(false,    '18') +
                  si(!offline, '22') +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +

          // Row 2: ADDRESS register (22 LEDs, dark-red segment bar)
          '<div class="regrow">' +
            '<div class="segbar addr"></div>' +
            '<div class="reginner">' +
              ledRow(pcB, G22, 'adr') +
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
                '<div class="pardots"><div class="pardot"></div><div class="pardot"></div></div>' +
                '<div class="parhl"><span>H</span><span>L</span></div>' +
                '<div class="parlbl">PAR</div>' +
              '</div>' +
              ledRow(pswB, G16, 'dat') +
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
            selRow('ADDR', addrModes) +
            selRow('DATA', dataModes) +
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
    }
  }

  customElements.define("pidp11-panel-card", PiDP11PanelCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type:             "pidp11-panel-card",
    name:             "PiDP-11 Front Panel",
    description:      "Faithful PDP-11/70 front panel — 22 ADDRESS LEDs, status row, SR toggles, rotary selectors, 20 Hz live animation.",
    preview:          true,
    documentationURL: "https://github.com/dmz006/pidp11-hacs",
  });
}());
