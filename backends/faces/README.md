# faces

The only part of Sumirrorize that handles face pictures and fingerprints. It does two jobs:

1. **Sign-up:** saves a person's face pictures, each with a *fingerprint*: 128 numbers that are
   close together for the same person.
2. **At the mirror:** takes a camera frame and says whose face it is, by finding the closest
   saved fingerprint, and how open their eyes are (for the mirror's blink check).

It uses three free models:

- [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) finds faces.
- [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) makes
  fingerprints.
- [open-closed-eye](https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/public/open-closed-eye-0001)
  says whether an eye is open.

There's no training step, so new sign-ups are recognized right away. Fingerprints live in the
`picture` table and are compared by the database (pgvector).

Internal only: on the server it's reachable only on the `sumirrorize` network, and every call
needs `Authorization: Bearer <FACES_API_KEY>`. The mirror backend and the sign-up app call it.

## How well it works

- **Clear separation between people.** The same person scores 0.6 to 0.97 similarity and different
  people stay under 0.3. Anything at or above **0.363** counts as a match (the model's recommended
  cutoff, `FACES_MATCH_THRESHOLD`).
- **Team photos (Nov 14):** with 15 of each person's 20 photos saved, all 15 held-back photos were
  recognized as the right person (similarity 0.59 to 0.89). No one was mistaken for someone else.
- **Live:** a browser with a fake webcam on `sumirrorize.marist.dev` was recognized about
  3 seconds after the page opened, and the mirror cleared 8 seconds after the person left.
- **Blinks (Nov 15):** on public videos of people talking to a camera, sampled 8 times a second
  like the mirror does, eyes score about 1.0 open and dip to 0.2 to 0.4 during a blink. Quick natural
  blinks are caught about half the time; a slow, deliberate one almost always. A still photo of
  the same person, shown to the same camera for 30 seconds, never registered a blink. Faces still
  match with their eyes shut (similarity 0.83 or more).
- **Speed:** about 30 ms per frame on the server, so roughly 30 frames a second in total.

## Running it

From the repo root, as part of the mirror (needs `FACES_API_KEY` in `.env`):

```bash
docker compose --profile d3l --profile mirror up -d --build
```

Directly, for development:

```bash
cd backends/faces
./download-models.sh                   # the Docker image downloads these itself
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest             # tests use fake models and a fake database
DATABASE_URL=... FACES_API_KEY=... FACES_MODELS_DIR=./models .venv/bin/uvicorn --factory app.main:create_app --port 3400
```

## API

Errors look like `{"error": "...", "code": "..."}`.

### `POST /identify`

The body is one image (`Content-Type: image/jpeg`, PNG or WebP, under 5 MB).

```json
{ "faces": 1, "match": { "personId": 3, "similarity": 0.82 }, "eyesOpen": 0.97 }
```

- **Which face counts:** the largest face, i.e. whoever is closest to the camera. Faces under
  60 pixels wide (someone far in the background) are ignored.
- **No match:** `match` is `null` when nobody is recognized. `faces` still says how many faces
  were seen, which the mirror uses to tell "a stranger is here" from "nobody is here".
- **`eyesOpen`:** how open that face's eyes are, from 0 (both shut) to 1 (both wide open), or
  `null` if no face is close enough. The mirror backend watches it go open, closed, open to see
  a blink. Each eye is cut out at several sizes and the model's answers are averaged, which is
  much steadier than a single cut-out.

### `GET /people/{id}/faces`

Which pictures a person has saved, without the pictures themselves. The sign-up app uses it to
show whether someone's face is set up.

```json
{ "pictures": [ { "angle": "front", "savedAt": "2026-11-14T18:02:11+00:00" } ] }
```

### `PUT /people/{id}/faces`

Replaces a person's face pictures. The JSON body takes 1 to 20 pictures:

```json
{ "pictures": [
  { "angle": "front", "image": "data:image/jpeg;base64,..." },
  { "angle": "left",  "image": "data:image/jpeg;base64,..." }
] }
```

`image` is a data URL, which is what a browser canvas gives you (`canvas.toDataURL("image/jpeg")`).
`angle` is any lowercase label.

- **Every picture must have exactly one clear face, and they must all be the same person.**
  Otherwise nothing is saved, the old pictures stay, and you get a `422`
  (`"code": "poor_pictures"`) saying which pictures to retake:

  ```json
  { "error": "Some pictures need retaking", "code": "poor_pictures",
    "pictures": [ { "angle": "front", "problem": null }, { "angle": "left", "problem": "too_small" } ] }
  ```

- **Problems:** `no_face`, `several_faces`, `too_small` (face under 80 pixels wide: move closer),
  `bad_lighting` (too dark or too bright), `different_person`. The size and lighting rules come
  from the face-recog enrollment script (`scripts/enrollment.py`).
- **Same person:** pictures from different angles don't all match each other, so each one is
  compared with the most typical picture of the set (the one most like all the rest) and must
  reach the usual match cutoff. On the real sign-ups so far, a person's own pictures score 0.47
  or more against it, and other people's 0.27 or less.
- **On success:** `{ "saved": 3, "pictures": [...] }`.
- **Other errors:** `404 no_such_person`, `400 bad_image`, `413 too_large`, `400 bad_request`.

### `DELETE /people/{id}/faces`

Deletes their pictures (`{ "deleted": 3 }`). They won't be recognized until they sign up again.

### Saving faces from files (for testing)

`app/enroll.py` sends photo files through `PUT /people/{id}/faces`. The container is read-only,
so run it from a throwaway container on the same network, with the photos mounted:

```bash
docker run --rm --network sumirrorize -v /path/to/photos:/photos:ro \
  -e FACES_URL=http://sumirrorize-faces:3400 -e FACES_API_KEY=<key> \
  sumirrorize-faces:latest python -m app.enroll <person_id> front=/photos/01.jpg left=/photos/02.jpg
```

## Privacy and security

- **Biometric data in one place.** Face pictures and fingerprints are biometric data. Only this
  service reads or writes them, and it isn't reachable from the internet.
- **Mirror frames aren't kept.** Camera frames sent to `/identify` are analyzed and thrown away.
- **Deleting a person** (or `DELETE /people/{id}/faces`) removes their pictures and fingerprints.
- **The face is the key at the mirror, and it has to blink.** A photo of a signed-up person is
  recognized, but the mirror backend only opens once it has seen that person's eyes go open,
  closed and open again, so a photo held up to the camera (or sent straight to the server)
  doesn't get in. A video of them blinking still would: this stops the easy trick, not a
  determined one. Recognizing a photo also still tells whoever holds it the person's first name.
- **Face photos are kept, though only the fingerprints are used.** See the note in
  [db/README.md](../../db/README.md#face-photos-are-stored).

## Files

| File | What |
|---|---|
| `app/main.py` | Routes, sign-up checks |
| `app/engine.py` | Finding faces, making fingerprints, measuring how open eyes are (OpenCV), sign-up photo rules |
| `app/store.py` | Saving pictures and finding the closest fingerprint (Postgres + pgvector) |
| `app/enroll.py` | Saving faces from photo files |
| `download-models.sh` | Gets the three model files for running outside Docker |
| `tests/` | Tests with fake models and a fake database |
