// Shows the browser d3l is running for this sign-in and sends clicks and typing back to it.
// Positions are sent as fractions (0-1) of the picture, so window scaling doesn't matter.

const stage = document.getElementById("stage");
const canvas = document.getElementById("screen");
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

// --- Mouse / touch ---

const BUTTONS = ["left", "middle", "right"];

function position(event) {
  const box = canvas.getBoundingClientRect();
  return { x: (event.clientX - box.left) / box.width, y: (event.clientY - box.top) / box.height };
}

canvas.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  canvas.focus();
  canvas.setPointerCapture(event.pointerId);
  send({ type: "down", ...position(event), button: BUTTONS[event.button] });
});

canvas.addEventListener("pointerup", (event) => {
  event.preventDefault();
  send({ type: "up", ...position(event), button: BUTTONS[event.button] });
});

// Moves are sent at most once per animation frame.
let pendingMove = null;
canvas.addEventListener("pointermove", (event) => {
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
