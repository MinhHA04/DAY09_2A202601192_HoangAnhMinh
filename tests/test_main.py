from __future__ import annotations

import unittest

from main import build_parser


class MainCliTests(unittest.TestCase):
    def test_development_flags_are_supported(self) -> None:
        args = build_parser().parse_args(["--offline", "--allow-partial"])
        self.assertTrue(args.offline)
        self.assertTrue(args.allow_partial)


if __name__ == "__main__":
    unittest.main()
