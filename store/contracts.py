from pyteal import *


class StoreContract:
    class Vars:
        creator_key = Bytes("C")
        token_id_key = Bytes("T")
        total_sold_amount_key = Bytes("TSA")
        total_bought_amount_key = Bytes("TBA")
        token_sold_amount_key = Bytes("TKSA")
        token_bought_amount_key = Bytes("TKBA")
        
    def on_create(self):
        return Seq(
            Assert(Txn.assets.length() == Int(1)),
            App.globalPut(self.Vars.total_sold_amount_key, Int(0)),
            App.globalPut(self.Vars.total_bought_amount_key, Int(0)),
            App.globalPut(self.Vars.creator_key, Txn.sender()),
            App.globalPut(self.Vars.token_id_key, Txn.assets[0]),
            Approve()
        )
    
    # will be used for reset user's sold token amount
    def on_set_sold(self):
        total_sold_amount = App.globalGet(self.Vars.total_sold_amount_key)
        user_sold_amount = App.localGet(Txn.accounts[0], self.Vars.token_sold_amount_key)
        return Seq(
            Assert(
                And(
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Txn.receiver() == Global.current_application_address(),
                    Txn.sender() == App.globalGet(self.Vars.creator_key),
                    Txn.xfer_asset() == App.globalGet(self.Vars.token_id_key),
                    Txn.amount() > Int(0),
                    Txn.accounts.length() == Int(1)
                )
            ),
            
            App.globalPut(self.Vars.total_sold_amount_key, total_sold_amount - user_sold_amount + Txn.amount()),
            App.localPut(Txn.accounts[0], self.Vars.token_sold_amount_key, Txn.amount()),
            Approve()
        )
        
    # will be used for reset user's bought token amount
    def on_set_bought(self):
        total_bought_amount = App.globalGet(self.Vars.total_bought_amount_key)
        user_bought_amount = App.localGet(Txn.accounts[0], self.Vars.token_bought_amount_key)
        return Seq(
            Assert(
                And(
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Txn.receiver() == Global.current_application_address(),
                    Txn.sender() == App.globalGet(self.Vars.creator_key),
                    Txn.xfer_asset() == App.globalGet(self.Vars.token_id_key),
                    Txn.amount() > Int(0),
                    Txn.accounts.length() == Int(1)
                )
            ),
            
            App.globalPut(self.Vars.total_bought_amount_key, total_bought_amount - user_bought_amount + Txn.amount()),
            App.localPut(Txn.receiver(), self.Vars.token_bought_amount_key, Txn.amount()),
            Approve()
        )
        
    def on_buy(self):
        seller_sold_token_amount = App.localGet(Txn.accounts[0], self.Vars.token_sold_amount_key)
        buyer_bought_token_amount = App.localGet(Txn.accounts[1], self.Vars.token_bought_amount_key)
        return Seq(
            Assert(
                And(
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Txn.receiver() == Global.current_application_address(),
                    Txn.sender() == App.globalGet(self.Vars.creator_key),
                    Txn.xfer_asset() == App.globalGet(self.Vars.token_id_key),
                    Txn.amount() > Int(0),
                    Txn.accounts.length() == Int(2)
                )
            ),
            
            App.localPut(Txn.accounts[0], self.Vars.token_sold_amount_key, seller_sold_token_amount + Txn.amount()),
            App.localPut(Txn.accounts[1], self.Vars.token_bought_amount_key, buyer_bought_token_amount + Txn.amount()),
            Approve()
        )
       
    def on_call(self):
        on_call_method = Txn.application_args[0]
        return Cond(
            [on_call_method == Bytes("set_sold"), self.on_set_sold()],
            [on_call_method == Bytes("set_bought"), self.on_set_bought()],
            [on_call_method == Bytes("buy"), self.on_buy()],
        )

    def approval_program(self):
        program = Cond(
            [Txn.application_id() == Int(0), self.on_create()],
            [Txn.on_completion() == OnComplete.NoOp, self.on_call()],
            [
                Or(
                    Txn.on_completion() == OnComplete.DeleteApplication,
                    Txn.on_completion() == OnComplete.OptIn,
                    Txn.on_completion() == OnComplete.CloseOut,
                    Txn.on_completion() == OnComplete.UpdateApplication,
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