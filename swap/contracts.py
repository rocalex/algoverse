from json import load
from pyteal import *

def approval_program():
    
    # for global state
    staking_address_key = Bytes("SA_ADDR")
    team_wallet_address_key = Bytes("TW_ADDR")
    
    # for local state
    offer_address_key = Bytes("O_ADDR")
    offering_token_id_key = Bytes("O_TKID")
    offering_amount_key = Bytes("O_AMT")
    accepting_token_id_key = Bytes("A_TKID")
    accepting_amount_key = Bytes("A_AMT")
    
    
    @Subroutine(TealType.uint64)
    def is_open(offer: Expr, swap_index: Expr) -> Expr:
        return If(And(
            App.localGet(swap_index, offering_token_id_key),
            App.localGet(swap_index, offering_amount_key),
            App.localGet(swap_index, accepting_token_id_key),
            App.localGet(swap_index, accepting_amount_key),
        )).Then(
            Return(App.localGet(swap_index, offer_address_key) == offer)
        ).Else(
            Return(Int(0))
        )
        
    @Subroutine(TealType.none)
    def handle_swap(offer: Expr, swap_index: Expr, o_tkid: Expr, o_amt: Expr, a_tkid: Expr, a_amt: Expr) -> Expr:
        return Seq(
            If(is_open(offer, swap_index)).Then(
                #return asset
                send_token_to(offer, App.localGet(swap_index, offering_token_id_key), App.localGet(swap_index, offering_amount_key)),
            ),
            
            App.localPut(swap_index, offer_address_key, offer),
            App.localPut(swap_index, offering_token_id_key, o_tkid),
            App.localPut(swap_index, offering_amount_key, o_amt),
            App.localPut(swap_index, accepting_token_id_key, a_tkid),
            App.localPut(swap_index, accepting_amount_key, a_amt),
        )
        
    @Subroutine(TealType.none)
    def handle_cancel_swap(offer: Expr, swap_index: Expr) -> Expr:
        return Seq(
            # return asset
            send_token_to(offer, App.localGet(swap_index, offering_token_id_key), App.localGet(swap_index, offering_amount_key)),
            
            App.localPut(swap_index, offering_token_id_key, Int(0)),
            App.localPut(swap_index, offering_amount_key, Int(0)),
            App.localPut(swap_index, accepting_token_id_key, Int(0)),
            App.localPut(swap_index, accepting_amount_key, Int(0)),
        )
        
    @Subroutine(TealType.none)
    def handle_accept(offer: Expr, bidder: Expr, swap_index: Expr) -> Expr:
        return Seq(
            # send offering asset to bidder
            send_token_to(bidder, App.localGet(swap_index, offering_token_id_key), App.localGet(swap_index, offering_amount_key)),
            
            # send accepting asset to offer
            send_token_to(offer, App.localGet(swap_index, accepting_token_id_key), App.localGet(swap_index, accepting_amount_key)),
            
            App.localPut(swap_index, offering_token_id_key, Int(0)),
            App.localPut(swap_index, offering_amount_key, Int(0)),
            App.localPut(swap_index, accepting_token_id_key, Int(0)),
            App.localPut(swap_index, accepting_amount_key, Int(0)),
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
            )
        ),
        App.globalPut(staking_address_key, Txn.accounts[1]),
        App.globalPut(team_wallet_address_key, Txn.accounts[2]),
        Approve(),
    )

    on_setup_txn_index = Txn.group_index() - Int(1)
    i = ScratchVar(TealType.uint64)
    on_setup = Seq(
        # opt into NFT asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        Assert(
            And(
                # payment to opt into asset
                Gtxn[on_setup_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_setup_txn_index].sender() == Txn.sender(),
                Gtxn[on_setup_txn_index].receiver() == Global.current_application_address(),
                Txn.assets.length() > Int(0),
                
                Gtxn[on_setup_txn_index].amount() >= Txn.assets.length() * (Global.min_txn_fee() + Int(100000)),
            )
        ),
        For(i.store(Int(0)), i.load() < Txn.assets.length(), i.store(i.load() + Int(1))).Do(
            optin_asset(Txn.assets[i.load()]),
        ),
        Approve(),
    )

    on_swap_pay_txn_index = Txn.group_index() - Int(2)
    on_swap_asset_txn_index = Txn.group_index() - Int(1)
    on_swap = Seq(
        # opt into NFT asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        Assert(
            And(
                # asset transfer
                Gtxn[on_swap_asset_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_swap_asset_txn_index].asset_receiver() == Global.current_application_address(),
                Gtxn[on_swap_asset_txn_index].xfer_asset() > Int(0),
                Gtxn[on_swap_asset_txn_index].asset_amount() > Int(0),
                
                # swap_index
                Txn.accounts.length() ==  Int(1),
                
                # may include old asset to return back, should add payment txn for fee in group txn
                Txn.assets.length() >= Int(2),
                Txn.assets[0] > Int(0), # offering
                Txn.assets[1] > Int(0), # accepting
                
                # accepting asset amount
                Txn.application_args.length() == Int(2),
                Btoi(Txn.application_args[1]) > Int(0),
            )
        ),
        If (is_open(Txn.sender(), Txn.accounts[1])).Then(
            If(Not(And(
                # the fee payment txn is before the app call
                Gtxn[on_swap_pay_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_swap_pay_txn_index].sender() == Txn.sender(),
                Gtxn[on_swap_pay_txn_index].receiver() == Global.current_application_address(),
                Gtxn[on_swap_pay_txn_index].amount() == Int(1000),
            ))).Then(
                Reject()
            )
        ),
        handle_swap(Txn.sender(), Txn.accounts[1], Txn.assets[0], Gtxn[on_swap_asset_txn_index].asset_amount(), 
                    Txn.assets[1], Btoi(Txn.application_args[1])),
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
                Gtxn[on_cancel_pay_txn_index].amount() == Int(1000),
                
                # swap_index
                Txn.accounts.length() == Int(1),
                is_open(Txn.sender(), Txn.accounts[1]),
                
                Txn.assets.length() == Int(1),
                Txn.assets[0] == App.localGet(Txn.accounts[1], offering_token_id_key),
            )
        ),
        handle_cancel_swap(Txn.sender(), Txn.accounts[1]),
        Approve(),
    )
    
    on_accept_pay_txn_index = Txn.group_index() - Int(2)
    on_accept_asset_txn_index = Txn.group_index() - Int(1)
    on_accept = Seq(
        Assert(
            And(
                # payment to opt into asset and txn
                Gtxn[on_accept_pay_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_accept_pay_txn_index].sender() == Txn.sender(), #accepter
                Gtxn[on_accept_pay_txn_index].amount() >= Int(2) * Global.min_txn_fee(),
                Gtxn[on_accept_pay_txn_index].receiver() == Global.current_application_address(),
                
                # the accept asset transfer is before the app call
                Gtxn[on_accept_asset_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_accept_asset_txn_index].asset_receiver() == Global.current_application_address(),
                Gtxn[on_accept_asset_txn_index].asset_amount() > Int(0),
                
                # offer, swap_index(rekeyed_address), distribution app address and team wallet address
                Txn.accounts.length() == Int(4),
                Txn.accounts[3] == App.globalGet(staking_address_key),
                Txn.accounts[4] == App.globalGet(team_wallet_address_key),
                
                is_open(Txn.accounts[1], Txn.accounts[2]),
                
                # include token_ids
                Txn.assets.length() == Int(2),
                Txn.assets[0] == App.localGet(Txn.accounts[2], offering_token_id_key),
                Txn.assets[1] == App.localGet(Txn.accounts[2], accepting_token_id_key),
                
                # should include offering asset amount
                Txn.application_args.length() == Int(2),
                Btoi(Txn.application_args[1]) == App.localGet(Txn.accounts[2], offering_amount_key),
                
                # should be equal asset transaction amount with the accepting amount
                Gtxn[on_accept_asset_txn_index].asset_amount() == App.localGet(Txn.accounts[2], accepting_amount_key),
            )
        ),
        handle_accept(Txn.accounts[1], Txn.sender(), Txn.accounts[2]),
        Approve(),
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("swap"), on_swap],
        [on_call_method == Bytes("cancel"), on_cancel],
        [on_call_method == Bytes("accept"), on_accept],
    )

    on_delete = Seq(
        # Assert(
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
    with open("swap_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("swap_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
