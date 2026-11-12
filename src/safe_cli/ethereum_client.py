from safe_eth.eth import EthereumClient, TxSpeed
from web3 import Web3
from web3.types import TxParams, Wei

# safe-cli refuses a cap above this many times the node's gas price. A cap that high is a typo more often than a
# choice: extra zeros, or wei typed as gwei.
MAX_FEE_PER_GAS_LIMIT = 10


class SafeCliEthereumClient(EthereumClient):
    """
    ``EthereumClient`` that sends EIP-1559 transactions with the ``maxFeePerGas`` the user gave in
    ``--max-fee-per-gas``. Without the option it behaves as ``EthereumClient``.
    """

    # The user's cap in wei, or None
    max_fee_per_gas: int | None = None

    def set_eip1559_fees(
        self, tx: TxParams, tx_speed: TxSpeed = TxSpeed.NORMAL
    ) -> TxParams:
        tx = super().set_eip1559_fees(tx, tx_speed)
        if self.max_fee_per_gas is None:
            return tx
        node_price = self.w3.eth.gas_price
        if node_price and self.max_fee_per_gas > MAX_FEE_PER_GAS_LIMIT * node_price:
            raise ValueError(
                f"--max-fee-per-gas: {Web3.from_wei(self.max_fee_per_gas, 'gwei')} gwei is more than "
                f"{MAX_FEE_PER_GAS_LIMIT} times the node's gas price ({Web3.from_wei(node_price, 'gwei')} gwei). "
                "safe-cli sent nothing."
            )
        tx["maxFeePerGas"] = Wei(self.max_fee_per_gas)
        # A node rejects a tip above the cap
        tx["maxPriorityFeePerGas"] = min(tx["maxPriorityFeePerGas"], tx["maxFeePerGas"])
        return tx
