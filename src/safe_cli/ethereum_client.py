from safe_eth.eth import EthereumClient, TxSpeed
from web3.types import TxParams, Wei


class SafeCliEthereumClient(EthereumClient):
    """
    ``EthereumClient`` that does not cap the fee of an EIP-1559 transaction below the node's own gas price.

    ``EthereumClient.set_eip1559_fees`` takes ``maxFeePerGas`` from ``eth_feeHistory``: the next block's forecast
    base fee plus the tip. A chain that charges more than its fee history forecasts (a fixed-fee chain whose node
    still projects a falling base fee) refuses such a transaction. There the node's ``eth_gasPrice`` is above the
    forecast, and it becomes the cap. Where the forecast is at or above ``eth_gasPrice``, nothing changes.
    """

    def set_eip1559_fees(
        self, tx: TxParams, tx_speed: TxSpeed = TxSpeed.NORMAL
    ) -> TxParams:
        """
        :return: TxParams in EIP1559 format, with ``maxFeePerGas`` of at least ``eth_gasPrice``
        :raises: ValueError if EIP1559 not supported
        """
        tx = super().set_eip1559_fees(tx, tx_speed)
        tx["maxFeePerGas"] = Wei(max(tx["maxFeePerGas"], self.w3.eth.gas_price))
        return tx
