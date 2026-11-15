// Takes one picture per angle, then sends them all to be checked and saved. If some aren't good
// enough, it goes back to just those, says why, and sends again.
import { api, hide, show } from "./api.js";

const $ = (id) => document.getElementById(id);

const STEPS = [
  { angle: "front", title: "FRONT FACING", instruction: "Look directly at the camera." },
  { angle: "left", title: "LEFT ANGLE", instruction: "Turn your head slightly to the left." },
  { angle: "right", title: "RIGHT ANGLE", instruction: "Turn your head slightly to the right." },
  { angle: "up", title: "UP ANGLE", instruction: "Tilt your head slightly up." },
  { angle: "down", title: "DOWN ANGLE", instruction: "Tilt your head slightly down." },
];

// What the faces service says is wrong with a picture, in words.
const PROBLEMS = {
  no_face: "We couldn't find your face. Make sure your whole face is in the circle.",
  several_faces: "There's more than one face in the picture. Make sure only you are in view.",
  too_small: "Your face is too small. Move closer to the camera.",
  bad_lighting: "It's too dark or too bright. Face a light, or move away from a bright window.",
};

const MAX_SIDE = 1280; // plenty for recognition, and keeps uploads small
const JPEG_QUALITY = 0.9;

const video = $("video");
const canvas = $("canvas");
const captureBtn = $("capture");
const retryBtn = $("retry");

const photos = new Array(STEPS.length).fill(null); // data URLs
const problems = new Array(STEPS.length).fill(null); // problem codes from the last upload
let current = 0;
let reviewing = false; // showing the photo just taken, waiting for Next or Retake
let saving = false;

/** The first step still needing a (good) photo, or -1 when every photo is ready to send. */
function nextStep() {
  return STEPS.findIndex((_, i) => !photos[i] || problems[i]);
}

function render() {
  const step = STEPS[current];
  $("stepTitle").textContent = `STEP ${current + 1}: ${step.title}`;
  $("instruction").textContent = step.instruction;
  const ready = photos.filter((photo, i) => photo && !problems[i]).length;
  $("progress").style.width = `${(ready / STEPS.length) * 100}%`;

  video.hidden = reviewing;
  canvas.hidden = !reviewing;
  retryBtn.hidden = !reviewing || saving;
  $("success").hidden = !reviewing || saving;
  if (saving) captureBtn.textContent = "Saving…";
  else if (!reviewing) captureBtn.textContent = "Capture Photo";
  else captureBtn.textContent = nextAfter(current) === -1 ? "Complete Registration" : "Next Angle";
  captureBtn.disabled = saving || !video.videoWidth;

  $("checklist").replaceChildren(
    ...STEPS.map((s, i) => {
      const item = document.createElement("p");
      const done = photos[i] && !problems[i];
      item.className = done ? "done" : problems[i] ? "problem" : "";
      item.textContent = `${done ? "✓" : problems[i] ? "✕" : "○"} ${s.title.toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}`;
      return item;
    })
  );
}

/** The step to go to after this one, assuming this one's photo is now good. */
function nextAfter(index) {
  return STEPS.findIndex((_, i) => i !== index && (!photos[i] || problems[i]));
}

function capture() {
  const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  // The picture is saved as the camera sees it (not mirrored), the same way the mirror sees you.
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  photos[current] = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  problems[current] = null;
  reviewing = true;
  hide($("error"));
  render();
}

function retake() {
  photos[current] = null;
  reviewing = false;
  render();
}

async function next() {
  reviewing = false;
  const step = nextStep();
  if (step !== -1) {
    current = step;
    showProblem();
    render();
    return;
  }
  await save();
}

function showProblem() {
  if (problems[current]) show($("error"), PROBLEMS[problems[current]] || "Please retake this picture.");
  else hide($("error"));
}

async function save() {
  saving = true;
  reviewing = true;
  render();
  try {
    await api("PUT", "/me/faces", {
      pictures: STEPS.map((s, i) => ({ angle: s.angle, image: photos[i] })),
    });
    finish();
  } catch (error) {
    saving = false;
    reviewing = false;
    if (error.code === "poor_pictures") {
      for (const result of error.body.pictures) {
        problems[STEPS.findIndex((s) => s.angle === result.angle)] = result.problem;
      }
      current = nextStep();
      showProblem();
    } else {
      // Nothing was wrong with the pictures (e.g. offline): stay on the last one so they can send again.
      reviewing = true;
      show($("error"), error.message);
    }
    render();
  }
}

function finish() {
  video.srcObject?.getTracks().forEach((track) => track.stop());
  $("camera-box").hidden = true;
  $("progress").style.width = "100%";
  $("finish").hidden = false;
  render();
}

captureBtn.addEventListener("click", () => (reviewing ? next() : capture()));
retryBtn.addEventListener("click", retake);
video.addEventListener("loadedmetadata", render);

async function startCamera() {
  try {
    video.srcObject = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
  } catch {
    show($("error"), "Camera access unavailable. Please allow camera permission and reload the page.");
  }
}

render();
startCamera();
