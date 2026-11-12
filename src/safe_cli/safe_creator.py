#!/bin/env python3
import argparse
import os
import secrets
import sys

from art import text2art
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_typing import URI
from hexbytes import HexBytes
from prompt_toolkit import print_formatted_text
from safe_eth.eth import EthereumClient, EthereumTxSent
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.contracts import get_safe_V1_4_1_contract
from safe_eth.safe import ProxyFactory, Safe
from safe_eth.util.util import to_0x_hex_str

from safe_cli.gas_fees import (
    MAX_FEE_ENVVAR,
    MAX_FEE_FLAG,
    MAX_FEE_HELP,
    PRIORITY_FEE_ENVVAR,
    PRIORITY_FEE_FLAG,
    PRIORITY_FEE_HELP,
    check_max_fee,
    check_priority_fee,
    describe,
    eip1559_fees,
    set_fees,
    take_fee_flags,
)
from safe_cli.safe_addresses import (
    get_default_fallback_handler_address,
    get_proxy_factory_address,
    get_safe_contract_address,
    get_safe_l2_contract_address,
)
from safe_cli.utils import yes_or_no_question

from . import VERSION
from .argparse_validators import (
    check_ethereum_address,
    check_positive_integer,
    check_private_key,
)


def get_epilog_msg():
    return """
        Example:
            safe-creator https://sepolia.drpc.org 0000000000000000000000000000000000000000000000000000000000000000
    """


