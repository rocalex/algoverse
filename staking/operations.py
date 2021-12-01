from typing import Tuple
from algosdk.v2client.algod import AlgodClient
from .contracts import StakingContract

from utils import fully_compile_contract


class StakingApp:
    def __init__(self, client: AlgodClient):
        self.algod = client
    
    def get_contracts(self) -> Tuple[bytes, bytes]:
        """Get the compiled TEAL contracts for the staking.

        Args:
            client: An algod client that has the ability to compile TEAL programs.

        Returns:
            A tuple of 2 byte strings. The first is the approval program, and the
            second is the clear state program.
        """
        
        contracts = StakingContract()
        approval = fully_compile_contract(self.algod, contracts.approval_program())
        clear_state = fully_compile_contract(self.algod, contracts.clear_program())

        return approval, clear_state