// Browser-free checks for the PiDP-11 Lovelace card.
//
// Usage: node check-card.mjs <path-to-pidp11-panel-card.js>
//
// Loads the card script into a jsdom window, creates the element the way
// Home Assistant does (document.createElement), exercises the Lovelace card
// contract, and prints one JSON object on stdout. It never throws for card
// failures: every failure is recorded in `errors` so the pytest side can
// report it. tests/integration/test_card_element.py asserts on this output.

import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const cardPath = process.argv[2];
if (!cardPath) {
  console.error("usage: node check-card.mjs <pidp11-panel-card.js>");
  process.exit(2);
}
const source = readFileSync(cardPath, "utf8");

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  runScripts: "outside-only",
  pretendToBeVisual: true,
  url: "http://localhost/",
});
const { window } = dom;
const { document } = window;

const result = {
  loaded: false,
  redefineOk: false,
  pickerRegistered: false,
  created: false,
  isHTMLElement: false,
  hasSetConfig: false,
  hasGetCardSize: false,
  cardSize: null,
  rendered: false,
  rvPc: null,
  subscribed: 0,
  unsubscribed: 0,
  errors: [],
};

function fail(where, err) {
  const msg = err && err.message ? err.message : String(err);
  result.errors.push(`${where}: ${msg}`);
}

// 1. Load the script the way a browser would.
try {
  window.eval(source);
  result.loaded = true;
} catch (e) {
  fail("load", e);
}

// 2. Loading again must not throw (customElements.define guard).
try {
  window.eval(source);
  result.redefineOk = true;
} catch (e) {
  fail("reload", e);
}

// 3. Card picker registration.
result.pickerRegistered = Array.isArray(window.customCards) &&
  window.customCards.some((c) => c && c.type === "pidp11-panel-card");

// 4. Create the element exactly as Lovelace does.
let el = null;
try {
  el = document.createElement("pidp11-panel-card");
  result.created = true;
} catch (e) {
  fail("createElement", e);
}

if (el) {
  result.isHTMLElement = el instanceof window.HTMLElement;
  result.hasSetConfig = typeof el.setConfig === "function";
  result.hasGetCardSize = typeof el.getCardSize === "function";

  try {
    if (!result.hasSetConfig) throw new TypeError("element has no setConfig");
    el.setConfig({});
  } catch (e) {
    fail("setConfig", e);
  }

  try {
    if (result.hasGetCardSize) result.cardSize = el.getCardSize();
  } catch (e) {
    fail("getCardSize", e);
  }

  // 5. Feed hass the way Lovelace does: states plus a connection with
  //    subscribeEvents. The lamp feed subscription is counted and its
  //    unsubscribe function is counted when called.
  const states = {
    "sensor.pidp11_cpu_state": { state: "running" },
    "sensor.pidp11_pc": { state: "000200" },
    "sensor.pidp11_psw": { state: "000000" },
    "sensor.pidp11_system": { state: "PDP-11/70" },
    "sensor.pidp11_cpu_mode": { state: "kernel" },
    "binary_sensor.pidp11_sr0": { state: "off" },
  };
  const hass = {
    states,
    connection: {
      subscribeEvents() {
        result.subscribed += 1;
        return Promise.resolve(() => {
          result.unsubscribed += 1;
        });
      },
    },
  };

  try {
    el.hass = hass;
    const root = el.shadowRoot;
    result.rendered = !!(root && root.querySelector(".card"));
    const pc = root && root.querySelector(".rv-pc");
    result.rvPc = pc ? pc.textContent : null;
  } catch (e) {
    fail("hass", e);
  }

  // 6. Connected then disconnected: the lamp subscription must be released.
  try {
    document.body.appendChild(el);
    el.remove();
    await new Promise((resolve) => setTimeout(resolve, 20));
  } catch (e) {
    fail("disconnect", e);
  }
}

process.stdout.write(JSON.stringify(result));
