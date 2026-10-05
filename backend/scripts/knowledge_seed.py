"""Starter knowledge base for Shopzilla support: two help articles per ticket category plus general guidance.
Seeded by scripts/seed_knowledge.py (idempotent by title); Admins edit them in the app afterwards."""

from __future__ import annotations

ARTICLES: list[dict[str, str | None]] = [
    # ---------------------------------------------------------------- Payments related
    {
        "category": "Payments related",
        "title": "Duplicate or double payment for one order",
        "body": (
            "When a customer reports being charged twice for a single order, open the order's payment record and "
            "count the successful captures at the gateway (not the attempts). A failed attempt that shows as a "
            "pending debit is usually reversed by the bank automatically within 48 hours.\n\n"
            "If two successful captures exist, raise a reversal for the duplicate amount from the Payments console "
            "the same day. Share the reversal reference with the customer. Card and UPI reversals reach the account "
            "in 5–7 business days; net banking can take up to 10.\n\n"
            "Never ask the customer for full card numbers, CVV or UPI PIN. For amounts of ₹10,000 or more, or if the "
            "customer has contacted us more than once, call them back within one hour."
        ),
    },
    {
        "category": "Payments related",
        "title": "Money debited but order not placed",
        "body": (
            "If the amount was debited but no order was created (the customer sees no order in My Orders), check "
            "the payment gateway for an orphan transaction against the customer's account and the timestamp.\n\n"
            "Orphan payments are auto-refunded to the source within 72 hours. If 72 hours have passed, raise a manual "
            "refund with the gateway transaction ID. Do not ask the customer to place the order again until the "
            "first payment is confirmed as refunded, to avoid a second debit.\n\n"
            "UPI: ask for the UTR number shown in the customer's UPI app; it identifies the transaction uniquely."
        ),
    },
    # ---------------------------------------------------------------- Refund Related
    {
        "category": "Refund Related",
        "title": "Refund policy and timelines",
        "body": (
            "Refunds start once a cancellation is confirmed or a returned item passes the quality check at the "
            "warehouse. Timelines after initiation: Shopzilla wallet — instant; UPI — 1–3 business days; credit or "
            "debit card — 5–7 business days; net banking — 5–10 business days; cash on delivery orders — refunded to "
            "the bank account or wallet the customer chooses, 3–5 business days.\n\n"
            "Always give the customer the refund reference number (RRN or ARN) once it is issued; their bank can "
            "trace the credit with it. Partial refunds apply when only some items of an order are returned.\n\n"
            "If a refund is past its timeline, escalate to the Refunds Desk with the order ID, refund reference and "
            "payment mode."
        ),
    },
    {
        "category": "Refund Related",
        "title": "Refund shown as processed but not received",
        "body": (
            "When the refund status is 'processed' but the customer says the money has not arrived, first confirm "
            "the payment mode and that the timeline for that mode has passed. Then share the ARN/RRN and ask the "
            "customer to check with their bank using it — the bank has received the credit once an ARN exists.\n\n"
            "If the bank cannot find the credit with the ARN after 7 business days, raise a refund trace with the "
            "payment gateway. Do not issue a second refund while a trace is open; it causes double credits that "
            "must be recovered later."
        ),
    },
    # ---------------------------------------------------------------- Returns
    {
        "category": "Returns",
        "title": "Return and reverse pickup policy",
        "body": (
            "Most items can be returned within 10 days of delivery (electronics: 7 days, with the original box and "
            "accessories). Items marked non-returnable on the product page cannot be returned unless they arrived "
            "damaged, defective or wrong.\n\n"
            "A reverse pickup is scheduled within 2 business days of the return request. The courier makes up to "
            "three pickup attempts. If all attempts fail, reschedule the pickup or offer self-shipping with a "
            "prepaid label. The refund or replacement starts after the item passes the warehouse quality check."
        ),
    },
    {
        "category": "Returns",
        "title": "Damaged, defective or wrong item received",
        "body": (
            "Ask the customer for photos of the item, the packaging and the shipping label within 48 hours of "
            "delivery. With photos attached to the ticket, approve a free replacement or a full refund without "
            "waiting for the pickup.\n\n"
            "For large appliances, book a technician visit instead of a pickup; the technician's report decides "
            "between repair, replacement and refund. Log the seller and courier against the ticket so repeated "
            "issues can be traced."
        ),
    },
    # ---------------------------------------------------------------- Order Related
    {
        "category": "Order Related",
        "title": "Delivery delayed beyond the promised date",
        "body": (
            "Check the last tracking scan. If the shipment has not moved for 48 hours, raise a 'stuck shipment' "
            "request with the courier partner and give the customer the new expected date.\n\n"
            "If the delay is more than 3 days past the promised date, offer cancellation with a full refund and "
            "apply a ₹100 goodwill coupon for Premium members. Never promise a delivery date the courier has not "
            "confirmed."
        ),
    },
    {
        "category": "Order Related",
        "title": "Installation and demo requests",
        "body": (
            "Products marked 'Free installation' get an installation visit within 48 hours of delivery in serviceable "
            "cities. The technician calls the customer before visiting. If no technician has called within 48 hours, "
            "escalate to the brand's service partner with the order ID.\n\n"
            "Installation does not include wall drilling materials or extra pipes; tell the customer about these "
            "charges up front to avoid disputes."
        ),
    },
    # ---------------------------------------------------------------- Cancellation
    {
        "category": "Cancellation",
        "title": "Cancelling an order",
        "body": (
            "Orders can be cancelled free of charge until they are shipped. After shipping, cancel the order and "
            "mark it for return-to-origin (RTO); the customer refuses the delivery and the refund starts when the "
            "parcel reaches the warehouse.\n\n"
            "Prepaid orders are refunded to the original payment method (see 'Refund policy and timelines'). "
            "Seller-cancelled orders are refunded automatically; apologise and suggest an alternative seller."
        ),
    },
    {
        "category": "Cancellation",
        "title": "Seller cancelled my order",
        "body": (
            "When a seller cancels an order (out of stock or unable to ship), the customer is refunded in full "
            "automatically. Confirm the refund has been initiated and share its reference.\n\n"
            "If the same seller cancels repeatedly, report it to Seller Onboarding with the order IDs. Offer the "
            "customer a ₹50 coupon if the product is available from another seller at a higher price."
        ),
    },
    # ---------------------------------------------------------------- Product Queries
    {
        "category": "Product Queries",
        "title": "Warranty claims",
        "body": (
            "Manufacturer warranty starts from the delivery date shown on the invoice. Share the brand's authorised "
            "service centre and the digital invoice from My Orders — service centres accept it.\n\n"
            "If the product fails within the return window, a return is faster than a warranty claim; offer the "
            "return first."
        ),
    },
    {
        "category": "Product Queries",
        "title": "Answering product specification questions",
        "body": (
            "Answer only from the product page specifications and the brand's official documentation. If the "
            "information is missing, raise a catalogue correction request for the listing and tell the customer when "
            "you expect an answer. Never guess compatibility (for example chargers or spare parts)."
        ),
    },
    # ---------------------------------------------------------------- Feedback
    {
        "category": "Feedback",
        "title": "Handling complaints about agent behaviour",
        "body": (
            "Thank the customer, apologise without arguing, and log the date, channel and agent name if known. "
            "Forward the interaction to the team lead for quality review within one business day. Do not discuss "
            "disciplinary action with the customer; tell them the feedback is being reviewed."
        ),
    },
    {
        "category": "Feedback",
        "title": "Delivery agent behaviour complaints",
        "body": (
            "Record the order ID and the delivery date and raise a courier feedback request; the courier partner "
            "investigates and responds within 3 business days. If the customer felt unsafe, escalate immediately to "
            "the courier escalation desk and mark the ticket Critical."
        ),
    },
    # ---------------------------------------------------------------- Offers & Cashback
    {
        "category": "Offers & Cashback",
        "title": "Cashback not credited",
        "body": (
            "Cashback is credited to the Shopzilla wallet within 7 days of delivery (not of the order), and only "
            "if the order met every offer condition: eligible payment method, minimum order value and the offer "
            "period.\n\n"
            "Check the order against the offer terms. If it qualified and 7 days have passed, credit the cashback "
            "manually from the Offers console and note the offer code on the ticket."
        ),
    },
    {
        "category": "Offers & Cashback",
        "title": "Coupon code not working",
        "body": (
            "Coupons fail when the cart is below the minimum value, an item is excluded, the coupon has expired or it "
            "was already used. Tell the customer which condition failed. If the coupon should have worked, raise a "
            "price adjustment for the coupon value after delivery."
        ),
    },
    # ---------------------------------------------------------------- Shopzilla Related
    {
        "category": "Shopzilla Related",
        "title": "Shopzilla Premium membership benefits",
        "body": (
            "Premium members get free delivery on all orders, early access to sales and priority support. Membership "
            "can be cancelled within 14 days of purchase for a full refund if no Premium benefit was used."
        ),
    },
    {
        "category": "Shopzilla Related",
        "title": "Account and wallet balance questions",
        "body": (
            "Wallet balance can be used for purchases but cannot be transferred to a bank account, except refunds "
            "that were credited to the wallet by mistake — those can be moved back to the source on request within "
            "30 days."
        ),
    },
    # ---------------------------------------------------------------- App/website
    {
        "category": "App/website",
        "title": "OTP not received",
        "body": (
            "Ask the customer to check that the registered mobile number is correct and that DND or SMS filtering is "
            "off, then wait 60 seconds before requesting a new OTP. After three failed OTPs the account is locked for "
            "30 minutes. Never read out or ask for an OTP."
        ),
    },
    {
        "category": "App/website",
        "title": "App crashes or payment page errors",
        "body": (
            "Ask for the app version, phone model and a screenshot. Updating the app and clearing its cache fixes "
            "most crashes. If an error occurs on the payment page, check whether money was debited (see 'Money "
            "debited but order not placed') before asking the customer to retry."
        ),
    },
    # ---------------------------------------------------------------- Onboarding related
    {
        "category": "Onboarding related",
        "title": "Seller registration documents",
        "body": (
            "Sellers need a GSTIN, a PAN, a bank account in the business's name and a pickup address. Verification "
            "takes 2–3 business days after all documents are uploaded. Rejections list the failed document; the "
            "seller can re-upload it without starting again."
        ),
    },
    {
        "category": "Onboarding related",
        "title": "Seller payment settlement",
        "body": (
            "Seller payouts are settled 7 days after delivery, minus commission and shipping fees, to the "
            "registered bank account. A payout on hold usually means the bank account verification failed."
        ),
    },
    # ---------------------------------------------------------------- Others
    {
        "category": "Others",
        "title": "Requests that fit no category",
        "body": (
            "Identify the underlying need and correct the ticket's category if one fits — routing then sends it to "
            "the right team. If nothing fits, answer what you can and keep the ticket with General Support."
        ),
    },
    {
        "category": "Others",
        "title": "Requests to delete personal data",
        "body": (
            "Customers can ask for their account and personal data to be deleted. Confirm the request from the "
            "registered e-mail or phone, then raise a data deletion request; it completes within 30 days. Orders "
            "within the return window must close first."
        ),
    },
    # ---------------------------------------------------------------- general
    {
        "category": None,
        "title": "Writing replies to customers",
        "body": (
            "Open with an apology or thanks that fits the situation, state what you have checked and what happens "
            "next, give a concrete timeline and a reference number when you have one, and close with how to reach us. "
            "Use the customer's name. Do not blame other teams, couriers or sellers. Never share another customer's "
            "information, and never promise outcomes you have not confirmed."
        ),
    },
    {
        "category": None,
        "title": "When to escalate a ticket",
        "body": (
            "Escalate when the customer threatens legal action or social-media complaints, the amount is ₹10,000 or "
            "more and unresolved, the customer has contacted us three or more times about the same issue, a safety "
            "concern is raised, or the SLA is about to breach without a resolution in sight. Write the reason in the "
            "escalation note — the admin sees it first."
        ),
    },
]
