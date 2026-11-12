import unittest
from unittest import mock

from eth_account import Account
from typer.testing import CliRunner
from web3 import Web3

from safe_cli import gas_fees
from safe_cli.gas_fees import (
    MAX_FEE_MULTIPLE,
    check_max_fee,
    check_priority_fee,
    eip1559_fees,
    parse_gwei,
    set_fees,
    take_fee_flags,
)
from safe_cli.main import app
from safe_cli.operators.hw_wallets.hw_wallet_manager import HwWalletManager

from .safe_cli_test_case_mixin import SafeCliTestCaseMixin

runner = CliRunner()
GWEI = 10**9


def client(base_fee: int, tip: int, node_price: int, eip1559: bool = True):
    ethereum_client = mock.Mock()
    ethereum_client.is_eip1559_supported.return_value = eip1559
    ethereum_client.estimate_fee_eip1559.return_value = (base_fee, tip)
    ethereum_client.w3.eth.gas_price = node_price
    return ethereum_client


class TestGasFees(unittest.TestCase):
    def tearDown(self):
        set_fees(None, None)

    def test_parse_gwei(self):
        self.assertEqual(parse_gwei("30", "--x"), 30 * GWEI)
        self.assertEqual(parse_gwei("1.5", "--x"), 1_500_000_000)
        self.assertEqual(parse_gwei("0.000000001", "--x"), 1)
        self.assertEqual(parse_gwei("0", "--x", allow_zero=True), 0)
        for value in ("0", "-1", "abc", "", "nan", "inf", "0.0000000001"):
            with self.assertRaises(ValueError):
                parse_gwei(value, "--x")

    def test_checks(self):
        for value in (None, "node", "30"):
            self.assertEqual(check_max_fee(value), value)
        for value in (None, "0", "2"):
            self.assertEqual(check_priority_fee(value), value)
        for check, value in (
            (check_max_fee, "fast"),
            (check_max_fee, "0"),
            (check_priority_fee, "node"),
            (check_priority_fee, "-1"),
        ):
            with self.assertRaises(ValueError):
                check(value)

    def test_take_flags_anywhere(self):
        arguments = ["safe-cli", "0xSafe", "--max-fee-per-gas", "http://node"]
        self.assertEqual(take_fee_flags(arguments), ["--max-fee-per-gas=node"])
        self.assertEqual(arguments, ["safe-cli", "0xSafe", "http://node"])

        arguments = [
            "safe-cli",
            "--max-priority-fee-per-gas",
            "2",
            "send-ether",
            "--max-fee-per-gas=40",
            "--max-fee-per-gas=50",
        ]
        self.assertEqual(
            take_fee_flags(arguments),
            ["--max-priority-fee-per-gas=2", "--max-fee-per-gas=50"],
        )
        self.assertEqual(arguments, ["safe-cli", "send-ether"])

        arguments = ["safe-cli", "0xSafe", "http://node"]
        self.assertEqual(take_fee_flags(arguments), [])
        self.assertEqual(arguments, ["safe-cli", "0xSafe", "http://node"])

    def test_default_is_unchanged(self):
        self.assertIsNone(eip1559_fees(client(10 * GWEI, 1 * GWEI, 11 * GWEI)))

    def test_cap_from_node(self):
        # The fee history forecasts less than the node's price (a fixed-fee chain): the cap follows the node
        set_fees("node", None)
        self.assertEqual(
            eip1559_fees(client(625_625 * GWEI, 0, 715_000 * GWEI)),
            {"maxFeePerGas": 715_000 * GWEI, "maxPriorityFeePerGas": 0},
        )
        # The fee history forecasts more: keep it
        self.assertEqual(
            eip1559_fees(client(20 * GWEI, 2 * GWEI, 15 * GWEI)),
            {"maxFeePerGas": 22 * GWEI, "maxPriorityFeePerGas": 2 * GWEI},
        )

    def test_fixed_cap_and_tip(self):
        set_fees("40", "3")
        self.assertEqual(
            eip1559_fees(client(20 * GWEI, 1 * GWEI, 21 * GWEI)),
            {"maxFeePerGas": 40 * GWEI, "maxPriorityFeePerGas": 3 * GWEI},
        )
        # Only a tip: the cap is base fee plus that tip, as safe-cli computes it
        set_fees(None, "3")
        self.assertEqual(
            eip1559_fees(client(20 * GWEI, 1 * GWEI, 21 * GWEI)),
            {"maxFeePerGas": 23 * GWEI, "maxPriorityFeePerGas": 3 * GWEI},
        )
        # A fixed cap below the estimated tip lowers the tip to the cap
        set_fees("1", None)
        self.assertEqual(
            eip1559_fees(client(1 * GWEI, 2 * GWEI, 3 * GWEI)),
            {"maxFeePerGas": 1 * GWEI, "maxPriorityFeePerGas": 1 * GWEI},
        )

    def test_refusals(self):
        set_fees(str(21 * MAX_FEE_MULTIPLE), None)
        self.assertEqual(
            eip1559_fees(client(20 * GWEI, 1 * GWEI, 21 * GWEI))["maxFeePerGas"],
            21 * MAX_FEE_MULTIPLE * GWEI,
        )
        set_fees(str(21 * MAX_FEE_MULTIPLE + 1), None)
        with self.assertRaisesRegex(ValueError, "more than 10 times"):
            eip1559_fees(client(20 * GWEI, 1 * GWEI, 21 * GWEI))
        set_fees("30", "31")
        with self.assertRaisesRegex(ValueError, "above the cap"):
            eip1559_fees(client(20 * GWEI, 1 * GWEI, 21 * GWEI))
        set_fees("node", None)
        with self.assertRaisesRegex(ValueError, "need a network with EIP-1559"):
            eip1559_fees(client(0, 0, 21 * GWEI, eip1559=False))

    def test_command_line_options(self):
        result = runner.invoke(app, ["--max-fee-per-gas=fast", "version"])
        self.assertEqual(result.exit_code, 2)

        result = runner.invoke(
            app, ["--max-fee-per-gas=31", "--max-priority-fee-per-gas=0", "version"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((gas_fees._max_fee, gas_fees._priority_fee), ("31", "0"))

        result = runner.invoke(app, ["version"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((gas_fees._max_fee, gas_fees._priority_fee), (None, None))

        with mock.patch.dict(
            "os.environ",
            {
                "SAFE_CLI_MAX_FEE_PER_GAS": "node",
                "SAFE_CLI_MAX_PRIORITY_FEE_PER_GAS": "1",
            },
        ):
            runner.invoke(app, ["version"])
            self.assertEqual((gas_fees._max_fee, gas_fees._priority_fee), ("node", "1"))
            # The command line overrides the environment
            runner.invoke(app, ["--max-fee-per-gas=32", "version"])
            self.assertEqual(gas_fees._max_fee, "32")

        with mock.patch.dict("os.environ", {"SAFE_CLI_MAX_FEE_PER_GAS": "30gwei"}):
            result = runner.invoke(app, ["version"])
            self.assertEqual(result.exit_code, 2)


class TestGasFeesTransactions(SafeCliTestCaseMixin, unittest.TestCase):
    def tearDown(self):
        set_fees(None, None)

    def _operator(self):
        safe_operator = self.setup_operator()
        safe_operator.accounts.add(self.ethereum_test_account)
        safe_operator.default_sender = self.ethereum_test_account
        self.w3.eth.send_transaction(
            {
                "from": self.ethereum_test_account.address,
                "to": safe_operator.address,
                "value": 10,
            }
        )
        return safe_operator

    def _sent(self, safe_operator, block: int):
        return [
            transaction
            for number in range(block + 1, self.w3.eth.block_number + 1)
            for transaction in self.w3.eth.get_block(number, True)["transactions"]
            if transaction["to"] == safe_operator.address
        ]

    def test_execute_fees(self):
        safe_operator = self._operator()
        to = Account.create().address
        cap = self.w3.eth.gas_price * 3
        set_fees(str(Web3.from_wei(cap, "gwei")), "1.5")
        block = self.w3.eth.block_number
        self.assertTrue(safe_operator.send_ether(to, 1))
        (transaction,) = self._sent(safe_operator, block)
        self.assertEqual(transaction["type"], 2)
        self.assertEqual(transaction["maxFeePerGas"], cap)
        self.assertEqual(transaction["maxPriorityFeePerGas"], 1_500_000_000)

        set_fees(str(Web3.from_wei(cap * 1000, "gwei")), None)
        block = self.w3.eth.block_number
        with self.assertRaises(ValueError):
            safe_operator.send_ether(to, 1)
        self.assertEqual(self._sent(safe_operator, block), [])

    def test_approve_hash_fees(self):
        safe_operator = self._operator()
        set_fees("node", "0.5")
        block = self.w3.eth.block_number
        self.assertTrue(
            safe_operator.approve_hash(
                Web3.keccak(text="fees"), self.ethereum_test_account.address
            )
        )
        (transaction,) = self._sent(safe_operator, block)
        self.assertEqual(transaction["type"], 2)
        self.assertEqual(transaction["maxPriorityFeePerGas"], 500_000_000)
        self.assertGreaterEqual(transaction["maxFeePerGas"], self.w3.eth.gas_price)

    def test_hardware_wallet_execute_fees(self):
        owner = self.ethereum_test_account
        safe = self.deploy_test_safe(
            owners=[owner.address],
            threshold=1,
            initial_funding_wei=self.w3.to_wei(0.1, "ether"),
        )
        safe_tx = safe.build_multisig_tx(Account.create().address, 10, b"")
        safe_tx.sign(owner.key)
        hw_wallet_manager = HwWalletManager()
        sender = mock.Mock()
        sender.address = owner.address
        signed = []

        def sign(tx, chain_id):
            signed.append(dict(tx))
            return self.w3.eth.account.sign_transaction(tx, owner.key).raw_transaction

        sender.get_signed_raw_transaction.side_effect = sign
        hw_wallet_manager.sender = sender
        fees = {"maxFeePerGas": self.w3.eth.gas_price * 2, "maxPriorityFeePerGas": 7}
        tx_hash, tx = hw_wallet_manager.execute_safe_tx(safe_tx, eip1559_fees=fees)
        self.assertEqual(signed[0]["maxFeePerGas"], fees["maxFeePerGas"])
        self.assertEqual(signed[0]["maxPriorityFeePerGas"], 7)
        self.assertNotIn("gasPrice", signed[0])
        transaction = self.w3.eth.get_transaction(tx_hash)
        self.assertEqual(transaction["type"], 2)
        self.assertEqual(transaction["maxPriorityFeePerGas"], 7)


if __name__ == "__main__":
    unittest.main()
