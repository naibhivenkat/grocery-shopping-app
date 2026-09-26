import unittest

from routes.razorpay_api import _amount_paise


class AmountValidationTests(unittest.TestCase):
    def test_amount_is_rounded_to_paise(self):
        self.assertEqual(_amount_paise("125.55"), 12555)
        self.assertEqual(_amount_paise(1.239), 124)

    def test_amount_rejects_invalid_or_out_of_range_values(self):
        for value in (None, "not-money", 0, -1, 10_000_001):
            with self.subTest(value=value):
                self.assertIsNone(_amount_paise(value))


if __name__ == "__main__":
    unittest.main()
