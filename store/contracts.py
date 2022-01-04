from pyteal import *


class StoreContract:
    
    class Vars:
        # for global state
        total_sold_amount_key = Bytes("TSA")
        total_bought_amount_key = Bytes("TBA")
        
        # for local state
        sold_amount_key = Bytes("SA")
        bought_amount_key = Bytes("BA")
        
        
    def on_create(self):
        return Seq(
            App.globalPut(self.Vars.total_sold_amount_key, Int(0)),
            App.globalPut(self.Vars.total_bought_amount_key, Int(0)),
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
        
    def on_buy(self):
        seller_sold_amount = App.localGet(Txn.accounts[1], self.Vars.sold_amount_key)
        buyer_bought_amount = App.localGet(Txn.accounts[2], self.Vars.bought_amount_key)
        return Seq(
            Assert(
                And(
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Txn.sender() == Global.creator_address(),
                    Txn.application_args.length() == Int(2),
                    Btoi(Txn.application_args[1]) > Int(0),
                    Txn.accounts.length() == Int(2)
                )
            ),
            
            App.localPut(Txn.accounts[1], self.Vars.sold_amount_key, seller_sold_amount + Btoi(Txn.application_args[1])),
            App.localPut(Txn.accounts[2], self.Vars.bought_amount_key, buyer_bought_amount + Btoi(Txn.application_args[1])),
            App.globalPut(self.Vars.total_sold_amount_key, seller_sold_amount + App.globalGet(self.Vars.total_sold_amount_key)),
            App.globalPut(self.Vars.total_bought_amount_key, buyer_bought_amount + App.globalGet(self.Vars.total_bought_amount_key)),
            Approve()
        )
       
    def on_call(self):
        on_call_method = Txn.application_args[0]
        return Cond(
            [on_call_method == Bytes("set_sold"), self.on_set_sold()],
            [on_call_method == Bytes("set_bought"), self.on_set_bought()],
            [on_call_method == Bytes("buy"), self.on_buy()],
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