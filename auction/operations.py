from typing import Tuple, List

from algosdk import encoding
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client.algod import AlgodClient

from account import Account
from utils import fully_compile_contract, get_app_global_state, wait_for_confirmation
from .contracts import approval_program, clear_state_program

APPROVAL_PROGRAM = b""
CLEAR_STATE_PROGRAM = b""


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
    sender: Account,
    seller: str,
    token_id: int,
    start_time: int,
    end_time: int,
    reserve: int,
    min_bid_increment: int,
) -> int:
    """Create a new auction.

    Args:
        client: An algod client.
        sender: The account that will create the auction application.
        seller: The address of the seller that currently holds the NFT being
            auctioned.
        token_id: The ID of the NFT being auctioned.
        start_time: A UNIX timestamp representing the start time of the auction.
            This must be greater than the current UNIX timestamp.
        end_time: A UNIX timestamp representing the end time of the auction. This
            must be greater than startTime.
        reserve: The reserve amount of the auction. If the auction ends without
            a bid that is equal to or greater than this amount, the auction will
            fail, meaning the bid amount will be refunded to the lead bidder and
            the NFT will return to the seller.
        min_bid_increment: The minimum different required between a new bid and
            the current leading bid.

    Returns:
        The ID of the newly created auction app.
    """
    approval, clear = get_contracts(client)

    global_schema = transaction.StateSchema(num_uints=7, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    app_args = [
        encoding.decode_address(seller),
        token_id.to_bytes(8, "big"),
        start_time.to_bytes(8, "big"),
        end_time.to_bytes(8, "big"),
        reserve.to_bytes(8, "big"),
        min_bid_increment.to_bytes(8, "big"),
    ]

    txn = transaction.ApplicationCreateTxn(
        sender=sender.get_address(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
        sp=client.suggested_params(),
    )

    signed_txn = txn.sign(sender.get_private_key())

    client.send_transaction(signed_txn)

    response = wait_for_confirmation(client, signed_txn.get_txid())
    assert response.application_index is not None and response.application_index > 0
    return response.application_index


def setup_auction_app(
    client: AlgodClient,
    app_id: int,
    funder: Account,
    token_holder: Account,
    token_id: int,
    asset_amount: int,
) -> None:
    """Finish setting up an auction.

    This operation funds the app auction escrow account, opts that account into
    the NFT, and sends the NFT to the escrow account, all in one atomic
    transaction group. The auction must not have started yet.

    The escrow account requires a total of 0.203 Algos for funding. See the code
    below for a breakdown of this amount.

    Args:
        client: An algod client.
        app_id: The app ID of the auction.
        funder: The account providing the funding for the escrow account.
        token_holder: The account holding the NFT.
        token_id: The NFT ID.
        asset_amount: The NFT amount being auctioned. Some NFTs has a total supply
            of 1, while others are fractional NFTs with a greater total supply,
            so use a value that makes sense for the NFT being auctioned.
    """
    app_address = get_application_address(app_id)

    params = client.suggested_params()

    funding_amount = (
        # min account balance
        100_000
        # additional min balance to opt into NFT
        + 100_000
        # 3 * min txn fee
        + 3 * 1_000
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

    fund_token_txn = transaction.AssetTransferTxn(
        sender=token_holder.get_address(),
        receiver=app_address,
        index=token_id,
        amt=asset_amount,
        sp=params,
    )

    transaction.assign_group_id([fund_app_txn, setup_txn, fund_token_txn])

    signed_fund_app_txn = fund_app_txn.sign(funder.get_private_key())
    signed_setup_txn = setup_txn.sign(funder.get_private_key())
    signed_fund_token_txn = fund_token_txn.sign(token_holder.get_private_key())

    client.send_transactions([signed_fund_app_txn, signed_setup_txn, signed_fund_token_txn])

    wait_for_confirmation(client, signed_fund_app_txn.get_txid())


def place_bid(client: AlgodClient, app_id: int, bidder: Account, bid_amount: int) -> None:
    """Place a bid on an active auction.

    Args:
        client: An Algod client.
        app_id: The app ID of the auction.
        bidder: The account providing the bid.
        bid_amount: The amount of the bid.
    """
    app_address = get_application_address(app_id)
    app_global_state = get_app_global_state(client, app_id)

    token_id = app_global_state[b"token_id"]

    if any(app_global_state[b"bid_account"]):
        # if "bid_account" is not the zero address
        prev_bid_leader = encoding.encode_address(app_global_state[b"bid_account"])
    else:
        prev_bid_leader = None

    suggested_params = client.suggested_params()

    pay_txn = transaction.PaymentTxn(
        sender=bidder.get_address(),
        receiver=app_address,
        amt=bid_amount,
        sp=suggested_params,
    )

    app_call_txn = transaction.ApplicationCallTxn(
        sender=bidder.get_address(),
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"bid"],
        foreign_assets=[token_id],
        # must include the previous lead bidder here to the app can refund that bidder's payment
        accounts=[prev_bid_leader] if prev_bid_leader is not None else [],
        sp=suggested_params,
    )

    transaction.assign_group_id([pay_txn, app_call_txn])

    signed_pay_txn = pay_txn.sign(bidder.get_private_key())
    signed_app_call_txn = app_call_txn.sign(bidder.get_private_key())

    client.send_transactions([signed_pay_txn, signed_app_call_txn])

    wait_for_confirmation(client, app_call_txn.get_txid())


def close_auction(client: AlgodClient, app_id: int, closer: Account):
    """Close an auction.

    This action can only happen before an auction has begun, in which case it is
    cancelled, or after an auction has ended.

    If called after the auction has ended and the auction was successful, the
    NFT is transferred to the winning bidder and the auction proceeds are
    transferred to the seller. If the auction was not successful, the NFT and
    all funds are transferred to the seller.

    Args:
        client: An Algod client.
        app_id: The app ID of the auction.
        closer: The account initiating the close transaction. This must be
            either the seller or auction creator if you wish to close the
            auction before it starts. Otherwise, this can be any account.
    """
    app_global_state = get_app_global_state(client, app_id)

    nft_id = app_global_state[b"token_id"]

    accounts: List[str] = [encoding.encode_address(app_global_state[b"seller"])]

    if any(app_global_state[b"bid_account"]):
        # if "bid_account" is not the zero address
        accounts.append(encoding.encode_address(app_global_state[b"bid_account"]))

    delete_txn = transaction.ApplicationDeleteTxn(
        sender=closer.get_address(),
        index=app_id,
        accounts=accounts,
        foreign_assets=[nft_id],
        sp=client.suggested_params(),
    )
    signed_delete_txn = delete_txn.sign(closer.get_private_key())

    client.send_transaction(signed_delete_txn)

    wait_for_confirmation(client, signed_delete_txn.get_txid())
