from pyteal import *

def approval_program():
    
    # for global state
    total_sold_amount_key = Bytes("TSA")
    total_bought_amount_key = Bytes("TBA")
    trade_app_id_key = Bytes("TA_ADDR")
    bid_app_id_key = Bytes("BA_ADDR")
    auction_app_id_key = Bytes("AA_ADDR")
    distribution_app_id_key = Bytes("DA_ADDR")
    
    # for local state
    sold_amount_key = Bytes("SA")
    bought_amount_key = Bytes("BA")
    lead_bid_account_key = Bytes("LB_ADDR")
    lead_bid_price_key = Bytes("LBP")
    
    
    @Subroutine(TealType.bytes)
    def get_app_address(appID: Expr) -> Expr:
        return Sha512_256(Concat(Bytes("appID") , Itob(appID)))
    
    
    on_create = Seq(
        App.globalPut(total_sold_amount_key, Int(0)),
        App.globalPut(total_bought_amount_key, Int(0)),
        Approve()
    )
    
    on_setup = Seq(
        Assert(
            And(
                Txn.sender() == Global.creator_address(),
                Txn.applications.length() == Int(4),
                Txn.applications[1] > Int(0),
                Txn.applications[2] > Int(0),
                Txn.applications[3] > Int(0),
                Txn.applications[4] > Int(0)
            )
        ),
        
        App.globalPut(trade_app_id_key, Txn.applications[1]),
        App.globalPut(bid_app_id_key, Txn.applications[2]),
        App.globalPut(auction_app_id_key, Txn.applications[3]),
        App.globalPut(distribution_app_id_key, Txn.applications[4]),
        
        Approve()
    )
    
    total_sold_amount = App.globalGet(total_sold_amount_key)
    total_bought_amount = App.globalGet(total_bought_amount_key)
    on_reset = Seq(
        Assert(
            And(
                Txn.type_enum() == TxnType.ApplicationCall,
                Txn.sender() == get_app_address(App.globalGet(distribution_app_id_key)),
                Txn.accounts.length() == Int(1)
            )
        ),
        
        Seq(
            App.globalPut(total_sold_amount_key, total_sold_amount - App.localGet(Txn.accounts[1], sold_amount_key)),
            App.localPut(Txn.accounts[1], sold_amount_key, Int(0)),
            App.globalPut(total_bought_amount_key, total_bought_amount - App.localGet(Txn.accounts[1], bought_amount_key)),
            App.localPut(Txn.accounts[1], bought_amount_key, Int(0)),
        ),
        
        Approve()
    )
    
    # use for trade contract
    seller_sold_amount = App.localGet(Txn.accounts[1], sold_amount_key)
    buyer_bought_amount = App.localGet(Txn.sender(), bought_amount_key)
    on_pay_txn_index = Txn.group_index() - Int(2)
    on_buy_txn_index = Txn.group_index() - Int(1)
    buying_price = Gtxn[on_pay_txn_index].amount() - Int(4) * Global.min_txn_fee()
    on_buy = Seq(
        Assert(
            And(
                # accept payment call
                Gtxn[on_pay_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_pay_txn_index].sender() == Txn.sender(), # buyer
                Gtxn[on_pay_txn_index].receiver() == get_app_address(App.globalGet(trade_app_id_key)),
                
                # trade app accept call
                Gtxn[on_buy_txn_index].type_enum() == TxnType.ApplicationCall,
                Gtxn[on_buy_txn_index].sender() == Txn.sender(),
                Gtxn[on_buy_txn_index].application_id() == App.globalGet(trade_app_id_key),
                
                Gtxn[on_buy_txn_index].application_args.length() == Int(2),
                Gtxn[on_buy_txn_index].application_args[0] == Bytes("accept"),
                Btoi(Gtxn[on_buy_txn_index].application_args[1]) > Int(0), # asset amount
                
                Gtxn[on_buy_txn_index].accounts.length() == Int(4),
                Txn.accounts.length() == Int(1),
                Gtxn[on_buy_txn_index].accounts[1] == Txn.accounts[1], # seller
                
                buying_price > Int(0),
            )
        ),
        
        App.localPut(Txn.accounts[1], sold_amount_key, seller_sold_amount + buying_price),
        App.localPut(Txn.sender(), bought_amount_key, buyer_bought_amount + buying_price),
        App.globalPut(total_sold_amount_key, buying_price + App.globalGet(total_sold_amount_key)),
        App.globalPut(total_bought_amount_key, buying_price + App.globalGet(total_bought_amount_key)),
        Approve()
    )
    
    # use for bid contract
    seller_sold_amount = App.localGet(Txn.sender(), sold_amount_key)
    buyer_bought_amount = App.localGet(Txn.accounts[1], bought_amount_key)
    on_asset_txn_index = Txn.group_index() - Int(2)
    on_sell_txn_index = Txn.group_index() - Int(1)
    on_sell = Seq(
        Assert(
            And(
                # accept asset txn call
                Gtxn[on_asset_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_asset_txn_index].receiver() == get_app_address(App.globalGet(bid_app_id_key)),
                
                # bid app accept call
                Gtxn[on_sell_txn_index].type_enum() == TxnType.ApplicationCall,
                Gtxn[on_sell_txn_index].sender() == Txn.sender(),
                Gtxn[on_sell_txn_index].application_id() == App.globalGet(bid_app_id_key),
                
                Gtxn[on_sell_txn_index].application_args.length() == Int(2),
                Gtxn[on_sell_txn_index].application_args[0] == Bytes("accept"),
                Btoi(Gtxn[on_sell_txn_index].application_args[1]) > Int(0), # bid price
                
                Gtxn[on_sell_txn_index].accounts.length() == Int(4),
                Txn.accounts.length() == Int(1),
                Gtxn[on_sell_txn_index].accounts[1] == Txn.accounts[1], # bidder
            )
        ),
        
        App.localPut(Txn.sender(), sold_amount_key, seller_sold_amount + Btoi(Gtxn[on_sell_txn_index].application_args[1])),
        App.localPut(Txn.accounts[1], bought_amount_key, buyer_bought_amount + Btoi(Gtxn[on_sell_txn_index].application_args[1])),
        App.globalPut(total_sold_amount_key, Btoi(Gtxn[on_sell_txn_index].application_args[1]) + App.globalGet(total_sold_amount_key)),
        App.globalPut(total_bought_amount_key, Btoi(Gtxn[on_sell_txn_index].application_args[1]) + App.globalGet(total_bought_amount_key)),
        Approve()
    )
    
    # use for auction contract
    seller_sold_amount = App.localGet(Txn.sender(), sold_amount_key)
    buyer_bought_amount = App.localGet(Txn.accounts[1], bought_amount_key)
    on_auction_txn_index = Txn.group_index() - Int(1)
    auction_index = Txn.accounts[2]
    lead_bidder = App.localGetEx(auction_index, Txn.applications[1], lead_bid_account_key)
    lead_bid_price = App.localGetEx(auction_index, Txn.applications[1], lead_bid_price_key)
    on_auction = Seq(
        lead_bidder,
        lead_bid_price,
        If(And(
            lead_bidder.value() != Global.zero_address(),
            lead_bid_price.value() > Int(0)
        ))
        .Then(Seq(
            # there are bids
            Assert(
                And(
                    # auction app close call
                    Gtxn[on_auction_txn_index].type_enum() == TxnType.ApplicationCall,
                    Gtxn[on_auction_txn_index].sender() == Txn.sender(), # sellor or creator
                    
                    Gtxn[on_auction_txn_index].application_id() == App.globalGet(auction_app_id_key),
                    
                    Gtxn[on_auction_txn_index].application_args.length() == Int(1),
                    Gtxn[on_auction_txn_index].application_args[0] == Bytes("close"),
                    
                    Gtxn[on_auction_txn_index].accounts.length() == Int(4),
                    Txn.accounts.length() == Int(2),
                    Gtxn[on_auction_txn_index].accounts[2] == Txn.accounts[1], # lead bidder
                    lead_bidder.value() == Txn.accounts[1],
                    auction_index == Gtxn[on_auction_txn_index].accounts[1],
                    
                    Txn.applications.length() == Int(1), # auction app
                    Txn.applications[1] == App.globalGet(auction_app_id_key),
                )
            ),
            
            App.localPut(Txn.sender(), sold_amount_key, seller_sold_amount + lead_bid_price.value()),
            App.localPut(Txn.accounts[1], bought_amount_key, buyer_bought_amount + lead_bid_price.value()),
            App.globalPut(total_sold_amount_key, lead_bid_price.value() + App.globalGet(total_sold_amount_key)),
            App.globalPut(total_bought_amount_key, lead_bid_price.value() + App.globalGet(total_bought_amount_key)),      
        )),
        Approve()
    )
    
    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("reset"), on_reset],
        [on_call_method == Bytes("set_sold"), on_set_sold],
        [on_call_method == Bytes("set_bought"), on_set_bought],
        [on_call_method == Bytes("buy"), on_buy],
        [on_call_method == Bytes("sell"), on_sell],
        [on_call_method == Bytes("auction"), on_auction],
    )
    

    on_delete = Seq(
        # Assert(
        #     Txn.sender() == Global.creator_address(),
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
            Txn.on_completion() == OnComplete.OptIn,
            Approve(),
        ],
        [
            Or(
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.ClearState,
            ),
            Reject(),
        ]
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("store_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("store_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
