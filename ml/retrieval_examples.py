"""Fixed test examples for retrieval (spec: "Similar tickets and KB search — fixed test examples").

KB_QUERIES: how customers actually phrase problems (typos, informal wording) -> the help article that answers it.
TICKET_TRIPLES: (complaint, a paraphrase of the same problem, a different problem) for similar-ticket search.
Used by ml/eval_retrieval.py (report) and tests/backend/test_retrieval_minilm.py (regression thresholds).
"""

KB_QUERIES: list[tuple[str, str]] = [
    ("I was charged twice for my order of ₹12,500", "Duplicate or double payment for one order"),
    ("amount deducted two times from my account for one order", "Duplicate or double payment for one order"),
    ("money got debited but order is not showing in my orders", "Money debited but order not placed"),
    ("payment failed but money was cut from my bank", "Money debited but order not placed"),
    ("when will I get my refund", "Refund policy and timelines"),
    ("how many days does a refund take to reach my card", "Refund policy and timelines"),
    ("refund status shows processed but my bank says nothing came", "Refund shown as processed but not received"),
    ("pickup boy did not come to collect my return", "Return and reverse pickup policy"),
    ("I want to return the shoes, size issue", "Return and reverse pickup policy"),
    ("received a broken mixer grinder", "Damaged, defective or wrong item received"),
    ("got a wrong product in the box", "Damaged, defective or wrong item received"),
    ("order still not delivered, it is late by 5 days", "Delivery delayed beyond the promised date"),
    ("tracking not updated since 3 days", "Delivery delayed beyond the promised date"),
    ("technician did not come for the AC installation", "Installation and demo requests"),
    ("how do I cancel my order", "Cancelling an order"),
    ("seller cancelled my order without telling me", "Seller cancelled my order"),
    ("warranty claim for my phone that stopped working", "Warranty claims"),
    ("is this charger compatible with my phone model", "Answering product specification questions"),
    ("the agent on the call was very rude to me", "Handling complaints about agent behaviour"),
    ("the delivery boy misbehaved with my mother", "Delivery agent behaviour complaints"),
    ("cashback not received after the offer", "Cashback not credited"),
    ("coupon code not applying at checkout", "Coupon code not working"),
    ("what are the benefits of premium membership", "Shopzilla Premium membership benefits"),
    ("can I transfer my wallet balance to my bank account", "Account and wallet balance questions"),
    ("not getting the otp on my mobile", "OTP not received"),
    ("the app keeps crashing when I try to pay", "App crashes or payment page errors"),
    ("which documents are needed to register as a seller", "Seller registration documents"),
    ("my seller payout is on hold", "Seller payment settlement"),
    ("please delete my account and all my data", "Requests to delete personal data"),
    ("the customer says he will go to consumer court", "When to escalate a ticket"),
]

TICKET_TRIPLES: list[tuple[str, str, str]] = [
    (
        "I was charged twice for my order",
        "the same payment was deducted two times from my account",
        "my parcel has not arrived yet",
    ),
    (
        "refund not received even after 10 days",
        "still waiting for my money back, refund is pending",
        "the app shows an error on login",
    ),
    (
        "pickup for my return was not done",
        "nobody came to collect the item I am returning",
        "I want to buy premium membership",
    ),
    (
        "the delivery is delayed by a week",
        "my order is late and still not delivered",
        "the cashback was not credited",
    ),
    (
        "I received a damaged product",
        "the item arrived broken",
        "how do I change my delivery address",
    ),
    (
        "OTP is not coming on my phone",
        "I don't receive the verification code by SMS",
        "the refund went to the wrong account",
    ),
    (
        "customer care executive was rude",
        "the support agent behaved badly on the call",
        "the product is out of stock",
    ),
    (
        "coupon is not working",
        "discount code gives an error at checkout",
        "my order was cancelled by the seller",
    ),
]
