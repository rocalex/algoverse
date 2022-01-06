from base64 import b64decode, b64encode
from typing import Dict, Tuple, Union, List, Any, Optional
from algosdk.future import transaction

from algosdk import encoding
from algosdk.error import AlgodHTTPError
from algosdk.future.transaction import LogicSigTransaction, assign_group_id
from algosdk.v2client.algod import AlgodClient
from pyteal import compileTeal, Expr, Mode

from account import Account
from algosdk import account, mnemonic
import json


def get_algod_client(url, token) -> AlgodClient:
    headers = {
        'X-API-Key': token
    }
    return AlgodClient(token, url, headers)


class PendingTxnResponse:
    def __init__(self, response: Dict[str, Any]) -> None:
        self.poolError: str = response["pool-error"]
        self.txn: Dict[str, Any] = response["txn"]

        self.application_index: Optional[int] = response.get("application-index")
        self.asset_index: Optional[int] = response.get("asset-index")
        self.close_rewards: Optional[int] = response.get("close-rewards")
        self.closing_amount: Optional[int] = response.get("closing-amount")
        self.confirmed_round: Optional[int] = response.get("confirmed-round")
        self.global_state_delta: Optional[Any] = response.get("global-state-delta")
        self.local_state_delta: Optional[Any] = response.get("local-state-delta")
        self.receiver_rewards: Optional[int] = response.get("receiver-rewards")
        self.sender_rewards: Optional[int] = response.get("sender-rewards")

        self.inner_txns: List[Any] = response.get("inner-txns", [])
        self.logs: List[bytes] = [b64decode(ll) for ll in response.get("logs", [])]


class TransactionGroup:

    def __init__(self, transactions: list):
        transactions = assign_group_id(transactions)
        self.transactions = transactions
        self.signed_transactions: list = [None for _ in self.transactions]

    def sign(self, user):
        user.sign_transaction_group(self)

    def sign_with_logicisg(self, logicsig):
        address = logicsig.address()
        for i, txn in enumerate(self.transactions):
            if txn.sender == address:
                self.signed_transactions[i] = LogicSigTransaction(txn, logicsig)

    def sign_with_private_key(self, account: Account):
        for i, txn in enumerate(self.transactions):
            if txn.sender == account.get_address():
                self.signed_transactions[i] = txn.sign(account.get_private_key())

    def submit(self, algod, wait=False):
        try:
            txid = algod.send_transactions(self.signed_transactions)
        except AlgodHTTPError as e:
            raise Exception(str(e))
        if wait:
            return wait_for_confirmation(algod, txid)
        return {'txid': txid}


def wait_for_confirmation(
        client: AlgodClient, tx_id: str
) -> PendingTxnResponse:
    last_status = client.status()
    last_round = last_status.get("last-round")
    pending_txn = client.pending_transaction_info(tx_id)
    while not (pending_txn.get("confirmed-round") and pending_txn.get("confirmed-round") > 0):
        print("Waiting for confirmation...")
        last_round += 1
        client.status_after_block(last_round)
        pending_txn = client.pending_transaction_info(tx_id)
    print(
        "Transaction {} confirmed in round {}.".format(
            tx_id, pending_txn.get("confirmed-round")
        )
    )
    return PendingTxnResponse(pending_txn)


def fully_compile_contract(client: AlgodClient, contract: Expr) -> bytes:
    teal = compileTeal(contract, mode=Mode.Application, version=5)
    response = client.compile(teal)
    return b64decode(response["result"])


def compile_teal(client: AlgodClient, teal) -> bytes:
    response = client.compile(teal)
    return b64decode(response["result"])


def int_to_bytes(num):
    return num.to_bytes(8, 'big')


def get_state_int(state, key):
    if type(key) == str:
        key = b64encode(key.encode())
    return state.get(key.decode(), {'uint': 0})['uint']


def get_state_bytes(state, key):
    if type(key) == str:
        key = b64encode(key.encode())
    return state.get(key.decode(), {'bytes': ''})['bytes']


