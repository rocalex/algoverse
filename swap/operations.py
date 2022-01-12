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
    """Get the compiled TEAL contracts for the swap.

    Args:
        client: An algod client that has the ability to compile TEAL programs.

    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    approval = fully_compile_contract(client, approval_program())
    clear_state = fully_compile_contract(client, clear_state_program())

    return approval, clear_state


def create_swap_app(
    client: AlgodClient,
    creator: Account
) -> int:
    """Create a new swap.

    Args:
        client: An algod client.
        sender: The account that will create the swap application.
        offer: The address of the offer that currently holds the NFT being
            swapd.
        token_id: The ID of the NFT being swapd.
        price: The price of the swap. If the swap ends without
            a swap that is equal to or greater than this amount, the swap will
            fail, meaning the swap amount will be refunded to the lead offer and
            the NFT will return to the offer.

    Returns:
        The ID of the newly created swap app.
    """
    approval, clear = get_contracts(client)

    global_schema = transaction.StateSchema(num_uints=0, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=4, num_byte_slices=1)
    
    staking_address = Account.from_mnemonic(os.environ.get("CREATOR_MN"))
    team_wallet_address = Account.from_mnemonic(os.environ.get("TEAM_MN"))
    
    sp = client.suggested_params()

    txn = transaction.ApplicationCreateTxn(
        sender=creator.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[],
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


def setup_swap_app(
    client: AlgodClient,
    app_id: int,
    funder: Account,
    token_ids: List[int],
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
        # min optin asset balance
        100_000
        # min txn fee
        + 1_000
    ) *  len(token_ids)

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
        foreign_assets=token_ids,
        sp=params,
    )

    transaction.assign_group_id([fund_app_txn, setup_txn])

    signed_fund_app_txn = fund_app_txn.sign(funder.get_private_key())
    signed_setup_txn = setup_txn.sign(funder.get_private_key())

    client.send_transactions([signed_fund_app_txn, signed_setup_txn])
    wait_for_confirmation(client, signed_fund_app_txn.get_txid())

    
def place_swap(client: AlgodClient, app_id: int, offer: Account, offering_token_id: int, offering_token_amount: int, accepting_token_id: int, accepting_token_amount, swap_index: str) -> None:
    """Place or replace a swap on an active swap.

    Args:
        client: An Algod client.
        app_id: The app ID of the swap.
        offer: The account providing the swap.
        token_amount: The asset amount of the swap.
        price: The price of the swap.
        swap_index: Index for replace swap.
    """
    app_address = get_application_address(app_id)
    suggested_params = client.suggested_params()
    
    if (is_opted_in_asset(client, accepting_token_id, offer.get_address()) == False):
        optin_asset(client, accepting_token_id, offer)
        
    tokens = [offering_token_id, accepting_token_id]
    # app optin asset for receiving the asset
    if is_opted_in_asset(client, offering_token_id, app_address) == False and is_opted_in_asset(client, accepting_token_id, app_address) == False:
        setup_swap_app(client=client, app_id=app_id, funder=offer, token_ids=tokens)
        
    if is_opted_in_asset(client, offering_token_id, app_address) == False:
        setup_swap_app(client=client, app_id=app_id, funder=offer, token_ids=[offering_token_id])
        
    if is_opted_in_asset(client, accepting_token_id, app_address) == False:
        setup_swap_app(client=client, app_id=app_id, funder=offer, token_ids=[accepting_token_id])
    
    n_address = swap_index
    # if bid_index is empty, find a usable(if the bid app local state's token id is 0) rekeyed address used in the past, 
    if not n_address:
        unused_rekeyed_address = ""
        rekeyed_addresses = get_rekeyed_addresses(offer.get_address()) # we can get this from network
        for rekeyed_address in rekeyed_addresses:
            if is_opted_in_app(client, app_id, rekeyed_address):
                state = get_app_local_state(client, app_id, rekeyed_address)
                print(f"local state of {rekeyed_address} :", state)
                if b"O_TKID" in state and state[b"O_TKID"] == 0:
                    unused_rekeyed_address = rekeyed_address
            else:
                # might have rekeyed address already but not optin app, we can use it
                unused_rekeyed_address = rekeyed_address
                optin_price = 100000 + 28500 * 4 + 50000 * 1 + 1000
                charge_optin_price(client, offer, unused_rekeyed_address, optin_price)
                optin_app_rekeyed_address(client, app_id, offer, unused_rekeyed_address)
                break
        
        # if not found, create one, and optin app for local state
        n_address = unused_rekeyed_address
        if not n_address:
            optin_price = 100000 + 28500 * 4 + 50000 * 1 + 1000
            n_address = generate_rekeyed_address(client, offer, optin_price)
            optin_app_rekeyed_address(client, app_id, offer, n_address)
            set_rekeyed_address(offer.get_address(), n_address, 1)
    else:
        state = get_app_local_state(client, app_id, swap_index)
        if b"O_TKID" in state and state[b"O_TKID"] > 0:
            tokens.append(state[b"O_TKID"])
        
    txns = []
    signed_txns = []
    if len(tokens) == 3:
        funding_amount = (
            # min asset txn fee to return back old asset
            + 1_000
        )        
        fund_app_txn = transaction.PaymentTxn(
            sender=offer.get_address(),
            receiver=app_address,
            amt=funding_amount,
            sp=suggested_params,
        )
        txns.append(fund_app_txn)
        
    token_txn = transaction.AssetTransferTxn(
        sender=offer.get_address(),
        receiver=app_address,
        index=offering_token_id,
        amt=offering_token_amount,
        sp=suggested_params,
    )
    print(f"token_txn: {token_txn}")
    txns.append(token_txn)

    app_call_txn = transaction.ApplicationCallTxn(
        sender=offer.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"swap", accepting_token_amount.to_bytes(8, "big")],
        accounts=[n_address],
        foreign_assets=tokens,
        sp=suggested_params,
    )
    txns.append(app_call_txn)
    
    transaction.assign_group_id(txns)
    
    print('tokens', len(tokens))
    if len(tokens) == 3:
        signed_fund_txn = fund_app_txn.sign(offer.get_private_key())
        signed_txns.append(signed_fund_txn)

    signed_token_txn = token_txn.sign(offer.get_private_key())
    signed_txns.append(signed_token_txn)
    
    signed_app_call_txn = app_call_txn.sign(offer.get_private_key())
    signed_txns.append(signed_app_call_txn)

    client.send_transactions(signed_txns)
    wait_for_confirmation(client, app_call_txn.get_txid())
    
    # if len(tokens) == 2 :
    #     tokens.append(offering_token_id)
        
    # funding_amount = (
    #     # min asset txn fee to return back old asset
    #     + 1_000
    # )        
    # fund_app_txn = transaction.PaymentTxn(
    #     sender=offer.get_address(),
    #     receiver=app_address,   
    #     amt=funding_amount,
    #     sp=suggested_params,
    # )
    
    # token_txn = transaction.AssetTransferTxn(
    #     sender=offer.get_address(),
    #     receiver=app_address,
    #     index=offering_token_id,
    #     amt=offering_token_amount,
    #     sp=suggested_params,
    # )
    # print(f"token_txn: {token_txn}")
    
    # app_call_txn = transaction.ApplicationCallTxn(
    #     sender=offer.get_address(),
    #     index=app_id,
    #     on_complete=transaction.OnComplete.NoOpOC,
    #     app_args=[b"swap", accepting_token_amount.to_bytes(8, "big")],
    #     accounts=[n_address],
    #     foreign_assets=tokens,
    #     sp=suggested_params,
    # )
    
    # transaction.assign_group_id([fund_app_txn, token_txn, app_call_txn])
    
    # signed_fund_txn = fund_app_txn.sign(offer.get_private_key())
    # signed_token_txn = token_txn.sign(offer.get_private_key())
    # signed_app_call_txn = app_call_txn.sign(offer.get_private_key())
    
    # client.send_transactions([signed_fund_txn, signed_token_txn, signed_app_call_txn])
    # wait_for_confirmation(client, app_call_txn.get_txid())
    
    return n_address
    
    
def cancel_swap(client: AlgodClient, app_id: int, offer: Account, swap_index: str) -> bool:
    """Place a swap on an active swap.

    Args:
        client: An Algod client.
        app_id: The app ID of the swap.
        offer: The account providing the swap.
    """
    if (is_opted_in_app(client, app_id, swap_index) == False): 
        return False
    
    offer_app_local_state = get_app_local_state(client, app_id, swap_index)
    token_id = offer_app_local_state[b"O_TKID"]
    suggested_params = client.suggested_params()
    
    app_address = get_application_address(app_id)
    funding_amount = 1_000

    # this is needed for returning asset, cause application will pay
    cancel_pay_txn = transaction.PaymentTxn(
        sender=offer.get_address(),
        receiver=app_address,
        amt=funding_amount,
        sp=suggested_params,
    )
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=offer.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"cancel"],
        accounts=[swap_index],
        foreign_assets=[token_id],
        sp=suggested_params,
    )
    
    transaction.assign_group_id([cancel_pay_txn, app_call_txn])

    signed_cancel_pay_txn = cancel_pay_txn.sign(offer.get_private_key())
    signed_app_call_txn = app_call_txn.sign(offer.get_private_key())
    client.send_transactions([signed_cancel_pay_txn, signed_app_call_txn])
    
    wait_for_confirmation(client, app_call_txn.get_txid())    
    
    # #do we need this store app opt out? cause the offer might wants to swap again later ?
    # app_global_state = get_app_global_state(client, app_id)
    # store_app_id = app_global_state[b"SA_ID"]
    # if is_opted_in_app(client, store_app_id, offer.get_address()) == True:
    #     # do we need this store app opt out? cause the offer might wants to swap again later ?
    #     optout_app(client, app_id, offer)
    # else:
    #     return False

    return True


def accept_swap(client: AlgodClient, app_id: int, accepter: Account, swap_index: str) -> None:
    """Accept on an active swap.

    Args:
        client: An Algod client.
        creator: The app creator.
        app_id: The app ID of the swap.
        offer: The account selling the asset.
        accepter: The account buying the asset.
    """
    app_address = get_application_address(app_id)
    app_global_state = get_app_global_state(client, app_id)
    suggested_params = client.suggested_params()

    if (is_opted_in_app(client, app_id, swap_index) == False): 
        return False
    
    offer_app_local_state = get_app_local_state(client, app_id, swap_index)
    offer = encoding.encode_address(offer_app_local_state[b"O_ADDR"])
    offering_token_id = offer_app_local_state[b"O_TKID"]
    offering_token_amount = offer_app_local_state[b"O_AMT"]
    accepting_token_id = offer_app_local_state[b"A_TKID"]
    accepting_token_amount = offer_app_local_state[b"A_AMT"]
    print(f"offer address", offer)
    print(f"offering_token_id", offering_token_id)
    print(f"offering_token_amount", offering_token_amount)
    print(f"accepting_token_id", accepting_token_id)
    print(f"accepting_token_amount", accepting_token_amount)
    
    # check if accepter has enough assets
    if get_balances(client, accepter.get_address())[accepting_token_id] < accepting_token_amount:
        return False
    
    if is_opted_in_asset(client, offering_token_id, app_address) == False:
        return False
    
    if is_opted_in_asset(client, accepting_token_id, app_address) == False:
        setup_swap_app(client=client, app_id=app_id, funder=offer, token_ids=[accepting_token_id])
    
    if (is_opted_in_asset(client, offering_token_id, accepter.get_address()) == False):
        optin_asset(client, offering_token_id, accepter)
        
    funding_amount = (
        # min asset txn fee on accept
        + 1_000 * 2
    )
    
    fund_app_txn = transaction.PaymentTxn(
        sender=accepter.get_address(),
        receiver=app_address,
        amt=funding_amount,
        sp=suggested_params,
    )
    
    token_txn = transaction.AssetTransferTxn(
        sender=accepter.get_address(),
        receiver=app_address,
        index=accepting_token_id,
        amt=accepting_token_amount,
        sp=suggested_params,
    )
    
    app_call_txn = transaction.ApplicationCallTxn(
        sender=accepter.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"accept", offering_token_amount.to_bytes(8, "big")],
        foreign_assets=[offering_token_id, accepting_token_id],
        # must include the offer here to the app can send accepting asset to the offer
        accounts=[offer, 
                  swap_index,
                  encoding.encode_address(app_global_state[b"SA_ADDR"]), 
                  encoding.encode_address(app_global_state[b"TW_ADDR"])],
        sp=suggested_params,
    )
    
    transaction.assign_group_id([fund_app_txn, token_txn, app_call_txn])
    signed_fund_app_txn = fund_app_txn.sign(accepter.get_private_key())
    signed_token_txn = token_txn.sign(accepter.get_private_key())
    signed_app_call_txn = app_call_txn.sign(accepter.get_private_key())
    
    client.send_transactions([signed_fund_app_txn, signed_token_txn, signed_app_call_txn])
    wait_for_confirmation(client, app_call_txn.get_txid())
    
    return True


def close_swap(client: AlgodClient, app_id: int, closer: Account, assets: List[int]):
    """Close an swap.

    This action can only happen before an swap has begun, in which case it is
    cancelled, or after an swap has ended.

    If called after the swap has ended and the swap was successful, the
    NFT is transferred to the winning offer and the swap proceeds are
    transferred to the offer. If the swap was not successful, the NFT and
    all funds are transferred to the offer.

    Args:
        client: An Algod client.
        app_id: The app ID of the swap.
        closer: The account initiating the close transaction. This must be
            the swap creator.
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
