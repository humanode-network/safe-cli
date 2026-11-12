import os
import unittest
from unittest import mock

import typer
from eth_account import Account
from safe_eth.eth import EthereumClient
from web3 import Web3

from safe_cli.operators.ethereum_client import (
    MAX_FEE_PER_GAS_ENV,
    SafeCliEthereumClient,
)
from safe_cli.operators.exceptions import SafeOperatorException
from safe_cli.operators.hw_wallets.hw_wallet_manager import HwWalletManager

from .safe_cli_test_case_mixin import SafeCliTestCaseMixin

GWEI = 10**9


class TestSafeCliEthereumClient(SafeCliTestCaseMixin, unittest.TestCase):
    def _client(self, max_fee_per_gas: str | None) -> SafeCliEthereumClient:
        with mock.patch.dict(os.environ):
            if max_fee_per_gas is None:
                os.environ.pop(MAX_FEE_PER_GAS_ENV, None)
            else:
                os.environ[MAX_FEE_PER_GAS_ENV] = max_fee_per_gas
            return SafeCliEthereumClient(self.ethereum_node_url)

    def _fees(
        self,
        ethereum_client: SafeCliEthereumClient,
        base_fee: int,
        tip: int,
        node_price: int = 20 * GWEI,
    ) -> tuple[dict, mock.PropertyMock]:
        with (
            mock.patch.object(
                EthereumClient, "estimate_fee_eip1559", return_value=(base_fee, tip)
            ),
            mock.patch.object(
                type(ethereum_client.w3.eth),
                "gas_price",
                new_callable=mock.PropertyMock,
                return_value=node_price,
            ) as gas_price,
        ):
            return ethereum_client.set_eip1559_fees({"gasPrice": 1}), gas_price

    def test_without_the_variable_nothing_changes(self):
        for value in (None, ""):
            ethereum_client = self._client(value)
            self.assertIsNone(ethereum_client.max_fee_per_gas)
            fees, gas_price = self._fees(ethereum_client, 20 * GWEI, 2 * GWEI)
            self.assertEqual(fees["maxFeePerGas"], 22 * GWEI)
            self.assertEqual(fees["maxPriorityFeePerGas"], 2 * GWEI)
            # No request is added either
            gas_price.assert_not_called()

    def test_max_fee_per_gas(self):
        for value, wei in (
            ("715000", 715_000 * GWEI),
            ("1.5", 1_500_000_000),
            ("0.000000001", 1),
        ):
            self.assertEqual(self._client(value).max_fee_per_gas, wei)

        # A node that forecasts 0.875 x the fee it charges, with no tip
        fees, _ = self._fees(
            self._client("715000"), 625_625 * GWEI, 0, node_price=715_000 * GWEI
        )
        self.assertEqual(fees["maxFeePerGas"], 715_000 * GWEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)
        self.assertNotIn("gasPrice", fees)

        # A cap below the estimated tip lowers the tip to the cap
        fees, _ = self._fees(self._client("1.5"), 20 * GWEI, 2 * GWEI)
        self.assertEqual(fees["maxFeePerGas"], 1_500_000_000)
        self.assertEqual(fees["maxPriorityFeePerGas"], 1_500_000_000)

    def test_invalid_values(self):
        for value in (
            "0",
            "0.0",
            "-1",
            "nan",
            "inf",
            "fast",
            "30gwei",
            "1e3",
            "1e999999",
            "1_0",
            " 30 ",
            "30,5",
            "0x1e",
            "٣٠",
            "1.0000000001",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    typer.BadParameter, "positive number of gwei"
                ):
                    self._client(value)

    def test_limit(self):
        # The node's gas price is 20 gwei: 197 gwei is under 9.9 times, 198 is 9.9 times
        fees, _ = self._fees(self._client("197"), 20 * GWEI, 0)
        self.assertEqual(fees["maxFeePerGas"], 197 * GWEI)
        for value in ("198", "200", "2000"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    SafeOperatorException,
                    r"\(200 gwei\) is 9.9 times the node's gas price \(20 gwei\)"
                    if value == "200"
                    else "9.9 times the node's gas price",
                ):
                    self._fees(self._client(value), 20 * GWEI, 0)

        # A node that reports a gas price of 0 gives nothing to compare with
        fees, _ = self._fees(self._client("200"), 20 * GWEI, 0, node_price=0)
        self.assertEqual(fees["maxFeePerGas"], 200 * GWEI)

    def _sent_to(self, address: str, since_block: int) -> list:
        return [
            transaction
            for number in range(since_block + 1, self.w3.eth.block_number + 1)
            for transaction in self.w3.eth.get_block(number, True)["transactions"]
            if transaction["to"] == address
        ]

    def test_every_way_of_sending_uses_it(self):
        owner = self.ethereum_test_account
        # Above the base fee, so the node includes it, and below the limit
        cap = self.w3.eth.get_block("latest")["baseFeePerGas"] * 3
        with mock.patch.dict(
            os.environ, {MAX_FEE_PER_GAS_ENV: format(Web3.from_wei(cap, "gwei"), "f")}
        ):
            safe_operator = self.setup_operator()
        self.assertEqual(safe_operator.ethereum_client.max_fee_per_gas, cap)
        safe_operator.accounts.add(owner)
        safe_operator.default_sender = owner
        self.w3.eth.send_transaction(
            {"from": owner.address, "to": safe_operator.address, "value": 10}
        )

        # Executing a Safe transaction with a local key
        block = self.w3.eth.block_number
        self.assertTrue(safe_operator.send_ether(Account.create().address, 1))
        (transaction,) = self._sent_to(safe_operator.address, block)
        self.assertEqual((transaction["type"], transaction["maxFeePerGas"]), (2, cap))

        # approve_hash
        block = self.w3.eth.block_number
        self.assertTrue(
            safe_operator.approve_hash(Web3.keccak(text="fee cap"), owner.address)
        )
        (transaction,) = self._sent_to(safe_operator.address, block)
        self.assertEqual((transaction["type"], transaction["maxFeePerGas"]), (2, cap))

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
        self.assertEqual((transaction["type"], transaction["maxFeePerGas"]), (2, cap))


if __name__ == "__main__":
    unittest.main()
