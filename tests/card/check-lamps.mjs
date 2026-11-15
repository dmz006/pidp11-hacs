// Lamp feed checks for the PiDP-11 Lovelace card.
//
// Usage: node check-lamps.mjs <pidp11-panel-card.js> '<scenario-json>'
//
// The scenario is {"states": {"<entity_id>": "<state>"}, "steps": [...]}. The card
// is created the way Lovelace creates it and connected to a fake hass whose
// subscribeEvents keeps the callback per event type. Steps:
//   {"op": "live", "seq": n, "leds": {...}}   a pidp11_lamps2 frame
//   {"op": "old", "data": {...}}              a pidp11_lamps event
//   {"op": "state", "states": {...}}          entity states, then a hass update
//   {"op": "advance", "ms": n}                move the card's clock forward
//   {"op": "snap", "label": "..."}            record what is drawn
// The clock is a fake Date.now(); the card's 1 s staleness tick runs on real time,
// so "advance" also waits a little past one tick. Output is one JSON object with the
// snapshots, the subscribed event types and any errors. Nothing is thrown for card failures.

import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const [cardPath, scenarioJson] = process.argv.slice(2);
if (!cardPath || !scenarioJson) {
  console.error("usage: node check-lamps.mjs <pidp11-panel-card.js> '<scenario-json>'");
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

let fakeNow = 1_000_000;
window.Date.now = () => fakeNow;

const result = { subscribed: [], snaps: {}, errors: [] };

function fail(where, err) {
  const msg = err && err.message ? err.message : String(err);
  result.errors.push(`${where}: ${msg}`);
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

try {
  window.eval(source);
} catch (e) {
  fail("load", e);
}

const subs = {};
const hass = {
  states: {},
  connection: {
    subscribeEvents(cb, type) {
      result.subscribed.push(type);
      subs[type] = cb;
      return Promise.resolve(() => {
        delete subs[type];
      });
    },
  },
};

function setStates(states) {
  for (const [id, value] of Object.entries(states || {})) {
    hass.states[id] = { state: value };
  }
}

function snapshot(el) {
  const root = el.shadowRoot;
  const text = (sel) => {
    const node = root.querySelector(sel);
    return node ? node.textContent.trim() : null;
  };
  const lv = (node) => node.style.getPropertyValue("--lv");
  const lamps = {};
  root.querySelectorAll("[data-lamp]").forEach((node) => {
    lamps[node.getAttribute("data-lamp")] = lv(node);
  });
  const mode = root.querySelector(".lmode");
  return {
    mode: text(".lmode"),
    dataMode: mode ? mode.getAttribute("data-mode") : null,
    adr: [...root.querySelectorAll(".adr")].map(lv),
    dat: [...root.querySelectorAll(".dat")].map(lv),
    lamps,
    rvPc: text(".rv-pc"),
  };
}

let el = null;
try {
  setStates(scenario.states);
  el = document.createElement("pidp11-panel-card");
  el.setConfig(scenario.config || {});
  el.hass = hass;
  document.body.appendChild(el);
} catch (e) {
  fail("setup", e);
}

for (const step of scenario.steps || []) {
  try {
    if (!el) throw new Error("card was not created");
    switch (step.op) {
      case "live":
        if (!subs["pidp11_lamps2"]) throw new Error("pidp11_lamps2 is not subscribed");
        subs["pidp11_lamps2"]({ data: { seq: step.seq ?? 1, leds: step.leds } });
        await wait(40);
        break;
      case "old":
        if (!subs["pidp11_lamps"]) throw new Error("pidp11_lamps is not subscribed");
        subs["pidp11_lamps"]({ data: step.data });
        await wait(40);
        break;
      case "state":
        setStates(step.states);
        el.hass = hass;
        await wait(40);
        break;
      case "advance":
        fakeNow += step.ms;
        await wait(1150);
        break;
      case "snap":
        result.snaps[step.label] = snapshot(el);
        break;
      default:
        throw new Error(`unknown op ${step.op}`);
    }
  } catch (e) {
    fail(`step ${step.op}`, e);
  }
}

// Disconnect the card (stops the live timer) and close the window, so Node can exit.
try {
  if (el) el.remove();
} catch (e) {
  fail("disconnect", e);
}
window.close();

process.stdout.write(JSON.stringify(result));
