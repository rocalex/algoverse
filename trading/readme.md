# Trade Contract

Trade contract has following 6 methods: 

[on_create()](#on_create)

[on_setup()](#on_setup)

[on_trade()](#on_trade)

[on_cancel()](#on_cancel)

[on_accept()](#on_accept)

[on_close()](#on_close)


## on_create()
Creating trade application

* Applications: store app id, which storing bought and sold amount 
* Accounts: staking app address and team wallet address

While creating application, store app id, staking app address and team wallet address is saving on global state.
After create application, the app creator should charge min balance(0.1 Algo) of application


## on_setup()
Opt app into providing asset

### Group transaction: 
[Funding payment transaction, App call transaction]

* Funding payment transaction
  * Funding amount: for opt app into asset and inner optin transaction fee

* Application call transaction
  * Assets: [asset_id]

### Inner transaction: 
Opt app into asset

## on_trade()
Place trade to sell asset.

Group transaction: 
[Funding asset transaction, App call transaction]

* Funding asset transaction
  * Asset amount: The amount seller wants to sell

* Application call transaction
  * App args: Price is seller wants to sell assets for
  * Accounts: Rekeyed address for trade index to save trade information on local state

## on_cancel()
Cancel opening trade

### Single transaction: App call transaction

* App call transaction
  * accounts: [trade_index]
  * Fee >= 2_000

### Inner transaction: Asset return transaction


## on_accept()
Accept on trade, Any user can be the buyer to accept the trade if the price is ok.

Group transaction: 
[Payment transaction, App call transaction, Store app call transaction]

* Payment transaction
  * Amount: Price + 4 * 1_000
 
* App call transaction
  * Application args: [trade asset amount] (trade asset amount is providing for confirmation same with the trade amount)
  * Assets: [asset_id] (Need to be provided for inner transaction)
  * Accounts: [tradeder address, trade index(rekeyed address), staking app address, team wallet address]
    
    * trade_index: For select a trade which seller wants to accept
    * tradeder address, staking app address, team wallet address: Need to be provided for inner transaction and confirmation if the accept is correct

* Store app call transaction
  * Accounts: [tradeder address]

## on_close()
Remove trade app

Sender must be app creator.
Remaining balance will be sent to the creator address



