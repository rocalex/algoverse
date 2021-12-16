from pyteal import *


def approval_program():
    
    store_app_address_key = Bytes("store_app_address")
    distribution_app_address_key = Bytes("distribution_app_address")
    team_wallet_address_key = Bytes("team_wallet_address")
    seller_key = Bytes("seller")
    token_id_key = Bytes("token_id")
    token_amount_key = Bytes("token_amount")
    price_key = Bytes("price")
    bid_amount_key = Bytes("bid_amount")
    bid_account_key = Bytes("bid_account")
    
    @Subroutine(TealType.none)
    def close_nft_to(asset_id: Expr, account: Expr) -> Expr:
        asset_holding = AssetHolding.balance(
            Global.current_application_address(), asset_id
        )
        return Seq(
            asset_holding,
            If(asset_holding.hasValue()).Then(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.AssetTransfer,
                            TxnField.xfer_asset: asset_id,
                            TxnField.asset_close_to: account,
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                )
            ),
        )

    @Subroutine(TealType.none)
    def close_payments(succeed: Expr) -> Expr:
        return If(Balance(Global.current_application_address()) != Int(0)).Then(
            If(succeed).Then(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.Payment,
                            TxnField.amount: (Balance(Global.current_application_address()) - Global.min_balance()) * Int(97) / Int(100),
                            TxnField.receiver: App.globalGet(seller_key),
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                    
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.Payment,
                            TxnField.amount: (Balance(Global.current_application_address()) - Global.min_balance()) * Int(3) / Int(200),
                            TxnField.receiver: App.globalGet(team_wallet_address_key),
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                    
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.Payment,
                            TxnField.amount: (Balance(Global.current_application_address()) - Global.min_balance()) * Int(3) / Int(200),
                            TxnField.receiver: App.globalGet(distribution_app_address_key),
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                )
            )
            .Else(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.Payment,
                            TxnField.close_remainder_to: App.globalGet(seller_key),
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                )
            )   
        )
    
    price = Btoi(Txn.application_args[4])
    on_create = Seq(
        App.globalPut(distribution_app_address_key, Txn.application_args[0]),
        App.globalPut(team_wallet_address_key, Txn.application_args[1]),
        App.globalPut(seller_key, Txn.application_args[2]),
        App.globalPut(token_id_key, Btoi(Txn.application_args[3])),
        App.globalPut(price_key, price),
        App.globalPut(bid_account_key, Global.zero_address()),
        App.globalPut(store_app_address_key, Txn.application_args[5]),
        Assert(price >= Global.min_txn_fee()),
        Approve(),
    )

    on_setup = Seq(
        # opt into NFT asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(token_id_key),
                TxnField.asset_receiver: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    on_bid_txn_index = Txn.group_index() - Int(1)
    on_bid_nft_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_id_key)
    )
    on_bid = Seq(
        on_bid_nft_holding,
        Assert(
            And(
                # the auction has been set up
                on_bid_nft_holding.hasValue(),
                on_bid_nft_holding.value() > Int(0),
                # the actual bid payment is before the app call
                Gtxn[on_bid_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_bid_txn_index].sender() == Txn.sender(),
                Gtxn[on_bid_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_bid_txn_index].amount() >= App.globalGet(price_key),
            )
        ),
        If(
            Gtxn[on_bid_txn_index].amount() >= App.globalGet(price_key)
        ).Then(
            Seq(
                App.globalPut(bid_amount_key, Gtxn[on_bid_txn_index].amount()),
                App.globalPut(bid_account_key, Gtxn[on_bid_txn_index].sender()),
                Approve(),
            )
        ),
        Reject(),
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("bid"), on_bid],
    )

    on_delete = Seq(
        Seq(
            # the auction has ended, pay out assets
            If(App.globalGet(bid_account_key) != Global.zero_address())
            .Then(
                Seq(
                    # the auction was successful: send lead bid account the nft
                    close_nft_to(App.globalGet(token_id_key), App.globalGet(bid_account_key)),
                    # send remaining funds to the seller
                    close_payments(Int(1)),   
                )
            )
            .Else(
                Seq(
                    # the auction was not successful because no bids were placed: return the nft to the seller
                    close_nft_to(App.globalGet(token_id_key), App.globalGet(seller_key)),
                    # send remaining funds to the seller
                    close_payments(Int(0)),   
                )
            ),
            Approve(),
        )
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        [
            Txn.on_completion() == OnComplete.DeleteApplication,
            on_delete,
        ],
        [
            Or(
                Txn.on_completion() == OnComplete.OptIn,
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.UpdateApplication,
            ),
            Reject(),
        ],
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("trading_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("trading_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
