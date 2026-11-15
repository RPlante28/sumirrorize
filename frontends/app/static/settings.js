import { api, hide, show } from "./api.js";

const $ = (id) => document.getElementById(id);

// --- Brightspace ---

const POLL_MS = 2000;
const SIGN_IN_TIMEOUT_MS = 11 * 60 * 1000; // d3l's sign-in links last 10 minutes

const STATUS_TEXT = {
  connected: "Connected",
  disconnected: "Not connected. The mirror needs it to show your classes and assignments.",
  signingIn: "Finish signing in, in the tab that just opened...",
  unknown: "Couldn't check right now. Reload in a minute.",
};

let polling = null;

function setBrightspace(state) {
  const status = $("bs-status");
  status.dataset.state = state;
  status.textContent = STATUS_TEXT[state];
  status.classList.toggle("done", state === "connected");
  $("bs-connect").hidden = state === "connected";
  $("bs-connect").textContent = state === "signingIn" ? "Open the sign-in tab again" : "Connect Brightspace";
  $("bs-disconnect").hidden = state !== "connected";
}

async function connect() {
  hide($("bs-error"));
  // open the tab now, during the click. browsers block tabs opened later
  const tab = window.open("about:blank", "_blank");
  try {
    const { url } = await api("POST", "/me/brightspace");
    if (tab) tab.location.href = url;
    else location.href = url;  // pop-ups blocked, use this tab
    setBrightspace("signingIn");
    watchSignIn();
  } catch (error) {
    tab?.close();
    show($("bs-error"), error.message);
  }
}

function watchSignIn() {
  clearInterval(polling);
  const started = Date.now();
  polling = setInterval(async () => {
    try {
      const session = await api("GET", "/me/brightspace");
      if (session.signedIn) {
        clearInterval(polling);
        setBrightspace("connected");
      } else if (!session.signingIn || Date.now() - started > SIGN_IN_TIMEOUT_MS) {
        // the tab was closed or the link ran out
        clearInterval(polling);
        setBrightspace("disconnected");
      }
    } catch {
      // a missed check is fine
    }
  }, POLL_MS);
}

async function disconnect() {
  if (!confirm("Disconnect Brightspace? The mirror won't show your classes until you connect again.")) return;
  hide($("bs-error"));
  try {
    await api("DELETE", "/me/brightspace");
    setBrightspace("disconnected");
  } catch (error) {
    show($("bs-error"), error.message);
  }
}

// --- Google Calendar ---

async function disconnectCalendar() {
  if (!confirm("Disconnect Google Calendar? The mirror will only show your Brightspace events.")) return;
  hide($("cal-error"));
  try {
    await api("DELETE", "/me/calendar");
    location.reload();
  } catch (error) {
    show($("cal-error"), error.message);
  }
}

// --- Weather units ---

function unitLabel(units) {
  return units === "imperial" ? "The mirror shows \u00b0F and mph." : "The mirror shows \u00b0C and km/h.";
}

async function saveUnits() {
  const select = $("unitSwitch");
  const units = select.value;
  const previous = units === "imperial" ? "metric" : "imperial";
  select.disabled = true;
  try {
    await api("PUT", "/me/units", { units });
    $("unitLabel").textContent = unitLabel(units);
  } catch (error) {
    select.value = previous;
    $("unitLabel").textContent = error.message;
  } finally {
    select.disabled = false;
  }
}

// --- API key ---

async function newKey() {
  hide($("key-error"));
  const hasShown = !$("key-shown").hidden;
  if (hasShown && !confirm("Make another key? The one shown stops working.")) return;
  try {
    const { apiKey } = await api("POST", "/me/api-key");
    $("key").textContent = apiKey;
    $("key-shown").hidden = false;
  } catch (error) {
    show($("key-error"), error.message);
  }
}

// --- Account ---

async function deleteAccount() {
  if (!confirm("Delete your account? Your face pictures, connections and settings are erased for good.")) return;
  hide($("delete-error"));
  try {
    await api("DELETE", "/me");
    location.href = "/";
  } catch (error) {
    show($("delete-error"), error.message);
  }
}

setBrightspace($("bs-status").dataset.state);
$("unitLabel").textContent = unitLabel($("unitSwitch").value);
$("bs-connect").addEventListener("click", connect);
$("bs-disconnect").addEventListener("click", disconnect);
$("cal-disconnect")?.addEventListener("click", disconnectCalendar);
$("unitSwitch").addEventListener("change", saveUnits);
$("key-new").addEventListener("click", newKey);
$("delete").addEventListener("click", deleteAccount);
