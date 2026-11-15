import { api } from "./api.js";
import { GRID, horizontalAlignment, place } from "./layout-model.mjs";

const VARIANTS = {
  clock: { full: "Time and date", time: "Time only" },
  greeting: { greeting: "Greeting and name", name: "Name only" },
  weather: { compact: "Temperature", current: "Current weather", hourly: "Hourly forecast" },
  calendar: { comfortable: "Comfortable", compact: "Compact" },
  assignments: { comfortable: "Comfortable", compact: "Compact" },
  announcements: { detailed: "With previews", headlines: "Headlines only" },
};
const DEFAULTS = { clock: "full", greeting: "greeting", weather: "current", calendar: "comfortable",
  assignments: "comfortable", announcements: "detailed" };

const canvas = document.getElementById("layout-canvas");
const list = document.getElementById("widget-list");
const status = document.getElementById("editor-status");
const mirrorFrame = document.querySelector(".mirror-frame");
const widgetsToggle = document.getElementById("toggle-widgets");
const widgets = JSON.parse(document.getElementById("widget-data").dataset.widgets).map((widget) => ({
  ...widget,
  variant: widget.variant ?? DEFAULTS[widget.key] ?? "default",
}));
let selected = null;

function positionBox(box, widget) {
  box.dataset.align = horizontalAlignment(widget);
  box.style.left = `${widget.x * 100}%`;
  box.style.top = `${widget.y * 100}%`;
  box.style.width = `${widget.w * 100}%`;
  box.style.height = `${widget.h * 100}%`;
}

function drawCanvas() {
  canvas.replaceChildren();
  for (const widget of widgets) {
    if (!widget.enabled) continue;
    const box = document.createElement("article");
    box.className = "preview-widget";
    box.dataset.key = widget.key;
    box.tabIndex = 0;
    box.setAttribute("aria-label", `${widget.name}. Use arrow keys to move; hold Shift and use arrow keys to resize.`);
    positionBox(box, widget);

    const content = document.createElement("div");
    content.className = "preview-content";
    content.append(widget.name);
    if (VARIANTS[widget.key]) content.append(document.createElement("small"));
    if (content.lastElementChild) content.lastElementChild.textContent = VARIANTS[widget.key][widget.variant];

    const resize = document.createElement("button");
    resize.type = "button";
    resize.className = "resize-handle";
    resize.setAttribute("aria-label", `Resize ${widget.name}`);
    resize.addEventListener("pointerdown", (event) => startPointer(event, widget, "resize"));
    box.append(content, resize);
    box.addEventListener("focus", () => select(widget.key));
    box.addEventListener("pointerdown", (event) => {
      select(widget.key);
      if (!event.target.closest(".resize-handle")) startPointer(event, widget, "move");
    });
    box.addEventListener("keydown", (event) => useKeyboard(event, widget));
    if (widget.key === selected) box.classList.add("selected");
    canvas.append(box);
  }
}

function drawList() {
  list.replaceChildren();
  for (const widget of widgets) {
    const label = document.createElement("label");
    label.className = "widget-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = widget.enabled;
    input.addEventListener("change", () => {
      widget.enabled = input.checked;
      drawCanvas();
      changed(`${widget.name} ${input.checked ? "shown" : "hidden"}.`);
    });
    label.append(input, widget.name);
    if (VARIANTS[widget.key]) {
      const select = document.createElement("select");
      select.setAttribute("aria-label", `${widget.name} style`);
      for (const [value, text] of Object.entries(VARIANTS[widget.key])) select.add(new Option(text, value));
      select.value = widget.variant;
      select.addEventListener("change", () => {
        widget.variant = select.value;
        drawCanvas();
        changed(`${widget.name} style changed.`);
      });
      label.append(select);
    }
    list.append(label);
  }
}

function select(key) {
  if (selected === key) return;
  selected = key;
  for (const box of canvas.children) box.classList.toggle("selected", box.dataset.key === key);
}

function startPointer(event, widget, action) {
  event.preventDefault();
  select(widget.key);
  const start = { x: event.clientX, y: event.clientY, widget: { ...widget } };
  const handle = event.currentTarget;
  const box = handle.classList.contains("preview-widget") ? handle : handle.closest(".preview-widget");
  const bounds = canvas.getBoundingClientRect();
  handle.setPointerCapture(event.pointerId);
  const move = (nextEvent) => {
    Object.assign(widget, place(start.widget, action,
      (nextEvent.clientX - start.x) / bounds.width, (nextEvent.clientY - start.y) / bounds.height));
    positionBox(box, widget);
  };
  const done = () => {
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", done);
    handle.removeEventListener("pointercancel", done);
    changed(`${widget.name} ${action === "move" ? "moved" : "resized"}.`);
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", done);
  handle.addEventListener("pointercancel", done);
}

function useKeyboard(event, widget) {
  const delta = { ArrowLeft: [-GRID, 0], ArrowRight: [GRID, 0], ArrowUp: [0, -GRID], ArrowDown: [0, GRID] }[event.key];
  if (!delta) return;
  event.preventDefault();
  Object.assign(widget, place(widget, event.shiftKey ? "resize" : "move", ...delta));
  positionBox(event.currentTarget, widget);
  changed(`${widget.name} ${event.shiftKey ? "resized" : "moved"}.`);
}

function changed(message) { status.textContent = `${message} Not saved.`; }

document.getElementById("save-layout").addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  try {
    await api("PUT", "/me/widgets", { widgets });
    status.textContent = "Saved.";
  } catch (error) {
    status.textContent = `Could not save: ${error.message}`;
  } finally {
    event.currentTarget.disabled = false;
  }
});

document.getElementById("reset-layout").addEventListener("click", async (event) => {
  if (!confirm("Reset every widget to the default layout?")) return;
  event.currentTarget.disabled = true;
  try {
    await api("POST", "/me/widgets/reset");
    location.reload();
  } catch (error) {
    status.textContent = `Could not reset: ${error.message}`;
    event.currentTarget.disabled = false;
  }
});

widgetsToggle.addEventListener("click", () => {
  const open = document.body.classList.toggle("widgets-open");
  widgetsToggle.setAttribute("aria-expanded", String(open));
});

function fitPreviewToScreen() {
  mirrorFrame.style.setProperty("--screen-ratio", `${window.innerWidth} / ${window.innerHeight}`);
}

window.addEventListener("resize", fitPreviewToScreen);
fitPreviewToScreen();
drawList();
drawCanvas();
