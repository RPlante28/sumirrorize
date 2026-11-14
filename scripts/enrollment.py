import argparse
import re
import shutil
import sys
import time

import cv2
import pygame

from mirror import DATA_DIR, detect_faces, draw_frame, exit_requested, load_detectors, open_camera

SAMPLE_COUNT = 20
CAPTURE_DELAY = 0.5
MIN_FACE_SIZE = 80
MIN_BRIGHTNESS = 35
MAX_BRIGHTNESS = 220


def clean_name(name):
    # keep weird names from becoming weird paths
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not cleaned:
        raise argparse.ArgumentTypeError("name needs at least one letter or number")
    return cleaned


def quality_issue(face, face_width):
    if face_width < MIN_FACE_SIZE:
        return "MOVE CLOSER"
    if not MIN_BRIGHTNESS <= face.mean() <= MAX_BRIGHTNESS:
        return "FIX LIGHTING"
    return None


def quality_score(face, previous_face):
    sharpness = cv2.Laplacian(face, cv2.CV_64F).var()
    difference = cv2.absdiff(face, previous_face).mean() if previous_face is not None else 0
    # some movement is good, just not more important than a clear pic
    return sharpness + min(difference, 30) * 2


def replace_enrollment(staging, target):
    # keep the old set around until the new one is ready
    backup = target.with_name(f".{target.name}-old")
    if backup.exists():
        if target.exists():
            shutil.rmtree(backup)
        else:
            backup.rename(target)
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if backup.exists():
            backup.rename(target)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def main(name):
    camera = None
    folder = None
    saved_files = []
    complete = False
    try:
        pygame.init()
        camera = open_camera()
        detectors = load_detectors()

        faces_folder = DATA_DIR / "faces"
        faces_folder.mkdir(parents=True, exist_ok=True)
        target_folder = faces_folder / name
        staging_folder = faces_folder / f".{name}-new"
        if staging_folder.exists():
            shutil.rmtree(staging_folder)
        staging_folder.mkdir()
        folder = staging_folder
        sample_count = 0

        pygame.display.set_caption("sumirrorize enrollment")
        pygame.display.set_mode((960, 540), pygame.RESIZABLE)
        clock = pygame.time.Clock()
        font = pygame.font.Font(None, 24)
        faces = ()
        frame_number = 0
        next_capture = time.monotonic() + CAPTURE_DELAY
        previous_face = None
        best_face = None
        best_score = -1
        status = "ONE FACE ONLY"

        while True:
            if exit_requested():
                return 0

            success, frame = camera.read()
            if not success:
                raise RuntimeError("Could not read a frame from the camera")
            frame = cv2.flip(frame, 1)

            frame_number = (frame_number + 1) % 3
            if frame_number == 0:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = detect_faces(gray_frame, detectors)
                if len(faces) != 1:
                    next_capture = time.monotonic() + CAPTURE_DELAY
                    best_face = None
                    best_score = -1
                    status = "ONE FACE ONLY"
                else:
                    x, y, width, height = faces[0]
                    face = cv2.resize(gray_frame[y : y + height, x : x + width], (200, 200))
                    status = quality_issue(face, width) or "CAPTURING"
                    if status == "CAPTURING":
                        score = quality_score(face, previous_face)
                        if score > best_score:
                            best_face, best_score = face, score

                    if best_face is not None and time.monotonic() >= next_capture:
                        sample = folder / f"{sample_count + 1:02}.jpg"
                        saved_files.append(sample)
                        if not cv2.imwrite(str(sample), best_face):
                            raise RuntimeError("Could not save enrollment image")
                        previous_face = best_face
                        best_face = None
                        best_score = -1
                        sample_count += 1
                        next_capture = time.monotonic() + CAPTURE_DELAY
                        if sample_count == SAMPLE_COUNT:
                            replace_enrollment(folder, target_folder)
                            folder = target_folder
                            complete = True

            for x, y, width, height in faces:
                cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 255, 0), 2)

            window = draw_frame(frame)
            hint = "DONE" if complete else status
            text = font.render(
                f"ENROLL {name}  {sample_count}/{SAMPLE_COUNT}  {hint}",
                False, "white", "black",
            )
            window.blit(text, (4, 4))
            pygame.display.flip()
            clock.tick(60)

            if complete:
                print(f"Saved {SAMPLE_COUNT} samples for {name}")
                return 0
    except Exception as error:
        print(f"Enrollment error: {error}", file=sys.stderr)
        return 1
    finally:
        if camera is not None:
            camera.release()
        pygame.quit()

        # only clean up what we just made
        if folder and not complete:
            for sample in saved_files:
                sample.unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("name", type=clean_name)
    raise SystemExit(main(parser.parse_args().name))