def _as_argument_type(check):
    def argument_type(value: str) -> str:
        try:
            return check(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    return argument_type


def setup_argument_parser():
    parser = argparse.ArgumentParser(description=get_epilog_msg())
    parser.add_argument(
        MAX_FEE_FLAG,
        metavar="[node|GWEI]",
        help=MAX_FEE_HELP,
        default=os.environ.get(MAX_FEE_ENVVAR),
        type=_as_argument_type(check_max_fee),
    )
    parser.add_argument(
        PRIORITY_FEE_FLAG,
        metavar="GWEI",
        help=PRIORITY_FEE_HELP,
        default=os.environ.get(PRIORITY_FEE_ENVVAR),
        type=_as_argument_type(check_priority_fee),
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"Safe Creator v{VERSION}",
        help="Show program's version number and exit.",
    )
    parser.add_argument("node_url", help="Ethereum node url")
    parser.add_argument(
        "private_key", help="Deployer private_key", type=check_private_key
    )
    parser.add_argument(
        "--no-confirm",
        help="Bypass any and all “Yes or no?” messages",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--threshold",
        help="Number of owners required to execute transactions on the created Safe. It must"
        "be greater than 0 and less or equal than the number of owners",
        type=check_positive_integer,
        default=1,
    )
    parser.add_argument(
        "--owners",
        help="Owners. By default it will be just the deployer",
        nargs="+",
        type=check_ethereum_address,
    )
    parser.add_argument(
        "--safe-contract",
        help="Use a custom Safe master copy",
        default=None,
        type=check_ethereum_address,
    )
    parser.add_argument(
        "--proxy-factory",
        help="Use a custom proxy factory",
        default=None,
        type=check_ethereum_address,
    )
    parser.add_argument(
        "--callback-handler",
        help="Use a custom fallback handler. It is not required for Safe Master Copies "
        "with version < 1.1.0",
        default=None,
        type=check_ethereum_address,
    )
    parser.add_argument(
        "--salt-nonce",
        help="Use a custom nonce for the deployment. Same nonce with same deployment configuration will "
        "lead to the same Safe address ",
        default=secrets.randbits(256),
        type=int,
    )
    parser.add_argument(
        "--without-events",
        help="Use non events deployment of the Safe instead of the regular one. Recommended for mainnet to save gas costs when using the Safe",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--generate-vanity-addresses",
        help="Don't deploy the Safe, only generate addresses",
        default=False,
        action="store_true",
    )

    return parser


def deploy_proxy_with_fees(
    ethereum_client: EthereumClient,
    proxy_factory: ProxyFactory,
    account: LocalAccount,
    master_copy: str,
    initializer: bytes,
    salt_nonce: int,
    fees: dict,
) -> EthereumTxSent:
    """
    ``ProxyFactory.deploy_proxy_contract_with_nonce`` with EIP-1559 fees given by hand (it only takes a legacy
    gas price).
    """
    create_proxy = proxy_factory.get_deploy_function(chain_specific=False)(
        master_copy, initializer, salt_nonce
    )
    contract_address = create_proxy.call({"from": account.address})
    tx = create_proxy.build_transaction(
        {"from": account.address, "chainId": ethereum_client.get_chain_id(), **fees}
    )
    tx_hash = ethereum_client.send_unsigned_transaction(tx, private_key=account.key)
    return EthereumTxSent(tx_hash, tx, contract_address)


def main(*args, **kwargs) -> EthereumTxSent | None:
    print_formatted_text(text2art("Safe Creator"))  # Print fancy text

    parser = setup_argument_parser()
    sys.argv[1:1] = take_fee_flags(sys.argv)
    args = parser.parse_args()
    set_fees(
        getattr(args, "max_fee_per_gas", None),
        getattr(args, "max_priority_fee_per_gas", None),
    )
    node_url: URI = args.node_url
    account: LocalAccount = Account.from_key(args.private_key)
    no_confirm: bool = args.no_confirm
    owners: list[str] = args.owners if args.owners else [account.address]
    threshold: int = args.threshold
    salt_nonce: int = args.salt_nonce
    without_events: bool = args.without_events
    generate_vanity_addresses: bool = args.generate_vanity_addresses
    to = NULL_ADDRESS
    data = b""
    payment_token = NULL_ADDRESS
    payment = 0
    payment_receiver = NULL_ADDRESS

    if len(owners) < threshold:
        print_formatted_text(
            "Threshold cannot be bigger than the number of unique owners"
        )
        sys.exit(1)

    def yes_or_no(prompt: str) -> bool:
        if no_confirm:
            return True
        return yes_or_no_question(prompt)

    ethereum_client = EthereumClient(node_url)
    ethereum_network = ethereum_client.get_network()

    safe_contract_address = args.safe_contract or (
        get_safe_contract_address(ethereum_client)
        if without_events
        else get_safe_l2_contract_address(ethereum_client)
    )
    proxy_factory_address = args.proxy_factory or get_proxy_factory_address(
        ethereum_client
    )
    fallback_handler = args.callback_handler or get_default_fallback_handler_address(
        ethereum_client
    )

    if not ethereum_client.is_contract(safe_contract_address):
        print_formatted_text(
            f"Safe contract address {safe_contract_address} "
            f"does not exist on network {ethereum_network.name}"
        )
        sys.exit(1)
    elif not ethereum_client.is_contract(proxy_factory_address):
        print_formatted_text(
            f"Proxy contract address {proxy_factory_address} "
            f"does not exist on network {ethereum_network.name}"
        )
        sys.exit(1)
    elif fallback_handler != NULL_ADDRESS and not ethereum_client.is_contract(
        fallback_handler
    ):
        print_formatted_text(
            f"Fallback handler address {fallback_handler} "
            f"does not exist on network {ethereum_network.name}"
        )
        sys.exit(1)

    account_balance: int = ethereum_client.get_balance(account.address)
    if not account_balance:
        print_formatted_text(
            "Client does not have any funds. Let's try anyway in case it's a network without gas costs"
        )
    else:
        ether_account_balance = round(
            ethereum_client.w3.from_wei(account_balance, "ether"), 6
        )
        print_formatted_text(
            f"Network {ethereum_client.get_network().name} - Sender {account.address} - "
            f"Balance: {ether_account_balance}Ξ"
        )

    if not ethereum_client.w3.eth.get_code(
        safe_contract_address
    ) or not ethereum_client.w3.eth.get_code(proxy_factory_address):
        print_formatted_text("Network not supported")
        sys.exit(1)

    print_formatted_text(
        f"Creating new Safe with owners={owners} threshold={threshold} salt-nonce={salt_nonce}"
    )
    safe_version = Safe(safe_contract_address, ethereum_client).retrieve_version()
    print_formatted_text(
        f"Safe-master-copy={safe_contract_address} version={safe_version}\n"
        f"Fallback-handler={fallback_handler}\n"
        f"Proxy factory={proxy_factory_address}"
    )
    if yes_or_no("Do you want to continue?"):
        safe_contract = get_safe_V1_4_1_contract(
            ethereum_client.w3, safe_contract_address
        )
        safe_creation_tx_data = HexBytes(
            safe_contract.functions.setup(
                owners,
                threshold,
                to,
                data,
                fallback_handler,
                payment_token,
                payment,
                payment_receiver,
            ).build_transaction({"gas": 1, "gasPrice": 1})["data"]
        )

        proxy_factory = ProxyFactory(proxy_factory_address, ethereum_client)
        if generate_vanity_addresses:
            for vanity_salt_nonce in range(2**256):
                expected_safe_address = proxy_factory.calculate_proxy_address(
                    safe_contract_address, safe_creation_tx_data, vanity_salt_nonce
                )
                print_formatted_text(f"{expected_safe_address} {vanity_salt_nonce}")
        else:
            expected_safe_address = proxy_factory.calculate_proxy_address(
                safe_contract_address, safe_creation_tx_data, salt_nonce
            )
            if ethereum_client.is_contract(expected_safe_address):
                print_formatted_text(
                    f"Safe on {expected_safe_address} is already deployed"
                )
                sys.exit(1)

            fees = eip1559_fees(ethereum_client)
            pricing = f" with {describe(fees)}" if fees else ""
            if yes_or_no(
                f"Safe will be deployed on {expected_safe_address}{pricing}, would you like to proceed?"
            ):
                if fees:
                    ethereum_tx_sent = deploy_proxy_with_fees(
                        ethereum_client,
                        proxy_factory,
                        account,
                        safe_contract_address,
                        safe_creation_tx_data,
                        salt_nonce,
                        fees,
                    )
                else:
                    ethereum_tx_sent = proxy_factory.deploy_proxy_contract_with_nonce(
                        account,
                        safe_contract_address,
                        safe_creation_tx_data,
                        salt_nonce,
                    )
                print_formatted_text(
                    f"Sent tx with tx-hash={to_0x_hex_str(ethereum_tx_sent.tx_hash)} "
                    f"Safe={ethereum_tx_sent.contract_address} is being created"
                )
                print_formatted_text(f"Tx parameters={ethereum_tx_sent.tx}")
                return ethereum_tx_sent
