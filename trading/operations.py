import os

from typing import Tuple, List

from algosdk import encoding
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client.algod import AlgodClient
from nacl import utils

from account import Account
from utils import *
from .contracts import approval_program, clear_state_program


def get_contracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    """Get the compiled TEAL contracts for the trading.

    Args:
        client: An algod client that has the ability to compile TEAL programs.

    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    approval = fully_compile_contract(client, approval_program())
    clear_state = fully_compile_contract(client, clear_state_program())

    return approval, clear_state


def create_trading_app(
    client: AlgodClient,
    creator: Account,
    store_app_id: int,
) -> int:
    """Create a new trading.

    Args:
        client: An algod client.
        sender: The account that will create the trading application.
        seller: The address of the seller that currently holds the NFT being
            traded.
        token_id: The ID of the NFT being traded.
        price: The price of the trading. If the trading ends without
            a bid that is equal to or greater than this amount, the trading will
            fail, meaning the bid amount will be refunded to the lead bidder and
            the NFT will return to the seller.

    Returns:
        The ID of the newly created trading app.
    """
    approval, clear = get_contracts(client)

    global_schema = transaction.StateSchema(num_uints=3, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=3, num_byte_slices=0)
    
    distribution_app_address = Account.from_mnemonic(os.environ.get("CREATOR_MN"))
    team_wallet_address = Account.from_mnemonic(os.environ.get("TEAM_MN"))
    
    app_args = [
        store_app_id.to_bytes(8, "big"),
        encoding.decode_address(distribution_app_address.get_address()),
        encoding.decode_address(team_wallet_address.get_address()),
    ]

    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
        sp=client.suggested_params(),
    )

    signed_txn = txn.sign(creator.get_private_key())

    client.send_transaction(signed_txn)

    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.application_index is not None and response.application_index > 0
    return response.application_index


def setup_trading_app(
    client: AlgodClient,
    app_id: int,
    funder: Account,
    token_id: int,
) -> None:
    """Finish setting up an trading.

    This operation funds the app trading escrow account, opts that account into
    the NFT, and sends the NFT to the escrow account, all in one atomic
    transaction group. The trading must not have started yet.

    The escrow account requires a total of 0.202 Algos for funding. See the code
    below for a breakdown of this amount.

    Args:
        client: An algod client.
        app_id: The app ID of the trading.
        funder: The account providing the funding for the escrow account.
        token_id: The NFT ID.
    """
    app_address = get_application_address(app_id)

    params = client.suggested_params()

    funding_amount = (
        # min account balance
        100_000
        # additional min balance to opt into NFT
        + 100_000
        # 2 * min txn fee
        + 2 * 1_000
    )

    fund_app_txn = transaction.PaymentTxn(
        sender=funder.get_address(),
        receiver=app_address,
        amt=funding_amount,
        sp=params,
    )

    setup_txn = transaction.ApplicationCallTxn(
        sender=funder.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"setup"],
        foreign_assets=[token_id],
        sp=params,
    )

    transaction.assign_group_id([fund_app_txn, setup_txn])

    signed_fund_app_txn = fund_app_txn.sign(funder.get_private_key())
    signed_setup_txn = setup_txn.sign(funder.get_private_key())

    client.send_transactions([signed_fund_app_txn, signed_setup_txn])

    wait_for_confirmation(client, signed_fund_app_txn.get_txid())
    
    
def place_trade(client: AlgodClient, app_id: int, seller: Account, token_id: int, token_amount: int, price: int) -> None:
    """Place or replace a bid on an active trading.

    Args:
        client: An Algod client.
        app_id: The app ID of the trading.
        bidder: The account providing the bid.
        bid_amount: The asset amount of the bid.
        bid_price: The price of the bid.
    """
    app_address = get_application_address(app_id)
    app_global_state = get_app_global_state(client, app_id)
    suggested_params = client.suggested_params()
    
    if is_opted_in_app(client, app_id, seller.get_address()) == False:
        print(f"bidder {seller.get_address()} opt in app {app_id}")
        optin_app(client, app_id, seller)
        
    store_app_id = app_global_state[b"SA_ID"]
    print(f"store_app_id", store_app_id)
    if is_opted_in_app(client, store_app_id, seller.get_address()) == False:
        print(f"bidder {seller.get_address()} opt in app {store_app_id}")
        optin_app(client, store_app_id, seller)
    
    token_txn = transaction.AssetTransferTxn(
        sender=seller.get_address(),
        receiver=app_address,
        index=token_id,
        amt=token_amount,
        sp=suggested_params,
    )
    print(f"token_txn: {token_txn}")

    app_call_txn = transaction.ApplicationCallTxn(
        sender=seller.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"trade", price.to_bytes(8, "big")],
        foreign_assets=[token_id],
        sp=suggested_params,
    )

    transaction.assign_group_id([token_txn, app_call_txn])
    
    signed_token_txn = token_txn.sign(seller.get_private_key())
    signed_app_call_txn = app_call_txn.sign(seller.get_private_key())

    client.send_transactions([signed_token_txn, signed_app_call_txn])

    wait_for_confirmation(client, app_call_txn.get_txid())
    return True
    
    
def cancel_trade(client: AlgodClient, app_id: int, seller: Account) -> None:
    """Place a bid on an active trading.

    Args:
        client: An Algod client.
        app_id: The app ID of the trading.
        bidder: The account providing the bid.
    """
    app_global_state = get_app_global_state(client, app_id)
    seller_app_local_state = get_app_local_state(client, app_id, seller.get_address())
    token_id = seller_app_local_state[b"TK_ID"]
    suggested_params = client.suggested_params()
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=seller.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"cancel"],
        foreign_assets=[token_id],
        sp=suggested_params,
    )

    signed_app_call_txn = app_call_txn.sign(seller.get_private_key())
    client.send_transaction(signed_app_call_txn)
    wait_for_confirmation(client, app_call_txn.get_txid())    
    
    store_app_id = app_global_state[b"SA_ID"]
    if is_opted_in_app(client, store_app_id, seller.get_address()) == True:
        # do we need this store app opt out? cause the bidder might wants to bid again later ?
        optout_app(client, app_id, seller)
    else:
        return False

    return True


def place_accept(client: AlgodClient, creator: Account, app_id: int, buyer: Account, seller: str) -> None:
    """Accept on an active trading.

    Args:
        client: An Algod client.
        creator: The app creator.
        app_id: The app ID of the trading.
        seller: The account selling the asset.
        buyer: The account buying the asset.
    """
    app_address = get_application_address(app_id)
    app_global_state = get_app_global_state(client, app_id)
    seller_app_local_state = get_app_local_state(client, app_id, seller)
    token_id = seller_app_local_state[b"TK_ID"]
    
    if (is_opted_in_app(client, app_id, seller) == False): 
        return False
    
    if is_opted_in_asset(client, token_id, buyer.get_address()) == False:
        print(f"bidder {buyer.get_address()} opt in asset {token_id}")
        optin_asset(client, token_id, buyer)
    
    price = seller_app_local_state[b"TP"]
    print(f"price", price)
    # check if buyer has enough algo
    if get_balances(client, seller.get_address())[0] < price:
        return False
    
    if is_opted_in_app(client, app_id, buyer.get_address()) == False:
        optin_app(client, app_id, buyer)
    
    store_app_id = app_global_state[b"SA_ID"]
    if is_opted_in_app(client, store_app_id, buyer.get_address()) == False:
        optin_app(client, store_app_id, buyer)
    
    suggested_params = client.suggested_params()

    pay_txn = transaction.PaymentTxn(
        sender=buyer.get_address(),
        receiver=app_address,
        amt=price,
        sp=suggested_params,
    )
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=buyer.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"accept"],
        foreign_assets=[token_id],
        # must include the bidder here to the app can refund that bidder's payment
        accounts=[seller, 
                  encoding.encode_address(app_global_state[b"DAA"]), 
                  encoding.encode_address(app_global_state[b"TWA"])],
        sp=suggested_params,
    )
    
    transaction.assign_group_id([pay_txn, app_call_txn])
    signed_pay_txn = pay_txn.sign(buyer.get_private_key())
    signed_app_call_txn = app_call_txn.sign(buyer.get_private_key())
    client.send_transactions([signed_pay_txn, signed_app_call_txn])
    wait_for_confirmation(client, app_call_txn.get_txid())

    store_app_call_txn = transaction.ApplicationCallTxn(
        sender=creator.get_address(),
        sp=suggested_params,
        index=store_app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"buy", price.to_bytes(8, 'big')
        ],
        accounts=[seller, buyer.get_address()]
    )    
    signed_store_app_call_txn = store_app_call_txn.sign(creator.get_private_key())
    client.send_transaction(signed_store_app_call_txn)
    wait_for_confirmation(client, store_app_call_txn.get_txid())
    
    return True


def close_trading(client: AlgodClient, app_id: int, closer: Account, assets: List[int]):
    """Close an trading.

    This action can only happen before an trading has begun, in which case it is
    cancelled, or after an trading has ended.

    If called after the trading has ended and the trading was successful, the
    NFT is transferred to the winning bidder and the trading proceeds are
    transferred to the seller. If the trading was not successful, the NFT and
    all funds are transferred to the seller.

    Args:
        client: An Algod client.
        app_id: The app ID of the trading.
        closer: The account initiating the close transaction. This must be
            the trading creator.
    """
    app_global_state = get_app_global_state(client, app_id)

    print(b"assets", assets)

    accounts: List[str] = [encoding.encode_address(app_global_state[b"DAA"]), 
                           encoding.encode_address(app_global_state[b"TWA"])]
    print(b"accounts", accounts)
    
    delete_txn = transaction.ApplicationDeleteTxn(
        sender=closer.get_address(),
        index=app_id,
        accounts=accounts,
        foreign_assets=assets,
        sp=client.suggested_params(),
    )
    signed_delete_txn = delete_txn.sign(closer.get_private_key())
    client.send_transaction(signed_delete_txn)

    wait_for_confirmation(client, signed_delete_txn.get_txid())
