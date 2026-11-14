import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from enrollment import quality_issue, quality_score, replace_enrollment


class EnrollmentQualityTests(unittest.TestCase):
    def setUp(self):
        self.good = ((np.indices((200, 200)).sum(axis=0) % 2) * 255).astype("uint8")

    def test_accepts_a_clear_face(self):
        self.assertIsNone(quality_issue(self.good, 150))

    def test_rejects_small_and_dark_faces(self):
        self.assertEqual(quality_issue(self.good, 60), "MOVE CLOSER")
        self.assertEqual(quality_issue(np.zeros((200, 200), dtype="uint8"), 150), "FIX LIGHTING")

    def test_prefers_a_different_frame(self):
        repeated = quality_score(self.good, self.good)
        changed = quality_score(np.roll(self.good, 1, axis=0), self.good)
        self.assertGreater(changed, repeated)

    def test_replaces_an_old_enrollment(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target, staging = root / "rohan", root / ".rohan-new"
            target.mkdir()
            staging.mkdir()
            (target / "old.jpg").touch()
            (staging / "new.jpg").touch()
            replace_enrollment(staging, target)
            self.assertFalse((target / "old.jpg").exists())
            self.assertTrue((target / "new.jpg").exists())


if __name__ == "__main__":
    unittest.main()
