"""
Bootstrap Seed Data — writes the 3 starter domains into the store if not
already present. Idempotent; safe to call every time.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.store import get_knowledge_store  # noqa: E402

_SEED_DOMAINS = {
    "booking_platform": {
        "name": "Booking Platform",
        "description": "A service where customers schedule appointments or reservations with providers (e.g. home services, salons, consultations).",
        "typical_modules": [
            "provider/vendor profiles", "availability & scheduling",
            "booking & cancellation flow", "payments", "reviews & ratings",
            "notifications/reminders",
        ],
        "seed_questions": [
            {"id": "bp_users", "text": "Who books — individuals, businesses, or both?", "category": "users"},
            {"id": "bp_providers", "text": "How do service providers get onboarded — self-signup or vetted by you?", "category": "operations"},
            {"id": "bp_scheduling", "text": "Do providers set their own availability, or is it assigned?", "category": "scheduling"},
            {"id": "bp_payment", "text": "Is payment taken at booking, after service, or both?", "category": "payments"},
            {"id": "bp_cancellation", "text": "What's your cancellation/refund policy?", "category": "policy"},
        ],
    },
    "e_commerce": {
        "name": "E-Commerce",
        "description": "A platform for browsing and purchasing physical or digital products online.",
        "typical_modules": [
            "product catalog", "cart & checkout", "payments",
            "inventory management", "shipping/fulfilment", "order tracking",
        ],
        "seed_questions": [
            {"id": "ec_catalog_size", "text": "Roughly how many products, and do you manage your own inventory?", "category": "catalog"},
            {"id": "ec_fulfilment", "text": "Who handles shipping — you, a third party, or dropshipping?", "category": "fulfilment"},
            {"id": "ec_payment", "text": "What payment methods do you need to support?", "category": "payments"},
            {"id": "ec_returns", "text": "What's your returns/refunds process?", "category": "policy"},
        ],
    },
    "marketplace": {
        "name": "Marketplace",
        "description": "A two-sided platform connecting independent buyers and sellers, where the platform doesn't own the inventory/service itself.",
        "typical_modules": [
            "buyer & seller profiles", "listing management", "search & discovery",
            "messaging between parties", "payments & payouts", "trust & safety",
        ],
        "seed_questions": [
            {"id": "mk_sides", "text": "Who are the two sides of your marketplace (e.g. buyers/sellers, requesters/providers)?", "category": "users"},
            {"id": "mk_revenue", "text": "How does the platform make money — commission, subscription, listing fees?", "category": "business_model"},
            {"id": "mk_trust", "text": "How will you build trust between strangers transacting (reviews, verification, escrow)?", "category": "trust_safety"},
            {"id": "mk_matching", "text": "How do buyers and sellers find each other — search, browse, matching algorithm?", "category": "discovery"},
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
