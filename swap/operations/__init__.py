import importlib.resources
from typing import Tuple

from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction

from .. import contracts

from ..utils import fully_compile_contract, wait_for_confirmation
from ..account import Account


def get_contracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    approval_teal = importlib.resources.read_text(contracts, 'validator_approval.teal')
    clear_teal = importlib.resources.read_text(contracts, 'validator_clear_state.teal')
    approval = fully_compile_contract(client, approval_teal)
    clear_state = fully_compile_contract(client, clear_teal)
    return approval, clear_state


def get_pool_logicsig(client: AlgodClient, validator_app_id, asset1_id, asset2_id):
    teal = importlib.resources.read_text(contracts, 'pool_logicsig.teal')
    teal = teal.replace("TMPL_ASSET_ID_1", str(asset1_id))
    teal = teal.replace("TMPL_ASSET_ID_2", str(asset2_id))
    teal = teal.replace("TMPL_VALIDATOR_APP_ID", str(validator_app_id))
    program_bytes = fully_compile_contract(client, teal)

    return transaction.LogicSig(program=program_bytes)


def create_validator_app(client: AlgodClient, creator: Account):
    approval, clear = get_contracts(client)

    global_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)
    local_schema = transaction.StateSchema(num_uints=16, num_byte_slices=0)

    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[b"create"],
        sp=client.suggested_params(),
    )

    signed_txn = txn.sign(creator.get_private_key())

    client.send_transaction(signed_txn)

    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.get('application-index') is not None and response.get('application-index') > 0
    return response.get('application-index')


def delete_validator_app(client: AlgodClient, creator: Account, app_id: int):
    txn = transaction.ApplicationDeleteTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        index=app_id
    )

    signed_txn = txn.sign(creator.get_private_key())
    
    client.send_transaction(signed_txn)

    wait_for_confirmation(client, signed_txn.get_txid())


def create_algoverse_token(client: AlgodClient, creator: Account):
    txn = transaction.AssetCreateTxn(
        sender=creator.get_address(),
        sp=client.suggested_params(),
        total=18_446_744_073_709_551_615,
        decimals=6,
        default_frozen=False,
        manager=creator.get_address(),
        reserve=creator.get_address(),
        freeze=creator.get_address(),
        clawback=creator.get_address(),
        asset_name="Algoverse USDC",
        unit_name="AVUSDC",
        url="https://algoverse.exchange"
    )

    signed_txn = txn.sign(creator.get_private_key())

    client.send_transaction(signed_txn)

    response = wait_for_confirmation(client, signed_txn.get_txid())

    assert response.get('asset-index') is not None and response.get('asset-index') > 0
    return response.get('asset-index')