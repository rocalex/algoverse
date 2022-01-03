from json import load
from pyteal import *

def approval_program():
    
    store_app_id_key = Bytes("SA_ID")
    distribution_app_address_key = Bytes("DAA")
    team_wallet_address_key = Bytes("TWA")
    
    trading_token_id_key = Bytes("TK_ID")
    trading_amount_key = Bytes("TA")
    trading_price_key = Bytes("TP")
    
    
    @Subroutine(TealType.uint64)
    def is_opening(trading_index: Expr, asset_id: Expr) -> Expr:
        return And(
            App.localGet(trading_index, trading_token_id_key),
            asset_id == App.localGet(trading_index, trading_token_id_key),
            App.localGet(trading_index, trading_amount_key),
            App.localGet(trading_index, trading_price_key),
        )
        
    @Subroutine(TealType.none)
    def handle_trading(seller: Expr, trading_index: Expr, asset_id: Expr, amount: Expr, price: Expr) -> Expr:
        return Seq(
            If(is_opening(trading_index, asset_id)).Then(
                #return asset
                send_token_to(seller, asset_id, App.localGet(trading_index, trading_amount_key)),
            ),
            
            App.localPut(trading_index, trading_token_id_key, asset_id),
            App.localPut(trading_index, trading_amount_key, amount),
            App.localPut(trading_index, trading_price_key, price),
        )
        
    @Subroutine(TealType.none)
    def handle_cancel_trading(seller: Expr, trading_index: Expr) -> Expr:
        return Seq(
            # return asset
            send_token_to(seller, App.localGet(trading_index, trading_token_id_key), App.localGet(trading_index, trading_amount_key)),
            
            App.localPut(trading_index, trading_token_id_key, Int(0)),
            App.localPut(trading_index, trading_amount_key, Int(0)),
            App.localPut(trading_index, trading_price_key, Int(0)),
        )
        
    @Subroutine(TealType.none)
    def handle_accept(seller: Expr, bidder: Expr, trading_index: Expr) -> Expr:
        return Seq(
            # send payment to seller
            send_payments(seller, App.localGet(trading_index, trading_price_key), Int(1)),
            
            # send asset to bidder
            send_token_to(bidder, App.localGet(trading_index, trading_token_id_key), App.localGet(trading_index, trading_amount_key)),
            
            App.localPut(trading_index, trading_token_id_key, Int(0)),
            App.localPut(trading_index, trading_amount_key, Int(0)),
            App.localPut(trading_index, trading_price_key, Int(0)),
        )
    
    @Subroutine(TealType.none)
    def optin_asset(asset_id: Expr) -> Expr:
        asset_holding = AssetHolding.balance(
            Global.current_application_address(), asset_id
        )
        return Seq(
            asset_holding,
            If(Not(asset_holding.hasValue())).Then(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.AssetTransfer,
                            TxnField.xfer_asset: asset_id,
                            TxnField.asset_receiver: Global.current_application_address(),
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                )
            )
        )
    
    @Subroutine(TealType.none)
    def send_token_to(account: Expr, asset_id: Expr, asset_amount: Expr) -> Expr:
        asset_holding = AssetHolding.balance(
            Global.current_application_address(), asset_id
        )
        return Seq(
            asset_holding,
            Assert(
                And(
                    asset_holding.hasValue(),    
                    asset_holding.value() >= asset_amount,
                )                
            ),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: asset_id,
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
            )
        )
    
    
    on_create = Seq(
        App.globalPut(store_app_id_key, Btoi(Txn.application_args[0])),
        App.globalPut(distribution_app_address_key, Txn.application_args[1]),
        App.globalPut(team_wallet_address_key, Txn.application_args[2]),
        Approve(),
    )

    on_setup = Seq(
        # opt into NFT asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        Assert(
            And(
                Txn.assets.length() == Int(1),
                Txn.assets[0] > Int(0),
            )
        ),
        optin_asset(Txn.assets[0]),
        Approve(),
    )

    on_trade_txn_index = Txn.group_index() - Int(1)
    on_trade = Seq(
        Assert(
            And(
                # the actual asset transfer is before the app call
                Gtxn[on_trade_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_trade_txn_index].asset_receiver() == Global.current_application_address(),
                
                # price
                Txn.application_args.length() == Int(2),
                Btoi(Txn.application_args[1]) > Int(0),
                
                # token id
                Txn.assets.length() == Int(1),
                Txn.assets[0] > Int(0),
                
                # rekeyed address
                Txn.accounts.length() == Int(1),
            )
        ),
        handle_trading(Txn.sender(), Txn.accounts[1], Txn.assets[0], 
                       Gtxn[on_trade_txn_index].asset_amount(), Btoi(Txn.application_args[1])),
        Approve(),
    )
    
    on_cancel_pay_txn_index = Txn.group_index() - Int(1)
    on_cancel = Seq(
        Assert(
            And(
                # the actual asset transfer is before the app call
                Gtxn[on_cancel_pay_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_cancel_pay_txn_index].sender() == Txn.sender(),
                Gtxn[on_cancel_pay_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_cancel_pay_txn_index].amount() == Int(2000),
                
                Txn.assets.length() == Int(1),
                Txn.assets[0] > Int(0),
                Txn.accounts.length() == Int(1),
                is_opening(Txn.accounts[1], Txn.assets[0]),
            )
        ),
        handle_cancel_trading(Txn.sender(), Txn.accounts[1]),
        Approve(),
    )
    
    on_accept_txn_index = Txn.group_index() - Int(1)
    on_accept = Seq(
        Assert(
            And(
                # the actual accept payment is before the app call
                Gtxn[on_accept_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_accept_txn_index].sender() == Txn.sender(),
                Gtxn[on_accept_txn_index].receiver() == Global.current_application_address(),
                
                # seller, trading_index(rekeyed_address), distribution app address and team wallet address
                Txn.accounts.length() == Int(4),
                Txn.accounts[3] == App.globalGet(distribution_app_address_key),
                Txn.accounts[4] == App.globalGet(team_wallet_address_key),
                
                # include token_id
                Txn.assets.length() == Int(1),
                is_opening(Txn.accounts[2], Txn.assets[0]),
                
                #should include buying asset amount
                Txn.application_args.length() == Int(2),
                Btoi(Txn.application_args[1]) == App.localGet(Txn.accounts[2], trading_amount_key),
                
                # should be equal buying price
                Gtxn[on_accept_txn_index].amount() == App.localGet(Txn.accounts[2], trading_price_key),
            )
        ),
        handle_accept(Txn.accounts[1], Txn.sender(), Txn.accounts[2]),
        Approve(),
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("trade"), on_trade],
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
