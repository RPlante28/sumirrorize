import json
import sys
import time
from pathlib import Path

import cv2
import pygame

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MODEL_PATH = DATA_DIR / "face-model.yml"
LABELS_PATH = DATA_DIR / "face-labels.json"
CONFIDENCE_LIMIT = 70
SESSION_TIMEOUT = 8 # timeout after face is not recognized
STABLE_MATCHES = 3


def update_session(state, recognized, face_present, now):
    current, pending, streak, last_face, last_confirmed = state
    if face_present:
        last_face = now

    # keep the current person around if they are still here
    if current != "UNKNOWN" and current in recognized:
        return current, "UNKNOWN", 0, last_face, now

    candidate = recognized[0] if recognized else "UNKNOWN"
    if candidate != "UNKNOWN":
        pending, streak = (pending, streak + 1) if candidate == pending else (candidate, 1)
        if streak >= STABLE_MATCHES:
            current, pending, streak, last_confirmed = candidate, "UNKNOWN", 0, now
    else:
        pending, streak = "UNKNOWN", 0
        if current != "UNKNOWN" and (
            (face_present and now - last_confirmed > SESSION_TIMEOUT)
            or (not face_present and now - last_face > SESSION_TIMEOUT)
        ):
            current = "UNKNOWN"

    return current, pending, streak, last_face, last_confirmed


def open_camera():
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise RuntimeError("Could not open the default camera")
    return camera


def load_detectors():
    # some OpenCV installs put this stuff somewhere else
    opencv_data = getattr(cv2, "data", None)
    cascade_dir = Path(opencv_data.haarcascades if opencv_data else "/usr/share/opencv4/haarcascades")
    front = cv2.CascadeClassifier(
        str(cascade_dir / "haarcascade_frontalface_default.xml")
    )
    profile = cv2.CascadeClassifier(
        str(cascade_dir / "haarcascade_profileface.xml")
    )
    if front.empty() or profile.empty():
        raise RuntimeError("Could not load the face detector")
    return front, profile


def detect_faces(gray_frame, detectors):
    settings = dict(scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    front, profile = detectors
    faces = front.detectMultiScale(gray_frame, **settings)
    # try the side view if the front view misses
    if not len(faces):
        faces = profile.detectMultiScale(gray_frame, **settings)
    if not len(faces):
        # flip it too in case they turned the other way
        faces = profile.detectMultiScale(cv2.flip(gray_frame, 1), **settings)
        faces = [
            (gray_frame.shape[1] - x - width, y, width, height)
            for x, y, width, height in faces
        ]
    return faces


def exit_requested():
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (
            event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
        ):
            return True
    return False


def draw_frame(frame):
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame_height, frame_width = frame.shape[:2]
    image = pygame.image.frombuffer(frame.tobytes(), (frame_width, frame_height), "RGB")
    window = pygame.display.get_surface()
    window_width, window_height = window.get_size()
    scale = min(window_width / frame_width, window_height / frame_height)
    size = (round(frame_width * scale), round(frame_height * scale))
    image = pygame.transform.smoothscale(image, size)
    window.fill("black")
    window.blit(image, ((window_width - size[0]) // 2, (window_height - size[1]) // 2))
    return window


def main():
    camera = None
    try:
        pygame.init()
        camera = open_camera()
        detectors = load_detectors()

        recognizer = None
        labels = []
        if MODEL_PATH.exists() and LABELS_PATH.exists():
            recognizer = cv2.face.LBPHFaceRecognizer_create()
            recognizer.read(str(MODEL_PATH))
            labels = json.loads(LABELS_PATH.read_text())

        pygame.display.set_caption("sumirrorize")
        pygame.display.set_mode((960, 540), pygame.RESIZABLE)
        clock = pygame.time.Clock()
        font = pygame.font.Font(None, 24)
        faces = () #track number of faces and stuff to keep track of the number of faces and stuff in da frame type sh
        frame_number = 0
        now = time.monotonic()
        session = ("UNKNOWN", "UNKNOWN", 0, now, now)

        while True:
            if exit_requested():
                return 0

            success, frame = camera.read()
            if not success:
                raise RuntimeError("Could not read a frame from the camera")

            # mirror the video feed to make it more like a MIRROR!!!!
            frame = cv2.flip(frame, 1)

            # look for face every three frame
            frame_number = (frame_number + 1) % 3
            if frame_number == 0:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = detect_faces(gray_frame, detectors)

                if recognizer:
                    matches = []
                    for x, y, width, height in faces:
                        face = cv2.resize(gray_frame[y : y + height, x : x + width], (200, 200))
                        # hopefully keeps the lighting from messing with the match
                        face = cv2.equalizeHist(face)
                        label, confidence = recognizer.predict(face)
                        # lower should mean a better match here
                        if confidence < CONFIDENCE_LIMIT and label < len(labels):
                            matches.append((confidence, labels[label]))
                    recognized = [name for _, name in sorted(matches)]
                    session = update_session(
                        session, recognized, bool(len(faces)), time.monotonic()
                    )

            for x, y, width, height in faces:
                cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 255, 0), 2)

            window = draw_frame(frame)
            if recognizer:
                text = font.render(f"ID {session[0].upper()}", False, "white", "black")
                window.blit(text, (4, 4))

            pygame.display.flip()
            clock.tick(60)
    except Exception as error:
        print(f"Camera error: {error}", file=sys.stderr)
        return 1
    finally:
        if camera is not None:
            camera.release()
        pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
