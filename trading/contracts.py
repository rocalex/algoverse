from pyteal import *

def approval_program():
    
    store_app_id_key = Bytes("SA_ID")
    distribution_app_address_key = Bytes("DAA")
    team_wallet_address_key = Bytes("TWA")
    
    token_id_key = Bytes("TK_ID")
    bid_amount_key = Bytes("BA")
    bid_price_key = Bytes("BP")
    
    @Subroutine(TealType.none)
    def send_token_to(account: Expr, asset_amount: Expr) -> Expr:
        asset_holding = AssetHolding.balance(
            Global.current_application_address(), App.globalGet(token_id_key)
        )
        return Seq(
            asset_holding,
            Assert(
                And(
                    asset_holding.hasValue(),    
                    asset_holding.value() > asset_amount,
                )                
            ),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(token_id_key),
                        TxnField.asset_sender: Global.current_application_address(),
                        TxnField.asset_receiver: account,
                        TxnField.asset_amount: asset_amount,
                    }
                ),
                InnerTxnBuilder.Submit(),
            )
        )
        

    @Subroutine(TealType.none)
    def send_payments(account: Expr, amount: Expr, succeed: Expr) -> Expr:
        return If(Balance(Global.current_application_address()) >= amount + Global.min_balance()).Then(
            Seq(
                If(succeed).Then(
                    Seq(
                        InnerTxnBuilder.Begin(),
                        InnerTxnBuilder.SetFields(
                            {
                                TxnField.type_enum: TxnType.Payment,
                                TxnField.amount: amount * Int(97) / Int(100),
                                TxnField.receiver: account,
                            }
                        ),
                        InnerTxnBuilder.Submit(),
                        
                        InnerTxnBuilder.Begin(),
                        InnerTxnBuilder.SetFields(
                            {
                                TxnField.type_enum: TxnType.Payment,
                                TxnField.amount: amount * Int(3) / Int(200),
                                TxnField.receiver: App.globalGet(team_wallet_address_key),
                            }
                        ),
                        InnerTxnBuilder.Submit(),
                        
                        InnerTxnBuilder.Begin(),
                        InnerTxnBuilder.SetFields(
                            {
                                TxnField.type_enum: TxnType.Payment,
                                TxnField.amount: amount * Int(3) / Int(200),
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
                                TxnField.amount: amount,
                                TxnField.receiver: account,
                            }
                        ),
                        InnerTxnBuilder.Submit(),
                    )
                ),
            
                App.localDel(account, bid_price_key),
                App.localDel(account, bid_amount_key),
            )
        )
    
    on_create = Seq(
        App.globalPut(store_app_id_key, Btoi(Txn.application_args[0])),
        App.globalPut(distribution_app_address_key, Txn.application_args[1]),
        App.globalPut(team_wallet_address_key, Txn.application_args[2]),
        App.globalPut(token_id_key, Btoi(Txn.application_args[3])),
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
    on_bid = Seq(
        Assert(
            And(
                # the actual bid payment is before the app call
                Gtxn[on_bid_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_bid_txn_index].sender() == Txn.sender(),
                Gtxn[on_bid_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_bid_txn_index].amount() >= Global.min_txn_fee(),
                Btoi(Txn.application_args[1]) > Int(0),
            )
        ),
        If(
            And(
                App.localGet(Txn.sender(), bid_amount_key) > Int(0),
                App.localGet(Txn.sender(), bid_price_key) > Int(0),
            )
        ) 
        .Then( #if already had bid
            Seq(
                # return prev payment to bidder
                send_payments(Txn.sender(), App.localGet(Txn.sender(), bid_price_key), Int(0)),
                
                App.localPut(Txn.sender(), bid_price_key, Gtxn[on_bid_txn_index].amount()),
                App.localPut(Txn.sender(), bid_amount_key, Btoi(Txn.application_args[1])),
            )
        )
        .Else(
            Seq(
                App.localPut(Txn.sender(), bid_price_key, Gtxn[on_bid_txn_index].amount()),
                App.localPut(Txn.sender(), bid_amount_key, Btoi(Txn.application_args[1])),
            )
        ),
        Approve(),
    )
    
    on_cancel = Seq(
        Assert(
            And(
                Txn.type_enum() == TxnType.ApplicationCall,
                App.localGet(Txn.sender(), bid_amount_key) > Int(0),
                App.localGet(Txn.sender(), bid_price_key) > Int(0),
            )
        ),
        Seq(
            # return payment to bidder
            send_payments(Txn.sender(), App.localGet(Txn.sender(), bid_price_key), Int(0)),
        ),
        Approve(),
    )
    
    on_accept_txn_index = Txn.group_index() - Int(1)
    on_accept = Seq(
        Assert(
            And(
                # the actual accept payment is before the app call
                Gtxn[on_accept_txn_index].type_enum() == TxnType.AssetTransfer,
                # Gtxn[on_accept_txn_index].asset_sender() == Txn.sender(),
                # Gtxn[on_accept_txn_index].asset_receiver() == Global.current_application_address(),
                Txn.accounts.length() == Int(3),
                # Gtxn[on_accept_txn_index].asset_amount() == App.localGet(Txn.accounts[1], bid_amount_key),
                # App.localGet(Txn.accounts[1], bid_amount_key) > Int(0),
                # App.localGet(Txn.accounts[1], bid_price_key) > Int(0),
            )
        ),
        Seq(
            # send payment to seller
            send_payments(Txn.sender(), App.localGet(Txn.accounts[1], bid_price_key), Int(1)),
            
            # send asset to buyer
            send_token_to(Txn.accounts[1], App.localGet(Txn.accounts[1], bid_amount_key)),
            
            Approve(),
        )
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("bid"), on_bid],
        [on_call_method == Bytes("cancel"), on_cancel],
        [on_call_method == Bytes("accept"), on_accept],
    )

    on_delete = Seq(
        # Assert(
        #     Balance(Global.current_application_address()) == Global.min_txn_fee(),
        # ),
        Approve(),
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
                Txn.on_completion() == OnComplete.ClearState,
            ),
            Approve(),
        ],
        [
            Or(
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
