import os

import dotenv

from account import Account
from swap.operations import create_validator_app, delete_validator_app, create_algoverse_token
from swap.utils import get_algod_client


def main():
    dotenv.load_dotenv('.env')

    client = get_algod_client(os.environ.get('ALGOD_URL'), os.environ.get('ALGOD_TOKEN'))

    creator = Account(os.environ.get('CREATOR_PK'))

    print(f"Creator address: {creator.get_address()}")

    app_id = create_validator_app(client, creator)
    print(f"App ID: {app_id}")
    # app_id = int(os.environ.get('VALIDATOR_APP_ID'))
    # delete_validator_app(client, creator, app_id)
    # asset_id = create_algoverse_token(client, creator)
    # print(asset_id)


if __name__ == '__main__':
    dotenv.load_dotenv('.env')
    main()
