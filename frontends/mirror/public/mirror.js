// The mirror display. Your face is the key: the page watches the webcam, sends a frame to the
// server twice a second, and shows the widgets of whoever it recognizes. When they leave, it
// clears. The camera's live view, flipped like a mirror, is the background. Frames aren't kept.

const REFRESH_MS = 5 * 60_000;      // widget data refresh while someone stays
const IDENTIFY_EVERY_MS = 500;
const FRAME_WIDTH = 640;            // frames are shrunk to this before sending

// Who's-there rules, from the face-recog mirror script (scripts/mirror.py):
const STABLE_MATCHES = 3;           // same person this many frames in a row before switching to them
const SESSION_TIMEOUT_MS = 8_000;   // clear the mirror after this long without recognizing them

const $ = (id) => document.getElementById(id);

// --- DOM helper: builds elements with text, never HTML, so Brightspace text can't inject markup ---

function h(tag, className, ...children) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

// Icons are fixed strings written here, so innerHTML is safe for them.
function icon(name) {
  const span = document.createElement("span");
  span.innerHTML = ICONS[name] ?? ICONS.cloudy;
  return span.firstElementChild;
}

// --- API ---

class PassExpired extends Error {}

/** One camera frame in, who's there out: { faces, person, pass, expiresAt }. */
async function identify(frame) {
  const response = await fetch("/api/identify", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: frame });
  if (response.status === 429) throw new Error("rate_limited");
  if (!response.ok) throw new Error(`identify: ${response.status}`);
  return response.json();
}

async function loadMirror(pass) {
  const response = await fetch("/api/mirror", { headers: { Authorization: `Bearer ${pass}` } });
  if (response.status === 401) throw new PassExpired();
  if (!response.ok) throw new Error(`mirror: ${response.status}`);
  return response.json();
}

// --- Time formatting (the mirror's own clock and timezone) ---

const fmt = (options) => new Intl.DateTimeFormat(undefined, options);
const timeFmt = fmt({ hour: "numeric", minute: "2-digit" });
const hourFmt = fmt({ hour: "numeric" });
const dateFmt = fmt({ weekday: "long", month: "long", day: "numeric" });
const weekdayFmt = fmt({ weekday: "long" });
const shortDayFmt = fmt({ weekday: "short" });
const monthDayFmt = fmt({ month: "short", day: "numeric" });

/** "3:41 PM" as ["3:41", "PM"] (period is "" on 24-hour clocks). */
function splitTime(date) {
  const parts = timeFmt.formatToParts(date);
  const period = parts.find((p) => p.type === "dayPeriod")?.value ?? "";
  const main = parts.filter((p) => p.type !== "dayPeriod").map((p) => p.value).join("").trim();
  return [main, period];
}

function startOfDay(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}
function daysFromToday(date) {
  return Math.round((startOfDay(date) - startOfDay(new Date())) / 86_400_000);
}
function dayName(date) {
  const days = daysFromToday(date);
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return weekdayFmt.format(date);
}
function dueText(date) {
  const days = daysFromToday(date);
  if (days === 0) return `today ${timeFmt.format(date)}`;
  if (days === 1) return `tomorrow ${timeFmt.format(date)}`;
  if (days > 1 && days < 7) return `${shortDayFmt.format(date)} ${timeFmt.format(date)}`;
  return monthDayFmt.format(date);
}
function postedText(date) {
  const days = daysFromToday(date);
  if (days === 0) return `Today ${timeFmt.format(date)}`;
  if (days === -1) return "Yesterday";
  if (days > -7) return weekdayFmt.format(date);
  return monthDayFmt.format(date);
}

