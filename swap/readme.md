# Swap Contract

Swap contract has following 7 methods: 

[on_create()](#on_create)

[on_setup()](#on_setup)

[on_swap()](#on_swap)

[on_cancel()](#on_cancel)

[on_accept()](#on_accept)

[on_update()](#on_update)

[on_delete()](#on_delete)


## on_create()
Creating swap application

While creating application, saving staking address and team wallet address on global state.
After create application, the app creator should charge min balance(0.1 Algo) and opt app in our token min balance with transaction fee


## on_setup()
Opt app into assets

### Group transaction: [Payment transaction, App call transaction]

* Payment transaction
  * Sender: swap offer
  * Amount: (Optin asset min balance + Transaction fee) * (Assets count)

* Application call transaction
  * Assets: [token_ids to swap]

### Inner transaction: opt app into asset transaction


## on_swap()
Hold assets to swap, can be enabled replace swap

### Group transaction: [Asset transaction, App call transaction]

* Asset transaction
  * Sender: swap offer

* Application call transaction
  * Assets: [Offerring asset id, Accepting asset id]
  * Args: [Offering asset amount, Accepting asset amount]
  * Accounts: [swap index(rekeyed address)]
  * Fee >= 2_000 to replace swap when swap_index has opening swap


## on_cancel()
Cancel swap

### Single transaction: App call transaction

* Application call transaction
  * Assets: [Offerring asset id, Accepting asset id]
  * Args: [Offering asset amount, Accepting asset amount]
  * Accounts: [swap index(rekeyed address)]


## on_accept()
Accept swap

### Group transaction: [Asset transaction, App call transaction]

* Asset transaction
  * Sender: swap accepter

* Application call transaction
  * Assets: [Offerring asset id, Accepting asset id]
  * Args: [Offering asset amount]
  * Accounts: [swap offer, swap index(rekeyed address), staking app address, team wallet address]

### Inner transaction: send offering tokens bidder, accepting tokens to accepter


## on_delete(), on_update()
Delete and Update application

Sender must be app creator.
Remaining balance will be sent to the creator address



