# Bid Contract

Bid contract has following 5 methods: 

[on_create()](#on_create)

[on_setup()](#on_setup)

[on_bid()](#on_bid)

[on_cancel()](#on_cancel)

[on_accept()](#on_accept)

[on_close()](#on_close)


## on_create()
Creating bid application

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

## on_bid()
Place bid to buy asset.

Group transaction: 
[Bid payment transaction, App call transaction]

* Bid payment transaction
  * Bid amount: The price is the amount buyer wants to buy asset for

* Application call transaction
  * App args: Start time, End time, Reserve amount, Min bid increment
  * Accounts: Rekeyed address for bid index to save bid information on local state

## on_cancel()
Cancel opening bid

Single transaction: App call transaction

* App call transaction
  * accounts: [bid_index]


## on_accept()
Accept on bid, Any asset holder can be the seller to accept the bid if the price is ok.

Group transaction: 
[Asset transaction, App call transaction, Store app call transaction]

* Asset transaction
  * Amount: bid asset amount
 
* App call transaction
  * Application args: [Method keyword, Bid price] (Bid price is providing for confirmation same with the bid amount)
  * Assets: [asset_id] (Need to be provided for inner transaction)
  * Accounts: [bidder address, bid index(rekeyed address), staking app address, team wallet address]
    
    * bid_index: For select a bid which seller wants to accept
    * bidder address, staking app address, team wallet address: Need to be provided for inner transaction and confirmation if the accept is correct

* Store app call transaction
  * Accounts: [bidder address]

## on_close()
Remove bid app

Sender must be app creator.
Remaining balance will be sent to the creator address



