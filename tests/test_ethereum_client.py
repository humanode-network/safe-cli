import unittest
from unittest import mock

from eth_account import Account
from safe_eth.eth import EthereumClient
from web3 import Web3

from safe_cli.ethereum_client import SafeCliEthereumClient
from safe_cli.operators.hw_wallets.hw_wallet_manager import HwWalletManager

from .safe_cli_test_case_mixin import SafeCliTestCaseMixin

GWEI = 10**9


class TestSafeCliEthereumClient(SafeCliTestCaseMixin, unittest.TestCase):
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

    def test_forecast_at_or_above_the_node_price_is_unchanged(self):
        for node_price in (15 * GWEI, 22 * GWEI):
            fees = self._fees(20 * GWEI, 2 * GWEI, node_price)
            self.assertEqual(fees["maxFeePerGas"], 22 * GWEI)
            self.assertEqual(fees["maxPriorityFeePerGas"], 2 * GWEI)
            self.assertNotIn("gasPrice", fees)

    def test_forecast_below_the_node_price(self):
        # A node that forecasts 625,625 gwei for the next block and charges 715,000
        fees = self._fees(625_625 * GWEI, 0, 715_000 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], 715_000 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def _sent_to(self, address: str, since_block: int) -> list:
        return [
            transaction
            for number in range(since_block + 1, self.w3.eth.block_number + 1)
            for transaction in self.w3.eth.get_block(number, True)["transactions"]
            if transaction["to"] == address
        ]

    def _assert_included(self, transaction, forecast: int):
        self.assertEqual(transaction["type"], 2)
        base_fee = self.w3.eth.get_block(transaction["blockNumber"])["baseFeePerGas"]
        self.assertLess(forecast, base_fee)
        self.assertGreaterEqual(transaction["maxFeePerGas"], base_fee)

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
        with mock.patch.object(
            EthereumClient, "estimate_fee_eip1559", return_value=(forecast, 0)
        ):
            # Executing a Safe transaction with a local key
            block = self.w3.eth.block_number
            self.assertTrue(safe_operator.send_ether(Account.create().address, 1))
            (transaction,) = self._sent_to(safe_operator.address, block)
            self._assert_included(transaction, forecast)

            # approve_hash
            block = self.w3.eth.block_number
            self.assertTrue(
                safe_operator.approve_hash(Web3.keccak(text="fee cap"), owner.address)
            )
            (transaction,) = self._sent_to(safe_operator.address, block)
            self._assert_included(transaction, forecast)

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
            self._assert_included(transaction, forecast)


if __name__ == "__main__":
    unittest.main()
