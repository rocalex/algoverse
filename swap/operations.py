import base64
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient

from account import Account
from swap.contracts import PoolLogicSig, SwapContract
from utils import fully_compile_contract, get_app_local_state, get_asset_info, wait_for_transaction


class SwapApp:
    def __init__(self, client: AlgodClient, creator: Account):
        self.algod_client = client
        self.app_id = 0
        self.creator = creator

    def get_contracts(self):
        app = SwapContract()
        approval_program = fully_compile_contract(
            self.algod_client, app.approval_program())
        clear_state_program = fully_compile_contract(
            self.algod_client, app.clear_state_program())
        return approval_program, clear_state_program

    def compile_smart_signature(self, source_code):
        compile_response = self.algod_client.compile(source_code)
        return compile_response['result'], compile_response['hash']

    def get_local_state(self, sender_address: str):
        return get_app_local_state(self.algod_client, self.app_id, sender_address)

    def create_dummy_asset(self):
        txn = transaction.AssetConfigTxn(
            sender=self.creator.get_address(),
            sp=self.algod_client.suggested_params(),
            total=1_000_000,
            decimals=2,
            asset_name="Algoverse Token",
            unit_name="AVT",
            default_frozen=False,
            strict_empty_address_check=False,
        )
        signed_txn = txn.sign(self.creator.get_private_key())

        self.algod_client.send_transaction(signed_txn)

        response = wait_for_transaction(
            self.algod_client, signed_txn.get_txid())
        assert response.asset_index is not None and response.asset_index > 0
        return response.asset_index

    def destroy_dummy_asset(self, token_id):
        txn = transaction.AssetDestroyTxn(
            sender=self.creator.get_address(),
            sp=self.algod_client.suggested_params(),
            index=token_id
        )
        signed_txn = txn.sign(self.creator.get_private_key())

        self.algod_client.send_transaction(signed_txn)

        wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def create_app(self):
        approval, clear = self.get_contracts()

        global_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)
        local_schema = transaction.StateSchema(num_uints=16, num_byte_slices=0)

        txn = transaction.ApplicationCreateTxn(
            sender=self.creator.get_address(),
            on_complete=transaction.OnComplete.NoOpOC,
            approval_program=approval,
            clear_program=clear,
            local_schema=local_schema,
            global_schema=global_schema,
            sp=self.algod_client.suggested_params(),
            app_args=[b"create"]
        )
        signed_txn = txn.sign(self.creator.get_private_key())

        self.algod_client.send_transaction(signed_txn)

        response = wait_for_transaction(
            self.algod_client, signed_txn.get_txid())
        assert response.application_index is not None and response.application_index > 0
        self.app_id = response.application_index

    def opt_in_app(self, pooler: Account):
        txn = transaction.ApplicationOptInTxn(
            sender=pooler.get_address(),
            index=self.app_id,
            sp=self.algod_client.suggested_params()
        )
        signed_txn = txn.sign(pooler.get_private_key())
        self.algod_client.send_transaction(signed_txn)

        wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def delete_app(self):
        txn = transaction.ApplicationDeleteTxn(
            sender=self.creator.get_address(),
            index=self.app_id,
            sp=self.algod_client.suggested_params()
        )
        signed_txn = txn.sign(self.creator.get_private_key())
        self.algod_client.send_transaction(signed_txn)

        wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def create_pool(self, asset1_id: int, asset2_id: int):
        pool_contract = PoolLogicSig(asset1_id, asset2_id, self.app_id)
        stateless_program_teal = pool_contract.compile()
        compile_response = self.algod_client.compile(stateless_program_teal)
        return compile_response['result'], compile_response['hash']

    def bootstrap_pool(self, pooler: Account, pool_address: str, pool_program: str, asset1_id: int, asset2_id: int):
        if asset1_id < asset2_id:
            t = asset2_id
            asset2_id = asset1_id
            asset1_id = t
        if asset2_id == 0:
            assets = [asset1_id]
            asset1_info = get_asset_info(self.algod_client, asset1_id)
            asset1_unit_name = asset1_info.get('params').get('unit-name')
            assert asset1_unit_name is not None
            asset_name = f"Algoverse Pool {asset1_unit_name}-ALGO"
        else:
            assets = [asset1_id, asset2_id]
            asset1_info = get_asset_info(self.algod_client, asset1_id)
            asset1_unit_name = asset1_info.get('params').get('unit-name')
            assert asset1_unit_name is not None
            asset2_info = get_asset_info(self.algod_client, asset2_id)
            asset2_unit_name = asset2_info.get('params').get('unit-name')
            assert asset2_unit_name is not None
            asset_name = f"Algoverse Pool {asset1_unit_name}-{asset2_unit_name}"

        encoded_program = pool_program.encode()
        program = base64.decodebytes(encoded_program)
        lsig = transaction.LogicSig(program)

        params = self.algod_client.suggested_params()
        params.flat_fee = True
        params.fee = 1_000

        payment_txn = transaction.PaymentTxn(
            sender=pooler.get_address(),
            receiver=pool_address,
            amt=960_000,
            sp=params,
        )
        app_call_txn = transaction.ApplicationCallTxn(
            sender=pool_address,
            index=self.app_id,
            on_complete=transaction.OnComplete.OptInOC,
            app_args=[
                b"bootstrap",
                asset1_id.to_bytes(8, 'big'),
                asset2_id.to_bytes(8, 'big')
            ],
            foreign_assets=assets,
            sp=params
        )
        asset_config_txn = transaction.AssetConfigTxn(
            sender=pool_address,
            sp=params,
            asset_name=asset_name,
            unit_name="AV1POOL",
            url="https://algoverse.exchange",
            total=18446744073709551615,
            decimals=6,
            strict_empty_address_check=False
        )
        asset_optin_txn = transaction.AssetOptInTxn(
            sender=pool_address,
            sp=params,
            index=asset1_id
        )

        transaction.assign_group_id(
            [payment_txn, app_call_txn, asset_config_txn, asset_optin_txn])

        signed_payment_txn = payment_txn.sign(pooler.get_private_key())
        signed_app_call_txn = transaction.LogicSigTransaction(
            app_call_txn, lsig)
        signed_asset_config_txn = transaction.LogicSigTransaction(
            asset_config_txn, lsig)
        signed_asset_optin_txn = transaction.LogicSigTransaction(
            asset_optin_txn, lsig)

        self.algod_client.send_transactions(
            [signed_payment_txn, signed_app_call_txn,
                signed_asset_config_txn, signed_asset_optin_txn]
        )

        wait_for_transaction(self.algod_client, signed_payment_txn.get_txid())

    def swap(self, swapper: Account, pool_address: str, pool_program: str,
             sell_asset_id: int, sell_asset_amount: int,
             buy_asset_id: int, buy_asset_amount: int):
        encoded_program = pool_program.encode()
        program = base64.decodebytes(encoded_program)
        lsig = transaction.LogicSig(program)

        params = self.algod_client.suggested_params()
        params.flat_fee = True
        params.fee = 1_000

        payment_txn = transaction.PaymentTxn(
            sender=swapper.get_address(),
            receiver=pool_address,
            amt=2_000,
            sp=params,
        )
        app_call_txn = transaction.ApplicationCallTxn(
            sender=pool_address,
            index=self.app_id,
            sp=params,
            on_complete=transaction.OnComplete.NoOpOC,
            accounts=[swapper.get_address()],
            app_args=[
                b"swap",
                b"fi"  # or b"fo"
            ]
        )
        if sell_asset_id == 0:
            sell_txn = transaction.PaymentTxn(
                sender=swapper.get_address(),
                receiver=pool_address,
                amt=sell_asset_amount,
                sp=params
            )
        else:
            sell_txn = transaction.AssetTransferTxn(
                sender=swapper.get_address(),
                receiver=pool_address,
                index=sell_asset_id,
                amt=sell_asset_amount,
                sp=params
            )

        if buy_asset_id == 0:
            buy_txn = transaction.PaymentTxn(
                sender=pool_address,
                receiver=swapper.get_address(),
                amt=sell_asset_amount,
                sp=params
            )
        else:
            buy_txn = transaction.AssetTransferTxn(
                sender=pool_address,
                receiver=swapper.get_address(),
                index=buy_asset_id,
                amt=buy_asset_amount,
                sp=params
            )

        signed_payment_txn = payment_txn.sign(swapper.get_private_key())
        signed_app_call_txn = transaction.LogicSigTransaction(
            app_call_txn, lsig)
        signed_sell_txn = sell_txn.sign(swapper.get_private_key())
        signed_buy_txn = transaction.LogicSigTransaction(buy_txn, lsig)

        transaction.assign_group_id(
            [payment_txn, app_call_txn, sell_txn, buy_txn]
        )

        self.algod_client.send_transactions(
            [signed_payment_txn, signed_app_call_txn,
                signed_sell_txn, signed_buy_txn]
        )

        wait_for_transaction(self.algod_client, signed_payment_txn.get_txid())
