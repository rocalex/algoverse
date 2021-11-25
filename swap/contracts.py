from pyteal import *


class SwapContract:
    def on_create(self):
        return Seq(
            Approve()
        )

    def on_bootstrap(self):
        asset1_id = ScratchVar(TealType.uint64, 101)
        asset2_id = ScratchVar(TealType.uint64, 102)
        asset1_unit_name = AssetParam.unitName(asset1_id.load())
        asset2_unit_name = AssetParam.unitName(asset2_id.load())
        pool_asset_name = Gtxn[2].config_asset_name()
        return Seq(
            asset1_id.store(Btoi(Txn.application_args[1])),
            asset2_id.store(Btoi(Txn.application_args[2])),
            App.localPut(Int(0), Bytes("a1"), asset1_id.load()),
            App.localPut(Int(0), Bytes("a2"), asset2_id.load()),
            asset1_unit_name,
            Assert(asset1_unit_name.hasValue()),
            If(asset2_id.load() == Int(0)).Then(Seq(
                Return(
                    Substring(pool_asset_name, Int(15), Len(pool_asset_name)) == Concat(
                        asset1_unit_name.value(), Bytes("-"), Bytes("ALGO"))
                )
            )),
            asset2_unit_name,
            Assert(asset2_unit_name.hasValue()),
            Return(Int(1))
        )

    def on_optin(self):
        on_optin_method = Txn.application_args[0]
        return Cond(
            [on_optin_method == Bytes("bootstrap"), self.on_bootstrap()]
        )

    def on_swap_mint_burn(self):
        return Seq(
            Approve()
        )

    def on_call(self):
        on_call_method = Txn.application_args[0]
        return Cond(
            [
                Or(
                    on_call_method == Bytes("swap"),
                    on_call_method == Bytes("mint"),
                    on_call_method == Bytes("burn"),
                ),
                self.on_swap_mint_burn()
            ]
        )

    def approval_program(self):
        program = Cond(
            [Txn.application_id() == Int(0), self.on_create()],
            [
                Or(
                    Txn.on_completion() == OnComplete.UpdateApplication,
                    Txn.on_completion() == OnComplete.CloseOut
                ),
                Reject()
            ],
            [
                Txn.on_completion() == OnComplete.DeleteApplication,
                Approve()
            ],
            [
                And(
                    Txn.on_completion() == OnComplete.OptIn,
                    Txn.application_args.length() == Int(0)
                ),
                Approve()
            ],
            [
                Txn.on_completion() == OnComplete.OptIn,
                self.on_optin()
            ],
            [
                Txn.on_completion() == OnComplete.NoOp,
                self.on_call()
            ]
        )
        return program

    def clear_state_program(self):
        return Approve()


