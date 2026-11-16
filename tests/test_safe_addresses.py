import unittest
from unittest import mock

from eth_account import Account
from safe_eth.eth import EthereumClient
from safe_eth.eth.tests.utils import just_test_if_mainnet_node

from safe_cli.safe_addresses import (
    _get_valid_contract,
    get_default_fallback_handler_address,
    get_last_multisend_address,
    get_last_multisend_call_only_address,
    get_last_sign_message_lib_address,
    get_proxy_factory_address,
    get_safe_contract_address,
    get_safe_l2_contract_address,
)

from .safe_cli_test_case_mixin import SafeCliTestCaseMixin


class TestSafeAddresses(SafeCliTestCaseMixin, unittest.TestCase):
    def test_get_valid_contract(self):
        addresses = [
            Account.create().address,
            Account.create().address,
            self.safe_contract_V1_4_1.address,
            Account.create().address,
        ]
        expected_address = self.safe_contract_V1_4_1.address
        self.assertEqual(
            _get_valid_contract(self.ethereum_client, addresses), expected_address
        )

        with self.assertRaisesRegex(
            ValueError,
            f"Network {self.ethereum_client.get_network().name} is not supported",
        ):
            _get_valid_contract(self.ethereum_client, addresses[:1])

    def test_get_addresses(self):
        mainnet_node = just_test_if_mainnet_node()
        ethereum_client = EthereumClient(mainnet_node)

        self.assertEqual(
            get_safe_contract_address(ethereum_client),
            "0x41675C099F32341bf84BFc5382aF534df5C7461a",
        )
        self.assertEqual(
            get_safe_l2_contract_address(ethereum_client),
            "0x29fcB43b46531BcA003ddC8FCB67FFE91900C762",
        )
        self.assertEqual(
            get_default_fallback_handler_address(ethereum_client),
            "0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99",
        )
        self.assertEqual(
            get_proxy_factory_address(ethereum_client),
            "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67",
        )
        self.assertEqual(
            get_last_multisend_address(ethereum_client),
            "0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526",
        )
        self.assertEqual(
            get_last_multisend_call_only_address(ethereum_client),
            "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D",
        )

    def test_v1_5_0_only_where_nothing_earlier(self):
        # function -> (v1.4.1 address, v1.5.0 address), from safe-deployments
        expected = {
            get_safe_contract_address: (
                "0x41675C099F32341bf84BFc5382aF534df5C7461a",
                "0xFf51A5898e281Db6DfC7855790607438dF2ca44b",
            ),
            get_safe_l2_contract_address: (
                "0x29fcB43b46531BcA003ddC8FCB67FFE91900C762",
                "0xEdd160fEBBD92E350D4D398fb636302fccd67C7e",
            ),
            get_default_fallback_handler_address: (
                "0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99",
                "0x3EfCBb83A4A7AfcB4F68D501E2c2203a38be77f4",
            ),
            get_proxy_factory_address: (
                "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67",
                "0x14F2982D601c9458F93bd70B218933A6f8165e7b",
            ),
            get_last_multisend_address: (
                "0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526",
                "0x218543288004CD07832472D464648173c77D7eB7",
            ),
            get_last_multisend_call_only_address: (
                "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D",
                "0xA83c336B20401Af773B6219BA5027174338D1836",
            ),
            get_last_sign_message_lib_address: (
                "0xd53cd0aB83D845Ac265BE939c57F53AD838012c9",
                "0x4FfeF8222648872B3dE295Ba1e49110E61f5b5aa",
            ),
        }
        v1_5_0_addresses = {v1_5_0 for _, v1_5_0 in expected.values()}
        ethereum_client = mock.Mock()
        for function, (v1_4_1, v1_5_0) in expected.items():
            with self.subTest(function=function.__name__):
                # A network with only v1.5.0 deployed
                ethereum_client.is_contract.side_effect = lambda address: (
                    address in v1_5_0_addresses
                )
                self.assertEqual(function(ethereum_client), v1_5_0)
                # A network with every version deployed keeps using v1.4.1
                ethereum_client.is_contract.side_effect = lambda address: True
                self.assertEqual(function(ethereum_client), v1_4_1)


if __name__ == "__main__":
    unittest.main()
