from __future__ import annotations

import unittest

from ecommerce_agents.config import ARRAY_LIMITS


class ArrayLimitTests(unittest.TestCase):
    def test_array_limits_match_contract_maxima(self) -> None:
        self.assertEqual(ARRAY_LIMITS["order_ids"], 5)

    def test_contract_maxima_are_preserved_for_evidence_and_context(self) -> None:
        self.assertEqual(ARRAY_LIMITS["item_ids"], 5)
        self.assertEqual(ARRAY_LIMITS["seller_ids"], 3)
        self.assertEqual(ARRAY_LIMITS["payment_ids"], 5)
        self.assertEqual(ARRAY_LIMITS["related_order_ids"], 5)
        self.assertEqual(ARRAY_LIMITS["evidence_ids"], 20)
        self.assertEqual(ARRAY_LIMITS["resolution_actions"], 5)


if __name__ == "__main__":
    unittest.main()
