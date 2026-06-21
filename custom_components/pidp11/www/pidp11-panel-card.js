/**
 * PiDP-11 Front Panel — Lovelace custom card.
 *
 * Renders an amber-on-dark blinkenlight panel showing the PDP-11/70 CPU
 * registers read from the PiDP-11 HA integration.
 *
 * Live animation: subscribes to pidp11_lamps HA events fired by the
 * coordinator's lamp watch task (port 2226, 20 Hz poll of EXAMINE PC/PSW).
 * LED state is updated via requestAnimationFrame without rebuilding the DOM.
 *
 * Lovelace config example:
 *   type: custom:pidp11-panel-card
 *
 * Optional overrides (entity IDs are auto-detected by default):
 *   state_entity:  sensor.pidp11_cpu_state
 *   pc_entity:     sensor.pidp11_pc
 *   psw_entity:    sensor.pidp11_psw
 *   system_entity: sensor.pidp11_system
 */

(function () {
  "use strict";

  if (customElements.get("pidp11-panel-card")) return;

  // ── Bit helpers ──────────────────────────────────────────────────────────────

  function octalToInt(s) {
    return s ? parseInt(s, 8) : 0;
  }

  // n → bit array of `len` bits, MSB first
  function intToBits(n, len) {
    const bits = [];
    for (let i = len - 1; i >= 0; i--) bits.push((n >>> i) & 1);
    return bits;
  }

  // Render a row of LEDs with a type class for targeted querySelectorAll.
  // groups = array of counts per group, e.g. [4,4,4,4].
  // cls = extra class added to each LED span (e.g. 'adr' or 'dat').
  function ledRow(bits, groups, cls) {
    let html = '<div class="leds">';
    let idx = 0;
    groups.forEach(function (count, gi) {
      if (gi > 0) html += '<span class="sep"></span>';
      for (let k = 0; k < count; k++, idx++) {
        html += '<span class="led ' + cls + " " + (bits[idx] ? "on" : "off") + '"></span>';
      }
    });
    return html + "</div>";
  }

  // ── Styles ───────────────────────────────────────────────────────────────────

  var CSS = /* css */ `
    :host { display: block; }

    .card {
      background: #111114;
      border-radius: 10px;
      overflow: hidden;
      font-family: 'Courier New', Courier, monospace;
      box-shadow: 0 6px 28px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,140,0,0.04);
      user-select: none;
    }

    /* ── Faceplate ── */
    .face {
      background: linear-gradient(175deg, #1e1e22 0%, #141418 100%);
      padding: 14px 18px 13px;
      border-bottom: 1px solid #0b0b0e;
    }

    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 14px;
    }

    .brand .name {
      margin: 0;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 4px;
      color: #c0c0c8;
      text-transform: uppercase;
    }
    .brand .sub {
      margin: 3px 0 0;
      font-size: 8px;
      letter-spacing: 2px;
      color: #3a3a44;
      text-transform: uppercase;
    }

    /* ── RUN lamp ── */
    .runlamp {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
    }
    .runlamp .dot {
      width: 16px;
      height: 16px;
      border-radius: 50%;
      border: 1px solid #1a0a00;
    }
    .runlamp.running .dot {
      background: radial-gradient(circle at 36% 36%, #ffd080, #ff8c00);
      box-shadow: 0 0 8px #ff8c00, 0 0 20px rgba(255,140,0,0.25);
    }
    .runlamp.halted .dot  { background: #200f00; }
    .runlamp.offline .dot { background: #111; border-color: #1c1c1c; }
    .runlamp .dlabel {
      font-size: 8px;
      letter-spacing: 2px;
      color: #3a3a44;
      text-transform: uppercase;
    }
    .runlamp.running .dlabel { color: #7a4a10; }

    /* ── Register rows ── */
    .regrow { margin-bottom: 11px; }
    .regrow:last-child { margin-bottom: 0; }

    .rowhead {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 5px;
    }
    .rowhead .rlabel {
      font-size: 8px;
      letter-spacing: 2px;
      color: #383840;
      text-transform: uppercase;
    }
    .rowhead .rval {
      font-size: 11px;
      color: #7a5020;
      letter-spacing: 1px;
    }

    /* ── LEDs ── */
    .leds {
      display: flex;
      align-items: center;
      gap: 3px;
    }
    .led {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1px solid #140800;
      flex-shrink: 0;
    }
    .led.on {
      background: radial-gradient(circle at 34% 34%, #ffd080, #ff8c00);
      box-shadow: 0 0 6px #ff8c00;
    }
    .led.off { background: #1a0a00; }
    .sep {
      display: inline-block;
      width: 5px;
      flex-shrink: 0;
    }

    /* ── Bottom bar ── */
    .bar {
      background: #0e0e11;
      padding: 10px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .sysinfo .syslbl {
      font-size: 8px;
      letter-spacing: 2px;
      color: #2e2e36;
      text-transform: uppercase;
      margin-bottom: 2px;
    }
    .sysinfo .sysval {
      font-size: 13px;
      color: #ff8c00;
      letter-spacing: 1px;
    }

    .indrow {
      display: flex;
      gap: 12px;
    }
    .ind {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 3px;
    }
    .ind .idot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #190b00;
      border: 1px solid #140800;
    }
    .ind .idot.on {
      background: #ff8c00;
      box-shadow: 0 0 4px #ff8c00;
    }
    .ind .ilbl {
      font-size: 7px;
      letter-spacing: 1px;
      color: #2a2a30;
      text-transform: uppercase;
      white-space: nowrap;
    }
  `;

  // ── Card class ────────────────────────────────────────────────────────────────

  var PiDP11PanelCard = (function () {
    function PiDP11PanelCard() {
      this.attachShadow({ mode: "open" });
      // Live register state — updated by lamp events (20 Hz) and entity state (5 s)
      this._livePC  = 0;
      this._livePSW = 0;
      // Promise returned by hass.connection.subscribeEvents(); null until subscribed
      this._lampSub = null;
      // requestAnimationFrame ID for pending LED repaint; null when idle
      this._rafId   = null;
    }

    PiDP11PanelCard.prototype = Object.create(HTMLElement.prototype);
    PiDP11PanelCard.prototype.constructor = PiDP11PanelCard;

    PiDP11PanelCard.prototype.setConfig = function (config) {
      this._cfg = {
        state_entity:  config.state_entity  || "sensor.pidp11_cpu_state",
        pc_entity:     config.pc_entity     || "sensor.pidp11_pc",
        psw_entity:    config.psw_entity    || "sensor.pidp11_psw",
        system_entity: config.system_entity || "sensor.pidp11_system",
      };
    };

    PiDP11PanelCard.prototype.getCardSize = function () { return 3; };

    PiDP11PanelCard.prototype.disconnectedCallback = function () {
      // Unsubscribe from lamp events when the card is removed from the DOM
      if (this._lampSub) {
        Promise.resolve(this._lampSub).then(function (unsub) {
          try { unsub && unsub(); } catch (e) {}
        });
        this._lampSub = null;
      }
      if (this._rafId) {
        cancelAnimationFrame(this._rafId);
        this._rafId = null;
      }
    };

    Object.defineProperty(PiDP11PanelCard.prototype, "hass", {
      set: function (hass) {
        this._hass = hass;

        // Subscribe to pidp11_lamps events exactly once per card instance.
        // The event is fired by coordinator._handle_lamp_line at 20 Hz when
        // the lamp watch task (port 2226) is connected.
        if (!this._lampSub) {
          var self = this;
          this._lampSub = hass.connection.subscribeEvents(
            function (ev) { self._onLamp(ev); },
            "pidp11_lamps"
          );
        }

        // Seed live register state from entity state.
        // This gives correct initial values before any lamp events arrive
        // and acts as a 5 s fallback if the lamp stream is unavailable.
        var pcOct  = this._st(this._cfg.pc_entity);
        var pswOct = this._st(this._cfg.psw_entity);
        if (pcOct  !== null) this._livePC  = octalToInt(pcOct);
        if (pswOct !== null) this._livePSW = octalToInt(pswOct);

        this._update();
      },
    });

    PiDP11PanelCard.prototype._st = function (id) {
      return this._hass && this._hass.states[id]
        ? this._hass.states[id].state
        : null;
    };

    // Fast path: called by RAF after a lamp event updates _livePC/_livePSW.
    // Updates only the LED class names and value text — does not rebuild innerHTML.
    PiDP11PanelCard.prototype._updateLeds = function () {
      var root = this.shadowRoot;
      if (!root) return;

      var adrLeds = root.querySelectorAll(".adr");
      var datLeds = root.querySelectorAll(".dat");
      var pcBits  = intToBits(this._livePC,  16);
      var pswBits = intToBits(this._livePSW, 16);

      for (var i = 0; i < adrLeds.length; i++) {
        adrLeds[i].className = "led adr " + (pcBits[i] ? "on" : "off");
      }
      for (var j = 0; j < datLeds.length; j++) {
        datLeds[j].className = "led dat " + (pswBits[j] ? "on" : "off");
      }

      // Update the octal value displays alongside the LEDs
      var pcEl  = root.querySelector(".rv-pc");
      var psEl  = root.querySelector(".rv-ps");
      if (pcEl)  pcEl.textContent  = this._livePC.toString(8).replace(/^0+/, "")  || "0";
      if (psEl)  psEl.textContent  = this._livePSW.toString(8).replace(/^0+/, "") || "0";
    };

    // Lamp event handler — fires on pidp11_lamps HA events at up to 20 Hz.
    PiDP11PanelCard.prototype._onLamp = function (ev) {
      var d = ev.data;
      if (!d) return;
      var pc  = (d.address !== undefined) ? parseInt(d.address, 8) : this._livePC;
      var ps  = (d.data    !== undefined) ? parseInt(d.data,    8) : this._livePSW;
      if (pc === this._livePC && ps === this._livePSW) return;
      this._livePC  = pc;
      this._livePSW = ps;
      // Coalesce rapid events: only schedule one RAF at a time
      if (this._rafId) return;
      var self = this;
      this._rafId = requestAnimationFrame(function () {
        self._rafId = null;
        self._updateLeds();
      });
    };

    // Slow path: full innerHTML rebuild on every hass update (5 s cadence).
    // Uses _livePC/_livePSW (updated by lamp events) for LED state so the
    // full render is always consistent with the live animation state.
    PiDP11PanelCard.prototype._update = function () {
      if (!this._cfg || !this._hass) return;

      var cpu    = this._st(this._cfg.state_entity) || "offline";
      var pcOct  = this._st(this._cfg.pc_entity);
      var pswOct = this._st(this._cfg.psw_entity);
      var sys    = this._st(this._cfg.system_entity) || "—";

      var running = cpu === "running";
      var offline = cpu === "offline" || cpu === "unavailable" || cpu === "unknown";

      var lampCls = offline ? "offline" : running ? "running" : "halted";
      var lampTxt = offline ? "OFFLN" : running ? "RUN" : "HALT";

      var pcBits  = intToBits(this._livePC,  16);
      var pswBits = intToBits(this._livePSW, 16);

      // Display text: show entity value when available, em-dashes when offline
      var pcDisp  = pcOct  ? pcOct.replace(/^0+/, "")  || "0" : "——————";
      var pswDisp = pswOct ? pswOct.replace(/^0+/, "") || "0" : "——————";

      // 16 LEDs in four groups of 4
      var G = [4, 4, 4, 4];

      this.shadowRoot.innerHTML =
        "<style>" + CSS + "</style>" +
        '<div class="card">' +
          '<div class="face">' +
            '<div class="topbar">' +
              '<div class="brand">' +
                '<div class="name">PDP-11/70</div>' +
                '<div class="sub">SimH \xb7 PiDP-11 \xb7 Home Assistant</div>' +
              "</div>" +
              '<div class="runlamp ' + lampCls + '">' +
                '<div class="dot"></div>' +
                '<div class="dlabel">' + lampTxt + "</div>" +
              "</div>" +
            "</div>" +

            '<div class="regrow">' +
              '<div class="rowhead">' +
                '<span class="rlabel">Address Register (PC)</span>' +
                '<span class="rval rv-pc">' + pcDisp + "</span>" +
              "</div>" +
              ledRow(pcBits, G, "adr") +
            "</div>" +

            '<div class="regrow">' +
              '<div class="rowhead">' +
                '<span class="rlabel">Data Register (PSW)</span>' +
                '<span class="rval rv-ps">' + pswDisp + "</span>" +
              "</div>" +
              ledRow(pswBits, G, "dat") +
            "</div>" +
          "</div>" +

          '<div class="bar">' +
            '<div class="sysinfo">' +
              '<div class="syslbl">System</div>' +
              '<div class="sysval">' + sys + "</div>" +
            "</div>" +
            '<div class="indrow">' +
              '<div class="ind">' +
                '<div class="idot' + (running ? " on" : "") + '"></div>' +
                '<div class="ilbl">PROC</div>' +
              "</div>" +
              '<div class="ind">' +
                '<div class="idot"></div>' +
                '<div class="ilbl">BUS</div>' +
              "</div>" +
              '<div class="ind">' +
                '<div class="idot"></div>' +
                '<div class="ilbl">PAR ERR</div>' +
              "</div>" +
              '<div class="ind">' +
                '<div class="idot"></div>' +
                '<div class="ilbl">ADRS ERR</div>' +
              "</div>" +
            "</div>" +
          "</div>" +
        "</div>";
    };

    return PiDP11PanelCard;
  })();

  customElements.define("pidp11-panel-card", PiDP11PanelCard);

  // Register with the HA card picker
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "pidp11-panel-card",
    name: "PiDP-11 Front Panel",
    description:
      "Amber blinkenlight display for the PDP-11/70 emulator — " +
      "live address LEDs (PC), data LEDs (PSW), run/halt lamp, and current OS. " +
      "Animates at 20 Hz when the lamp stream is connected.",
    preview: true,
    documentationURL: "https://github.com/dmz006/pidp11-hacs",
  });
})();
