from typing import Tuple
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient

from .contracts import StakingContract

from utils import fully_compile_contract, get_app_address, wait_for_confirmation
from account import Account


class StakingPool:
    def __init__(self, client: AlgodClient, creator: Account, token_id: int):
        self.algod: AlgodClient = client
        self.creator: Account = creator
        self.token_id: int = token_id
        self.app_id: int = 0
    
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
    
    def create_app(self):
        approval, clear = self.get_contracts()
        
        global_schema = transaction.StateSchema(num_uints=56, num_byte_slices=1)
        local_schema = transaction.StateSchema(num_uints=16, num_byte_slices=0)
        
        txn = transaction.ApplicationCreateTxn(
            sender=self.creator.get_address(),
            on_complete=transaction.OnComplete.NoOpOC,
            approval_program=approval,
            clear_program=clear,
            global_schema=global_schema,
            local_schema=local_schema,
            foreign_assets=[self.token_id],
            sp=self.algod.suggested_params()
        )
        
        signed_txn = txn.sign(self.creator.get_private_key())
        
        self.algod.send_transaction(signed_txn)
        
        response = wait_for_confirmation(self.algod, signed_txn.get_txid())
        assert response.application_index is not None and response.application_index > 0
        self.app_id = response.application_index
        print(f"App ID: {self.app_id}")
        print(f"App address: {get_app_address(self.app_id)}")
        
        txn = transaction.PaymentTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            receiver=get_app_address(self.app_id),
            amt=201_000,
        )
        
        signed_txn = txn.sign(self.creator.get_private_key())
        
        self.algod.send_transaction(signed_txn)
        
        wait_for_confirmation(self.algod, signed_txn.get_txid())
        
    def setup_app(self):
        txn = transaction.ApplicationCallTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            app_args=[b"setup"],
            foreign_assets=[self.token_id],
            on_complete=transaction.OnComplete.NoOpOC,
        )
        
        signed_txn = txn.sign(self.creator.get_private_key())
        
        self.algod.send_transaction(signed_txn)
        
        wait_for_confirmation(self.algod, signed_txn.get_txid())
        
    def delete_app(self):
        txn = transaction.ApplicationDeleteTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id
        )
        
        signed_txn = txn.sign(self.creator.get_private_key())
        
        self.algod.send_transaction(signed_txn)
        
        wait_for_confirmation(self.algod, signed_txn.get_txid())
        
    def is_opted_in(self, user_address):
        account_info = self.algod.account_info(user_address)  
        for a in account_info.get('apps-local-state', []):
            if a['id'] == self.app_id:
                return True
        return False
    
    def optin_app(self, sender: Account):
        txn = transaction.ApplicationOptInTxn(
            sender=sender.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id
        )
        signed_txn = txn.sign(sender.get_private_key())
        self.algod.send_transaction(signed_txn)
        
        wait_for_confirmation(self.algod, signed_txn.get_txid())
        
    def optout_app(self, sender: Account):
        txn = transaction.ApplicationClearStateTxn(
            sender=sender.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id
        )
        signed_txn = txn.sign(sender.get_private_key())
        self.algod.send_transaction(signed_txn)
        
        wait_for_confirmation(self.algod, signed_txn.get_txid())
        
    def stake_token(self, sender: Account, amount: int):
        transfer_txn = transaction.AssetTransferTxn(
            sender=sender.get_address(),
            sp=self.algod.suggested_params(),
            receiver=get_app_address(self.app_id),
            index=self.token_id,
            amt=amount,
        )
        call_txn = transaction.ApplicationCallTxn(
            sender=sender.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"stake",
            ]
        )
        transaction.assign_group_id([transfer_txn, call_txn])
        
        signed_transfer_txn = transfer_txn.sign(sender.get_private_key())
        signed_call_txn = call_txn.sign(sender.get_private_key())
        tx_id = self.algod.send_transactions([signed_transfer_txn, signed_call_txn])
        
        wait_for_confirmation(self.algod, tx_id)
    
    def withdraw_token(self, sender: Account, amount: int):
        payment_txn = transaction.PaymentTxn(
            sender=sender.get_address(),
            sp=self.algod.suggested_params(),
            receiver=get_app_address(self.app_id),
            amt=100_000
        )
        call_txn = transaction.ApplicationCallTxn(
            sender=sender.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"withdraw",
                amount.to_bytes(8, 'big'),
            ],
            foreign_assets=[self.token_id]
        )
        transaction.assign_group_id([payment_txn, call_txn])
        
        signed_payment_txn = payment_txn.sign(sender.get_private_key())
        signed_call_txn = call_txn.sign(sender.get_private_key())
        tx_id = self.algod.send_transactions([signed_payment_txn, signed_call_txn])
        
        wait_for_confirmation(self.algod, tx_id)
    
    def claim_rewards(self):
        pass