from safe_eth.eth import EthereumClient, TxSpeed
from web3 import Web3
from web3.types import TxParams, Wei

# A cap above this many times the node's gas price is refused: far more likely a typing mistake (extra zeros, wei
# taken for gwei) than an intended fee
MAX_FEE_PER_GAS_LIMIT = 10


class SafeCliEthereumClient(EthereumClient):
    """
    ``EthereumClient`` whose EIP-1559 ``maxFeePerGas`` the user can set, with ``--max-fee-per-gas``.

    ``EthereumClient.set_eip1559_fees`` takes ``maxFeePerGas`` from ``eth_feeHistory`` and offers no way to change
    it. Some chains refuse that estimate (a fixed-fee chain whose node forecasts less than it charges), and on a
    busy chain the user may want a higher cap. A cap above ``MAX_FEE_PER_GAS_LIMIT`` times the node's gas price is
    refused before anything is sent.
    """

    # Cap in wei for every transaction sent. ``None`` keeps the estimate.
    max_fee_per_gas: int | None = None

    def set_eip1559_fees(
        self, tx: TxParams, tx_speed: TxSpeed = TxSpeed.NORMAL
    ) -> TxParams:
        tx = super().set_eip1559_fees(tx, tx_speed)
        if self.max_fee_per_gas is not None:
            node_price = self.w3.eth.gas_price
            if node_price and self.max_fee_per_gas > MAX_FEE_PER_GAS_LIMIT * node_price:
                raise ValueError(
                    f"--max-fee-per-gas: {Web3.from_wei(self.max_fee_per_gas, 'gwei')} gwei is more than "
                    f"{MAX_FEE_PER_GAS_LIMIT} times the node's gas price "
                    f"({Web3.from_wei(node_price, 'gwei')} gwei), nothing was sent"
                )
            tx["maxFeePerGas"] = Wei(self.max_fee_per_gas)
            # The tip cannot be above the cap
            tx["maxPriorityFeePerGas"] = min(
                tx["maxPriorityFeePerGas"], tx["maxFeePerGas"]
            )
        return tx
