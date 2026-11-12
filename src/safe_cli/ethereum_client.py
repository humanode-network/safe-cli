from safe_eth.eth import EthereumClient, TxSpeed
from web3.types import TxParams, Wei

# Headroom of maxFeePerGas over the forecast base fee. ethers, viem and web3.py's default strategy use the same
# factor: the base fee can rise 12.5% per block, so 2x keeps a transaction valid for about six full blocks in a row.
BASE_FEE_MULTIPLIER = 2


class SafeCliEthereumClient(EthereumClient):
    """
    ``EthereumClient`` whose EIP-1559 fees leave headroom over the forecast base fee.

    ``EthereumClient.set_eip1559_fees`` sets ``maxFeePerGas`` to the next block's forecast base fee plus the tip,
    with no headroom. If the base fee rises before the transaction is included, the cap falls below it and the
    transaction waits. A chain that charges more than its fee history forecasts (a fixed-fee chain whose node still
    projects a falling base fee) refuses the transaction outright.

    ``maxFeePerGas`` is a cap, not a price: the sender still pays the base fee plus the tip. The sender's balance
    must cover ``gas * maxFeePerGas``, so a higher cap needs a larger balance.
    """

    def set_eip1559_fees(
        self, tx: TxParams, tx_speed: TxSpeed = TxSpeed.NORMAL
    ) -> TxParams:
        """
        :return: TxParams in EIP1559 format, with ``maxFeePerGas = BASE_FEE_MULTIPLIER * base fee + tip``
        :raises: ValueError if EIP1559 not supported
        """
        tx = super().set_eip1559_fees(tx, tx_speed)
        # The parent sets maxFeePerGas = base fee + tip
        tip = tx["maxPriorityFeePerGas"]
        base_fee = tx["maxFeePerGas"] - tip
        tx["maxFeePerGas"] = Wei(BASE_FEE_MULTIPLIER * base_fee + tip)
        return tx
