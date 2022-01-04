from pyteal import *

class StoreContract:
    
    class Vars:
        # for global state
        total_sold_amount_key = Bytes("TSA")
        total_bought_amount_key = Bytes("TBA")
        trade_app_id_key = Bytes("TA_ADDR")
        bid_app_id_key = Bytes("BA_ADDR")
        auction_app_id_key = Bytes("AA_ADDR")
        
        # for local state
        sold_amount_key = Bytes("SA")
        bought_amount_key = Bytes("BA")
        
        
    @Subroutine(TealType.bytes)
    def get_app_address(appID: Expr) -> Expr:
        return Sha512_256(Concat(b"appID" , Itob(appID)))
        
    def on_create(self):
        return Seq(
            App.globalPut(self.Vars.total_sold_amount_key, Int(0)),
            App.globalPut(self.Vars.total_bought_amount_key, Int(0)),
            Approve()
        )
        
    def on_setup(self):
        return Seq(
            Assert(
                And(
                    Txn.sender() == Global.creator_address(),
                    Txn.applications.length() == Int(3),
                )
            ),
            App.globalPut(self.Vars.trade_app_id_key, Txn.applications[1]),
            App.globalPut(self.Vars.bid_app_id_key, Txn.applications[2]),
            App.globalPut(self.Vars.auction_app_id_key, Txn.applications[3]),
            Approve()
        )
    
    # will be used for reset user's sold amount
    def on_set_sold(self):
        total_sold_amount = App.globalGet(self.Vars.total_sold_amount_key)
        user_sold_amount = App.localGet(Txn.accounts[1], self.Vars.sold_amount_key)
        return Seq(
            Assert(
                And(
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Txn.sender() == Global.creator_address(),
                    Btoi(Txn.application_args[1]) > Int(0),
                    Txn.accounts.length() == Int(1)
                )
            ),
            
            App.globalPut(self.Vars.total_sold_amount_key, total_sold_amount - user_sold_amount + Btoi(Txn.application_args[1])),
            App.localPut(Txn.accounts[1], self.Vars.sold_amount_key, Btoi(Txn.application_args[1])),
            Approve()
        )
        
    # will be used for reset user's bought amount
    def on_set_bought(self):
        total_bought_amount = App.globalGet(self.Vars.total_bought_amount_key)
        user_bought_amount = App.localGet(Txn.accounts[1], self.Vars.bought_amount_key)
        return Seq(
            Assert(
                And(
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Txn.sender() == Global.creator_address(),
                    Txn.application_args.length() == Int(2),
                    Btoi(Txn.application_args[1]) > Int(0),
                    Txn.accounts.length() == Int(1)
                )
            ),
            
            App.globalPut(self.Vars.total_bought_amount_key, total_bought_amount - user_bought_amount + Btoi(Txn.application_args[1])),
            App.localPut(Txn.receiver(), self.Vars.bought_amount_key, Btoi(Txn.application_args[1])),
            Approve()
        )
    
    def on_buy(self): # use for trade
        seller_sold_amount = App.localGet(Txn.accounts[1], self.Vars.sold_amount_key)
        buyer_bought_amount = App.localGet(Txn.sender(), self.Vars.bought_amount_key)
        on_pay_txn_index = Txn.group_index() - Int(2)
        on_buy_txn_index = Txn.group_index() - Int(1)
        buying_price = Gtxn[on_pay_txn_index].amount() - Int(4) * Global.min_txn_fee()
        return Seq(
            Assert(
                And(
                    # accept payment call
                    Gtxn[on_pay_txn_index].type_enum() == TxnType.Payment,
                    Gtxn[on_pay_txn_index].sender() == Txn.sender(), # buyer
                    # Gtxn[on_pay_txn_index].receiver() == self.get_app_address(App.globalGet(self.Vars.trade_app_id_key)),
                    
                    # trade app accept call
                    Gtxn[on_buy_txn_index].type_enum() == TxnType.ApplicationCall,
                    Gtxn[on_buy_txn_index].sender() == Txn.sender(),
                    Gtxn[on_buy_txn_index].application_id() == App.globalGet(self.Vars.trade_app_id_key),
                    
                    Gtxn[on_buy_txn_index].application_args.length() == Int(2),
                    Gtxn[on_buy_txn_index].application_args[0] == Bytes("accept"),
                    Btoi(Gtxn[on_buy_txn_index].application_args[1]) > Int(0), # asset amount
                    
                    Gtxn[on_buy_txn_index].accounts.length() == Int(4),
                    Txn.accounts.length() == Int(1),
                    Gtxn[on_buy_txn_index].accounts[1] == Txn.accounts[1], # seller
                    
                    buying_price > Int(0),
                )
            ),
            
            App.localPut(Txn.accounts[1], self.Vars.sold_amount_key, seller_sold_amount + buying_price),
            App.localPut(Txn.sender(), self.Vars.bought_amount_key, buyer_bought_amount + buying_price),
            App.globalPut(self.Vars.total_sold_amount_key, buying_price + App.globalGet(self.Vars.total_sold_amount_key)),
            App.globalPut(self.Vars.total_bought_amount_key, buying_price + App.globalGet(self.Vars.total_bought_amount_key)),
            Approve()
        )
    
    def on_sell(self): # use for bid
        seller_sold_amount = App.localGet(Txn.sender(), self.Vars.sold_amount_key)
        buyer_bought_amount = App.localGet(Txn.accounts[1], self.Vars.bought_amount_key)
        on_asset_txn_index = Txn.group_index() - Int(2)
        on_sell_txn_index = Txn.group_index() - Int(1)
        return Seq(
            Assert(
                And(
                    # accept asset txn call
                    Gtxn[on_asset_txn_index].type_enum() == TxnType.AssetTransfer,
                    # Gtxn[on_asset_txn_index].receiver() == self.get_app_address(App.globalGet(self.Vars.bid_app_id_key)),
                    
                    # bid app accept call
                    Gtxn[on_sell_txn_index].type_enum() == TxnType.ApplicationCall,
                    Gtxn[on_sell_txn_index].sender() == Txn.sender(),
                    Gtxn[on_sell_txn_index].application_id() == App.globalGet(self.Vars.bid_app_id_key),
                    
                    Gtxn[on_sell_txn_index].application_args.length() == Int(2),
                    Gtxn[on_sell_txn_index].application_args[0] == Bytes("accept"),
                    Btoi(Gtxn[on_sell_txn_index].application_args[1]) > Int(0), # bid price
                    
                    Gtxn[on_sell_txn_index].accounts.length() == Int(4),
                    Txn.accounts.length() == Int(1),
                    Gtxn[on_sell_txn_index].accounts[1] == Txn.accounts[1], # bidder
                )
            ),
            
            App.localPut(Txn.sender(), self.Vars.sold_amount_key, seller_sold_amount + Btoi(Gtxn[on_sell_txn_index].application_args[1])),
            App.localPut(Txn.accounts[1], self.Vars.bought_amount_key, buyer_bought_amount + Btoi(Gtxn[on_sell_txn_index].application_args[1])),
            App.globalPut(self.Vars.total_sold_amount_key, Btoi(Gtxn[on_sell_txn_index].application_args[1]) + App.globalGet(self.Vars.total_sold_amount_key)),
            App.globalPut(self.Vars.total_bought_amount_key, Btoi(Gtxn[on_sell_txn_index].application_args[1]) + App.globalGet(self.Vars.total_bought_amount_key)),
            Approve()
        )
        
    def on_call(self):
        on_call_method = Txn.application_args[0]
        return Cond(
            [on_call_method == Bytes("setup"), self.on_setup()],
            [on_call_method == Bytes("set_sold"), self.on_set_sold()],
            [on_call_method == Bytes("set_bought"), self.on_set_bought()],
            [on_call_method == Bytes("buy"), self.on_buy()],
            [on_call_method == Bytes("sell"), self.on_sell()],
        )
        
    def on_delete(self): 
        return Seq(
            # Assert(
            #     Txn.sender() == Global.creator_address(),
            # ),
            Approve(),
        )
    
    def on_update(self):
        return Seq(
            Assert(
                Txn.sender() == Global.creator_address(),
            ),
            Approve(),
        )

    def approval_program(self):
        program = Cond(
            [Txn.application_id() == Int(0), self.on_create()],
            [Txn.on_completion() == OnComplete.NoOp, self.on_call()],
            [
                Txn.on_completion() == OnComplete.DeleteApplication,
                self.on_delete(),
            ],
            [
                Txn.on_completion() == OnComplete.UpdateApplication,
                self.on_update(),
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

    def clear_program(self):
        return Approve()


if __name__ == '__main__':
    contract = StoreContract()
    with open("staking_approval.teal", "w") as f:
        compiled = compileTeal(contract.approval_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)

    with open("staking_clear_state.teal", "w") as f:
        compiled = compileTeal(contract.clear_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)