import os

from typing import Tuple, List

from algosdk import encoding
from algosdk.constants import MIN_TXN_FEE
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
    staking_address: str,
    team_wallet_address: str
) -> int:
    """Create a new trading.

    Args:
        client: An algod client.
        sender: The account that will create the trading application.
        seller: The address of the seller that currently holds the NFT being
            traded.
        token_id: The ID of the NFT being traded.
        price: The price of the trading. If the trading ends without
            a trade that is equal to or greater than this amount, the trading will
            fail, meaning the trade amount will be refunded to the lead seller and
            the NFT will return to the seller.

    Returns:
        The ID of the newly created trading app.
    """
    approval, clear = get_contracts(client)

    global_schema = transaction.StateSchema(num_uints=1, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=3, num_byte_slices=1)
    
    sp = client.suggested_params()

    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[],
        foreign_apps=[store_app_id],
        accounts=[staking_address, team_wallet_address],
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
        # for optin asset
        + 100_000
        # optin asset fee
        + 1_000
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
    
    params = client.suggested_params()
    optin_asset_fee = (
        # min optin asset fee
        100_000
        # min txn fee
        + 1_000
    )
    params.fee = optin_asset_fee + 1_000
    
    setup_txn = transaction.ApplicationCallTxn(
        sender=funder.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"setup"],
        foreign_assets=[token_id],
        sp=params,
    )

    signed_setup_txn = setup_txn.sign(funder.get_private_key())
    client.send_transaction(signed_setup_txn)        
    wait_for_confirmation(client, signed_setup_txn.get_txid())
    
    
def place_trade(client: AlgodClient, app_id: int, seller: Account, token_id: int, token_amount: int, price: int, trading_index: str) -> None:
    """Place or replace a trade on an active trading.

    Args:
        client: An Algod client.
        app_id: The app ID of the trading.
        seller: The account providing the trade.
        token_amount: The asset amount of the trade.
        price: The price of the trade.
        trading_index: Index for replace trade.
    """
    app_address = get_application_address(app_id)
    app_global_state = get_app_global_state(client, app_id)
    suggested_params = client.suggested_params()
    
    # optin store app for saving information    
    store_app_id = app_global_state[b"SA_ID"]
    print(f"store_app_id", store_app_id)
    if is_opted_in_app(client, store_app_id, seller.get_address()) == False:
        print(f"seller {seller.get_address()} opt in app {store_app_id}")
        optin_app(client, store_app_id, seller)
        
    # app optin asset for receiving the asset
    if is_opted_in_asset(client, token_id, app_address) == False:
        setup_trading_app(client=client, app_id=app_id, funder=seller, token_id=token_id)
    
    suggested_params.fee = 2 * 1_000
    tokens = [token_id]
    n_address = trading_index
    # if bid_index is empty, find a usable(if the bid app local state's token id is 0) rekeyed address used in the past, 
    if not n_address:
        unused_rekeyed_address = ""
        rekeyed_addresses = get_rekeyed_addresses(seller.get_address()) # we can get this from network
        for rekeyed_address in rekeyed_addresses:
            if is_opted_in_app(client, app_id, rekeyed_address):
                state = get_app_local_state(client, app_id, rekeyed_address)
                print(f"local state of {rekeyed_address} :", state)
                if b"TK_ID" in state and state[b"TK_ID"] == 0:
                    unused_rekeyed_address = rekeyed_address
                    
                if state[b"TK_ID"] > 0 and state[b"TA"] > 0:
                    suggested_params.fee = 3 * 1_000 # add inner returning asset txn fee
                    
            else:
                # might have rekeyed address already but not optin app, we can use it
                unused_rekeyed_address = rekeyed_address
                optin_price = 100000 + 28500 * 3 + 50000 * 1 + 1000
                charge_optin_price(client, seller, unused_rekeyed_address, optin_price)
                optin_app_rekeyed_address(client, app_id, seller, unused_rekeyed_address)
                break
        
        # if not found, create one, and optin app for local state
        n_address = unused_rekeyed_address
        if not n_address:
            optin_price = 100000 + 28500 * 3 + 50000 * 1 + 1000
            n_address = generate_rekeyed_address(client, seller, optin_price)
            optin_app_rekeyed_address(client, app_id, seller, n_address)
            set_rekeyed_address(seller.get_address(), n_address, 1)
    else:
        state = get_app_local_state(client, app_id, trading_index)
        if b"TK_ID" in state and state[b"TK_ID"] > 0 and state[b"TA"] > 0:
            tokens.append(state[b"TK_ID"])
            suggested_params.fee = 3 * 1_000 # add inner returning asset txn fee    
    
    token_txn = transaction.AssetTransferTxn(
        sender=seller.get_address(),
        receiver=app_address,
        index=token_id,
        amt=token_amount,
        sp=suggested_params,
    )
    print(f"token_txn: {token_txn}")

    suggested_params.fee = 0
    app_call_txn = transaction.ApplicationCallTxn(
        sender=seller.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"trade", price.to_bytes(8, "big")],
        accounts=[n_address],
        foreign_assets=tokens,
        sp=suggested_params,
    )

    transaction.assign_group_id([token_txn, app_call_txn])
    
    signed_token_txn = token_txn.sign(seller.get_private_key())
    signed_app_call_txn = app_call_txn.sign(seller.get_private_key())

    client.send_transactions([signed_token_txn, signed_app_call_txn])
    wait_for_confirmation(client, app_call_txn.get_txid())
    
    return n_address
    
    
