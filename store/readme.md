# Store Contract

Store contract has following 8 methods: 

[on_create()](#on_create)

[on_setup()](#on_setup)

[on_reset()](#on_reset)

[on_set_sold()](#on_set_sold)

[on_set_bought()](#on_set_bought)

[on_buy()](#on_buy)

[on_sell()](#on_sell)

[on_auction()](#on_auction)

[on_update()](#on_update)

[on_delete()](#on_delete)


## on_create()
Creating store application

While creating application, initializing total sold and bought amount on global state.
After create application, the app creator should charge min balance(0.1 Algo) and opt app in our token min balance with transaction fee


## on_setup()
Save app ids(trade_app_id, bid_app_id, auction_app_id, distribution_app_id) on global state

Sender must be app creator

### Single transaction: App call transaction

* Application call transaction
  * Applications: [trade_app_id, bid_app_id, auction_app_id, distribution_app_id]


## on_reset()
Reset user's sold amount and bought amount (0)

Sender must be distribution app

### Single transaction:  App call transaction


## on_set_sold()
Set sold amount of user with a specific amount.

### Single transaction: App call transaction

* Application call transaction
  * Args: setting amount


## on_set_bought()
Set bought amount of user with a specific amount.

### Single transaction: App call transaction

* Application call transaction
  * Args: setting amount


## on_buy()
Call with trading contract accept method

### Group transaction: [Payment transaction, Trading accept call transaction, App call transaction]

* Payment transaction

  * Sender: buyer
  * Receiver: trading app
  * Amount: trading price

* Trading accept call transaction
  * Sender: buyer

* App call transaction
  * Accounts: seller



## on_sell()
Call with bid contract accept method

### Group transaction: [Asset transaction, Bid accept call transaction, App call transaction]

* Asset transaction

  * Sender: seller
  * Receiver: bid app
  * Amount: bid amount

* Bid accept call transaction
  * Sender: seller

* App call transaction
  * Accounts: bidder


## on_auction()
Call with auction contract close method

### Group transaction: [Auction close call transaction, App call transaction]

* Auction close call transaction
  * Sender: seller

* App call transaction
  * Applications: auction app id


## on_delete(), on_update()
Delete and Update application

Sender must be app creator.
Remaining balance will be sent to the creator address



