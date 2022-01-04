from pyteal import *

def approval_program():
    
    # for global state
    store_app_id_key = Bytes("SA_ID")
    staking_address_key = Bytes("SA_ADDR")
    team_wallet_address_key = Bytes("TW_ADDR")
    
    # for local state
    bidder_address_key = Bytes("B_ADDR") 
    bid_token_id_key = Bytes("TK_ID")
    bid_amount_key = Bytes("TA")
    bid_price_key = Bytes("TP")
    
    
    @Subroutine(TealType.uint64)
    def is_open(bidder: Expr, bid_index: Expr) -> Expr:
        return If(And(
            App.localGet(bid_index, bid_token_id_key),
            App.localGet(bid_index, bid_amount_key),
            App.localGet(bid_index, bid_price_key),
        )).Then(
            Return(App.localGet(bid_index, bidder_address_key) == bidder)
        ).Else(
            Return(Int(0))
        )
    
    @Subroutine(TealType.none)
    def handle_bid(bidder: Expr, bid_index: Expr, asset_id: Expr, amount: Expr, price: Expr) -> Expr:
        return Seq(
            If(is_open(bidder, bid_index)).Then(
                #return payment
                send_payments(bidder, App.localGet(bid_index, bid_price_key), Int(0)),
            ),
            
            App.localPut(bid_index, bidder_address_key, bidder),
            App.localPut(bid_index, bid_token_id_key, asset_id),
            App.localPut(bid_index, bid_amount_key, amount),
            App.localPut(bid_index, bid_price_key, price),
        )
    
    @Subroutine(TealType.none)
    def handle_cancel_bid(bidder: Expr, bid_index: Expr) -> Expr:
        return Seq(
            # return payment
            send_payments(bidder, App.localGet(bid_index, bid_price_key), Int(0)),
            
            App.localPut(bid_index, bid_token_id_key, Int(0)),
            App.localPut(bid_index, bid_amount_key, Int(0)),
            App.localPut(bid_index, bid_price_key, Int(0)),
        )
    
    @Subroutine(TealType.none)
    def handle_accept(seller: Expr, bidder: Expr, bid_index: Expr) -> Expr:
        return Seq(
            # send payment to seller
            send_payments(seller, App.localGet(bid_index, bid_price_key), Int(1)),
            
            # send asset to bidder
            send_token_to(bidder, App.localGet(bid_index, bid_token_id_key), App.localGet(bid_index, bid_amount_key)),
            
            App.localPut(bid_index, bid_token_id_key, Int(0)),
            App.localPut(bid_index, bid_amount_key, Int(0)),
            App.localPut(bid_index, bid_price_key, Int(0)),
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
                                TxnField.receiver: App.globalGet(staking_address_key),
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
        Assert(
            And(
                # staking app address and team wallet address
                Txn.accounts.length() == Int(2),
                # store app id
                Txn.application_args.length() == Int(1),
            )
        ),
        App.globalPut(store_app_id_key, Btoi(Txn.application_args[0])),
        App.globalPut(staking_address_key, Txn.accounts[1]),
        App.globalPut(team_wallet_address_key, Txn.accounts[2]),
        Approve(),
    )
    
    on_setup_txn_index = Txn.group_index() - Int(1)
    on_setup = Seq(
        # opt into NFT asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        Assert(
            And(
                # payment to opt into asset
                Gtxn[on_setup_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_setup_txn_index].sender() == Txn.sender(),
                Gtxn[on_setup_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_setup_txn_index].amount() >= Global.min_txn_fee() + Int(235500),
                
                Txn.assets.length() == Int(1),
                Txn.assets[0] > Int(0),
            )
        ),
        optin_asset(Txn.assets[0]),
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
                Gtxn[on_bid_txn_index].amount() > Int(4) * Global.min_txn_fee(),
                Txn.application_args.length() == Int(2),
                # asset amount
                Btoi(Txn.application_args[1]) > Int(0),
                # token id
                Txn.assets.length() == Int(1),
                Txn.assets[0] > Int(0),
                # rekeyed address
                Txn.accounts.length() == Int(1),
            )
        ),
        handle_bid(Txn.sender(), Txn.accounts[1], Txn.assets[0], 
                   Btoi(Txn.application_args[1]), Gtxn[on_bid_txn_index].amount() - Int(4) * Global.min_txn_fee()),
        Approve(),
    )
    
    on_cancel = Seq(
        Assert(
            And(
                Txn.accounts.length() == Int(1),
                is_open(Txn.sender(), Txn.accounts[1]),
            )
        ),
        handle_cancel_bid(Txn.sender(), Txn.accounts[1]),
        Approve(),
    )
    
    on_accept_txn_index = Txn.group_index() - Int(1)
    on_store_txn_index = Txn.group_index() + Int(1)
    on_accept = Seq(
        Assert(
            And(
                # the actual accept asset transfer is before the app call
                Gtxn[on_accept_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_accept_txn_index].asset_receiver() == Global.current_application_address(),
                
                # bidder, bid_index(rekeyed_address), distribution app address and team wallet address
                Txn.accounts.length() == Int(4),
                Txn.accounts[3] == App.globalGet(staking_address_key),
                Txn.accounts[4] == App.globalGet(team_wallet_address_key),
                
                is_open(Txn.accounts[1], Txn.accounts[2]),
                
                Txn.assets.length() == Int(1),
                Txn.assets[0] == Gtxn[on_accept_txn_index].xfer_asset(),
                Txn.assets[0] == App.localGet(Txn.accounts[2], bid_token_id_key),
                
                # should include selling price
                Txn.application_args.length() == Int(2),
                Btoi(Txn.application_args[1]) == App.localGet(Txn.accounts[2], bid_price_key),
                
                # should be equal selling asset amounts
                Gtxn[on_accept_txn_index].asset_amount() == App.localGet(Txn.accounts[2], bid_amount_key),
                
                # store app call
                Gtxn[on_store_txn_index].type_enum() == TxnType.ApplicationCall,
                Gtxn[on_store_txn_index].sender() == Global.creator_address(),
                Gtxn[on_store_txn_index].application_id() == App.globalGet(store_app_id_key),
                Gtxn[on_store_txn_index].application_args.length() == Int(2),
                Gtxn[on_store_txn_index].application_args[0] == Bytes("buy"),
                Gtxn[on_store_txn_index].application_args[1] == Txn.application_args[1],
                Gtxn[on_store_txn_index].accounts.length() == Int(2),
                Gtxn[on_store_txn_index].accounts[1] == Txn.sender(),
                Gtxn[on_store_txn_index].accounts[2] == Txn.accounts[1],
            )
        ),
        handle_accept(Txn.sender(), Txn.accounts[1], Txn.accounts[2]),
        Approve(),
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
        #     Txn.sender() == Global.creator_address(),
        #     Balance(Global.current_application_address()) == Global.min_txn_fee(),
        # ),
        Approve(),
    )
    
    on_update = Seq(
        Assert(
            Txn.sender() == Global.creator_address(),
        ),
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
            Txn.on_completion() == OnComplete.UpdateApplication,
            on_update,
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
            ),
            Reject(),
        ],
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("bidding_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("bidding_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