def cancel_trade(client: AlgodClient, app_id: int, seller: Account, trading_index: str) -> bool:
    """Place a trade on an active trading.

    Args:
        client: An Algod client.
        app_id: The app ID of the trading.
        seller: The account providing the trade.
    """
    if (is_opted_in_app(client, app_id, trading_index) == False): 
        return False
    
    seller_app_local_state = get_app_local_state(client, app_id, trading_index)
    token_id = seller_app_local_state[b"TK_ID"]
    suggested_params = client.suggested_params()
    suggested_params.fee = 2_000
        
    app_call_txn = transaction.ApplicationCallTxn(
        sender=seller.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"cancel"],
        accounts=[trading_index],
        foreign_assets=[token_id],
        sp=suggested_params,
    )
    
    signed_app_call_txn = app_call_txn.sign(seller.get_private_key())
    client.send_transaction(signed_app_call_txn)
    wait_for_confirmation(client, app_call_txn.get_txid())    
    
    # #do we need this store app opt out? cause the seller might wants to trade again later ?
    # app_global_state = get_app_global_state(client, app_id)
    # store_app_id = app_global_state[b"SA_ID"]
    # if is_opted_in_app(client, store_app_id, seller.get_address()) == True:
    #     # do we need this store app opt out? cause the seller might wants to trade again later ?
    #     optout_app(client, app_id, seller)
    # else:
    #     return False


def accept_trade(client: AlgodClient, app_id: int, buyer: Account, seller: str, trading_index: str) -> None:
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
    suggested_params = client.suggested_params()

    if (is_opted_in_app(client, app_id, trading_index) == False): 
        return False
    
    seller_app_local_state = get_app_local_state(client, app_id, trading_index)
    token_id = seller_app_local_state[b"TK_ID"]
    token_amount = seller_app_local_state[b"TA"]
    trading_price = seller_app_local_state[b"TP"]
    print(f"token_amount", token_amount)
    print(f"price", trading_price)
    
    # check if buyer has enough algo
    if get_balances(client, buyer.get_address())[0] < trading_price:
        return False
    
    store_app_id = app_global_state[b"SA_ID"]
    if is_opted_in_app(client, store_app_id, buyer.get_address()) == False:
        optin_app(client, store_app_id, buyer)
        
    if (is_opted_in_asset(client, token_id, buyer.get_address()) == False):
        optin_asset(client, token_id, buyer)
    
    pay_txn = transaction.PaymentTxn(
        sender=buyer.get_address(),
        receiver=app_address,
        amt=trading_price + 4_000, # 1_000 is for asset txn, 3_000 is for split payment txn
        sp=suggested_params,
    )
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=buyer.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"accept", token_amount.to_bytes(8, "big")],
        foreign_assets=[token_id],
        # must include the seller here to the app can refund that seller's payment
        accounts=[seller, 
                  trading_index,
                  encoding.encode_address(app_global_state[b"SA_ADDR"]), 
                  encoding.encode_address(app_global_state[b"TW_ADDR"])],
        sp=suggested_params,
    )
    
    store_app_call_txn = transaction.ApplicationCallTxn(
        sender=buyer.get_address(),
        sp=suggested_params,
        index=store_app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"buy"],
        accounts=[seller]
    )
    
    transaction.assign_group_id([pay_txn, app_call_txn, store_app_call_txn])
    signed_pay_txn = pay_txn.sign(buyer.get_private_key())
    signed_app_call_txn = app_call_txn.sign(buyer.get_private_key())
    signed_store_app_call_txn = store_app_call_txn.sign(buyer.get_private_key())
    
    client.send_transactions([signed_pay_txn, signed_app_call_txn, signed_store_app_call_txn])
    wait_for_confirmation(client, app_call_txn.get_txid())


def close_trading(client: AlgodClient, app_id: int, closer: Account, assets: List[int]):
    """Close an trading.

    This action can only happen before an trading has begun, in which case it is
    cancelled, or after an trading has ended.

    If called after the trading has ended and the trading was successful, the
    NFT is transferred to the winning seller and the trading proceeds are
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

    accounts: List[str] = [encoding.encode_address(app_global_state[b"SA_ADDR"]), 
                           encoding.encode_address(app_global_state[b"TW_ADDR"])]
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
