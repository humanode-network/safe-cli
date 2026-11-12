"""
EIP-1559 fees set by hand.

By default safe-cli takes the fees of every transaction it sends from ``eth_feeHistory``: the next block's base fee
plus the median tip. Two global options override them:

- ``--max-fee-per-gas``: a cap of at least ``eth_gasPrice``, for chains whose fee history forecasts less than they
  charge; ``--max-fee-per-gas=<gwei>``: that cap;
- ``--max-priority-fee-per-gas=<gwei>``: that tip, for example to be included sooner on a busy chain or to replace
  a pending transaction.

The environment variables ``SAFE_CLI_MAX_FEE_PER_GAS`` (``node`` or gwei) and ``SAFE_CLI_MAX_PRIORITY_FEE_PER_GAS``
(gwei) set defaults; the command line overrides them.
"""

from decimal import Decimal, InvalidOperation

from safe_eth.eth import EthereumClient, TxSpeed
from web3 import Web3
from web3.types import TxParams

MAX_FEE_FLAG = "--max-fee-per-gas"
MAX_FEE_ENVVAR = "SAFE_CLI_MAX_FEE_PER_GAS"
MAX_FEE_HELP = (
    "Cap the fee per gas of every transaction sent. Without a value (or with 'node'): at least eth_gasPrice, for "
    "chains whose fee history forecasts less than they charge. With a value: that many gwei, at most 10 times the "
    "node's price."
)
PRIORITY_FEE_FLAG = "--max-priority-fee-per-gas"
PRIORITY_FEE_ENVVAR = "SAFE_CLI_MAX_PRIORITY_FEE_PER_GAS"
PRIORITY_FEE_HELP = (
    "Tip per gas, in gwei, of every transaction sent, instead of the fee history's median: for example to be "
    "included sooner, or to replace a pending transaction. At most the cap."
)
NODE_PRICE = "node"
# A cap above this many times the node's price is refused: far more likely a typing mistake (gwei taken for wei,
# extra zeros) than an intended fee.
MAX_FEE_MULTIPLE = 10

_max_fee: str | None = None
_priority_fee: str | None = None


def parse_gwei(value: str, flag: str, allow_zero: bool = False) -> int:
    """
    :return: ``value`` gwei in wei
    :raises ValueError: unless ``value`` is a finite number of gwei, positive (or zero if allowed), that is a whole
        number of wei
    """
    try:
        gwei = Decimal(value)
        valid = gwei.is_finite() and (gwei > 0 or (allow_zero and gwei == 0))
    except InvalidOperation:
        valid = False
    wei = gwei * 10**9 if valid else Decimal(0)
    if not valid or wei != wei.to_integral_value():
        expected = (
            "a gas price in gwei" if allow_zero else "a positive gas price in gwei"
        )
        if flag == MAX_FEE_FLAG:
            expected = f"'{NODE_PRICE}' or {expected}"
        raise ValueError(f"{flag}: expected {expected}, got {value!r}")
    return int(wei)


def check_max_fee(value: str | None) -> str | None:
    if value is not None and value != NODE_PRICE:
        parse_gwei(value, MAX_FEE_FLAG)
    return value


def check_priority_fee(value: str | None) -> str | None:
    if value is not None:
        parse_gwei(value, PRIORITY_FEE_FLAG, allow_zero=True)
    return value


def set_fees(max_fee: str | None, priority_fee: str | None) -> None:
    """
    Sets the fees of every transaction sent from now on. ``None`` for both keeps safe-cli's estimate.
    """
    global _max_fee, _priority_fee
    _max_fee, _priority_fee = check_max_fee(max_fee), check_priority_fee(priority_fee)


def take_fee_flags(arguments: list[str]) -> list[str]:
    """
    Removes the fee options from ``arguments``, wherever they are, so they can be given anywhere on the command line,
    and ``--max-fee-per-gas`` without a value.

    :return: the options in the one form the parsers declare (``--flag=value``), the last one of each given winning
    """
    taken: dict[str, str] = {}
    remaining: list[str] = []
    arguments_iter = iter(arguments)
    for argument in arguments_iter:
        if argument == MAX_FEE_FLAG:
            taken[MAX_FEE_FLAG] = NODE_PRICE
        elif argument == PRIORITY_FEE_FLAG:
            taken[PRIORITY_FEE_FLAG] = next(arguments_iter, "")
        elif argument.startswith((MAX_FEE_FLAG + "=", PRIORITY_FEE_FLAG + "=")):
            flag, value = argument.split("=", 1)
            taken[flag] = value
        else:
            remaining.append(argument)
    arguments[:] = remaining
    return [f"{flag}={value}" for flag, value in taken.items()]


def eip1559_fees(ethereum_client: EthereumClient) -> TxParams | None:
    """
    :return: ``maxFeePerGas`` and ``maxPriorityFeePerGas`` for the next transaction, or ``None`` to keep safe-cli's
        estimate
    :raises ValueError: if the network has no EIP-1559 fee history, if the cap is more than ``MAX_FEE_MULTIPLE``
        times the node's price, or if the tip is above the cap
    """
    if _max_fee is None and _priority_fee is None:
        return None
    if not ethereum_client.is_eip1559_supported():
        raise ValueError(
            f"{MAX_FEE_FLAG} and {PRIORITY_FEE_FLAG} need a network with EIP-1559 fees, nothing was sent"
        )
    base_fee, estimated_tip = ethereum_client.estimate_fee_eip1559(TxSpeed.NORMAL)
    node_price = ethereum_client.w3.eth.gas_price
    if _priority_fee is None:
        tip = estimated_tip
    else:
        tip = parse_gwei(_priority_fee, PRIORITY_FEE_FLAG, allow_zero=True)
    if _max_fee is None:
        max_fee = base_fee + tip
    elif _max_fee == NODE_PRICE:
        max_fee = max(base_fee + tip, node_price)
    else:
        max_fee = parse_gwei(_max_fee, MAX_FEE_FLAG)
    reference = max(node_price, base_fee + estimated_tip)
    if reference and max_fee > reference * MAX_FEE_MULTIPLE:
        raise ValueError(
            f"{MAX_FEE_FLAG}: {gwei(max_fee)} gwei is more than {MAX_FEE_MULTIPLE} times the node's price "
            f"({gwei(reference)} gwei), nothing was sent"
        )
    if tip > max_fee:
        if _priority_fee is not None:
            raise ValueError(
                f"{PRIORITY_FEE_FLAG}: {gwei(tip)} gwei is above the cap of {gwei(max_fee)} gwei, nothing was sent"
            )
        tip = max_fee
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip}


def gwei(wei: int) -> str:
    return str(Web3.from_wei(wei, "gwei"))


def describe(fees: TxParams) -> str:
    return (
        f"max fee per gas {gwei(fees['maxFeePerGas'])} gwei, "
        f"max priority fee per gas {gwei(fees['maxPriorityFeePerGas'])} gwei"
    )
