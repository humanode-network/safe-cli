from safe_eth.eth import EthereumClient, TxSpeed
from web3.types import TxParams, Wei

# Headroom of maxFeePerGas over the forecast base fee, as ethers, viem and web3.py's default strategy use: the base
# fee can rise 12.5% per block, so 2x keeps a transaction valid for about six full blocks in a row.
BASE_FEE_MULTIPLIER = 2


class SafeCliEthereumClient(EthereumClient):
    """
    ``EthereumClient`` whose EIP-1559 fees leave headroom over the forecast base fee.

    ``EthereumClient.set_eip1559_fees`` sets ``maxFeePerGas`` to the next block's forecast base fee plus the tip,
    with no headroom. If the base fee rises before the transaction is included, the cap falls below it and the
    transaction waits; on chains that charge more than their fee history forecasts (a fixed-fee chain whose node
    still projects a falling base fee) it is refused outright. ``maxFeePerGas`` is only a cap: the sender still pays
    the base fee plus the tip.
    """

    def set_eip1559_fees(
        self, tx: TxParams, tx_speed: TxSpeed = TxSpeed.NORMAL
    ) -> TxParams:
        tx = super().set_eip1559_fees(tx, tx_speed)
        tip = tx["maxPriorityFeePerGas"]
        base_fee = tx["maxFeePerGas"] - tip
        tx["maxFeePerGas"] = Wei(BASE_FEE_MULTIPLIER * base_fee + tip)
        return tx
