"""
Saves someone's face from photo files, through the same route the sign-up app uses. For testing.
The faces container is read-only, so run it from a throwaway container with the photos mounted:

    docker run --rm --network sumirrorize -v /path/to/photos:/photos:ro \
      -e FACES_URL=http://sumirrorize-faces:3400 -e FACES_API_KEY=<key> \
      sumirrorize-faces:latest python -m app.enroll 3 front=/photos/01.jpg left=/photos/02.jpg

or locally with FACES_URL set. Each argument is angle=path.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[0].isdigit() or not all("=" in a for a in argv[1:]):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    person_id, pictures = int(argv[0]), []
    for argument in argv[1:]:
        angle, path = argument.split("=", 1)
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as file:
            pictures.append({"angle": angle, "image": f"data:{mime};base64,{base64.b64encode(file.read()).decode()}"})

    request = urllib.request.Request(
        f"{os.environ.get('FACES_URL', 'http://localhost:3400')}/people/{person_id}/faces",
        data=json.dumps({"pictures": pictures}).encode(),
        method="PUT",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['FACES_API_KEY']}"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            print(json.dumps(json.load(response), indent=2))
            return 0
    except urllib.error.HTTPError as error:
        print(json.dumps(json.load(error), indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
