from algosdk.future.transaction import ApplicationClearStateTxn
from algosdk.v2client.algod import AlgodClient


def get_optout_transactions(client: AlgodClient, sender, validator_app_id):
    suggested_params = client.suggested_params()

    txn = ApplicationClearStateTxn(
        sender=sender,
        sp=suggested_params,
        index=validator_app_id,
    )

    return [txn], [None]