class PoolLogicSig:
    def __init__(self, asset1_id, asset2_id, app_id):
        self.asset1_id = asset1_id
        self.asset2_id = asset2_id
        self.app_id = app_id

    def compile(self):
        fee_total = ScratchVar(TealType.uint64, 1)
        program = Seq(
            # ensure ASSET_ID_1 > ASSET_ID_2
            Assert(Int(self.asset1_id) > Int(self.asset2_id)),
            Assert(Txn.close_remainder_to() == Global.zero_address()),
            Assert(Txn.asset_close_to() == Global.zero_address()),
            Assert(Txn.rekey_to() == Global.zero_address()),
            Assert(Global.group_size() > Int(1)),

            # ensure gtxn 1 is ApplicationCall to Validator App
            Assert(Gtxn[1].sender() == Txn.sender()),
            Assert(Gtxn[1].type_enum() == TxnType.ApplicationCall),
            Assert(Gtxn[1].application_id() == Int(self.app_id)),
            # Bootstrap?
            If(
                And(
                    Gtxn[1].on_completion() == OnComplete.OptIn,
                    Gtxn[1].application_args.length() == Int(3),
                    Gtxn[1].application_args[0] == Bytes("bootstrap")
                )
            ).Then(Seq(
                # Ensure group size is correct 4 or 5:
                # 0: Pay Fees (signed by Pooler)
                # 1: Call App (signed by Pool LogicSig)
                # 2: Asset Creation (signed by Pool LogicSig)
                # 3: Asset Optin (signed by Pool LogicSig)
                # If asset 2 is an ASA:
                # (4): Asset Optin (signed by Pool LogicSig)
                Assert(Global.group_size() == If(
                    Int(self.asset2_id) == Int(0), Int(4), Int(5))),
                Assert(
                    And(
                        Btoi(Gtxn[1].application_args[1]) == Int(
                            self.asset1_id),
                        Btoi(Gtxn[1].application_args[2]) == Int(
                            self.asset2_id),
                    )
                ),

                # ensure sender (signer) of AssetConfig tx is same as sender of app call
                Assert(Gtxn[2].sender() == Txn.sender()),
                # ensure gtxn 2 is type AssetConfig
                Assert(Gtxn[2].type_enum() == TxnType.AssetConfig),
                # ensure a new asset is being created
                # Assert(Gtxn[2].config_asset() == Int(0)),
                # ensure asset total amount is max int
                Assert(Gtxn[2].config_asset_total() == ~Int(0)),
                # ensure decimals is 6
                Assert(Gtxn[2].config_asset_decimals() == Int(6)),
                # ensure default frozen is false
                Assert(Gtxn[2].config_asset_default_frozen() == Int(0)),
                # ensure unit name is 'AV1POOL'
                Assert(Gtxn[2].config_asset_unit_name() == Bytes("AV1POOL")),
                # ensure asset name begins with 'Tinyman Pool '
                # the Validator app ensures the name ends with "{asset1_unit_name}-{asset2_unit_name}"
                Assert(Substring(Gtxn[2].config_asset_name(), Int(
                    0), Int(15)) == Bytes("Algoverse Pool ")),
                # ensure asset url is 'https://algoverse.com'
                Assert(Gtxn[2].config_asset_url() ==
                       Bytes("https://algoverse.exchange")),
                # ensure no asset manager address is set
                Assert(Gtxn[2].config_asset_manager()
                       == Global.zero_address()),
                # ensure no asset reserve address is set
                Assert(Gtxn[2].config_asset_reserve()
                       == Global.zero_address()),
                # ensure no asset freeze address is set
                Assert(Gtxn[2].config_asset_freeze() == Global.zero_address()),
                # ensure no asset clawback address is set
                Assert(Gtxn[2].config_asset_clawback()
                       == Global.zero_address()),

                # Asset 1 optin
                # Ensure optin txn is signed by the same sig as this txn
                Assert(Gtxn[3].sender() == Txn.sender()),
                # ensure txn type is AssetTransfer
                Assert(Gtxn[3].type_enum() == TxnType.AssetTransfer),
                # ensure the asset id is the same as asset 1
                Assert(Gtxn[3].xfer_asset() == Int(self.asset1_id)),
                # ensure the receiver is the sender
                Assert(Gtxn[3].asset_receiver() == Txn.sender()),
                # ensure the amount is 0 for Optin
                Assert(Gtxn[3].asset_amount() == Int(0)),
                # if asset 2 is not 0 (Algo), it needs an optin
                If(Int(self.asset2_id) != Int(0)).Then(Seq(
                    # verify 5th txn is asset 2 optin txn
                    Assert(Gtxn[4].sender() == Txn.sender()),
                    Assert(Gtxn[4].type_enum() == TxnType.AssetTransfer),
                    # ensure the asset id is the same as asset 2
                    Assert(Gtxn[4].xfer_asset() == Int(self.asset2_id)),
                    # ensure the receiver is the sender
                    Assert(Gtxn[4].asset_receiver() == Txn.sender()),
                    # ensure the amount is 0 for Optin
                    Assert(Gtxn[4].asset_amount() == Int(0)),

                    fee_total.store(
                        Gtxn[1].fee() + Gtxn[2].fee() + Gtxn[3].fee() + Gtxn[4].fee()),

                    # ensure gtxn 0 amount covers all fees
                    # ensure Pool is not paying the fee
                    Assert(Gtxn[0].sender() != Txn.sender()),
                    # ensure Pool is receiving the fee
                    Assert(Gtxn[0].receiver() == Txn.sender()),
                    Return(Gtxn[0].amount() >= fee_total.load())
                )),

                fee_total.store(Gtxn[1].fee() + Gtxn[2].fee() + Gtxn[3].fee()),

                # ensure gtxn 0 amount covers all fees
                # ensure Pool is not paying the fee
                Assert(Gtxn[0].sender() != Txn.sender()),
                # ensure Pool is receiving the fee
                Assert(Gtxn[0].receiver() == Txn.sender()),
                Return(Gtxn[0].amount() >= fee_total.load())
            )),

            # The remaining operations (Mint/Burn/Swap/Redeem/Fees) must all have OnCompletion=NoOp
            Assert(Gtxn[1].on_completion() == OnComplete.NoOp),

            # Swap?
            If(
                And(
                    Gtxn[1].application_args.length() == Int(2),
                    Gtxn[1].application_args[0] == Bytes("swap")
                )
            ).Then(Seq(
                # TODO: swap
                fee_total.store(Gtxn[1].fee() + Gtxn[3].fee()),

                # ensure gtxn 0 amount covers all fees
                # ensure Pool is not paying the fee
                Assert(Gtxn[0].sender() != Txn.sender()),
                # ensure Pool is receiving the fee
                Assert(Gtxn[0].receiver() == Txn.sender()),
                Return(Gtxn[0].amount() >= fee_total.load())
            )),

            # The remaining operations (Mint/Burn/Redeem/Fees) must all have NumAppArgs=1
            Assert(Gtxn[1].application_args.length() == Int(1)),

            # Mint?
            # Mint Checks:
            #
            # # ensure group size is 5
            # global GroupSize == 5

            # 	# ensure transaction fees are covered by txn 0
            # 	# ensure Pool is not paying the fee
            # 	gtxn 0 Sender != txn Sender
            # 	gtxn 0 Receiver == txn Sender
            # 	gtxn 0 Amount >= (gtxn 1 Fee + gtxn 4 Fee)

            # 	# verify the receiver of the liquidity token asset is the one whose local state is updated
            # 	gtxna 1 Accounts 1 != txn Sender
            # 	gtxna 1 Accounts 1 == gtxn 4 AssetReceiver

            # 	# from Pooler to Pool asset 1
            # 	gtxn 2 Sender (Pooler) != txn Sender (Pool)
            # 	gtxn 2 AssetReceiver (Pool) == txn Sender (Pool)
            # 	gtxn 2 Sender (Pooler) == gtxn 3 Sender (Pooler)

            # 	# from Pooler to Pool asset 2
            # 	txn Sender (Pool) == (gtxn 3 AssetReceiver or gtxn 3 Receiver) (Pool)


            # 	# from Pool to Pooler liquidity token
            # 	gtxn 4 AssetReceiver (Pooler) == gtxn 2 Sender (Poooler)
            # 	gtxn 4 Sender (Pool) == txn Sender (Pool)
            If(Gtxn[1].application_args[0] == Bytes("mint")).Then(Seq(
                # ensure group size is 5:
                # 0: Pay Fees (signed by Pooler)
                # 1: Call App (signed by Pool LogicSig)
                # 2: Asset Transfer/Pay (signed by Pooler)
                # 3: Asset Transfer/Pay (signed by Pooler)
                # 4: Asset Transfer/Pay (signed by Pool LogicSig)
                Assert(Global.group_size() == Int(5)),

                # verify the receiver of the asset is the one whose local state is updated
                Assert(Gtxn[1].accounts[1] != Txn.sender()),
                Assert(Gtxn[1].accounts[1] == Gtxn[4].asset_receiver()),

                # verify txn 2 is AssetTransfer from Pooler to Pool
                Assert(Gtxn[2].sender() != Txn.sender()),
                Assert(Gtxn[2].asset_receiver() == Txn.sender()),
                Assert(Gtxn[3].sender() == Gtxn[2].sender()),

                # verify txn 3 is AssetTransfer from Pooler to Pool
                Assert(
                    If(Gtxn[3].type_enum() == TxnType.Payment,
                       Gtxn[3].receiver(), Gtxn[3].asset_receiver()) == Txn.sender()
                ),
                # verify txn 4 is AssetTransfer from Pool to Pooler
                Assert(Gtxn[4].sender() == Txn.sender()),
                Assert(Gtxn[4].asset_receiver() == Gtxn[2].sender()),

                fee_total.store(Gtxn[1].fee() + Gtxn[4].fee()),
                # ensure gtxn 0 amount covers all fees
                # ensure Pool is not paying the fee
                Assert(Gtxn[0].sender() != Txn.sender()),
                # ensure Pool is receiving the fee
                Assert(Gtxn[0].receiver() == Txn.sender()),
                Return(Gtxn[0].amount() == fee_total.load())
            )),

            # Burn?
            If(Gtxn[1].application_args[0] == Bytes("burn")).Then(Seq(
                # TODO: burn
                fee_total.store(Gtxn[1].fee() + Gtxn[2].fee() + Gtxn[3].fee()),
                # ensure gtxn 0 amount covers all fees
                # ensure Pool is not paying the fee
                Assert(Gtxn[0].sender() != Txn.sender()),
                # ensure Pool is receiving the fee
                Assert(Gtxn[0].receiver() == Txn.sender()),
                Return(Gtxn[0].amount() >= fee_total.load())
            )),

            # Redeem?
            If(Gtxn[1].application_args[0] == Bytes("redeem")).Then(Seq(
                # TODO: redeem
                fee_total.store(Gtxn[1].fee() + Gtxn[2].fee()),
                # ensure gtxn 0 amount covers all fees
                # ensure Pool is not paying the fee
                Assert(Gtxn[0].sender() != Txn.sender()),
                # ensure Pool is receiving the fee
                Assert(Gtxn[0].receiver() == Txn.sender()),
                Return(Gtxn[0].amount() >= fee_total.load())
            )),

            # Fees?
            If(Gtxn[1].application_args[0] == Bytes("fees")).Then(Seq(
                # ensure group size is 3:
                # 0: Pay Fees (signed by User)
                # 1: Call App (signed by Pool LogicSig)
                # 2: Asset Transfer/Pay (signed by Pool LogicSig)
                Assert(Global.group_size() == Int(3)),
                fee_total.store(Gtxn[1].fee() + Gtxn[2].fee()),
                # ensure gtxn 0 amount covers all fees
                # ensure Pool is not paying the fee
                Assert(Gtxn[0].sender() != Txn.sender()),
                # ensure Pool is receiving the fee
                Assert(Gtxn[0].receiver() == Txn.sender()),
                Return(Gtxn[0].amount() >= fee_total.load())
            )),
            Err()
        )
        return compileTeal(program, Mode.Signature, version=5)


if __name__ == '__main__':
    contract = SwapContract()
    pool_contract = PoolLogicSig(1, 0, 28)

    with open("swap_approval.teal", "w") as f:
        compiled = compileTeal(contract.approval_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)

    with open("swap_clear_state.teal", "w") as f:
        compiled = compileTeal(
            contract.clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("pool_logicsig.teal", "w") as f:
        compiled = pool_contract.compile()
        f.write(compiled)
