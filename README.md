# Sumirrorize

A smart mirror for students. It will recognize the user and show their morning
greeting, weather, schedule, assignments, and a quick summary of the day.

A web app will let students set up their account and customize what appears on
the mirror.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### Database

```bash
cp .env.example .env   # set POSTGRES_PASSWORD
docker compose up -d
```

See [db/README.md](db/README.md) for the tables and common queries.

Run every command below from the repository root.

## 1. Enroll people

Enrollment is the only command that saves camera images:

```bash
.venv/bin/python scripts/enrollment.py "Rohan"
.venv/bin/python scripts/enrollment.py "Alex"
.venv/bin/python scripts/enrollment.py "Nathan"
```

Keep exactly one face in frame and move naturally while it captures 20 small samples.
Every half-second it automatically saves the sharpest, most varied valid frame it saw. Only a
distant face or unusable lighting pauses capture. Follow the plain on-screen message if needed.
Escape cancels the current enrollment and removes only the new incomplete samples.
Running enrollment again safely replaces that person's old images only after all 20 new ones finish.

## 2. Train recognition

Training requires at least three enrolled people:

```bash
.venv/bin/python scripts/train.py
```

This creates the local label map and LBPH model under `data/`.

## 3. Start the mirror

```bash
.venv/bin/python scripts/mirror.py
```

Press Escape or close the window to exit. Without a trained model, the mirror still starts but
only draws face boxes.

Once recognized, a user stays active through brief missed or unknown detections. The mirror clears
them after 15 seconds without a usable confirmation, or switches after another person is confirmed.

## Local data

The entire `data/` directory is ignored by Git. It contains biometric images, generated models,
and labels. None of it should be committed or pushed.

## Troubleshooting

- Use `.venv/bin/python`, not plain `python3`, so the project gets the tested OpenCV build.
- `No module named cv2` or `pygame`: rerun the setup install command above.
- `Could not open the default camera`: close other camera apps and try again.
- Training says to enroll three people: check that `data/faces/` has three person folders.
- Recognition changes require retraining with `scripts/train.py`.
