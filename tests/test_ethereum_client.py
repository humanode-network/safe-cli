import unittest
from unittest import mock

from eth_account import Account
from safe_eth.eth import EthereumClient
from typer.testing import CliRunner
from web3 import Web3

from safe_cli.ethereum_client import MAX_FEE_PER_GAS_LIMIT, SafeCliEthereumClient
from safe_cli.main import app, main
from safe_cli.operators.hw_wallets.hw_wallet_manager import HwWalletManager

from .safe_cli_test_case_mixin import SafeCliTestCaseMixin

GWEI = 10**9
runner = CliRunner()


class TestSafeCliEthereumClient(SafeCliTestCaseMixin, unittest.TestCase):
    def tearDown(self):
        SafeCliEthereumClient.max_fee_per_gas = None

    def _fees(self, base_fee: int, tip: int, node_price: int) -> dict:
        ethereum_client = SafeCliEthereumClient(self.ethereum_node_url)
        with (
            mock.patch.object(
                EthereumClient, "estimate_fee_eip1559", return_value=(base_fee, tip)
            ),
            mock.patch.object(
                type(ethereum_client.w3.eth),
                "gas_price",
                new_callable=mock.PropertyMock,
                return_value=node_price,
            ),
        ):
            return ethereum_client.set_eip1559_fees({"gasPrice": 1})

    def test_without_the_option_nothing_changes(self):
        fees = self._fees(20 * GWEI, 2 * GWEI, 25 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], 22 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 2 * GWEI)

    def test_max_fee_per_gas(self):
        SafeCliEthereumClient.max_fee_per_gas = 715_000 * GWEI
        # A node that forecasts 625,625 gwei for the next block and charges 715,000
        fees = self._fees(625_625 * GWEI, 0, 715_000 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], 715_000 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)
        self.assertNotIn("gasPrice", fees)

        # A cap below the estimated tip lowers the tip to the cap
        SafeCliEthereumClient.max_fee_per_gas = 1 * GWEI
        fees = self._fees(20 * GWEI, 2 * GWEI, 22 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], 1 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 1 * GWEI)

    def test_limit(self):
        SafeCliEthereumClient.max_fee_per_gas = MAX_FEE_PER_GAS_LIMIT * 22 * GWEI
        fees = self._fees(20 * GWEI, 2 * GWEI, 22 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], MAX_FEE_PER_GAS_LIMIT * 22 * GWEI)

        SafeCliEthereumClient.max_fee_per_gas += 1
        with self.assertRaisesRegex(ValueError, "more than 10 times"):
            self._fees(20 * GWEI, 2 * GWEI, 22 * GWEI)

        # A node that reports no gas price (some development chains) gives nothing to compare with
        self._fees(20 * GWEI, 2 * GWEI, 0)

    def test_command_line_option(self):
        result = runner.invoke(app, ["--max-fee-per-gas", "31.5", "version"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(SafeCliEthereumClient.max_fee_per_gas, 31_500_000_000)

        result = runner.invoke(app, ["version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(SafeCliEthereumClient.max_fee_per_gas)

        for value in ("0", "-1", "nan", "fast"):
            result = runner.invoke(app, [f"--max-fee-per-gas={value}", "version"])
            self.assertEqual(result.exit_code, 2, value)

        with mock.patch.dict("os.environ", {"SAFE_CLI_MAX_FEE_PER_GAS": "40"}):
            runner.invoke(app, ["version"])
            self.assertEqual(SafeCliEthereumClient.max_fee_per_gas, 40 * GWEI)
            # The command line overrides the environment
            runner.invoke(app, ["--max-fee-per-gas=41", "version"])
            self.assertEqual(SafeCliEthereumClient.max_fee_per_gas, 41 * GWEI)

    @mock.patch.object(type(app), "__call__")
    def test_attended_mode_after_the_option(self, mock_app: mock.MagicMock):
        safe, node = Account.create().address, "http://localhost:8545"
        for arguments, expected in (
            ([safe, node], ["attended-mode", safe, node]),
            (
                ["--max-fee-per-gas", "30", safe, node],
                ["--max-fee-per-gas", "30", "attended-mode", safe, node],
            ),
            (
                ["--max-fee-per-gas=30", safe, node],
                ["--max-fee-per-gas=30", "attended-mode", safe, node],
            ),
            (
                ["--max-fee-per-gas", "30", "send-ether", safe, node],
                ["--max-fee-per-gas", "30", "send-ether", safe, node],
            ),
        ):
            with mock.patch("sys.argv", ["safe-cli", *arguments]) as argv:
                main()
                self.assertEqual(argv[1:], expected)

    def _sent_to(self, address: str, since_block: int) -> list:
        return [
            transaction
            for number in range(since_block + 1, self.w3.eth.block_number + 1)
            for transaction in self.w3.eth.get_block(number, True)["transactions"]
            if transaction["to"] == address
        ]

    def test_every_way_of_sending_uses_it(self):
        safe_operator = self.setup_operator()
        owner = self.ethereum_test_account
        safe_operator.accounts.add(owner)
        safe_operator.default_sender = owner
        self.w3.eth.send_transaction(
            {"from": owner.address, "to": safe_operator.address, "value": 10}
        )
        # A fee history that forecasts 0.6 x the base fee the chain charges. A cap at the forecast is below the
        # base fee and the node refuses the transaction: "max fee per gas less than block base fee".
        forecast = self.w3.eth.get_block("latest")["baseFeePerGas"] * 6 // 10
        cap = self.w3.eth.gas_price * 3
        SafeCliEthereumClient.max_fee_per_gas = cap
        with mock.patch.object(
            EthereumClient, "estimate_fee_eip1559", return_value=(forecast, 0)
        ):
            # Executing a Safe transaction with a local key
            block = self.w3.eth.block_number
            self.assertTrue(safe_operator.send_ether(Account.create().address, 1))
            (transaction,) = self._sent_to(safe_operator.address, block)
            self.assertEqual(
                (transaction["type"], transaction["maxFeePerGas"]), (2, cap)
            )

            # approve_hash
            block = self.w3.eth.block_number
            self.assertTrue(
                safe_operator.approve_hash(Web3.keccak(text="fee cap"), owner.address)
            )
            (transaction,) = self._sent_to(safe_operator.address, block)
            self.assertEqual(
                (transaction["type"], transaction["maxFeePerGas"]), (2, cap)
            )

            # Executing a Safe transaction with a hardware wallet
            sender = mock.Mock()
            sender.address = owner.address
            sender.get_signed_raw_transaction.side_effect = lambda tx, chain_id: (
                self.w3.eth.account.sign_transaction(tx, owner.key).raw_transaction
            )
            safe_operator.default_sender = None
            safe_operator.hw_wallet_manager = HwWalletManager()
            safe_operator.hw_wallet_manager.sender = sender
            block = self.w3.eth.block_number
            self.assertTrue(safe_operator.send_ether(Account.create().address, 1))
            (transaction,) = self._sent_to(safe_operator.address, block)
            self.assertEqual(
                (transaction["type"], transaction["maxFeePerGas"]), (2, cap)
            )

        # Without the option the node refuses the same estimate
        SafeCliEthereumClient.max_fee_per_gas = None
        safe_operator.default_sender = owner
        forecast = self.w3.eth.get_block("latest")["baseFeePerGas"] * 6 // 10
        with (
            mock.patch.object(
                EthereumClient, "estimate_fee_eip1559", return_value=(forecast, 0)
            ),
            self.assertRaisesRegex(
                Exception, "max fee per gas less than block base fee"
            ),
        ):
            safe_operator.send_ether(Account.create().address, 1)


if __name__ == "__main__":
    unittest.main()
