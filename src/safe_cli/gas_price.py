"""
Legacy gas pricing.

By default every transaction is sent as EIP-1559, with fees estimated from ``eth_feeHistory``. Some chains charge a
fee that their fee history does not forecast, so those fees are refused. ``--legacy-gas-price`` sends legacy
transactions instead:

- ``--legacy-gas-price`` (or ``SAFE_CLI_LEGACY_GAS=1``): priced at ``eth_gasPrice``;
- ``--legacy-gas-price=<gwei>`` (or ``SAFE_CLI_LEGACY_GAS_PRICE=<gwei>``): priced at that fixed value, for example
  to pay more than the node suggests when the chain is busy.
"""

import os
import sys
from decimal import Decimal, InvalidOperation

from web3 import Web3

LEGACY_GAS_PRICE_FLAG = "--legacy-gas-price"


def parse_gwei(value: str) -> int:
    """
    :return: ``value`` gwei in wei
    :raises ValueError: unless ``value`` is a positive, finite number of gwei that is a whole number of wei
    """
    try:
        gwei = Decimal(value)
        valid = gwei.is_finite() and gwei > 0
    except InvalidOperation:
        valid = False
    wei = gwei * 10**9 if valid else Decimal(0)
    if not valid or wei != wei.to_integral_value():
        raise ValueError(
            f"{LEGACY_GAS_PRICE_FLAG}: expected a positive gas price in gwei, got {value!r}"
        )
    return int(wei)


def take_legacy_gas_price_flag(arguments: list[str]) -> None:
    """
    Removes ``--legacy-gas-price`` and ``--legacy-gas-price=<gwei>`` from ``arguments``, wherever they are, and
    records them in the environment, so they apply to every command and to the interactive mode.
    """
    for argument in list(arguments):
        if argument == LEGACY_GAS_PRICE_FLAG:
            os.environ["SAFE_CLI_LEGACY_GAS"] = "1"
        elif argument.startswith(LEGACY_GAS_PRICE_FLAG + "="):
            value = argument.split("=", 1)[1]
            try:
                parse_gwei(value)
            except ValueError as error:
                sys.exit(str(error))
            os.environ["SAFE_CLI_LEGACY_GAS_PRICE"] = value
        else:
            continue
        arguments.remove(argument)


def legacy_gas_price(w3: Web3) -> int | None:
    """
    :return: gas price in wei for a legacy transaction, or ``None`` to use EIP-1559 fees
    """
    fixed = os.environ.get("SAFE_CLI_LEGACY_GAS_PRICE", "")
    if fixed:
        return parse_gwei(fixed)
    if os.environ.get("SAFE_CLI_LEGACY_GAS", "") == "1":
        return w3.eth.gas_price
    return None


def describe(gas_price: int) -> str:
    return f"legacy gas price {Web3.from_wei(gas_price, 'gwei')} gwei"
