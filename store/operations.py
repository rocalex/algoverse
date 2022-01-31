from dis import dis
from typing import Tuple
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from prometheus_client import Enum
from pyteal.ast import txn

from .contracts import approval_program, clear_state_program

from utils import fully_compile_contract, get_app_address, wait_for_confirmation
from account import Account

def get_contracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    """Get the compiled TEAL contracts for the bidding.

    Args:
        client: An algod client that has the ability to compile TEAL programs.

    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    approval = fully_compile_contract(client, approval_program())
    clear_state = fully_compile_contract(client, clear_state_program())

    return approval, clear_state


def create_store_app(client: AlgodClient, creator: Account) -> int:
    approval, clear = get_contracts(client=client)
    
    global_schema = transaction.StateSchema(num_uints=6, num_byte_slices=0)
    local_schema = transaction.StateSchema(num_uints=2, num_byte_slices=0)
    
    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        sp=client.suggested_params()
    )
    
    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)        
    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.application_index is not None and response.application_index > 0
    app_id = response.application_index
    print(f"Store App ID: {app_id}")
    print(f"Store App address: {get_app_address(app_id)}")
    
    txn = transaction.PaymentTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        receiver=get_app_address(app_id),
        amt=201_000,  # min balance of the application
    )
    
    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)
    wait_for_confirmation(client, signed_txn.get_txid())

    return app_id


def set_up(client: AlgodClient, creator: Account, app_id: int, trade_app_id: int, bid_app_id: int, auction_app_id: int, distribution_app_id: int):
    call_txn = transaction.ApplicationCallTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        foreign_apps=[trade_app_id, bid_app_id, auction_app_id, distribution_app_id],
        app_args=[b"setup"],
    )
    signed_txn = call_txn.sign(creator.get_private_key())
    tx_id = client.send_transaction(signed_txn)
    wait_for_confirmation(client, tx_id)