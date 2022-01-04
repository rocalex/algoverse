from pyteal import *


def approval_program():
    
    # for global state
    store_app_address_key = Bytes("SAA")
    distribution_app_address_key = Bytes("DAA")
    team_wallet_address_key = Bytes("TWA")
    
    # for local state
    seller_key = Bytes("S_ADDR")
    token_id_key = Bytes("TK_ID")
    token_amount_key = Bytes("TKA")
    start_time_key = Bytes("ST")
    end_time_key = Bytes("ET")
    reserve_amount_key = Bytes("RA")
    min_bid_increment_key = Bytes("MBI")
    num_bids_key = Bytes("NB")
    lead_bid_amount_key = Bytes("LBA")
    lead_bid_account_key = Bytes("LB_ADDR")
    
    
    @Subroutine(TealType.uint64)
    def is_opening(bid_index: Expr, asset_id: Expr) -> Expr:
        return And(
            App.localGet(bid_index, bid_token_id_key),
            asset_id == App.localGet(bid_index, bid_token_id_key),
            App.localGet(bid_index, bid_amount_key),
            App.localGet(bid_index, bid_price_key),
        )
    
    @Subroutine(TealType.none)
    def handle_bid(bidder: Expr, bid_index: Expr, asset_id: Expr, amount: Expr, price: Expr) -> Expr:
        return Seq(
            If(is_opening(bid_index, asset_id)).Then(
                #return payment
                send_payments(bidder, App.localGet(bid_index, bid_price_key), Int(0)),
            ),
            
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
                        TxnField.asset_sender: Global.zero_address(),
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

    @Subroutine(TealType.none)
    def repay_previous_lead_bidder(prev_lead_bidder: Expr, prev_lead_bid_amount: Expr) -> Expr:
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.amount: prev_lead_bid_amount - Global.min_txn_fee(),
                    TxnField.receiver: prev_lead_bidder,
                }
            ),
            InnerTxnBuilder.Submit(),
        )
  

    on_create = Seq(
        App.globalPut(store_app_address_key, Txn.application_args[0]),
        App.globalPut(distribution_app_address_key, Txn.application_args[1]),
        App.globalPut(team_wallet_address_key, Txn.application_args[2]),
        Approve(),
    )

    start_time = Btoi(Txn.application_args[5])
    end_time = Btoi(Txn.application_args[6])
    reserve_amount = Btoi(Txn.application_args[7])
    on_setup = Seq(
        Assert(
            And(
                Global.latest_timestamp() < start_time,
                start_time < end_time,
                # TODO: should we impose a maximum auction length?
                reserve_amount > Global.min_txn_fee(),
                
                # auction_index rekeyed address
                Txn.accounts.length() == Int(1),
            )
        ),
        
        App.globalPut(seller_key, Txn.application_args[2]),
        App.globalPut(token_id_key, Btoi(Txn.application_args[3])),
        App.globalPut(token_amount_key, Btoi(Txn.application_args[4])),
        App.globalPut(start_time_key, start_time),
        App.globalPut(end_time_key, end_time),
        App.globalPut(reserve_amount_key, reserve_amount),
        App.globalPut(min_bid_increment_key, Btoi(Txn.application_args[8])), # why do we need this?
        App.globalPut(lead_bid_account_key, Global.zero_address()),
        App.globalPut(lead_bid_amount_key, Int(0)),
        App.globalPut(num_bids_key, Int(0)),
        
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
                # the auction has started
                #App.globalGet(start_time_key) <= Global.latest_timestamp(), #disabled this line for local sandbox testing
                # the auction has not ended
                Global.latest_timestamp() < App.globalGet(end_time_key),
                # the actual bid payment is before the app call
                Gtxn[on_bid_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_bid_txn_index].sender() == Txn.sender(),
                Gtxn[on_bid_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_bid_txn_index].amount() >= App.globalGet(reserve_amount_key),
            )
        ),
        If(
            Gtxn[on_bid_txn_index].amount()
            >= App.globalGet(lead_bid_amount_key) + App.globalGet(min_bid_increment_key)
        ).Then(
            Seq(
                If(App.globalGet(lead_bid_account_key) != Global.zero_address()).Then(
                    repay_previous_lead_bidder(
                        App.globalGet(lead_bid_account_key),
                        App.globalGet(lead_bid_amount_key),
                    )
                ),
                App.globalPut(lead_bid_amount_key, Gtxn[on_bid_txn_index].amount()),
                App.globalPut(lead_bid_account_key, Gtxn[on_bid_txn_index].sender()),
                App.globalPut(num_bids_key, App.globalGet(num_bids_key) + Int(1)),
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
        #disabled follow lines for local sandbox testing
        # If(Global.latest_timestamp() < App.globalGet(start_time_key)).Then(
        #     Seq(
        #         # the auction has not yet started, it's ok to delete
        #         Assert(
        #             Or(
        #                 # sender must either be the seller or the auction creator
        #                 Txn.sender() == App.globalGet(seller_key),
        #                 Txn.sender() == Global.creator_address(),
        #             )
        #         ),
        #         # if the auction contract account has opted into the nft, close it out
        #         close_nft_to(App.globalGet(token_id_key), App.globalGet(seller_key)),
        #         # if the auction contract still has funds, send them all to the seller // how can has funds?
        #         close_payments(Int(0)),
        #         Approve(),
        #     )
        # ),
        # If(App.globalGet(end_time_key) <= Global.latest_timestamp()).Then(
        #     Seq(
                # the auction has ended, pay out assets
                If(App.globalGet(lead_bid_account_key) != Global.zero_address())
                .Then(
                    If(App.globalGet(lead_bid_amount_key)
                        >= App.globalGet(reserve_amount_key))
                    .Then(
                        Seq(
                            # the auction was successful: send lead bid account the nft
                            close_nft_to(
                                App.globalGet(token_id_key),
                                App.globalGet(lead_bid_account_key),
                            ),
                            # send remaining funds to the seller
                            close_payments(Int(1)),   
                        )
                    )
                    .Else(
                        Seq(
                            # the auction was not successful because the reserve was not met: return
                            # the nft to the seller and repay the lead bidder
                            close_nft_to(
                                App.globalGet(token_id_key), App.globalGet(seller_key)
                            ),
                            repay_previous_lead_bidder(
                                App.globalGet(lead_bid_account_key),
                                App.globalGet(lead_bid_amount_key),
                            ),
                            # send remaining funds to the seller
                            close_payments(Int(0)),
                        )
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
            # )
        # ),
        # Reject(),
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
    with open("auction_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("auction_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
