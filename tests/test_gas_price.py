import os
import unittest
from unittest import mock

from safe_cli.gas_price import (
    legacy_gas_price,
    parse_gwei,
    take_legacy_gas_price_flag,
)


class TestGasPrice(unittest.TestCase):
    def test_parse_gwei(self):
        self.assertEqual(parse_gwei("715000"), 715_000 * 10**9)
        self.assertEqual(parse_gwei("1.5"), 1_500_000_000)
        self.assertEqual(parse_gwei("0.000000001"), 1)
        for value in ("0", "-1", "abc", "", "nan", "inf", "0.0000000001"):
            with self.assertRaises(ValueError):
                parse_gwei(value)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_take_flag_anywhere(self):
        arguments = ["safe-cli", "0xSafe", "--legacy-gas-price", "http://node"]
        take_legacy_gas_price_flag(arguments)
        self.assertEqual(arguments, ["safe-cli", "0xSafe", "http://node"])
        self.assertEqual(os.environ["SAFE_CLI_LEGACY_GAS"], "1")
        self.assertNotIn("SAFE_CLI_LEGACY_GAS_PRICE", os.environ)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_take_flag_with_price(self):
        arguments = ["safe-cli", "--legacy-gas-price=800000", "send-ether", "0xSafe"]
        take_legacy_gas_price_flag(arguments)
        self.assertEqual(arguments, ["safe-cli", "send-ether", "0xSafe"])
        self.assertEqual(os.environ["SAFE_CLI_LEGACY_GAS_PRICE"], "800000")

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_take_flag_rejects_bad_price(self):
        with self.assertRaises(SystemExit):
            take_legacy_gas_price_flag(["safe-cli", "--legacy-gas-price=fast"])

    def test_legacy_gas_price(self):
        w3 = mock.Mock()
        w3.eth.gas_price = 123
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(legacy_gas_price(w3))
        with mock.patch.dict(os.environ, {"SAFE_CLI_LEGACY_GAS": "1"}, clear=True):
            self.assertEqual(legacy_gas_price(w3), 123)
        with mock.patch.dict(
            os.environ,
            {"SAFE_CLI_LEGACY_GAS": "1", "SAFE_CLI_LEGACY_GAS_PRICE": "2"},
            clear=True,
        ):
            self.assertEqual(legacy_gas_price(w3), 2 * 10**9)
