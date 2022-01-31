from pyteal import *

def approval_program():
    
    # global state
    token_id_key = Bytes("TK_ID")
    token_app_id_key = Bytes("TA")
    lock_time_key = Bytes("PTL")
    week_total_asset_amount_key = Bytes("WTTA") 
    distribution_algo_amount_key = Bytes("DAA") 
    
    # local state
    token_amount_key = Bytes("TA")
    last_claimed_time_key = Bytes("CDT")
    week_withdraw_amount = Bytes("WWA")
    week_stake_amount = Bytes("WSA")
    
    # 0.01% percent
    @Subroutine(TealType.uint64)
    def calculate_fraction(amount: Expr, percent: Expr):
        return WideRatio([amount, percent], [Int(10000)])
    
    @Subroutine(TealType.bytes)
    def get_app_address(appID: Expr) -> Expr:
        return Sha512_256(Concat(Bytes("appID") , Itob(appID)))
    
    @Subroutine(TealType.none)
    def send_tokens(receiver: Expr, amount: Expr):
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: Txn.assets[0],
            TxnField.asset_receiver: receiver,
            TxnField.asset_amount: amount,
        }),
        InnerTxnBuilder.Submit(),
    
    @Subroutine(TealType.none)
    def closeAccountTo(account: Expr) -> Expr:
        return If(Balance(Global.current_application_address()) != Int(0)).Then(
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.Payment,
                        TxnField.close_remainder_to: account,
                    }
                ),
                InnerTxnBuilder.Submit(),
            )
        )

    
    
    on_create = Seq(
        Assert(Txn.assets.length() == Int(1)),
            
        App.globalPut(token_id_key, Txn.assets[0]),
        App.globalPut(token_app_id_key, Txn.applications[1]),
        Approve()
    )
    
    on_setup = Seq(
        Assert(
            And(
                Global.creator_address() == Txn.sender(),
                App.globalGet(token_id_key) == Txn.assets[0],
            )
        ),
        
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: Txn.assets[0],
            TxnField.asset_receiver: Global.current_application_address(),
        }),
        InnerTxnBuilder.Submit(),
        
        # initialization of the lock time
        App.globalPut(lock_time_key, Global.latest_timestamp()),
        
        Approve()
    )

    on_set_timelock = Seq(
        Assert(
            And(
                Global.creator_address() == Txn.sender(),
                
                Txn.application_args.length() == Int(2),
            )
        ),
        
        # initialization of the lock time
        #App.globalPut(lock_time_key, Global.latest_timestamp()),
        App.globalPut(lock_time_key, Txn.application_args[1]),
        
        Approve()
    )
    
    old_token_amount = App.localGet(Txn.sender(), token_amount_key)
    requested_amount = Btoi(Txn.application_args[1])
    on_stake = Seq(
        Assert(
            And(
                Global.group_size() == Int(2),
                
                Gtxn[0].type_enum() == TxnType.ApplicationCall,
                Gtxn[0].application_args[0] == Bytes("transfer"),
                Gtxn[0].application_id() == App.globalGet(token_app_id_key),
                Gtxn[0].sender() == Txn.sender(),
                
                # fee includes two inner send txns from transfer call of token app
                Gtxn[0].fee() + Txn.fee() >= Int(4) * Global.min_txn_fee(),
                
                Txn.application_args.length() == Int(2),
                requested_amount > Int(0),
            )
        ),
        
        App.localPut(Txn.sender(), token_amount_key, calculate_fraction(requested_amount, Int(9980)) + old_token_amount),
        App.localPut(Txn.sender(), week_stake_amount, App.localGet(Txn.sender(), week_stake_amount) + 
                     calculate_fraction(requested_amount, Int(9980))),
        
        Approve()
    )
    
    old_token_amount = App.localGet(Txn.sender(), token_amount_key)
    requested_amount = Btoi(Txn.application_args[1])
    on_withdraw = Seq(
        Assert(
            And(
                Global.group_size() == Int(2),
                
                Gtxn[0].type_enum() == TxnType.ApplicationCall,
                Gtxn[0].application_args[0] == Bytes("transfer"),
                Gtxn[0].application_id() == App.globalGet(token_app_id_key),
                Gtxn[0].sender() == Txn.sender(),
                
                # fee includes two inner send txns from transfer call of token app
                Gtxn[0].fee() + Txn.fee() >= Int(4) * Global.min_txn_fee(),
                
                Txn.application_args.length() == Int(2),
                requested_amount > Int(0),
                requested_amount <= old_token_amount,
            )
        ),
        
        App.localPut(Txn.sender(), week_withdraw_amount, App.localGet(Txn.sender(), week_withdraw_amount) + requested_amount),
        App.localPut(Txn.sender(), token_amount_key, old_token_amount - requested_amount),
        
        Approve()
    )
    
    total_amount = AssetHolding.balance(Global.current_application_address(), Txn.assets[0])
    token_amount = App.localGet(Txn.sender(), token_amount_key)
    algo_amount = Balance(Global.current_application_address())
    last_claimed_date = App.localGet(Txn.sender(), last_claimed_time_key)
    on_claim = Seq(
        total_amount,
        Assert(
            And(
                App.globalGet(token_id_key) == Txn.assets[0],
                token_amount > Int(0),
                total_amount.hasValue(),
                
                # if once claimed for the current lock time, cannot claim more
                App.globalGet(lock_time_key) > last_claimed_date,
            )
        ),
        
        If(Global.latest_timestamp() >= App.globalGet(lock_time_key) + Int(86400) * Int(7)).Then(
            Seq(
                App.globalPut(distribution_algo_amount_key, algo_amount - Global.min_balance()),
                App.globalPut(week_total_asset_amount_key, total_amount.value()),
                App.globalPut(lock_time_key, Global.latest_timestamp()),
            )
        ),
        
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: Txn.sender(),
            TxnField.amount: WideRatio([token_amount - App.localGet(Txn.sender(), week_stake_amount), 
                                        App.globalGet(distribution_algo_amount_key)], 
                                       [App.globalGet(week_total_asset_amount_key)]) - Int(201_000)
        }),
        InnerTxnBuilder.Submit(),
        
        App.localPut(Txn.sender(), last_claimed_time_key, App.globalGet(lock_time_key)),
        App.localPut(Txn.sender(), week_withdraw_amount, Int(0)),
        App.localPut(Txn.sender(), week_stake_amount, Int(0)),
        
        Approve()
    )
    
    
    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("set_timelock"), on_set_timelock],
        [on_call_method == Bytes("stake"), on_stake],
        [on_call_method == Bytes("withdraw"), on_withdraw],
        [on_call_method == Bytes("claim"), on_claim]
    )
    
    on_delete = Seq(
        # Assert(
        #     Txn.sender() == Global.creator_address(),
        # ),
        # closeAccountTo(Global.creator_address()),
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
            Or(
                Txn.on_completion() == OnComplete.DeleteApplication,
                Txn.on_completion() == OnComplete.ClearState,    
            ),            
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
            Txn.on_completion() == OnComplete.CloseOut,
            Reject(),
        ],
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("staking_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("staking_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
