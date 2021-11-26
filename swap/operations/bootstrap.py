from algosdk.future.transaction import ApplicationOptInTxn, PaymentTxn, AssetCreateTxn, AssetOptInTxn
from algosdk.v2client.algod import AlgodClient

from . import get_pool_logicsig
from ..utils import int_to_bytes, TransactionGroup


def prepare_bootstrap_transactions(
        client: AlgodClient,
        validator_app_id: int,
        asset1_id: int,
        asset2_id: int,
        asset1_unit_name: str,
        asset2_unit_name: str,
        sender: str,
        suggested_params
):
    pool_logicsig = get_pool_logicsig(client, validator_app_id, asset1_id, asset2_id)
    pool_address = pool_logicsig.address()

    assert (asset1_id > asset2_id)

    if asset2_id == 0:
        asset2_unit_name = 'ALGO'

    txns = [
        PaymentTxn(
            sender=sender,
            sp=suggested_params,
            receiver=pool_address,
            amt=961000 if asset2_id > 0 else 860000,
            note='fee',
        ),
        ApplicationOptInTxn(
            sender=pool_address,
            sp=suggested_params,
            index=validator_app_id,
            app_args=['bootstrap', int_to_bytes(asset1_id), int_to_bytes(asset2_id)],
            foreign_assets=[asset1_id] if asset2_id == 0 else [asset1_id, asset2_id],
        ),
        AssetCreateTxn(
            sender=pool_address,
            sp=suggested_params,
            total=0xFFFFFFFFFFFFFFFF,
            decimals=6,
            unit_name='TM1POOL',
            asset_name=f'Tinyman Pool {asset1_unit_name}-{asset2_unit_name}',
            url='https://tinyman.org',
            default_frozen=False,
        ),
        AssetOptInTxn(
            sender=pool_address,
            sp=suggested_params,
            index=asset1_id,
        ),
    ]
    if asset2_id > 0:
        txns += [
            AssetOptInTxn(
                sender=pool_address,
                sp=suggested_params,
                index=asset2_id,
            )
        ]
    txn_group = TransactionGroup(txns)
    txn_group.sign_with_logicisg(pool_logicsig)
    return txn_group
