import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from constants.licenses import (
    VERDICT_NONE,
    VERDICT_PERMISSIVE,
    VERDICT_STRONG,
    VERDICT_UNKNOWN,
    VERDICT_WEAK,
    classify,
)


class LicenseTests(unittest.TestCase):
    def test_permissive(self):
        for spdx in ("MIT", "Apache-2.0", "BSD-3-Clause", "Unlicense"):
            self.assertEqual(classify(spdx), VERDICT_PERMISSIVE)

    def test_copyleft(self):
        self.assertEqual(classify("MPL-2.0"), VERDICT_WEAK)
        self.assertEqual(classify("GPL-3.0"), VERDICT_STRONG)
        self.assertEqual(classify("AGPL-3.0-only"), VERDICT_STRONG)

    def test_missing(self):
        self.assertEqual(classify(None), VERDICT_NONE)
        self.assertEqual(classify("NONE"), VERDICT_NONE)
        self.assertEqual(classify("NOASSERTION"), VERDICT_NONE)

    def test_unknown(self):
        self.assertEqual(classify("Made-Up-1.0"), VERDICT_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
