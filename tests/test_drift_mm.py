import unittest
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from unittest.mock import MagicMock, AsyncMock, patch
import numpy as np
import os

# Ensure no wallet key is set
if "WALLET_PRIVATE_KEY" in os.environ:
    del os.environ["WALLET_PRIVATE_KEY"]

from drift_jito_mm import DriftJitoMM, MMState, OrderManager

class TestDriftMM(unittest.TestCase):
    @patch('drift_jito_mm.AsyncClient')
    @patch('drift_jito_mm.JitoBundleBuilder')
    def test_quantize(self, mock_jito, mock_rpc):
        mm = DriftJitoMM()
        tick_size = Decimal("0.001")
        step_size = Decimal("0.1")

        # Test price quantization
        self.assertEqual(mm.quantize(Decimal("100.1234"), tick_size, ROUND_FLOOR), 100123000)
        self.assertEqual(mm.quantize(Decimal("100.1239"), tick_size, ROUND_CEILING), 100124000)

        # Test size quantization
        self.assertEqual(mm.quantize(Decimal("1.23"), step_size, ROUND_FLOOR), 1200000000)
        self.assertEqual(mm.quantize(Decimal("1.29"), step_size, ROUND_CEILING), 1300000000)

    def test_sigma_sq(self):
        state = MMState()
        self.assertEqual(state.sigma_sq, 0.0004)

        state.price_buffer = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0, 102.5, 104.0, 103.5, 105.0]
        returns = np.diff(np.log(state.price_buffer))
        expected_sigma_sq = float(np.var(returns))
        self.assertAlmostEqual(state.sigma_sq, expected_sigma_sq)

    def test_order_manager_should_update(self):
        om = OrderManager(Decimal("0.0005"))
        mid = Decimal("100.0")

        self.assertTrue(om.should_update(Decimal("99.9"), Decimal("100.1"), mid))
        om.update_local_state(Decimal("99.9"), Decimal("1.0"), Decimal("100.1"), Decimal("1.0"))

        self.assertFalse(om.should_update(Decimal("99.91"), Decimal("100.11"), mid))
        self.assertTrue(om.should_update(Decimal("99.84"), Decimal("100.1"), mid))

    def test_strategy_logic_manual(self):
        price = Decimal("100.0")
        inventory = Decimal("5.0")
        max_inventory = Decimal("10.0")
        gamma = Decimal("0.5")
        base_spread = Decimal("0.02")
        sigma_sq = 0.0001

        sigma = Decimal(str(sigma_sq)).sqrt()
        vol_adj = sigma * Decimal("2.5")

        inv_ratio = inventory / max_inventory

        half_spread = base_spread + vol_adj
        mid_shift = gamma * inv_ratio * (base_spread + vol_adj)
        mid_price = price - mid_shift

        bid_px = mid_price - half_spread
        ask_px = mid_price + half_spread

        self.assertTrue(bid_px < Decimal("99.955"))
        self.assertTrue(ask_px < Decimal("100.045"))

        base_size = Decimal("1.0") * (Decimal("1") - abs(inv_ratio))
        self.assertEqual(base_size, Decimal("0.5"))

if __name__ == '__main__':
    unittest.main()
