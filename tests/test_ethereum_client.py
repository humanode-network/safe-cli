import unittest
from unittest import mock

from eth_account import Account
from safe_eth.eth import EthereumClient
from web3 import Web3

from safe_cli.ethereum_client import SafeCliEthereumClient

from .safe_cli_test_case_mixin import SafeCliTestCaseMixin

GWEI = 10**9


class TestSafeCliEthereumClient(SafeCliTestCaseMixin, unittest.TestCase):
    def _fees(self, base_fee: int, tip: int) -> dict:
        ethereum_client = SafeCliEthereumClient(self.ethereum_node_url)
        with mock.patch.object(
            EthereumClient, "estimate_fee_eip1559", return_value=(base_fee, tip)
        ):
            return ethereum_client.set_eip1559_fees({"gasPrice": 1})

    def test_headroom_over_the_forecast(self):
        fees = self._fees(20 * GWEI, 2 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], 42 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 2 * GWEI)
        self.assertNotIn("gasPrice", fees)

    def test_chain_charging_more_than_it_forecasts(self):
        # The node forecasts 625,625 gwei for the next block and charges 715,000: the cap now clears it
        fees = self._fees(625_625 * GWEI, 0)
        self.assertEqual(fees["maxFeePerGas"], 1_251_250 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_operator_sends_with_it(self):
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
        # A fee history that forecasts 0.6 x the base fee the chain charges, as on a chain that charges more than
        # it forecasts: stock fees (cap 0.6 x) would be refused, 2 x 0.6 clears it
        forecast = self.w3.eth.get_block("latest")["baseFeePerGas"] * 6 // 10
        with mock.patch.object(
            EthereumClient, "estimate_fee_eip1559", return_value=(forecast, 0)
        ):
            self.assertTrue(safe_operator.send_ether(Account.create().address, 1))
            executed = self.w3.eth.get_transaction(
                safe_operator.executed_transactions[-1]
            )
            self.assertEqual(executed["type"], 2)
            self.assertGreaterEqual(
                executed["maxFeePerGas"],
                self.w3.eth.get_block(executed["blockNumber"])["baseFeePerGas"],
            )

            block = self.w3.eth.block_number
            self.assertTrue(
                safe_operator.approve_hash(
                    Web3.keccak(text="fee cap"), self.ethereum_test_account.address
                )
            )
            (approval,) = [
                transaction
                for number in range(block + 1, self.w3.eth.block_number + 1)
                for transaction in self.w3.eth.get_block(number, True)["transactions"]
            ]
            self.assertEqual(approval["type"], 2)
            self.assertGreaterEqual(
                approval["maxFeePerGas"],
                self.w3.eth.get_block(approval["blockNumber"])["baseFeePerGas"],
            )


if __name__ == "__main__":
    unittest.main()
