from pyteal import *


class TradeContract:
    def on_create(self):
        return Seq(
            Approve()
        )

    def on_call(self):
        return Cond(

        )

    def approval_program(self):
        program = Cond(
            [Txn.application_id() == Int(0), self.on_create()],
            [Txn.on_completion() == OnComplete.NoOp, self.on_call()],
            [
                Txn.on_completion() == OnComplete.DeleteApplication,
                Approve(),
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

    def clear_program(self):
        return Approve()


if __name__ == '__main__':
    contract = TradeContract()
    with open("trade_approval.teal", "w") as f:
        compiled = compileTeal(contract.approval_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)

    with open("trade_clear_state.teal", "w") as f:
        compiled = compileTeal(contract.clear_program(),
                               mode=Mode.Application, version=5)
        f.write(compiled)
