import os

import dotenv
from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction

from account import Account
from utils import get_algod_client, wait_for_confirmation


def create_dummy_asset(client: AlgodClient, sender: Account, total: int, decimals: int, asset_name: str, unit_name: str):
    txn = transaction.AssetConfigTxn(
        sender=sender.get_address(),
        sp=client.suggested_params(),
        total=total,
        decimals=decimals,
        asset_name=asset_name,
        unit_name=unit_name,
        default_frozen=False,
        manager=sender.get_address(),
        reserve=sender.get_address(),
        freeze=sender.get_address(),
        clawback=sender.get_address()
    )
    signed_txn = txn.sign(sender.get_private_key())

    client.send_transaction(signed_txn)

    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.asset_index is not None and response.asset_index > 0
    return response.asset_index


if __name__ == '__main__':
    dotenv.load_dotenv('.env')

    client = get_algod_client(os.environ.get('ALGOD_URL'), os.environ.get('ALGOD_TOKEN'))
    creator = Account(os.environ.get("CREATOR_PK"))
    asset_id = create_dummy_asset(client, creator, 1_000_000_000, 3, "Algoverse Token", "AVT")
    print(f"Token ID: {asset_id}")