function greetingWord(now) {
  const hour = now.getHours();
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// --- Widgets: each takes the widget's data and returns its contents ---

const live = []; // parts that update every second (clock, greeting)

const renderers = {
  clock() {
    const time = h("div", "clock-time");
    const date = h("div", "clock-date");
    live.push(() => {
      const now = new Date();
      const [main, period] = splitTime(now);
      time.replaceChildren(main, period ? h("small", null, period) : null);
      date.textContent = dateFmt.format(now);
    });
    return [time, date];
  },

  greeting(data) {
    const el = h("div", null);
    live.push(() => {
      const text = `${greetingWord(new Date())}, ${data.name}`;
      if (el.textContent === text) return;
      el.textContent = text;
      const content = el.closest(".widget-content");
      if (content) shrinkToFit(content);
    });
    return [el];
  },

  summary(data) {
    return [h("p", null, data.text || "Have a good day.")];
  },

  weather(data) {
    const unit = data.units.temperature;
    const deg = (t) => `${Math.round(t)}°`;
    const c = data.current;
    const alert = data.alerts?.[0];
    return [
      alert ? h("div", "weather-alert", `⚠ ${alert.event}`) : null,
      h("div", "weather-now", icon(weatherIcon(c.weatherCode, c.isDay)), h("div", "weather-temp", deg(c.temperature))),
      h("div", "weather-desc", `${c.description} · feels ${deg(c.feelsLike)}${unit.slice(-1)}`),
      h("div", "weather-detail",
        `H ${deg(data.today.high)}  L ${deg(data.today.low)}  ·  ${c.windDirection} ${Math.round(c.windSpeed)} ${data.units.speed}`),
      h("div", "hourly", ...data.hourly.slice(1, 7).map((hour) => h("div", null,
        h("div", "hour-time", hourFmt.format(new Date(hour.time))),
        icon(weatherIcon(hour.weatherCode, hour.isDay)),
        h("div", null, deg(hour.temperature)),
        h("div", "hour-rain", hour.precipitationChance >= 20 ? `${Math.round(hour.precipitationChance)}%` : " "),
      ))),
    ];
  },

  calendar(data) {
    const list = h("div", "list");
    if (data.events.length === 0) list.append(h("div", "empty", "Nothing coming up this week."));
    let lastDay = null;
    for (const event of data.events) {
      const starts = new Date(event.starts);
      const day = dayName(starts);
      if (day !== lastDay) {
        list.append(h("div", "day", day));
        lastDay = day;
      }
      const details = [event.course, event.location].filter(Boolean).join(" · ");
      list.append(h("div", "row",
        h("div", "row-when", event.allDay ? "All day" : timeFmt.format(starts)),
        h("div", null,
          h("div", "ellipsis", event.title),
          details ? h("div", "meta ellipsis", details) : null),
      ));
    }
    return [h("div", "label", "Calendar"), list];
  },

  assignments(data) {
    const list = h("div", "list");
    if (data.assignments.length === 0) list.append(h("div", "empty", "Nothing due. Nice."));
    for (const work of data.assignments) {
      const due = new Date(work.due);
      const when = work.overdue
        ? h("span", "late", `Overdue, was due ${monthDayFmt.format(due)}`)
        : `Due ${dueText(due)}`;
      list.append(h("div", null,
        h("div", "ellipsis", work.name),
        h("div", "meta ellipsis", when, work.course ? ` · ${work.course}` : null),
      ));
    }
    return [h("div", "label", "Assignments"), list];
  },

  announcements(data) {
    const list = h("div", "list");
    if (data.announcements.length === 0) list.append(h("div", "empty", "No announcements in the last two weeks."));
    for (const item of data.announcements) {
      list.append(h("div", null,
        h("div", "ellipsis", item.title),
        h("div", "meta ellipsis", [item.course, postedText(new Date(item.posted))].filter(Boolean).join(" · ")),
        item.text ? h("div", "item-text", item.text) : null,
      ));
    }
    return [h("div", "label", "Announcements"), list];
  },
};

function renderWidget(widget) {
  // The outer box is placed and sized; the inner one holds the content. Text sizes in cqh/cqw
  // only measure against a parent box, which is why the content needs its own element.
  const box = h("div", "widget");
  box.style.setProperty("left", `${widget.x * 100}%`);
  box.style.setProperty("top", `${widget.y * 100}%`);
  box.style.setProperty("width", `${widget.w * 100}%`);
  box.style.setProperty("height", `${widget.h * 100}%`);

  const content = h("div", `widget-content w-${widget.key}`);
  const render = renderers[widget.key];
  if (widget.error) {
    content.append(h("div", "widget-error", widget.error.code === "signin_required"
      ? "Connect Brightspace in the app to see this."
      : `${widget.name} is unavailable right now.`));
  } else if (render) {
    content.append(...render(widget.data).filter(Boolean));
  }
  box.append(content);
  return box;
}

// --- Fitting content to its box ---

/** Shows only the list items that fit whole, and counts the rest in a "+N more" line. */
function fitList(list) {
  list.querySelector(":scope > .more")?.remove();
  const children = [...list.children];
  for (const child of children) child.hidden = false;

  const bottom = list.getBoundingClientRect().bottom + 1;
  const overflows = (el) => el.getBoundingClientRect().bottom > bottom;
  const firstHidden = children.findIndex(overflows);
  if (firstHidden === -1) return;

  for (const child of children.slice(firstHidden)) child.hidden = true;
  const visible = children.slice(0, firstHidden);
  const more = h("div", "more");
  list.append(more);
  const count = () => {
    const hiddenItems = children.filter((c) => c.hidden && !c.classList.contains("day")).length;
    more.textContent = `+${hiddenItems} more`;
  };
  count();
  // Make room for the "+N more" line itself, then drop any day heading left with nothing under it.
  while (visible.length && overflows(more)) {
    visible.pop().hidden = true;
    count();
  }
  while (visible.length && visible.at(-1).classList.contains("day")) visible.pop().hidden = true;
  count();
}

/** Shrinks a text widget's font until all of its text fits. */
function shrinkToFit(content) {
  content.style.removeProperty("font-size");
  let size = parseFloat(getComputedStyle(content).fontSize);
  while (content.scrollHeight > content.clientHeight + 1 && size > 9) {
    size *= 0.92;
    content.style.setProperty("font-size", `${size}px`);
  }
}

function fitAll() {
  for (const list of document.querySelectorAll("#widgets .list")) fitList(list);
  for (const text of document.querySelectorAll("#widgets .w-greeting, #widgets .w-summary")) shrinkToFit(text);
}

// --- Weather icons ---

function weatherIcon(code, isDay) {
  if (code <= 1) return isDay ? "sun" : "moon";
  if (code === 2) return isDay ? "partly" : "partlyNight";
  if (code === 3) return "cloudy";
  if (code === 45 || code === 48) return "fog";
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "snow";
  if (code >= 95) return "storm";
  return "rain";
}

const svg = (body) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const CLOUD = "M7 18.5h10.5a4 4 0 0 0 .4-7.98 6 6 0 0 0-11.6 1.1A3.5 3.5 0 0 0 7 18.5z";
const SMALL_CLOUD = "M7 15h9a3.5 3.5 0 0 0 .3-7 5 5 0 0 0-9.7 1A3 3 0 0 0 7 15z";
const ICONS = {
  sun: svg(`<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/>`),
  moon: svg(`<path d="M19.5 14.8A8 8 0 0 1 9.2 4.5a8 8 0 1 0 10.3 10.3z"/>`),
  partly: svg(`<path d="M8 3v1.5M3.6 5.6l1 1M2 10h1.5M12.4 5.6l-1 1"/><path d="M5.3 11.6A3.5 3.5 0 0 1 11 7.8"/><path d="${CLOUD}"/>`),
  partlyNight: svg(`<path d="M10.5 4.2a4.5 4.5 0 0 0-5.8 6.3"/><path d="${CLOUD}"/>`),
  cloudy: svg(`<path d="${CLOUD}"/>`),
  fog: svg(`<path d="M4 9h16M3 13h18M5 17h14"/>`),
  rain: svg(`<path d="${SMALL_CLOUD}"/><path d="M8 18l-1 2.5M12 18l-1 2.5M16 18l-1 2.5"/>`),
  snow: svg(`<path d="${SMALL_CLOUD}"/><path d="M8 19h.01M12 20.5h.01M16 19h.01M10 21.5h.01M14 22h.01"/>`),
  storm: svg(`<path d="${SMALL_CLOUD}"/><path d="M12.5 15.5l-2 3.5h3l-2 3.5"/>`),
};

// --- Screens ---

function show(screen) {
  for (const id of ["idle", "mirror"]) $(id).hidden = id !== screen;
}

function tick() {
  for (const update of live) update();
}

function idleClock() {
  live.length = 0;
  live.push(() => {
    const now = new Date();
    $("idle-time").textContent = splitTime(now)[0];
    $("idle-date").textContent = dateFmt.format(now);
  });
  tick();
}

function setPrompt(text, showRetry = false) {
  $("idle-prompt").textContent = text;
  $("camera-retry").hidden = !showRetry;
}

// --- Who's at the mirror ---

const session = {
  person: null,       // { id, name } of whoever the mirror is showing
  pass: null,         // proof from the server that it recognized them; needed to load their data
  pending: null,      // someone recognized but not yet confirmed
  streak: 0,
  lastFace: 0,
  lastConfirmed: 0,
};
let refreshTimer = null;

/** Applies one recognition result. Ported from update_session in scripts/mirror.py. */
function update(result, now) {
  const recognized = result.person;
  if (result.faces > 0) session.lastFace = now;

  // Still the same person: keep them, and keep the newest pass.
  if (session.person && recognized?.id === session.person.id) {
    session.pass = result.pass;
    session.lastConfirmed = now;
    session.pending = null;
    session.streak = 0;
    return;
  }

  if (recognized) {
    if (session.pending?.id === recognized.id) session.streak += 1;
    else Object.assign(session, { pending: recognized, streak: 1 });
    if (session.streak >= STABLE_MATCHES) {
      Object.assign(session, { person: recognized, pass: result.pass, lastConfirmed: now, pending: null, streak: 0 });
      showPerson();
    }
    return;
  }

  session.pending = null;
  session.streak = 0;
  const gone = result.faces > 0
    ? now - session.lastConfirmed > SESSION_TIMEOUT_MS   // someone's there, but not them
    : now - session.lastFace > SESSION_TIMEOUT_MS;       // nobody's there
  if (session.person && gone) showNobody();
}

async function showPerson() {
  show("mirror");
  clearInterval(refreshTimer);
  await refresh();
  refreshTimer = setInterval(refresh, REFRESH_MS);
}

function showNobody() {
  Object.assign(session, { person: null, pass: null });
  clearInterval(refreshTimer);
  // Their data leaves the screen (and the page) as soon as they do.
  $("widgets").replaceChildren();
  idleClock();
  setPrompt("Step up to the mirror");
  show("idle");
}

async function refresh() {
  const person = session.person;
  if (!person) return;
  try {
    const mirror = await loadMirror(session.pass);
    if (session.person?.id !== person.id) return; // they left while it loaded
    live.length = 0;
    $("widgets").replaceChildren(...mirror.widgets.map(renderWidget));
    $("offline").hidden = true;
    tick();
    fitAll();
  } catch (error) {
    // An expired pass gets replaced on the next recognition; anything else, keep the old data up.
    if (!(error instanceof PassExpired)) $("offline").hidden = false;
  }
}

// --- Camera ---

const video = $("camera");
const canvas = document.createElement("canvas");

async function startCamera() {
  try {
    video.srcObject = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    await video.play();
    setPrompt("Step up to the mirror");
    return true;
  } catch (error) {
    const blocked = error?.name === "NotAllowedError";
    setPrompt(blocked ? "The mirror needs camera access to recognize you." : "No camera found.", blocked);
    return false;
  }
}

function captureFrame() {
  const scale = Math.min(1, FRAME_WIDTH / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
}

let watching = false;

/** Starts the recognition loop (once). */
function startWatching() {
  if (watching) return;
  watching = true;
  watch();
}

/** Sends a frame, applies the answer, and schedules the next one. Only one request at a time. */
async function watch() {
  let delay = IDENTIFY_EVERY_MS;
  if (!document.hidden && video.videoWidth) {
    try {
      const frame = await captureFrame();
      update(await identify(frame), performance.now());
      if (!session.person) setPrompt("Step up to the mirror");
    } catch (error) {
      delay = 2000;
      if (error.message !== "rate_limited" && !session.person) setPrompt("Can't reach the server…");
      // Treat a failed check like an empty frame, so the mirror still clears when it should.
      update({ faces: 0, person: null }, performance.now());
    }
  }
  setTimeout(watch, delay);
}

// --- Start ---

async function start() {
  setInterval(tick, 1000);

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(fitAll, 150);
  });
  // Esc clears the mirror right away (it comes back if they're still there).
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && session.person) showNobody();
  });
  $("camera-retry").addEventListener("click", async () => {
    if (await startCamera()) startWatching();
  });

  showNobody();
  if (await startCamera()) startWatching();
}

start();
