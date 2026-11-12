import os
import re
from decimal import Decimal

import typer
from safe_eth.eth import EthereumClient, TxSpeed
from web3 import Web3
from web3.types import TxParams, Wei

from .exceptions import SafeOperatorException

MAX_FEE_PER_GAS_ENV = "SAFE_CLI_MAX_FEE_PER_GAS"
# A cap of 9.9 times the node's gas price, or more, is refused: one zero too many is 10 times
MAX_FEE_PER_GAS_LIMIT = Decimal("9.9")


def max_fee_per_gas_from_environment() -> int | None:
    """
    :return: ``SAFE_CLI_MAX_FEE_PER_GAS`` in wei, or ``None`` if it is not set
    :raises typer.BadParameter: unless the value is a positive decimal number of gwei, such as ``30`` or ``1.5``
    """
    value = os.environ.get(MAX_FEE_PER_GAS_ENV)
    if not value:
        return None
    # Digits only, so that "1e3" or "1_0" is not read as another amount; at most 9 decimals, a whole number of wei
    if re.fullmatch(r"[0-9]+(\.[0-9]{1,9})?", value):
        max_fee_per_gas = int(Decimal(value) * 10**9)
        if max_fee_per_gas > 0:
            return max_fee_per_gas
    raise typer.BadParameter(
        f"expected a positive number of gwei, got {value!r}",
        param_hint=MAX_FEE_PER_GAS_ENV,
    )


def _gwei(wei: int) -> str:
    return format(Web3.from_wei(wei, "gwei"), "f")


class SafeCliEthereumClient(EthereumClient):
    """
    ``EthereumClient`` that sends EIP-1559 transactions with the ``maxFeePerGas`` set in the environment variable
    ``SAFE_CLI_MAX_FEE_PER_GAS``, in gwei. Without the variable it behaves as ``EthereumClient``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_fee_per_gas = max_fee_per_gas_from_environment()

    def set_eip1559_fees(
        self, tx: TxParams, tx_speed: TxSpeed = TxSpeed.NORMAL
    ) -> TxParams:
        tx = super().set_eip1559_fees(tx, tx_speed)
        if self.max_fee_per_gas is None:
            return tx
        node_price = self.w3.eth.gas_price
        if node_price and self.max_fee_per_gas >= MAX_FEE_PER_GAS_LIMIT * node_price:
            raise SafeOperatorException(
                f"{MAX_FEE_PER_GAS_ENV} ({_gwei(self.max_fee_per_gas)} gwei) is {MAX_FEE_PER_GAS_LIMIT} times the "
                f"node's gas price ({_gwei(node_price)} gwei) or more. Nothing was sent."
            )
        tx["maxFeePerGas"] = Wei(self.max_fee_per_gas)
        # A node rejects a tip above the cap
        tx["maxPriorityFeePerGas"] = min(tx["maxPriorityFeePerGas"], tx["maxFeePerGas"])
        return tx