def decode_state(state_array: List[Any]) -> Dict[bytes, Union[int, bytes]]:
    state: Dict[bytes, Union[int, bytes]] = dict()

    for pair in state_array:
        key = b64decode(pair["key"])

        value = pair["value"]
        value_type = value["type"]

        if value_type == 2:
            # value is uint64
            value = value.get("uint", 0)
        elif value_type == 1:
            # value is byte array
            value = b64decode(value.get("bytes", ""))
        else:
            raise Exception(f"Unexpected state type: {value_type}")

        state[key] = value

    return state


def get_app_global_state(
        client: AlgodClient, app_id: int
) -> Dict[bytes, Union[int, bytes]]:
    app_info = client.application_info(app_id)
    return decode_state(app_info["params"]["global-state"])


def get_app_local_state(
        client: AlgodClient, app_id: int, sender_address: str
) -> Dict[bytes, Union[int, bytes]]:
    account_info = client.account_info(sender_address)
    for local_state in account_info["apps-local-state"]:
        if local_state["id"] == app_id:
            if "key-value" not in local_state:
                return {}

            return decode_state(local_state["key-value"])
    return {}


def get_app_address(app_id: int) -> str:
    to_hash = b"appID" + app_id.to_bytes(8, "big")
    return encoding.encode_address(encoding.checksum(to_hash))


def get_balances(client: AlgodClient, account: str) -> Dict[int, int]:
    balances: Dict[int, int] = dict()

    account_info = client.account_info(account)

    # set key 0 to Algo balance
    balances[0] = account_info["amount"]

    assets: List[Dict[str, Any]] = account_info.get("assets", [])
    for assetHolding in assets:
        asset_id = assetHolding["asset-id"]
        amount = assetHolding["amount"]
        balances[asset_id] = amount

    return balances


def get_asset_info(client: AlgodClient, asset_id: int):
    return client.asset_info(asset_id)


def get_last_block_timestamp(client: AlgodClient) -> Tuple[int, int]:
    status = client.status()
    lastRound = status["last-round"]
    block = client.block_info(lastRound)
    timestamp = block["block"]["ts"]

    return block, timestamp


def is_opted_in_app(client: AlgodClient, app_id: int, user_address: str):
    account_info = client.account_info(user_address)  
    for a in account_info.get('apps-local-state', []):
        if a['id'] == app_id:
            return True
    return False


def optin_app(client: AlgodClient, app_id: int, sender: Account):
    txn = transaction.ApplicationOptInTxn(
        sender=sender.get_address(),
        sp=client.suggested_params(),
        index=app_id
    )
    signed_txn = txn.sign(sender.get_private_key())
    client.send_transaction(signed_txn)
    
    wait_for_confirmation(client, signed_txn.get_txid())
    
    
def optin_app_rekeyed_address(client: AlgodClient, app_id: int, sender: Account, rekeyed_adr: str):
    txn = transaction.ApplicationOptInTxn(
        sender=rekeyed_adr,
        sp=client.suggested_params(),
        index=app_id
    )
    signed_txn = txn.sign(sender.get_private_key())
    client.send_transaction(signed_txn)
    wait_for_confirmation(client, signed_txn.get_txid())
    
    
def optout_app(client: AlgodClient, app_id: int, sender: Account):
    txn = transaction.ApplicationClearStateTxn(
        sender=sender.get_address(),
        sp=client.suggested_params(),
        index=app_id
    )
    signed_txn = txn.sign(sender.get_private_key())
    client.send_transaction(signed_txn)
    wait_for_confirmation(client, signed_txn.get_txid())
    
    
def is_opted_in_asset(client: AlgodClient, asset_id: int, user_address: str):
    account_info = client.account_info(user_address)  
    for a in account_info.get('assets', []):
        if a['asset-id'] == asset_id:
            return True
    return False
    
    
