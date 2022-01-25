# Auction Contract

Auction contract has following 4 methods: 

[on_create()](#on_create)

[on_setup()](#on_setup)

[on_bid()](#on_bid)

[on_close()](#on_close)


## on_create()
Creating auction application

* Applications: store app id
* Accounts: staking app address and team wallet address

While creating application, store app id, staking app address and team wallet address is saving on global state.
After create application, the app creator should charge min balance(0.1 Algo) of application


## on_setup()
Pooling assets to be auction

### Group transaction: 
[Funding payment transaction, App call transaction, Pooling asset transaction]

* Funding payment transaction
  * Funding amount: for opt app into asset and inner optin transaction fee

* Application call transaction
  * App args: 

          Start time, 
          End time, 
          Reserve amount(should be large than min txn fee), 
          Min bid increment

  * Accounts: [Rekeyed address for local state]

* Pooling asset transaction
  * Transfer assets to the application


### Inner transaction: 
Opt app into asset

## on_bid()
Bid on auction

Group transaction: 
[Bid payment transaction, App call transaction]

* Bid payment transaction
  * Bid amount: Should be larger than reserve amount and four min txn fees (This fees will be used while split payment as the inner transaction when succeed auction)

* Application call transaction
  * App args: Start time, End time, Reserve amount, Min bid increment
  * Accounts: Rekeyed address for local state

## on_close()
Close auction

Single or Group transaction

Single transaction: This can be processed when auction creator wants to close auction before users bid
Group transaction: This can be processed when there are bidders



