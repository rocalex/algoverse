import os

from typing import Tuple, List

from algosdk import encoding
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client.algod import AlgodClient
from nacl import utils
from pyteal.ast import app

from account import Account
from utils import *
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


def create_bidding_app(
    client: AlgodClient,
    creator: Account,
    store_app_id: int,
) -> int:
    """Create a new bidding.

    Args:
        client: An algod client.
        sender: The account that will create the bidding application.
        seller: The address of the seller that currently holds the NFT being
            traded.
        token_id: The ID of the NFT being traded.
        price: The price of the bidding. If the bidding ends without
            a bid that is equal to or greater than this amount, the bidding will
            fail, meaning the bid amount will be refunded to the lead bidder and
            the NFT will return to the seller.

    Returns:
        The ID of the newly created bidding app.
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


def setup_bidding_app(
    client: AlgodClient,
    app_id: int,
    funder: Account,
    token_id: int,
) -> None:
    """Finish setting up an bidding.

    This operation funds the app bidding escrow account, opts that account into
    the NFT, and sends the NFT to the escrow account, all in one atomic
    transaction group. The bidding must not have started yet.

    The escrow account requires a total of 0.202 Algos for funding. See the code
    below for a breakdown of this amount.

    Args:
        client: An algod client.
        app_id: The app ID of the bidding.
        funder: The account providing the funding for the escrow account.
        token_id: The NFT ID.
    """
    app_address = get_application_address(app_id)

    params = client.suggested_params()

    funding_amount = (
        # min account balance
        100_000
        # enough balance to opt into NFT
        + 100_000_000
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
    
    
def place_bid(client: AlgodClient, app_id: int, bidder: Account, token_id: int, bid_amount: int, bid_price: int, bid_index: str) -> str: 
    """Place or replace a bid on an active bidding.
    Returning rekeyed address as bid index

    Args:
        client: An Algod client.
        app_id: The app ID of the bidding.
        bidder: The account providing the bid.
        bid_amount: The asset amount of the bid.
        bid_price: The price of the bid.
        bid_index: rekeyed address for replace bid
    """
    app_address = get_application_address(app_id)
    suggested_params = client.suggested_params()
    
    # optin asset for receiving the asset
    if is_opted_in_asset(client, token_id, bidder.get_address()) == False:
        print(f"bidder {bidder.get_address()} opt in asset {token_id}")
        optin_asset(client, token_id, bidder)
    
    # optin store app for saving information    
    app_global_state = get_app_global_state(client, app_id)
    store_app_id = app_global_state[b"SA_ID"]
    print(f"store_app_id", store_app_id)
    if is_opted_in_app(client, store_app_id, bidder.get_address()) == False:
        print(f"bidder {bidder.get_address()} opt in app {store_app_id}")
        optin_app(client, store_app_id, bidder)
    
    n_address = bid_index
    # if bid_index is empty, find a usable(if the bid app local state's token id is 0) rekeyed address used in the past, 
    if not n_address:
        unused_rekeyed_address = ""
        rekeyed_addresses = get_rekeyed_addresses(bidder.get_address()) # we will get this from network
        for rekeyed_address in rekeyed_addresses:
            if is_opted_in_app(client, app_id, rekeyed_address):
                state = get_app_local_state(client, app_id, rekeyed_address)
                print(f"local state of {rekeyed_address} :", state)
                if state[b"TK_ID"] == 0:
                    unused_rekeyed_address = rekeyed_address
            else:
                # might have rekeyed address already but not optin app, we can use it
                unused_rekeyed_address = rekeyed_address
                optin_app_rekeyed_address(client, app_id, bidder, unused_rekeyed_address)
                break
        
        # if not found, create one, and optin app for local state
        n_address = unused_rekeyed_address
        if not n_address:
            n_address = generate_rekeyed_account_keypair(client, bidder)
            optin_app_rekeyed_address(client, app_id, bidder, n_address)
            set_rekeyed_address(bidder.get_address(), n_address, 1)
    
    pay_txn = transaction.PaymentTxn(
        sender=bidder.get_address(),
        receiver=app_address,
        amt=bid_price,
        sp=suggested_params,
    )

    app_call_txn = transaction.ApplicationCallTxn(
        sender=bidder.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"bid", bid_amount.to_bytes(8, "big")],
        foreign_assets=[token_id],
        accounts=[n_address],
        sp=suggested_params,
    )

    transaction.assign_group_id([pay_txn, app_call_txn])
    
    signed_pay_txn = pay_txn.sign(bidder.get_private_key())
    signed_app_call_txn = app_call_txn.sign(bidder.get_private_key())

    client.send_transactions([signed_pay_txn, signed_app_call_txn])

    wait_for_confirmation(client, app_call_txn.get_txid())
    return n_address
    
    
def cancel_bid(client: AlgodClient, app_id: int, bidder: Account, bid_index: str) -> None:
    """Place a bid on an active bidding.

    Args:
        client: An Algod client.
        app_id: The app ID of the bidding.
        bidder: The account providing the bid.
    """
    if (is_opted_in_app(client, app_id, bid_index) == False): 
        return False
    
    app_local_state = get_app_local_state(client, app_id, bid_index)
    token_id = app_local_state[b"TK_ID"]
    suggested_params = client.suggested_params()
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=bidder.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"cancel"],
        accounts=[bid_index],
        foreign_assets=[token_id],
        sp=suggested_params,
    )

    signed_app_call_txn = app_call_txn.sign(bidder.get_private_key())
    client.send_transaction(signed_app_call_txn)
    wait_for_confirmation(client, app_call_txn.get_txid())    
    
    # #do we need this store app opt out? cause the bidder might wants to bid again later ?
    # app_global_state = get_app_global_state(client, app_id)
    # store_app_id = app_global_state[b"SA_ID"]
    # if is_opted_in_app(client, store_app_id, bidder.get_address()) == True:
    #     optout_app(client, app_id, bidder)
    # else:
    #     return False
    
    return True


def place_accept(client: AlgodClient, creator: Account, app_id: int, seller: Account, bidder: str, bid_index: str) -> None:
    """Accept on an active bidding.

    Args:
        client: An Algod client.
        creator: The app creator.
        app_id: The app ID of the bidding.
        seller: The accouont selling the asset.
        bidder: The account address offerring the bid.
    """
    app_address = get_application_address(app_id)
    suggested_params = client.suggested_params()
    app_global_state = get_app_global_state(client, app_id)
    
    if (is_opted_in_app(client, app_id, bidder) == False): 
        return False
    
    app_bidder_local_state = get_app_local_state(client, app_id, bid_index)
    token_id = app_bidder_local_state[b"TK_ID"]
    token_amount = app_bidder_local_state[b"TA"]
    bid_price = app_bidder_local_state[b"TP"]
    print(f"token_amount", token_amount)
    print(f"price", bid_price)
    if get_balances(client, seller.get_address())[token_id] < token_amount:
        return False
    
    # if is_opted_in_app(client, app_id, seller.get_address()) == False:
    #     optin_app(client, app_id, seller)
    
    store_app_id = app_global_state[b"SA_ID"]
    if is_opted_in_app(client, store_app_id, seller.get_address()) == False:
        optin_app(client, store_app_id, seller)
    
    asset_txn = transaction.AssetTransferTxn(
        sender=seller.get_address(),
        receiver=app_address,
        index=token_id,
        amt=token_amount,
        sp=suggested_params,
    )
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=seller.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"accept", bid_price.to_bytes(8, "big")],
        foreign_assets=[token_id],
        # must include the bidder here to the app can refund that bidder's payment
        accounts=[bidder, 
                  bid_index, 
                  encoding.encode_address(app_global_state[b"DAA"]), 
                  encoding.encode_address(app_global_state[b"TWA"])],
        sp=suggested_params,
    )
    
    transaction.assign_group_id([asset_txn, app_call_txn])
    signed_asset_txn = asset_txn.sign(seller.get_private_key())
    signed_app_call_txn = app_call_txn.sign(seller.get_private_key())
    client.send_transactions([signed_asset_txn, signed_app_call_txn])
    wait_for_confirmation(client, app_call_txn.get_txid())

    store_app_call_txn = transaction.ApplicationCallTxn(
        sender=creator.get_address(),
        sp=suggested_params,
        index=store_app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"buy", token_amount.to_bytes(8, "big")
        ],
        accounts=[seller.get_address(), bidder]
    )    
    signed_store_app_call_txn = store_app_call_txn.sign(creator.get_private_key())
    client.send_transaction(signed_store_app_call_txn)
    wait_for_confirmation(client, store_app_call_txn.get_txid())
    
    return True


def close_bidding(client: AlgodClient, app_id: int, closer: Account, assets: List[int]):
    """Close an bidding.

    This action can only happen before an bidding has begun, in which case it is
    cancelled, or after an bidding has ended.

    If called after the bidding has ended and the bidding was successful, the
    NFT is transferred to the winning bidder and the bidding proceeds are
    transferred to the seller. If the bidding was not successful, the NFT and
    all funds are transferred to the seller.

    Args:
        client: An Algod client.
        app_id: The app ID of the bidding.
        closer: The account initiating the close transaction. This must be
            the bidding creator.
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