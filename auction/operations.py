import os

from typing import Tuple, List

from algosdk import encoding
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client.algod import AlgodClient
from pyteal.ast import app
from pyteal.ast.global_ import Global

from account import Account
from utils import *
from .contracts import approval_program, clear_state_program


def get_contracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    """Get the compiled TEAL contracts for the auction.

    Args:
        client: An algod client that has the ability to compile TEAL programs.

    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    approval = fully_compile_contract(client, approval_program())
    clear_state = fully_compile_contract(client, clear_state_program())

    return approval, clear_state


def create_auction_app(
    client: AlgodClient,
    creator: Account,
    store_app_id: int
) -> int:
    """Create a new auction.

    Args:
        client: An algod client.
        creator: The account that will create the auction application.
        staking_address: staking app address,
        team_wallet_address: team wallet address,
        store_app_id: The store application id, which storing bought and sold amount

    Returns:
        The ID of the newly created auction app.
    """
    approval, clear = get_contracts(client)

    global_schema = transaction.StateSchema(num_uints=1, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=8, num_byte_slices=2)
    sp = client.suggested_params()
    
    staking_address = Account.from_mnemonic(os.environ.get("CREATOR_MN"))
    team_wallet_address = Account.from_mnemonic(os.environ.get("TEAM_MN"))
    
    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        foreign_apps=[store_app_id],
        accounts=[staking_address.get_address(), team_wallet_address.get_address()],
        sp=sp,
    )

    signed_txn = txn.sign(creator.get_private_key())
    client.send_transaction(signed_txn)
    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.application_index is not None and response.application_index > 0
    
    app_id = response.application_index
    initial_funding_amount = (
        # min account balance
        100_000
    )
    
    initial_fund_app_txn = transaction.PaymentTxn(
        sender=creator.get_address(),
        receiver=get_application_address(appID=app_id),
        amt=initial_funding_amount,
        sp=sp,
    )
    signed_initial_fund_app_txn = initial_fund_app_txn.sign(creator.get_private_key())
    client.send_transaction(signed_initial_fund_app_txn)
    wait_for_confirmation(client, initial_fund_app_txn.get_txid())
    
    return app_id


def setup_auction_app(
    client: AlgodClient,
    app_id: int,
    seller: Account,
    token_id: int,
    token_amount: int,
    start_time: int,
    end_time: int,
    reserve: int,
    min_bid_increment: int
) -> int:
    """Create a new auction and return auction_index (rekeyed address)

    Args:
        client: An algod client.
        seller: The address of the seller that currently holds the asset being
            auctioned.
        token_id: The ID of the asset being auctioned.
        start_time: A UNIX timestamp representing the start time of the auction.
            This must be greater than the current UNIX timestamp.
        end_time: A UNIX timestamp representing the end time of the auction. This
            must be greater than startTime.
        reserve: The reserve amount of the auction. If the auction ends without
            a bid that is equal to or greater than this amount, the auction will
            fail, meaning the bid amount will be refunded to the lead bidder and
            the asset will return to the seller.
        min_bid_increment: The minimum different required between a new bid and
            the current leading bid.

    Returns:
        Auction index.
    """
    app_address = get_application_address(app_id)
    sp = client.suggested_params()
    app_global_state = get_app_global_state(client, app_id)
    
    # optin store app for saving information    
    store_app_id = app_global_state[b"SA_ID"]
    print(f"store_app_id", store_app_id)
    if is_opted_in_app(client, store_app_id, seller.get_address()) == False:
        print(f"seller {seller.get_address()} opt in app {store_app_id}")
        optin_app(client, store_app_id, seller)
        
    n_address = get_usable_rekeyed_address(client=client, auther=seller, app_id=app_id)
    
    funding_amount = (
        # balance for the app to opt into asset
        + 100_000
        # optin asset min txn fee 
        + 1_000
    )
    
    app_address = get_application_address(app_id)
    pay_txn = transaction.PaymentTxn(
        sender=seller.get_address(),
        receiver=app_address,
        amt=funding_amount,
        sp=sp,
    )

    app_args = [
        b"setup",
        start_time.to_bytes(8, "big"),
        end_time.to_bytes(8, "big"),
        reserve.to_bytes(8, "big"),
        min_bid_increment.to_bytes(8, "big"),
    ]

    setup_txn = transaction.ApplicationCallTxn(
        sender=seller.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=app_args,
        foreign_assets=[token_id],
        accounts=[n_address],
        sp=sp,
    )
    
    fund_token_txn = transaction.AssetTransferTxn(
        sender=seller.get_address(),
        receiver=app_address,
        index=token_id,
        amt=token_amount,
        sp=sp,
    )
    
    transaction.assign_group_id([pay_txn, setup_txn, fund_token_txn])
    
    signed_pay_txn = pay_txn.sign(seller.get_private_key())
    signed_setup_txn = setup_txn.sign(seller.get_private_key())
    signed_fund_token_txn = fund_token_txn.sign(seller.get_private_key())
    
    client.send_transactions([signed_pay_txn, signed_setup_txn, signed_fund_token_txn])
    
    wait_for_confirmation(client, signed_setup_txn.get_txid())
    return n_address

    
def get_usable_rekeyed_address(client: AlgodClient, auther: Account, app_id: int):
    n_address = ""
    rekeyed_addresses = get_rekeyed_addresses(auther.get_address()) # we can get this from network
    for rekeyed_address in rekeyed_addresses:
        if is_opted_in_app(client, app_id, rekeyed_address):
            state = get_app_local_state(client, app_id, rekeyed_address)
            print(f"local state of {rekeyed_address} :", state)
            if b"TK_ID" in state and state[b"TK_ID"] == 0:
                n_address = rekeyed_address
        else:
            # might have rekeyed address already but not optin app, we can use it
            n_address = rekeyed_address
            additional_balance = 100000 + 28500 * 8 + 50000 * 2 + 1000
            charge_optin_price(client, auther, n_address, additional_balance)
            optin_app_rekeyed_address(client, app_id, auther, n_address)
            break
    
    # if not found, create one, and optin app for local state
    if not n_address:
        optin_price = 100000 + 28500 * 8 + 50000 * 2 + 1000
        n_address = generate_rekeyed_address(client, auther, optin_price)
        optin_app_rekeyed_address(client, app_id, auther, n_address)
        set_rekeyed_address(auther.get_address(), n_address, 1)
        
    return n_address

    
def place_bid(client: AlgodClient, 
              app_id: int, 
              auction_index: str,
              bidder: Account, 
              bid_amount: int) -> None:
    """Place a bid on an active auction.

    Args:
        client: An Algod client.
        app_id: The app ID of the auction.
        auction_index: seller's rekeyed address.
        bidder: The account providing the bid.
        bid_amount: The amount of the bid.
    """
    
    if (is_opted_in_app(client, app_id, auction_index) == False): 
        return False
    
    app_global_state = get_app_global_state(client, app_id)
    store_app_id = app_global_state[b"SA_ID"]
    if (is_opted_in_app(client, store_app_id, bidder.get_address()) == False):
        optin_app(client, store_app_id, bidder)
    
    app_local_state = get_app_local_state(client, app_id, auction_index)
    token_id = app_local_state[b"TK_ID"]
    if token_id == 0: # invalid auction_index
        return False
    
    if (is_opted_in_asset(client, token_id, bidder.get_address()) == False):
        optin_asset(client, token_id, bidder)

    if any(app_local_state[b"LB_ADDR"]):
        # if "bid_account" is not the zero address
        prev_bid_leader = encoding.encode_address(app_local_state[b"LB_ADDR"])
    else:
        prev_bid_leader = None

    suggested_params = client.suggested_params()

    app_address = get_application_address(app_id)
    pay_txn = transaction.PaymentTxn(
        sender=bidder.get_address(),
        receiver=app_address,
        amt=bid_amount,
        sp=suggested_params,
    )
    
    print('prev_bid_leader', prev_bid_leader)
    app_call_txn = transaction.ApplicationCallTxn(
        sender=bidder.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"bid"],
        foreign_assets=[token_id],
        # must include the previous lead bidder here to the app can refund that bidder's payment
        accounts=[auction_index, prev_bid_leader] if prev_bid_leader is not None else [auction_index],
        sp=suggested_params,
    )
    
    transaction.assign_group_id([pay_txn, app_call_txn])
    signed_pay_txn = pay_txn.sign(bidder.get_private_key())
    signed_app_call_txn = app_call_txn.sign(bidder.get_private_key())
    client.send_transactions([signed_pay_txn, signed_app_call_txn])

    wait_for_confirmation(client, app_call_txn.get_txid())
    

def close_auction(client: AlgodClient, 
                  app_id: int, 
                  auction_index: str, 
                  closer: Account):
    """Close an auction.

    This action can only happen before an auction has begun, in which case it is
    cancelled, or after an auction has ended.

    If called after the auction has ended and the auction was successful, the
    asset is transferred to the winning bidder and the auction proceeds are
    transferred to the seller. If the auction was not successful, 
    the asset will be transferred to the seller.

    Args:
        client: An Algod client.
        app_id: The app ID of the auction.
        auction_index: rekeyed address has the auction information in local state.
        closer: The account initiating the close transaction. This must be
            either the seller or creator.
    """
    app_global_state = get_app_global_state(client, app_id)
    print("app_global_state", app_global_state)
    sp=client.suggested_params()
    
    if (is_opted_in_app(client, app_id, auction_index) == False): 
        return False
    
    accounts: List[str] = [auction_index]
    token_id = 0
    lead_bidder = None
    
    auction_index_local_state = get_app_local_state(client, app_id, auction_index)
    if auction_index_local_state[b"TK_ID"] > 0:
        token_id = auction_index_local_state[b"TK_ID"]
        
    if any(auction_index_local_state[b"LB_ADDR"]):
        lead_bidder = encoding.encode_address(auction_index_local_state[b"LB_ADDR"])
    
    if token_id == 0:
        return False
    
    if lead_bidder != None:
        accounts.append(lead_bidder)
        accounts.append(encoding.encode_address(app_global_state[b"SA_ADDR"])) 
        accounts.append(encoding.encode_address(app_global_state[b"TW_ADDR"]))
    print(accounts)
    
    sp.fee = 2 * 1_000 # include inner txn
    close_txn = transaction.ApplicationCallTxn(
        sender=closer.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"close"],
        accounts=accounts,
        foreign_assets=[token_id],
        sp=sp,
    )
    
    if len(accounts) == 4:
        store_app_id = app_global_state[b"SA_ID"]
        sp.fee = 1_000
        store_app_call_txn = transaction.ApplicationCallTxn(
            sender=closer.get_address(),
            index=store_app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[b"auction"],
            accounts=[lead_bidder, auction_index],
            foreign_apps=[app_id],
            sp=sp,
        )
        
        transaction.assign_group_id([close_txn, store_app_call_txn])
        signed_close_txn = close_txn.sign(closer.get_private_key())
        signed_store_app_call_txn = store_app_call_txn.sign(closer.get_private_key())
        client.send_transactions([signed_close_txn, signed_store_app_call_txn])
        
        wait_for_confirmation(client, signed_close_txn.get_txid())
        
    else:
        signed_close_txn = close_txn.sign(closer.get_private_key())
        client.send_transaction(signed_close_txn)
        
        wait_for_confirmation(client, signed_close_txn.get_txid())

