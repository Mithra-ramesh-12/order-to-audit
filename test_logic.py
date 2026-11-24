
import unittest
from decimal import Decimal

from logic import (
    money_to_paise,
    paise_to_rupees,
    to_decimal,
    decimal_text,
    convert_quantity,
    calculate_variance,
    calculate_gst,
    weighted_average_cost,
    calculate_run_cost,
)


class TestMoneyFunctions(unittest.TestCase):

    def test_rupees_to_paise(self):
        self.assertEqual(money_to_paise("50"), 5000)

    def test_decimal_rupees_to_paise(self):
        self.assertEqual(money_to_paise("187.50"), 18750)

    def test_paise_to_rupees(self):
        self.assertEqual(paise_to_rupees(787500), Decimal("7875.00"))

    def test_negative_money_rejected(self):
        with self.assertRaises(ValueError):
            money_to_paise("-10")


class TestDecimalFunctions(unittest.TestCase):

    def test_decimal_conversion(self):
        self.assertEqual(to_decimal("10.50"), Decimal("10.50"))

    def test_decimal_text(self):
        self.assertEqual(decimal_text("10.500"), "10.5")


class TestUnitConversions(unittest.TestCase):

    def test_kg_to_grams(self):
        self.assertEqual(
            convert_quantity("2", "kg", "g"),
            Decimal("2000")
        )

    def test_grams_to_kg(self):
        self.assertEqual(
            convert_quantity("2500", "g", "kg"),
            Decimal("2.500")
        )

    def test_carton_to_packets(self):
        self.assertEqual(
            convert_quantity("10", "carton", "packet"),
            Decimal("200")
        )

    def test_packets_to_cartons(self):
        self.assertEqual(
            convert_quantity("40", "packet", "carton"),
            Decimal("2.00")
        )


class TestVariance(unittest.TestCase):

    def test_variance_within_tolerance(self):
        result = calculate_variance(100, 99)

        self.assertFalse(result["flagged"])
        self.assertEqual(result["variance_percent"], Decimal("-1.00"))

    def test_variance_beyond_tolerance(self):
        result = calculate_variance(200, 188)

        self.assertTrue(result["flagged"])
        self.assertEqual(result["variance_percent"], Decimal("-6.00"))

    def test_material_overuse(self):
        result = calculate_variance(10, 10.5)

        self.assertTrue(result["flagged"])
        self.assertEqual(result["variance_percent"], Decimal("5.00"))


class TestGST(unittest.TestCase):

    def test_tamil_nadu_customer(self):
        result = calculate_gst(750000, 500, "Tamil Nadu")

        self.assertEqual(result["cgst_paise"], 18750)
        self.assertEqual(result["sgst_paise"], 18750)
        self.assertEqual(result["igst_paise"], 0)
        self.assertEqual(result["total_paise"], 787500)

    def test_other_state_customer(self):
        result = calculate_gst(750000, 500, "Karnataka")

        self.assertEqual(result["cgst_paise"], 0)
        self.assertEqual(result["sgst_paise"], 0)
        self.assertEqual(result["igst_paise"], 37500)
        self.assertEqual(result["total_paise"], 787500)


class TestWeightedAverageCost(unittest.TestCase):

    def test_weighted_average(self):
        result = weighted_average_cost(
            opening_quantity=100,
            opening_rate_paise=4200,
            purchases=[
                {
                    "quantity": 60,
                    "rate_paise": 4500
                }
            ]
        )

        self.assertEqual(result, 4313)


class TestProductionCost(unittest.TestCase):

    def test_cost_per_packet(self):
        result = calculate_run_cost(
            material_costs=[100000, 50000, 10000],
            labour_cost_paise=120000,
            power_gas_cost_paise=60000,
            good_packets=188
        )

        self.assertEqual(result["total_cost_paise"], 340000)
        self.assertEqual(result["cost_per_packet_paise"], 1809)


if __name__ == "__main__":
    unittest.main()
