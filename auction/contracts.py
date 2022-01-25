from pyteal import *


def approval_program():
    
    # for global state
    store_app_id_key = Bytes("SA_ID")
    staking_address_key = Bytes("SA_ADDR")
    team_wallet_address_key = Bytes("TW_ADDR")
    
    # for local state
    seller_address_key = Bytes("S_ADDR")
    token_id_key = Bytes("TK_ID")
    token_amount_key = Bytes("TKA")
    start_time_key = Bytes("ST")
    end_time_key = Bytes("ET")
    reserve_amount_key = Bytes("RA")
    min_bid_increment_key = Bytes("MBI")
    num_bids_key = Bytes("NB")
    lead_bid_price_key = Bytes("LBP")
    lead_bid_account_key = Bytes("LB_ADDR")
    
    
    @Subroutine(TealType.uint64)
    def is_open(seller: Expr, auction_index: Expr) -> Expr:
        return If(And(
            App.localGet(auction_index, token_id_key),
            App.localGet(auction_index, token_amount_key),
            Global.latest_timestamp() > start_time,
            Global.latest_timestamp() < end_time
        )).Then(
            Return(App.localGet(auction_index, seller_address_key) == seller)
        ).Else(
            Return(Int(0))
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
                Txn.applications.length() == Int(1),
                Txn.accounts.length() == Int(2),
            )
        ),
        App.globalPut(store_app_id_key, Txn.applications[1]),
        App.globalPut(staking_address_key, Txn.accounts[1]),
        App.globalPut(team_wallet_address_key, Txn.accounts[2]),
        Approve(),
    )

    on_setup_pay_txn_index = Txn.group_index() - Int(1)
    on_setup_asset_txn_index = Txn.group_index() + Int(1)
    start_time = Btoi(Txn.application_args[1])
    end_time = Btoi(Txn.application_args[2])
    reserve_amount = Btoi(Txn.application_args[3])
    auction_index = Txn.accounts[1]
    on_setup = Seq(
        Assert(
            And(
                # the actual bid payment is before the app call
                Gtxn[on_setup_pay_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_setup_pay_txn_index].sender() == Txn.sender(),
                Gtxn[on_setup_pay_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_setup_pay_txn_index].amount() >= Global.min_balance() + Global.min_txn_fee(),
                
                Gtxn[on_setup_asset_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_setup_asset_txn_index].asset_receiver() == Global.current_application_address(),
                Gtxn[on_setup_asset_txn_index].asset_amount() > Int(0),
                
                # Global.latest_timestamp() < start_time,
                start_time < end_time,
                
                # TODO: should we impose a maximum auction length?
                reserve_amount > Global.min_txn_fee(),
                
                # auction_index rekeyed address
                Txn.accounts.length() == Int(1),
            )
        ),
        
        # save auction information into local state
        App.localPut(auction_index, seller_address_key, Txn.sender()),
        App.localPut(auction_index, token_id_key, Txn.assets[0]),
        App.localPut(auction_index, token_amount_key, Gtxn[on_setup_asset_txn_index].asset_amount()),
        App.localPut(auction_index, start_time_key, start_time),
        App.localPut(auction_index, end_time_key, end_time),
        App.localPut(auction_index, reserve_amount_key, reserve_amount),
        App.localPut(auction_index, min_bid_increment_key, Btoi(Txn.application_args[4])),
        App.localPut(auction_index, lead_bid_account_key, Global.zero_address()),
        App.localPut(auction_index, lead_bid_price_key, Int(0)),
        App.localPut(auction_index, num_bids_key, Int(0)),
        
        # opt into asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        optin_asset(Txn.assets[0]),
        Approve(),
    )

    on_bid_txn_index = Txn.group_index() - Int(1)
    on_bid_asset_holding = AssetHolding.balance(
        Global.current_application_address(), App.localGet(auction_index, token_id_key)
    )
    on_bid = Seq(
        on_bid_asset_holding,
        Assert(
            And(
                # auction_index rekeyed address and pre lead bid account
                Txn.accounts.length() >= Int(1),
                
                # the auction has been set up
                on_bid_asset_holding.hasValue(),
                on_bid_asset_holding.value() > Int(0),
                
                # # the auction has started
                App.localGet(auction_index, start_time_key) <= Global.latest_timestamp(), #disabled this line for local sandbox testing
                
                # # the auction has not ended
                Global.latest_timestamp() < App.localGet(auction_index, end_time_key),
                
                # the actual bid payment is before the app call
                Gtxn[on_bid_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_bid_txn_index].sender() == Txn.sender(),
                Gtxn[on_bid_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_bid_txn_index].amount() >= App.localGet(auction_index, reserve_amount_key) + Int(3) * Global.min_txn_fee(),
            )
        ),
        If(
            Gtxn[on_bid_txn_index].amount()
            >= App.localGet(auction_index, lead_bid_price_key) + App.localGet(auction_index, min_bid_increment_key) + Int(4) * Global.min_txn_fee()
        ).Then(
            Seq(
                If(App.localGet(auction_index, lead_bid_account_key) != Global.zero_address()).Then(
                    send_payments(
                        App.localGet(auction_index, lead_bid_account_key),
                        App.localGet(auction_index, lead_bid_price_key),
                        Int(0)
                    )
                ),
                App.localPut(auction_index, lead_bid_price_key, Gtxn[on_bid_txn_index].amount() - Int(4) * Global.min_txn_fee()),
                App.localPut(auction_index, lead_bid_account_key, Txn.sender()),
                App.localPut(auction_index, num_bids_key, App.localGet(auction_index, num_bids_key) + Int(1)),
                Approve(),
            )
        ),
        Reject(),
    )
    
    on_store_txn_index = Txn.group_index() + Int(1)
    on_close = Seq(
        # single call is allowing without store call
        Assert(
            And(
                # 0: auction_index(rekeyed address)
                Txn.accounts.length() >= Int(1),
                # sender must be the seller or app creator
                Or(
                    Txn.sender() == App.localGet(auction_index, seller_address_key),
                    Txn.sender() == Global.creator_address()
                )
            )
        ),
        
        # disabled follow lines for local sandbox testing
        If(Global.latest_timestamp() < App.localGet(auction_index, start_time_key)).Then(
            # the auction has not yet started, it's ok to close
            Seq(
                # return the asset to the seller
                send_token_to(Txn.sender(), 
                              App.localGet(auction_index, token_id_key), 
                              App.localGet(auction_index, token_amount_key)),
                Approve(),
            )
        ),
        
        # the auction has ended, pay out assets
        If(Global.latest_timestamp() >= App.localGet(auction_index, end_time_key)).Then(
            Seq(
                If(App.localGet(auction_index, lead_bid_account_key) == Global.zero_address())
                .Then( 
                    # the auction has ended, but there is not bidder
                    Seq(
                        # return the asset to the seller
                        send_token_to(Txn.sender(), 
                                      App.localGet(auction_index, token_id_key), 
                                      App.localGet(auction_index, token_amount_key)),
                        Approve(),
                    )
                ).Else(
                    # single call is not allowing, if there is a bidder
                    Seq(
                        If(And(
                            Txn.accounts.length() == Int(4),
                            Txn.accounts[2] == App.localGet(auction_index, lead_bid_account_key),
                            Txn.accounts[3] == App.globalGet(staking_address_key),
                            Txn.accounts[4] == App.globalGet(team_wallet_address_key),
                            
                            # store app call
                            Gtxn[on_store_txn_index].type_enum() == TxnType.ApplicationCall,
                            Gtxn[on_store_txn_index].sender() == Txn.sender(),
                            Gtxn[on_store_txn_index].application_id() == App.globalGet(store_app_id_key),
                            Gtxn[on_store_txn_index].application_args.length() == Int(1),
                            Gtxn[on_store_txn_index].application_args[0] == Bytes("auction"),
                            Gtxn[on_store_txn_index].accounts.length() == Int(2),
                            Gtxn[on_store_txn_index].accounts[1] == Txn.accounts[2], # lead bidder
                            Gtxn[on_store_txn_index].accounts[2] == auction_index, # auction_index(rekeyed address)
                        ))
                        .Then(
                            Seq(
                                # the auction was successful: send lead bid account the asset
                                send_token_to(
                                    App.localGet(auction_index, lead_bid_account_key),
                                    App.localGet(auction_index, token_id_key),
                                    App.localGet(auction_index, token_amount_key),
                                ),
                                
                                # send payments
                                send_payments(
                                    Txn.sender(), 
                                    App.localGet(auction_index, lead_bid_price_key), 
                                    Int(1)),
                                
                                Approve(),
                            )
                        )
                    )
                ),
            )
        ),
        
        Reject(),
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("bid"), on_bid],
        [on_call_method == Bytes("close"), on_close],
    )

    on_delete = Seq(
        # Reject()
        Approve() # for test
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
            Txn.on_completion() == OnComplete.OptIn,
            Approve(),
        ],
        [
            Txn.on_completion() == OnComplete.UpdateApplication,
            on_update,
        ],
        [
            Or(
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.ClearState,
            ),
            # Reject(),
            Approve() # for test
        ],
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("auction_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("auction_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
