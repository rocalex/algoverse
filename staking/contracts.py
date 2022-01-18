from pyteal import *


class StakingContract:
    class Vars:
        # global state
        token_id_key = Bytes("T")
        distribute_app_id_key = Bytes("DA")
        lock_time_key = Bytes("PTL")
        week_total_asset_amount_key = Bytes("WTTA") 
        distribution_algo_amount_key = Bytes("DAA") 
        
        # local state
        token_amount_key = Bytes("TA")
        last_claimed_time_key = Bytes("CDT")
        week_withdraw_amount = Bytes("WWA")
        week_stake_amount = Bytes("WSA")
        

    def on_create(self):
        return Seq(
            Assert(Txn.assets.length() == Int(1)),
            
            App.globalPut(self.Vars.token_id_key, Txn.assets[0]),
            App.globalPut(self.Vars.distribute_app_id_key, Txn.applications[1]),
            # initialization of the lock time
            App.globalPut(self.Vars.lock_time_key, Global.latest_timestamp()),
            Approve()
        )
        
    def on_setup(self):
        return Seq(
            Assert(
                And(
                    Global.creator_address() == Txn.sender(),
                    App.globalGet(self.Vars.token_id_key) == Txn.assets[0]
                )
            ),
            
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: Txn.assets[0],
                TxnField.asset_receiver: Global.current_application_address(),
            }),
            InnerTxnBuilder.Submit(),
            Approve()
        )
        
    def on_stake(self):
        old_token_amount = App.localGet(Txn.sender(), self.Vars.token_amount_key)
        return Seq(
            Assert(
                And(
                    Global.group_size() == Int(3),
                    Gtxn[0].type_enum() == TxnType.AssetTransfer,
                    Gtxn[0].xfer_asset() == App.globalGet(self.Vars.token_id_key),
                    Gtxn[0].asset_receiver() == Global.current_application_address(),
                    Gtxn[1].type_enum() == TxnType.ApplicationCall,
                    Gtxn[1].application_args[0] == Bytes("transfer"),
                    Gtxn[1].application_id() == App.globalGet(self.Vars.distribute_app_id_key),
                )
            ),
            
            App.localPut(Txn.sender(), self.Vars.token_amount_key, Gtxn[0].asset_amount() + old_token_amount),
            App.localPut(Txn.sender(), self.Vars.week_stake_amount, App.localGet(Txn.sender(), self.Vars.week_stake_amount) + Gtxn[0].asset_amount()),
            Approve()
        )
        
    def on_withdraw(self):
        old_token_amount = App.localGet(Txn.sender(), self.Vars.token_amount_key)
        requested_amount = Btoi(Txn.application_args[1])
        return Seq(
            Assert(
                And(
                    Global.group_size() == Int(2),
                    Gtxn[0].type_enum() == TxnType.Payment,
                    App.globalGet(self.Vars.token_id_key) == Txn.assets[0],
                    requested_amount <= old_token_amount
                )
            ),
            
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: Txn.assets[0],
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: requested_amount
            }),
            InnerTxnBuilder.Submit(),
            
            App.localPut(Txn.sender(), self.Vars.week_withdraw_amount, App.localGet(Txn.sender(), self.Vars.week_withdraw_amount) + requested_amount),
            App.localPut(Txn.sender(), self.Vars.token_amount_key, old_token_amount - requested_amount),
            Approve()
        )
        
    def on_claim(self):
        total_amount = AssetHolding.balance(Global.current_application_address(), Txn.assets[0])
        token_amount = App.localGet(Txn.sender(), self.Vars.token_amount_key)
        algo_amount = Balance(Global.current_application_address())
        last_claimed_date = App.localGet(Txn.sender(), self.Vars.last_claimed_time_key)
        
        return Seq(
            total_amount,
            Assert(
                And(
                    App.globalGet(self.Vars.token_id_key) == Txn.assets[0],
                    token_amount > Int(0),
                    total_amount.hasValue(),
                    Global.group_size() == Int(2),
                    Gtxn[0].type_enum() == TxnType.Payment,
                    Gtxn[0].amount() == Int(201_000),
                    
                    # if once claimed for the current lock time, cannot claim more
                    App.globalGet(self.Vars.lock_time_key) > last_claimed_date,
                )
            ),
            
            If(Global.latest_timestamp() >= App.globalGet(self.Vars.lock_time_key) + Int(86400) * Int(7)).Then(
                Seq(
                    App.globalPut(self.Vars.distribution_algo_amount_key, algo_amount),
                    App.globalPut(self.Vars.week_total_asset_amount_key, total_amount.value()),
                    App.globalPut(self.Vars.lock_time_key, Global.latest_timestamp()),
                )
            ),
            
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: Txn.sender(),
                TxnField.amount: WideRatio([token_amount - App.localGet(Txn.sender(), self.Vars.week_stake_amount), App.globalGet(self.Vars.distribution_algo_amount_key)], [App.globalGet(self.Vars.week_total_asset_amount_key)]) - Int(201_000)
            }),
            InnerTxnBuilder.Submit(),
            
            App.localPut(Txn.sender(), self.Vars.last_claimed_time_key, App.globalGet(self.Vars.lock_time_key)),
            App.localPut(Txn.sender(), self.Vars.week_withdraw_amount, Int(0)),
            App.localPut(Txn.sender(), self.Vars.week_stake_amount, Int(0)),
            
            Approve()
        )
        
    def on_call(self):
        on_call_method = Txn.application_args[0]
        return Cond(
            [on_call_method == Bytes("setup"), self.on_setup()],
            [on_call_method == Bytes("stake"), self.on_stake()],
            [on_call_method == Bytes("withdraw"), self.on_withdraw()],
            [on_call_method == Bytes("claim"), self.on_claim()]
        )

    def approval_program(self):
        program = Cond(
            [Txn.application_id() == Int(0), self.on_create()],
            [Txn.on_completion() == OnComplete.NoOp, self.on_call()],
            [
                Or(
                    Txn.on_completion() == OnComplete.DeleteApplication,
                    Txn.on_completion() == OnComplete.OptIn,
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

    def clear_program(self):
        return Approve()


if __name__ == '__main__':
    contract = StakingContract()
    with open("staking_approval.teal", "w") as f:
        compiled = compileTeal(contract.approval_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)

    with open("staking_clear_state.teal", "w") as f:
        compiled = compileTeal(contract.clear_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)