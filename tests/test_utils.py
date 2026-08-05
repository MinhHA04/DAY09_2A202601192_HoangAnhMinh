from __future__ import annotations

import unittest

from ecommerce_agents.utils import variance_hours


class UtilityTests(unittest.TestCase):
    def test_variance_hours_rounds_to_two_decimals(self) -> None:
        self.assertEqual(
            variance_hours("2018-03-31 15:23:33", "2018-03-28 00:00:00"),
            87.39,
        )

    def test_missing_timestamp_returns_null(self) -> None:
        self.assertIsNone(variance_hours(None, "2018-03-28 00:00:00"))


if __name__ == "__main__":
    unittest.main()
