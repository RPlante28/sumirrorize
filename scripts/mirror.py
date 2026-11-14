import sys
import cv2
import pygame


def main():
    camera = None
    try:
        pygame.init()
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            raise RuntimeError("Could not open the default camera")

        face_detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        if face_detector.empty():
            raise RuntimeError("Could not load the face detector")

        pygame.display.set_caption("sumirrorize")
        window = pygame.display.set_mode((960, 540), pygame.RESIZABLE)
        clock = pygame.time.Clock()
        faces = () #track number of faces and stuff to keep track of the number of faces and stuff in da frame type sh
        frame_number = 0

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
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
                faces = face_detector.detectMultiScale(
                    gray_frame, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
                )

            for x, y, width, height in faces:
                cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 255, 0), 2)

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_height, frame_width = frame.shape[:2]
            image = pygame.image.frombuffer(
                frame.tobytes(), (frame_width, frame_height), "RGB"
            )

            window = pygame.display.get_surface()
            window_width, window_height = window.get_size()
            scale = min(window_width / frame_width, window_height / frame_height)
            size = (round(frame_width * scale), round(frame_height * scale))
            image = pygame.transform.smoothscale(image, size)
            position = ((window_width - size[0]) // 2, (window_height - size[1]) // 2)

            #added black bars to avoid camera stretching
            window.fill("black")
            window.blit(image, position)
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
