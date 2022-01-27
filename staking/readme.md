# Bid Contract

Bid contract has following 5 methods: 

[on_create()](#on_create)

[on_setup()](#on_setup)

[on_set_timelock()](#on_set_timelock)

[on_stake()](#on_stake)

[on_withdraw()](#on_withdraw)

[on_claim()](#on_claim)

[on_delete()](#on_delete)

[on_update()](#on_update)


## on_create()
Creating staking application

* Applications: token app id, which burning staking asset
* Assets: our token id

While creating application, token app id, our token id is saving on global state.
After create application, the app creator should charge min balance(0.1 Algo) and opt app in our token min balance with transaction fee


## on_setup()
Opt app into our asset

Sender must be app creator

### Single transaction: App call transaction

* Application call transaction
  * Assets: [asset_id]

### Inner transaction: 
Opt app into asset

## on_set_timelock()
Set timelock for period to lock time

Sender must be app creator

### Single transaction:  App call transaction

* App call transaction
  * Args: time to lock

## on_stake()
Stake our token

### Group transaction: [Token app call transaction, Staking app call transaction]

* Token app call transaction
  * Args: [b"transfer", amount]
  * index: token app id
  * Fee >= 3 * 1000

*  Staking app call transaction
  * Args: [token amount]


## on_withdraw()
Withdraw staking tokens

### Group transaction: [Token app call transaction, Staking app call transaction]

* Token app call transaction
  * Args: [b"transfer", amount]
  * index: token app id
  * Fee >= 3 * 1000

*  Staking app call transaction
  * Args: [token amount]


## on_claim()
Claim reward based on staking token amount
The request time to claim should be later than locked time.

### Single transaction: App call transaction

### Inner transaction: 
Sending reward payment


## on_delete(), on_update()
Delete and Update application

Sender must be app creator.
Remaining balance will be sent to the creator address