def optin_asset(client: AlgodClient, asset_id: int, sender: Account):
    txn = transaction.AssetOptInTxn(
        sender=sender.get_address(),
        sp=client.suggested_params(),
        index=asset_id
    )
    signed_txn = txn.sign(sender.get_private_key())
    client.send_transaction(signed_txn)
    wait_for_confirmation(client, signed_txn.get_txid())
    
    
def generate_account_keypair():
    private_key, address = account.generate_account()
    print("new address: {}".format(address))
    print("new private_key: {}".format(private_key))
    print("new passphrase: {}".format(mnemonic.from_private_key(private_key)))
    return private_key, address
    

def generate_rekeyed_address(client: AlgodClient, rekey_to: Account, optin_price: int):
    """Generate rekeyed address and charge balance to optin app.   

    Args:
        client: An Algod client.
        rekey_to: Auth address.
        optin_price: Additional min balance to optin app.
    """
    private_key, address = generate_account_keypair()
    
    funding_amount = (
        # min account balance
        100_000
        # additional min balance to opt into app: 100000 + 28500 * 3 + 50000
        + optin_price
        # min txn fee for rekeying
        + 1_000
    )

    fund_account_txn = transaction.PaymentTxn(
        sender=rekey_to.get_address(),
        receiver=address,
        amt=funding_amount,
        sp=client.suggested_params(),
    )
    signed_fund_txn = fund_account_txn.sign(rekey_to.get_private_key())
    client.send_transaction(signed_fund_txn)
    wait_for_confirmation(client, signed_fund_txn.get_txid())
    
    txn = transaction.PaymentTxn(
        sender=address,
        receiver=address,
        amt=0,
        rekey_to=rekey_to.get_address(),
        sp=client.suggested_params(),
    )
    
    signed_txn = txn.sign(private_key)
    client.send_transaction(signed_txn)
    wait_for_confirmation(client, signed_txn.get_txid())
    
    return address


def charge_optin_price(client: AlgodClient, sender: Account, receiver: str, optin_price: int):
    fund_account_txn = transaction.PaymentTxn(
        sender=sender.get_address(),
        receiver=receiver,
        amt=optin_price,
        sp=client.suggested_params(),
    )
    signed_fund_txn = fund_account_txn.sign(sender.get_private_key())
    client.send_transaction(signed_fund_txn)
    wait_for_confirmation(client, signed_fund_txn.get_txid())


def get_rekeyed_addresses(sender: str) -> List:
    result = []
    obj = read_rekeyed_addresses()
    for key in obj:
        if (key == sender):
            for address in obj[key]:
                result.append(address)
        return result
    return []


def write_rekeyed_addresses(obj):
    with open("rekeyed_addresses.json", 'w') as f:
        json.dump(obj, f)
        

def read_rekeyed_addresses():
    with open("rekeyed_addresses.json", 'r') as f:
        return json.load(f)
        

def set_rekeyed_address(sender: str, new_address: str, optedin: int = 0):
    obj = read_rekeyed_addresses()
    #print("obj", obj)
    for key in obj:
        if (key == sender):
            obj[key][new_address] = optedin
            write_rekeyed_addresses(obj)
            return
    
    no = {}
    no[new_address] = optedin
    obj[sender] = no
    write_rekeyed_addresses(obj)


def get_account_info(client: AlgodClient, sender_address: str):
    account_info = client.account_info(sender_address)
    print("account_info", account_info)


# for testing purpose
def deleteApps(client: AlgodClient, app_ids: List[int], sender: Account):
    for app_id in app_ids:
        delete_txn = transaction.ApplicationDeleteTxn(
            sender=sender.get_address(),
            index=app_id,
            sp=client.suggested_params(),
        )
        signed_delete_txn = delete_txn.sign(sender.get_private_key())
        client.send_transaction(signed_delete_txn)
        wait_for_confirmation(client, signed_delete_txn.get_txid())
    
    
# for testing purpose
def optoutApps(client: AlgodClient, app_ids: List[int], account: Account):
    for app_id in app_ids:
        optout_app(client, app_id, account)