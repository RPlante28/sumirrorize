// Shows the browser d3l is running for this sign-in and sends clicks and typing back to it.
// Positions are sent as fractions (0-1) of the picture, so window scaling doesn't matter.

const stage = document.getElementById("stage");
const canvas = document.getElementById("screen");
const keys = document.getElementById("keys");
const statusText = document.getElementById("status");
const message = document.getElementById("message");
const ctx = canvas.getContext("2d");

const socketUrl = location.origin.replace(/^http/, "ws") + location.pathname.replace(/\/$/, "") + "/stream";
const socket = new WebSocket(socketUrl);
socket.binaryType = "blob";
let finished = false;

function send(data) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data));
}

function finish(text, ok = false) {
  finished = true;
  canvas.hidden = true;
  message.hidden = false;
  message.textContent = text;
  statusText.textContent = ok ? "Signed in" : "Closed";
  statusText.classList.toggle("ok", ok);
}

// --- Screen ---

// Frames are decoded asynchronously; drop any that finish after a newer one was drawn.
let frameCount = 0;
let drawnFrame = 0;

async function drawFrame(blob) {
  const frame = ++frameCount;
  const bitmap = await createImageBitmap(blob);
  if (frame > drawnFrame) {
    drawnFrame = frame;
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
    }
    ctx.drawImage(bitmap, 0, 0);
  }
  bitmap.close();
}

socket.addEventListener("open", () => {
  statusText.textContent = "Sign in as you normally would. This window is a browser running on the Sumirrorize server.";
  sendSize();
  canvas.focus();
});

socket.addEventListener("message", (event) => {
  if (typeof event.data !== "string") {
    drawFrame(event.data);
    return;
  }
  const { type } = JSON.parse(event.data);
  if (type === "done") {
    finish("You're signed in. You can close this tab.", true);
    // Only works when the app opened this tab itself, which is the normal case.
    setTimeout(() => window.close(), 1500);
  } else if (type === "expired") {
    finish("This sign-in timed out. Start again from the app.");
  }
});

socket.addEventListener("close", (event) => {
  if (finished) return;
  finish(
    event.code === 4409
      ? "This sign-in is already open in another tab."
      : "Lost connection to the sign-in. Start again from the app."
  );
});

// Match the remote browser to this window so the picture is sharp and 1:1.
let resizeTimer;
function sendSize() {
  send({ type: "resize", width: stage.clientWidth, height: stage.clientHeight });
}
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(sendSize, 200);
});

// --- Mouse ---

const BUTTONS = ["left", "middle", "right"];

function position(event) {
  const box = canvas.getBoundingClientRect();
  return { x: (event.clientX - box.left) / box.width, y: (event.clientY - box.top) / box.height };
}

canvas.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  if (event.pointerType === "touch") {
    startTouch(event);
    return;
  }
  canvas.focus();
  canvas.setPointerCapture(event.pointerId);
  send({ type: "down", ...position(event), button: BUTTONS[event.button] });
});

canvas.addEventListener("pointerup", (event) => {
  event.preventDefault();
  if (event.pointerType === "touch") {
    endTouch(event);
    return;
  }
  send({ type: "up", ...position(event), button: BUTTONS[event.button] });
});

// Moves are sent at most once per animation frame.
let pendingMove = null;
canvas.addEventListener("pointermove", (event) => {
  if (event.pointerType === "touch") {
    moveTouch(event);
    return;
  }
  if (!pendingMove) requestAnimationFrame(() => {
    send({ type: "move", ...pendingMove });
    pendingMove = null;
  });
  pendingMove = position(event);
});

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.height : 1;
  send({ type: "wheel", ...position(event), dx: event.deltaX * scale, dy: event.deltaY * scale });
}, { passive: false });

canvas.addEventListener("contextmenu", (event) => event.preventDefault());

// --- Touch: a tap is a click, a drag scrolls ---

const DRAG_STARTS_AFTER = 10; // pixels a finger can wobble and still count as a tap
let touch = null;             // the finger on the screen: where it started and where it was last

function startTouch(event) {
  touch = { id: event.pointerId, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, dragging: false };
  canvas.setPointerCapture(event.pointerId);
}

function moveTouch(event) {
  if (event.pointerId !== touch?.id) return;
  if (!touch.dragging && Math.hypot(event.clientX - touch.startX, event.clientY - touch.startY) < DRAG_STARTS_AFTER) return;
  touch.dragging = true;
  // The picture may be shown smaller than the remote page really is; scroll in the page's pixels.
  const scale = canvas.width / canvas.getBoundingClientRect().width;
  send({ type: "wheel", ...position(event), dx: (touch.x - event.clientX) * scale, dy: (touch.y - event.clientY) * scale });
  touch.x = event.clientX;
  touch.y = event.clientY;
}

function endTouch(event) {
  if (event.pointerId !== touch?.id) return;
  const tapped = !touch.dragging;
  touch = null;
  if (!tapped) return;
  const at = position(event);
  send({ type: "down", ...at, button: "left" });
  send({ type: "up", ...at, button: "left" });
  showKeyboard(event);
}

canvas.addEventListener("pointercancel", () => {
  touch = null;
});

// --- Keyboard ---

canvas.addEventListener("keydown", (event) => {
  // Let Ctrl/Cmd+V through so the paste event below fires (for password managers).
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") return;
  event.preventDefault();
  send({
    type: "key",
    key: event.key,
    ctrl: event.ctrlKey,
    alt: event.altKey,
    meta: event.metaKey,
    shift: event.shiftKey,
  });
});

document.addEventListener("paste", (event) => {
  event.preventDefault();
  const text = event.clipboardData.getData("text");
  if (text) send({ type: "text", text });
});

// --- Phone keyboards ---
//
// A phone only shows its keyboard for a real text field, and what it types often doesn't arrive
// as key presses. So a tap puts the cursor in an invisible field (#keys), and whatever changes in
// that field is passed on: new characters are typed, removed ones become Backspace.

// The field always holds this, so there's something for Backspace to delete.
const FILLER = "  ";
let typed = FILLER;
keys.value = FILLER;

/** Brings up the keyboard. Must be called while handling a tap, or phones ignore it. */
function showKeyboard(event) {
  // Sitting where the tap was, the phone scrolls that spot into view above its keyboard.
  keys.style.left = `${event.clientX}px`;
  keys.style.top = `${event.clientY}px`;
  keys.focus();
}

keys.addEventListener("input", (event) => {
  const now = keys.value;
  let same = 0;
  while (same < typed.length && same < now.length && typed[same] === now[same]) same++;
  for (let i = same; i < typed.length; i++) send({ type: "key", key: "Backspace" });
  const added = now.slice(same);
  if (added.length === 1) send({ type: "key", key: added });
  else if (added) send({ type: "text", text: added }); // a suggestion, autofill or paste
  // Some keyboards build a word up in the field before settling on it; leave it alone meanwhile.
  if (event.isComposing) {
    typed = now;
  } else {
    typed = keys.value = FILLER;
  }
});

keys.addEventListener("compositionend", () => {
  typed = keys.value = FILLER;
});

keys.addEventListener("keydown", (event) => {
  // Characters and Backspace show up as changes to the field (above). Named keys don't.
  if (event.key.length === 1 || ["Backspace", "Unidentified", "Process", "Dead"].includes(event.key)) return;
  event.preventDefault();
  send({ type: "key", key: event.key, ctrl: event.ctrlKey, alt: event.altKey, meta: event.metaKey, shift: event.shiftKey });
});
