from typing import Tuple
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from pyteal.ast import txn

from .contracts import StoreContract

from utils import fully_compile_contract, get_app_address, wait_for_confirmation
from account import Account


class StoringPool:
    def __init__(self, client: AlgodClient, creator: Account):
        self.algod: AlgodClient = client
        self.creator: Account = creator
        self.app_id: int = 0
    
    def get_contracts(self) -> Tuple[bytes, bytes]:
        """Get the compiled TEAL contracts for the staking.

        Args:
            client: An algod client that has the ability to compile TEAL programs.

        Returns:
            A tuple of 2 byte strings. The first is the approval program, and the
            second is the clear state program.
        """
        
        contracts = StoreContract()
        approval = fully_compile_contract(self.algod, contracts.approval_program())
        clear_state = fully_compile_contract(self.algod, contracts.clear_program())

        return approval, clear_state
    
    def create_app(self):
        approval, clear = self.get_contracts()
        
        global_schema = transaction.StateSchema(num_uints=5, num_byte_slices=0)
        local_schema = transaction.StateSchema(num_uints=2, num_byte_slices=0)
        
        txn = transaction.ApplicationCreateTxn(
            sender=self.creator.get_address(),
            on_complete=transaction.OnComplete.NoOpOC,
            approval_program=approval,
            clear_program=clear,
            global_schema=global_schema,
            local_schema=local_schema,
            sp=self.algod.suggested_params()
        )
        
        signed_txn = txn.sign(self.creator.get_private_key())
        self.algod.send_transaction(signed_txn)        
        response = wait_for_confirmation(self.algod, signed_txn.get_txid())
        assert response.application_index is not None and response.application_index > 0
        self.app_id = response.application_index
        print(f"Store App ID: {self.app_id}")
        print(f"Store App address: {get_app_address(self.app_id)}")
        
        txn = transaction.PaymentTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            receiver=get_app_address(self.app_id),
            amt=201_000,  # min balance of the application
        )
        
        signed_txn = txn.sign(self.creator.get_private_key())
        self.algod.send_transaction(signed_txn)
        wait_for_confirmation(self.algod, signed_txn.get_txid())
        
    def set_up(self, trade_app_id: int, bid_app_id: int, auction_app_id: int):
        call_txn = transaction.ApplicationCallTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            foreign_apps=[trade_app_id, bid_app_id, auction_app_id],
            app_args=[b"setup"],
        )
        signed_txn = call_txn.sign(self.creator.get_private_key())
        tx_id = self.algod.send_transaction(signed_txn)
        wait_for_confirmation(self.algod, tx_id)
        
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
      
    def set_sold_amount(self, account: Account, amount: int):
        call_txn = transaction.ApplicationCallTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"set_sold", amount
            ],
            accounts=[account.get_address()]
        )
        signed_txn = call_txn.sign(self.creator.get_private_key())
        tx_id = self.algod.send_transaction(signed_txn)
        wait_for_confirmation(self.algod, tx_id)
    
    def set_bought_amount(self, account: Account, amount: int):
        call_txn = transaction.ApplicationCallTxn(
            sender=self.creator.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"set_bought", amount
            ],
            accounts=[account.get_address()]
        )
        signed_txn = call_txn.sign(self.creator.get_private_key())
        tx_id = self.algod.send_transaction(signed_txn)
        wait_for_confirmation(self.algod, tx_id)
        
    def buy(self, seller: Account, buyer: Account, amount: int):
        call_txn = transaction.ApplicationCallTxn(
            sender=self.buyer.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"buy", amount
            ],
            accounts=[seller.get_address()]
        )
        signed_txn = call_txn.sign(self.creator.get_private_key())
        tx_id = self.algod.send_transaction(signed_txn)
        wait_for_confirmation(self.algod, tx_id)
        
    def sell(self, seller: Account, buyer: Account, amount: int):
        call_txn = transaction.ApplicationCallTxn(
            sender=seller.get_address(),
            sp=self.algod.suggested_params(),
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"sell", amount
            ],
            accounts=[buyer.get_address()]
        )
        signed_txn = call_txn.sign(self.seller.get_private_key())
        tx_id = self.algod.send_transaction(signed_txn)
        wait_for_confirmation(self.algod, tx_id)