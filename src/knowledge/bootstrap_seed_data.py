import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from knowledge.store import get_knowledge_store  # noqa: E402

_SEED_DOMAINS = {
    "booking_platform": {
        "name": "Booking Platform",
        "description": "A service where customers schedule appointments or reservations with providers.",
        "typical_modules": ["provider/vendor profiles", "availability & scheduling", "booking & cancellation flow", "payments", "reviews & ratings", "notifications/reminders"],
        "seed_questions": [
            {"id": "bp_users", "text": "Who books — individuals, businesses, or both?", "category": "users",
             "options": ["Individual consumers", "Small businesses", "Enterprise teams", "Both individuals and businesses"]},
            {"id": "bp_providers", "text": "How do service providers get onboarded — self-signup or vetted by you?", "category": "operations",
             "options": ["Self-signup, no vetting", "Self-signup with a review step", "Fully vetted/curated by us", "Not decided yet"]},
            {"id": "bp_scheduling", "text": "Do providers set their own availability, or is it assigned?", "category": "scheduling",
             "options": ["Providers set their own availability", "Availability is assigned centrally", "A mix of both", "Not sure yet"]},
            {"id": "bp_payment", "text": "Is payment taken at booking, after service, or both?", "category": "payments",
             "options": ["At time of booking", "After the service is completed", "Split — deposit then balance", "Not decided yet"]},
            {"id": "bp_cancellation", "text": "What's your cancellation/refund policy?", "category": "policy",
             "options": ["Flexible — full refunds", "Strict — limited or no refunds", "Tiered based on notice given", "Haven't decided yet"]},
        ],
    },
    "e_commerce": {
        "name": "E-Commerce",
        "description": "A platform for browsing and purchasing physical or digital products online.",
        "typical_modules": ["product catalog", "cart & checkout", "payments", "inventory management", "shipping/fulfilment", "order tracking"],
        "seed_questions": [
            {"id": "ec_catalog_size", "text": "Roughly how many products, and do you manage your own inventory?", "category": "catalog",
             "options": ["Fewer than 50 products", "50–500 products", "500+ products", "Not sure yet"]},
            {"id": "ec_fulfilment", "text": "Who handles shipping — you, a third party, or dropshipping?", "category": "fulfilment",
             "options": ["We handle it ourselves", "A third-party logistics partner", "Dropshipping", "Not decided yet"]},
            {"id": "ec_payment", "text": "What payment methods do you need to support?", "category": "payments",
             "options": ["Cards only", "Cards + digital wallets (Apple/Google Pay)", "Cards + buy-now-pay-later", "Not sure yet"]},
            {"id": "ec_returns", "text": "What's your returns/refunds process?", "category": "policy",
             "options": ["Flexible — full refunds", "Strict — limited or no refunds", "Store credit / exchange only", "Haven't decided yet"]},
        ],
    },
    "marketplace": {
        "name": "Marketplace",
        "description": "A two-sided platform connecting independent buyers and sellers.",
        "typical_modules": ["buyer & seller profiles", "listing management", "search & discovery", "messaging between parties", "payments & payouts", "trust & safety"],
        "seed_questions": [
            {"id": "mk_sides", "text": "Who are the two sides of your marketplace?", "category": "users",
             "options": ["Individuals & individuals (P2P)", "Individuals & small businesses", "Businesses & businesses (B2B)", "Something else"]},
            {"id": "mk_revenue", "text": "How does the platform make money — commission, subscription, listing fees?", "category": "business_model",
             "options": ["Commission on transactions", "Subscription fees", "Listing/posting fees", "A combination of these"]},
            {"id": "mk_trust", "text": "How will you build trust between strangers transacting?", "category": "trust_safety",
             "options": ["Verified profiles / ID checks", "Ratings & reviews", "Escrow / secure payments", "Not decided yet"]},
            {"id": "mk_matching", "text": "How do buyers and sellers find each other?", "category": "discovery",
             "options": ["Search & filters", "Algorithmic recommendations", "Browsing categories", "A mix of these"]},
        ],
    },
}


def bootstrap(store=None):
    store = store or get_knowledge_store()
    for name, data in _SEED_DOMAINS.items():
        if not store.domain_exists(name):
            store.save_domain(name, data)
    return store


if __name__ == "__main__":
    s = bootstrap()
    print(f"Store now has {len(s.list_domains())} domain(s): {s.list_domains()}")
