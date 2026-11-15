// Entity lookup checks for the PiDP-11 Lovelace card.
//
// Usage: node check-entities.mjs <pidp11-panel-card.js> '<scenario-json>'
//
// The scenario is {"config": {...}, "states": {"<entity_id>": {"state": "..."}}}.
// The card is created the way Lovelace creates it, given the config and the
// states, and then the rendered output is reported as JSON on stdout. Only
// what a user would see is reported (header text, PC readout, lit SR
// switches), so the pytest side stays independent of card internals.
// Card failures are recorded in `errors` and never thrown.

import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const [cardPath, scenarioJson] = process.argv.slice(2);
if (!cardPath || !scenarioJson) {
  console.error("usage: node check-entities.mjs <pidp11-panel-card.js> '<scenario-json>'");
  process.exit(2);
}
const source = readFileSync(cardPath, "utf8");
const scenario = JSON.parse(scenarioJson);

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  runScripts: "outside-only",
  pretendToBeVisual: true,
  url: "http://localhost/",
});
const { window } = dom;
const { document } = window;

const result = {
  rendered: false,
  cpuText: null,
  sysText: null,
  rvPc: null,
  srOn: null,
  errors: [],
};

function fail(where, err) {
  const msg = err && err.message ? err.message : String(err);
  result.errors.push(`${where}: ${msg}`);
}

try {
  window.eval(source);
} catch (e) {
  fail("load", e);
}

try {
  const el = document.createElement("pidp11-panel-card");
  el.setConfig(scenario.config || {});
  const hass = {
    states: scenario.states || {},
    connection: { subscribeEvents: () => Promise.resolve(() => {}) },
  };
  el.hass = hass;
  const root = el.shadowRoot;
  if (root && root.querySelector(".card")) {
    result.rendered = true;
    const text = (sel) => {
      const node = root.querySelector(sel);
      return node ? node.textContent.trim() : null;
    };
    result.cpuText = text(".cpustate");
    result.sysText = text(".sysval");
    result.rvPc = text(".rv-pc");
    result.srOn = root.querySelectorAll(".sw.on").length;
  }
} catch (e) {
  fail("render", e);
}

process.stdout.write(JSON.stringify(result));
