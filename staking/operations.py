from encodings import utf_8
from typing import Tuple
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient

from utils import fully_compile_contract, get_app_address, get_app_global_state, wait_for_confirmation
from account import Account
from time import time
from .contracts import approval_program, clear_state_program


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


def create_staking_app(client: AlgodClient, creator: Account, token_id: int, token_app_id: int) -> int:
    approval, clear = get_contracts(client)
    
    global_schema = transaction.StateSchema(num_uints=5, num_byte_slices=0)
    local_schema = transaction.StateSchema(num_uints=4, num_byte_slices=0)
    
    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        foreign_assets=[token_id],
        foreign_apps=[token_app_id],
        sp=client.suggested_params()
    )
    
    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)
    
    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.application_index is not None and response.application_index > 0
    app_id = response.application_index
    print(f"App ID: {app_id}")
    print(f"App address: {get_app_address(app_id)}")
    
    funding_amount = (
        # account min balance
        100_000
        # optin asset
        + 100_000
        # optin txn
        + 1_000
    )
    txn = transaction.PaymentTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        receiver=get_app_address(app_id),
        amt=funding_amount,  # min balance of the application
    )
    
    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)
    
    wait_for_confirmation(client, signed_txn.get_txid())
    return app_id


def setup_app(client: AlgodClient, app_id: int, creator: Account):
    globalState = get_app_global_state(client, app_id)
    token_id = globalState[b"TK_ID"]
    
    txn = transaction.ApplicationCallTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        index=app_id,
        app_args=[b"setup"],
        foreign_assets=[token_id],
        on_complete=transaction.OnComplete.NoOpOC,
    )
    
    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)
    
    wait_for_confirmation(client, signed_txn.get_txid())


def set_timelock(client: AlgodClient, app_id: int, creator: Account):
    txn = transaction.ApplicationCallTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        index=app_id,
        app_args=[b"set_timelock", int(time()).to_bytes(8, "big")],
        on_complete=transaction.OnComplete.NoOpOC,
    )
    
    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)
    
    wait_for_confirmation(client, signed_txn.get_txid())


def stake_token(client: AlgodClient, app_id: int, sender: Account, amount: int):
    globalState = get_app_global_state(client, app_id)
    sp = client.suggested_params()
    
    sp.fee = 3 * 1_000
    transfer_call_txn = transaction.ApplicationCallTxn(
        sender=sender.get_address(),
        sp=sp,
        index=globalState[b"TA"],
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"transfer",
            amount.to_bytes(8, 'big'),
        ],
    )
    sp.fee = 1_000
    call_txn = transaction.ApplicationCallTxn(
        sender=sender.get_address(),
        sp=sp,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"stake",
            amount.to_bytes(8, 'big'),
        ],
    )
    transaction.assign_group_id([transfer_call_txn, call_txn])
    
    signed_transfer_call_txn = transfer_call_txn.sign(sender.get_private_key())
    signed_call_txn = call_txn.sign(sender.get_private_key())
    tx_id = client.send_transactions([signed_transfer_call_txn, signed_call_txn])
    
    wait_for_confirmation(client, tx_id)


def withdraw_token(client: AlgodClient, app_id: int, sender: Account, amount: int):
    sp = client.suggested_params()
    globalState = get_app_global_state(client, app_id)
    token_id = globalState[b"TK_ID"]
    
    sp.fee = 3 * 1_000
    transfer_call_txn = transaction.ApplicationCallTxn(
        sender=sender.get_address(),
        sp=sp,
        index=globalState[b"TA"],
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"transfer",
            amount.to_bytes(8, 'big'),
        ],
    )
    sp.fee = 1_000
    call_txn = transaction.ApplicationCallTxn(
        sender=sender.get_address(),
        sp=sp,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"withdraw",
            amount.to_bytes(8, 'big'),
        ],
        foreign_assets=[token_id]
    )
    
    transaction.assign_group_id([transfer_call_txn, call_txn])
    
    signed_transfer_call_txn = transfer_call_txn.sign(sender.get_private_key())
    signed_call_txn = call_txn.sign(sender.get_private_key())
    tx_id = client.send_transactions([signed_transfer_call_txn, signed_call_txn])
    
    wait_for_confirmation(client, tx_id)
        

def claim_rewards(client: AlgodClient, app_id: int, sender: Account):
    globalState = get_app_global_state(client, app_id)
    token_id = globalState[b"TK_ID"]
    
    call_txn = transaction.ApplicationCallTxn(
        sender=sender.get_address(),
        sp=client.suggested_params(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"claim",
        ],
        foreign_assets=[token_id]
    )
    
    signed_call_txn = call_txn.sign(sender.get_private_key())
    tx_id = client.send_transaction(signed_call_txn)
    
    wait_for_confirmation(client, tx_id)
    
    
def delete_staking_app(client: AlgodClient, app_id: int, closer: Account):
    delete_txn = transaction.ApplicationDeleteTxn(
        sender=closer.get_address(),
        index=app_id,
        sp=client.suggested_params(),
    )
    signed_delete_txn = delete_txn.sign(closer.get_private_key())
    client.send_transaction(signed_delete_txn)

    wait_for_confirmation(client, signed_delete_txn.get_txid())
