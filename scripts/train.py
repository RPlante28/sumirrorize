import json
from pathlib import Path

import cv2
import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def discover_samples(root):
    names, samples = [], []
    if not root.exists():
        return names, samples
    for folder in sorted(root.iterdir()):
        files = sorted(folder.glob("*.jpg")) if folder.is_dir() else []
        if files:
            label = len(names)
            names.append(folder.name)
            samples.extend((label, path) for path in files)
    return names, samples


def main():
    names, samples = discover_samples(DATA_DIR / "faces")
    if len(names) < 3:
        raise RuntimeError("Enroll at least 3 people before training")

    images, labels = [], []
    for label, path in samples:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError(f"Could not read {path}")
        # hopefully keeps random lighting from mattering too much
        images.append(cv2.equalizeHist(image))
        labels.append(label)

    # small local model should be fine for this
    model = cv2.face.LBPHFaceRecognizer_create()
    model.train(images, np.array(labels))
    model.write(str(DATA_DIR / "face-model.yml"))
    (DATA_DIR / "face-labels.json").write_text(json.dumps(names))
    print(f"Trained {len(names)} people from {len(images)} images")


if __name__ == "__main__":
    main()
