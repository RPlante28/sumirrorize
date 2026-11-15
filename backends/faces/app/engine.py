"""
Finding faces in a picture and turning each into a fingerprint: 128 numbers that are close
together for the same person. Uses three free models:
- YuNet finds faces: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- SFace makes fingerprints: https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface
- open-closed-eye says whether an eye is open, for the mirror's blink check:
  https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/public/open-closed-eye-0001
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import cv2
import numpy as np

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"
EYES_FILE = "open_closed_eye.onnx"

# Bigger pictures are shrunk first; faces stay plenty big and detection stays fast.
MAX_SIDE = 1280
DETECTION_CONFIDENCE = 0.8

# Sign-up photo checks, from the face-recog enrollment script (scripts/enrollment.py).
MIN_ENROLL_FACE = 80          # pixels wide
MIN_BRIGHTNESS, MAX_BRIGHTNESS = 35, 220
# At the mirror, ignore faces this small: someone far behind, not the person at the mirror.
MIN_MIRROR_FACE = 60

# The eye model takes a 32-pixel square around one eye. How much of the face that square should
# cover varies from face to face, so each eye is cut out at several sizes (as fractions of the
# distance between the eyes) and the answers are averaged, which is much steadier than one size.
EYE_SIZE = 32
EYE_CROP_SCALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


@dataclass(frozen=True)
class Face:
    width: int                 # pixels, in the picture as given
    brightness: float          # 0-255, average over the face
    fingerprint: np.ndarray    # 128 float32 numbers
    eyes_open: float           # 0 (both eyes shut) to 1 (both wide open)


@dataclass(frozen=True)
class Analysis:
    faces: list[Face]          # largest first

    @property
    def largest(self) -> Optional[Face]:
        return self.faces[0] if self.faces else None


class BadImage(ValueError):
    """The bytes aren't a picture OpenCV can read."""


class Engine(Protocol):
    def analyze(self, image: bytes) -> Analysis: ...


class OpenCvEngine:
    def __init__(self, models_dir: Path):
        for name in (DETECTOR_FILE, RECOGNIZER_FILE, EYES_FILE):
            if not (models_dir / name).is_file():
                raise RuntimeError(f"Missing model {models_dir / name} (see backends/faces/README.md)")
        self._detector = cv2.FaceDetectorYN.create(str(models_dir / DETECTOR_FILE), "", (320, 320), DETECTION_CONFIDENCE)
        self._recognizer = cv2.FaceRecognizerSF.create(str(models_dir / RECOGNIZER_FILE), "")
        self._eyes = cv2.dnn.readNetFromONNX(str(models_dir / EYES_FILE))
        # The OpenCV objects keep state between calls, so only one picture at a time.
        self._lock = threading.Lock()

    def analyze(self, image: bytes) -> Analysis:
        picture = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if picture is None:
            raise BadImage("Not a readable image")
        scale = min(1.0, MAX_SIDE / max(picture.shape[:2]))
        if scale < 1:
            picture = cv2.resize(picture, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY)

        with self._lock:
            self._detector.setInputSize((picture.shape[1], picture.shape[0]))
            _, found = self._detector.detect(picture)
            rows = [] if found is None else sorted(found, key=lambda f: f[2] * f[3], reverse=True)
            faces = []
            for row in rows:
                x, y, w, h = (max(0, int(v)) for v in row[:4])
                crop = gray[y:y + h, x:x + w]
                fingerprint = self._recognizer.feature(self._recognizer.alignCrop(picture, row)).flatten()
                faces.append(Face(
                    width=round(w / scale),
                    brightness=float(crop.mean()) if crop.size else 0.0,
                    fingerprint=fingerprint.astype(np.float32),
                    eyes_open=self._eyes_open(picture, row),
                ))
        return Analysis(faces)

    def _eyes_open(self, picture: np.ndarray, row: np.ndarray) -> float:
        """How open the face's eyes are. `row` is YuNet's result, which includes where each eye is."""
        right, left = row[4:6].astype(np.float32), row[6:8].astype(np.float32)
        apart = float(np.linalg.norm(left - right))
        if apart < 1:
            return 0.0
        # Turn each cut-out so the eyes sit level, as in the pictures the model learned from.
        tilt = float(np.degrees(np.arctan2(left[1] - right[1], left[0] - right[0])))
        crops = []
        for eye in (right, left):
            for scale in EYE_CROP_SCALES:
                matrix = cv2.getRotationMatrix2D((float(eye[0]), float(eye[1])), tilt, EYE_SIZE / (apart * scale))
                matrix[:, 2] += EYE_SIZE / 2 - eye
                crops.append(cv2.warpAffine(picture, matrix, (EYE_SIZE, EYE_SIZE), flags=cv2.INTER_AREA,
                                            borderMode=cv2.BORDER_REPLICATE))
        self._eyes.setInput(cv2.dnn.blobFromImages(crops, 1 / 255, (EYE_SIZE, EYE_SIZE), (127, 127, 127)))
        # One row per cut-out: [chance it's closed, chance it's open].
        return float(self._eyes.forward().reshape(len(crops), 2)[:, 1].mean())


def enrollment_problem(analysis: Analysis) -> Optional[str]:
    """Why a sign-up photo isn't good enough, or None if it's fine."""
    if not analysis.faces:
        return "no_face"
    if len(analysis.faces) > 1:
        return "several_faces"
    face = analysis.faces[0]
    if face.width < MIN_ENROLL_FACE:
        return "too_small"
    if not MIN_BRIGHTNESS <= face.brightness <= MAX_BRIGHTNESS:
        return "bad_lighting"
    return None


def other_people(fingerprints: list[np.ndarray], threshold: float) -> set[int]:
    """
    Which of one person's sign-up pictures (by position) look like someone else. Pictures from
    different angles don't all match each other, so each is compared with the most typical one:
    the picture that's most like all the rest.
    """
    if len(fingerprints) < 2:
        return set()
    unit = np.stack([f / np.linalg.norm(f) for f in fingerprints])
    alike = unit @ unit.T
    typical = int(alike.sum(axis=1).argmax())
    return {i for i in range(len(fingerprints)) if alike[typical, i] < threshold}


def mirror_face(analysis: Analysis) -> Optional[Face]:
    """The face of whoever is at the mirror: the largest one, if it's close enough."""
    face = analysis.largest
    return face if face and face.width >= MIN_MIRROR_FACE else None
