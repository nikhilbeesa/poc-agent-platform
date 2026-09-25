"""
content_kit.py — shared content-generation library used by the four
downstream agents (Business Analyst, Product Manager, Product Requirements,
UX/Product Flow) when running in MOCK mode (no LLM configured).

Rather than each agent inventing a handful of generic bullet points, all
four draw from the same module library and vocabulary for a given project,
so the requirement -> story -> screen -> QA traceability chain stays
consistent, and the resulting documents reach the level of detail expected
of a real specification package (dozens of functional requirements,
business rules, data entities, screens, and flows — not three).

This module has no side effects and does not call the LLM; it's pure
Python data + formatting, used only when `get_client()` returns None.
"""
from __future__ import annotations
import re


def _story_clause(fr_name: str, fr_description: str) -> str:
    """Extract a natural third-person verb phrase for the FR description
    ('The system shall allow a Buyer to VERB...' -> 'VERB...'). Falls back
    to a generic, always-grammatical phrasing built from the FR name when
    the description doesn't follow that pattern (e.g. system-initiated
    capabilities like rate limiting)."""
    m = re.search(r"shall (?:allow|enable)\b[^,.]*? to (.+?)(?:\.| within a| before | so | and shall | and will )", fr_description)
    if m:
        return m.group(1).strip().rstrip(",. ")
    return f'make use of "{fr_name}"'


def _first_person_clause(clause: str) -> str:
    """Re-pronoun a third-person clause ('...using their identifier...')
    into first person ('...using my identifier...') for an 'I want to ...'
    user-story sentence. Keep the original third-person clause for anything
    narrated about the actor from the outside (main/alternative/exception
    flow steps), where 'they'/'their' is the grammatically correct form."""
    for src, dst in ((r"\btheir\b", "my"), (r"\bthey\b", "I"), (r"\bthem\b", "me"), (r"\bthemselves\b", "myself")):
        clause = re.sub(src, dst, clause, flags=re.IGNORECASE)
    return clause


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _classify_fr(fr_name: str, fr_description: str) -> str:
    """Classify a functional requirement into the kind of screen/behavior it
    represents, so downstream builders (screens, story flows) can produce
    content that actually differs by what the requirement does, instead of
    reusing one generic template for every requirement regardless of module.
    Buckets: create, edit, admin, browse, detail, settings."""
    text = f"{fr_name} {fr_description}".lower()
    if any(k in text for k in ("approve", "reject", "moderat", "overrid", "audit log", "admin ")):
        return "admin"
    if any(k in text for k in ("create", "add ", "new ", "post ", "upload", "submit", "register")):
        return "create"
    if any(k in text for k in ("edit", "update", "modify", "publish", "unpublish", "cancel", "reschedul")):
        return "edit"
    if any(k in text for k in ("search", "filter", "sort", "browse", "discover", "zero-result", "recent", "saved search")):
        return "browse"
    if any(k in text for k in ("preference", "setting", "deactivat", "notification")):
        return "settings"
    return "detail"


def _module_primary_actor(m: dict, fallback: str) -> str:
    """Pick a concrete, screen-appropriate actor for a module — 'All roles'
    (used for cross-cutting requirements like security) isn't a usable UI
    actor, so fall back to the caller-provided default (typically Admin,
    since cross-cutting requirements are usually enforced/managed there)."""
    actors = m.get("actors", [])
    return actors[0] if actors and actors[0] != "All roles" else fallback


# ---------------------------------------------------------------------------
# Domain vocabulary — the words each domain uses for buyer/seller/item/etc.
# ---------------------------------------------------------------------------

DOMAIN_VOCAB = {
    "booking_platform": {"buyer": "Customer", "seller": "Provider", "item": "Service",
                          "transaction": "Booking", "catalog_name": "Service Catalog"},
    "e_commerce": {"buyer": "Customer", "seller": "Merchant", "item": "Product",
                   "transaction": "Order", "catalog_name": "Product Catalog"},
    "marketplace": {"buyer": "Buyer", "seller": "Seller", "item": "Listing",
                     "transaction": "Transaction", "catalog_name": "Listings"},
}
DEFAULT_VOCAB = {"buyer": "Customer", "seller": "Provider", "item": "Item",
                  "transaction": "Transaction", "catalog_name": "Catalog"}


def get_vocab(domain: str | None) -> dict:
    return DOMAIN_VOCAB.get(domain or "", DEFAULT_VOCAB)


def domain_readable(context) -> str:
    return (context.domain_classification or "general business").replace("_", " ")


def _answers_text(context) -> str:
    return " ".join(str(q.answer) for q in context.discovery_questions if q.answer).lower()


def target_users_phrase(context) -> str:
    for q in context.discovery_questions:
        if q.category == "users" and q.answer:
            return q.answer
    return "end users"


def _fmt(text, vocab, **extra):
    if isinstance(text, list):
        return [_fmt(t, vocab, **extra) for t in text]
    return text.format(**vocab, **extra)


# ---------------------------------------------------------------------------
# Module library
# ---------------------------------------------------------------------------
# Each module: key, name, and either always=True or a domains=(...) filter.
# purpose/actors/inputs/processing/outputs/business_rules/fr use
# {buyer}/{seller}/{item}/{transaction}/{catalog_name} placeholders resolved
# against DOMAIN_VOCAB at select time.

MODULE_LIBRARY = [
    {
        "key": "authentication", "name": "Authentication & Account Management", "always": True,
        "purpose": "Provides secure account creation, login, and session management so that {buyer}s and {seller}s can access role-appropriate functionality. This module is the entry point that gates every authenticated action elsewhere in the product.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Email or phone identifier", "Password or one-time code", "Account profile details"],
        "processing": [
            "Validate the identifier format and check for an existing account",
            "Create the account record and assign a default role",
            "Issue an authenticated session on successful login",
            "Handle password reset and account recovery requests",
        ],
        "outputs": ["Authenticated session", "Account confirmation", "Password reset confirmation"],
        "business_rules": [
            "A {buyer} or {seller} must verify their identifier (email or phone) before completing a {transaction}.",
            "Accounts are uniquely identified by email or phone; duplicate accounts for the same identifier are not permitted.",
            "After 5 consecutive failed login attempts, the account is temporarily locked for a cooldown period.",
        ],
        "fr": [
            {"name": "{buyer}/{seller} Registration", "description": "The system shall allow a new {buyer} or {seller} to create an account using a supported identifier (email or phone) and password, or a supported third-party identity provider. Required fields, format validation, and duplicate-account prevention must be enforced before the account is created.", "priority": "P0"},
            {"name": "Login", "description": "The system shall allow a registered user to authenticate using their identifier and password (or one-time code), establishing a session that persists across page reloads until logout or expiry.", "priority": "P0"},
            {"name": "Password Reset", "description": "The system shall allow a user who has forgotten their password to request a reset link or code via their verified identifier, and to set a new password after that code is verified.", "priority": "P1"},
            {"name": "Identity Verification", "description": "The system shall verify a user's email or phone number via a one-time code or link before the account is treated as fully active and able to transact.", "priority": "P1"},
            {"name": "Session & Logout", "description": "The system shall allow an authenticated user to log out, immediately invalidating their session, and shall automatically expire idle sessions after a configurable timeout.", "priority": "P2"},
        ],
        "entities": {"Account": ["Account ID", "Email", "Phone", "Password hash", "Role", "Status", "Created date", "Last login date"]},
        "notifications": ["Account created", "Email/phone verification", "Password reset requested", "Password changed", "Suspicious login detected"],
    },
    {
        "key": "user_profile", "name": "User Profile Management", "always": True,
        "purpose": "Lets {buyer}s and {seller}s maintain the personal and account information the product needs to operate correctly — contact details, preferences, and (where relevant) payment or payout details.",
        "actors": ["{buyer}", "{seller}"],
        "inputs": ["Name, contact details", "Profile photo (optional)", "Preferences", "Addresses"],
        "processing": ["Validate and persist profile edits", "Enforce which fields are editable per role", "Propagate profile changes to dependent records (e.g. display name on past {transaction}s)"],
        "outputs": ["Updated profile record", "Confirmation of saved changes"],
        "business_rules": [
            "A {buyer} or {seller} may only view and edit their own profile, except where an Admin role is explicitly granted override access.",
            "Changing the primary contact identifier (email/phone) requires re-verification.",
            "A user's display name must be unique enough to avoid confusion in shared views (e.g. booking history, reviews) but is not required to be globally unique.",
        ],
        "fr": [
            {"name": "View & Edit Profile", "description": "The system shall allow an authenticated user to view and edit their own profile fields (name, contact details, preferences), with changes validated and saved immediately.", "priority": "P0"},
            {"name": "Manage Addresses", "description": "The system shall allow a {buyer} to add, edit, and remove one or more saved addresses, and to designate a default address used to pre-fill future {transaction}s.", "priority": "P1"},
            {"name": "Profile Photo", "description": "The system shall allow a user to upload, replace, or remove a profile photo, with size and format validation applied before storage.", "priority": "P3"},
            {"name": "Account Deactivation", "description": "The system shall allow a user to request account deactivation, after which the account is disabled for login while historical {transaction} records are retained per the data retention policy.", "priority": "P2"},
            {"name": "Notification Preferences (Profile)", "description": "The system shall let a user manage basic profile-level preferences (language, contact preference) from within their profile, separate from per-category notification settings.", "priority": "P3"},
        ],
        "entities": {"Profile": ["Profile ID", "Account ID", "Display name", "Contact details", "Address(es)", "Preferences", "Photo URL"]},
        "notifications": ["Profile updated", "Contact identifier changed"],
    },
    {
        "key": "search_discovery", "name": "Search & Discovery", "always": True,
        "purpose": "Helps a {buyer} find the right {item} quickly through search, filtering, and browsing, translating an open-ended need into a short, relevant list of {item}s to choose from.",
        "actors": ["{buyer}"],
        "inputs": ["Search query", "Filters (category, price, location, availability)", "Sort preference"],
        "processing": ["Parse and normalize the search query", "Apply active filters against the {catalog_name}", "Rank and return matching results", "Track search-to-result and search-to-{transaction} conversion for analytics"],
        "outputs": ["Ranked list of matching {item}s", "Zero-result guidance when nothing matches"],
        "business_rules": [
            "Only active, published {item}s are returned in search and browse results.",
            "Filters must be combinable (e.g. category AND price range AND location) rather than mutually exclusive.",
            "Search relevance ranking must not be purchasable/manipulable by a {seller} outside of clearly labeled promoted placements, if any exist.",
        ],
        "fr": [
            {"name": "Keyword Search", "description": "The system shall allow a {buyer} to search the {catalog_name} by free-text keyword, matching against {item} titles and descriptions, and return ranked results.", "priority": "P0"},
            {"name": "Filter Results", "description": "The system shall allow a {buyer} to narrow search or browse results using category, price range, and (where applicable) location and availability filters, with the result count updating as filters are applied.", "priority": "P0"},
            {"name": "Sort Results", "description": "The system shall allow a {buyer} to sort results by relevance, price, rating, or newest, persisting the chosen sort within the session.", "priority": "P2"},
            {"name": "Zero-Result Handling", "description": "The system shall present clear guidance (e.g. suggested filter changes) when a search or filter combination returns no results, rather than a blank screen.", "priority": "P2"},
            {"name": "Recent & Saved Searches", "description": "The system shall let a {buyer} revisit recent search queries and optionally save a search/filter combination for quick reuse.", "priority": "P3"},
        ],
        "entities": {"SearchQuery": ["Query ID", "Search text", "Filters applied", "Result count", "Timestamp"]},
        "notifications": [],
    },
    {
        "key": "catalog", "name": "{catalog_name}", "always": True,
        "purpose": "Maintains the authoritative set of {item}s a {seller} offers, including descriptions, pricing, media, and availability status, so {buyer}s always see accurate, up-to-date listings.",
        "actors": ["{seller}", "Admin", "{buyer}"],
        "inputs": ["{item} title, description, price", "Category/tags", "Media (photos)", "Availability/stock status"],
        "processing": ["Validate required fields before publishing", "Apply category and pricing rules", "Version/track edits to published {item}s", "Reflect availability/stock changes in near real time"],
        "outputs": ["Published {item} listing", "Draft saved confirmation", "Out-of-stock/unavailable status"],
        "business_rules": [
            "A {item} must have a title, description, price, and at least one category before it can be published.",
            "A {seller} may only edit or remove their own {item}s; Admins may moderate any listing.",
            "An {item} that is out of stock or unavailable must not be bookable/purchasable until restocked or re-enabled.",
        ],
        "fr": [
            {"name": "Create {item} Listing", "description": "The system shall allow a {seller} to create a new {item} listing with title, description, price, category, and media, saving it as a draft until required fields are complete.", "priority": "P0"},
            {"name": "Edit {item} Listing", "description": "The system shall allow a {seller} to edit an existing {item} listing's details, with changes reflected to {buyer}s immediately upon save.", "priority": "P0"},
            {"name": "Publish / Unpublish Listing", "description": "The system shall allow a {seller} to publish a completed listing (making it visible in search/browse) or unpublish it (hiding it without deleting the underlying record).", "priority": "P1"},
            {"name": "Manage Availability/Stock", "description": "The system shall allow a {seller} to mark an {item} as unavailable/out of stock, automatically preventing new {transaction}s against it until it is re-enabled.", "priority": "P0"},
            {"name": "Category Browsing", "description": "The system shall organize {item}s into browsable categories so a {buyer} can explore the {catalog_name} without an explicit search query.", "priority": "P2"},
        ],
        "entities": {"{item}": ["{item} ID", "{seller} ID", "Title", "Description", "Price", "Category", "Media URLs", "Status", "Created date"]},
        "notifications": ["Listing published", "Listing out of stock", "Listing flagged/moderated"],
    },
    {
        "key": "transaction", "name": "{transaction} & Checkout", "always": True,
        "purpose": "Lets a {buyer} commit to a {item} — selecting details, reviewing cost, and confirming — and turns that intent into a tracked {transaction} record that both sides can rely on.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Selected {item}", "Quantity/date/time as applicable", "Delivery/service address", "Payment method"],
        "processing": [
            "Validate {item} availability at the moment of {transaction}",
            "Calculate total cost including any fees or taxes",
            "Create the {transaction} record in a pending state",
            "Confirm the {transaction} once payment succeeds",
            "Notify both {buyer} and {seller} of the confirmed {transaction}",
        ],
        "outputs": ["{transaction} confirmation", "Unique {transaction} ID", "Updated {transaction} status"],
        "business_rules": [
            "A {transaction} may only be created against an {item} that is currently published and available.",
            "The total cost shown to the {buyer} before confirmation must match the amount actually charged.",
            "A {transaction} moves through a defined status lifecycle (pending, confirmed, in progress, completed, cancelled) and may not skip states.",
        ],
        "fr": [
            {"name": "Create {transaction}", "description": "The system shall allow a {buyer} to initiate a {transaction} for a selected {item}, capturing all details required (date/time, quantity, address, etc.) before proceeding to payment.", "priority": "P0"},
            {"name": "Review Before Confirming", "description": "The system shall present a review step summarizing the {item}, chosen details, and total cost, requiring explicit {buyer} confirmation before payment is captured.", "priority": "P0"},
            {"name": "{transaction} Confirmation", "description": "The system shall generate a unique {transaction} ID and confirmation once payment succeeds, and shall not create a confirmed {transaction} record if payment fails.", "priority": "P0"},
            {"name": "View {transaction} History", "description": "The system shall allow a {buyer} and the corresponding {seller} to view their past and upcoming {transaction}s with current status.", "priority": "P1"},
            {"name": "Cancel {transaction}", "description": "The system shall allow a {buyer} (or {seller}, per policy) to cancel a {transaction} prior to completion, applying the active cancellation policy to determine any applicable refund.", "priority": "P1"},
            {"name": "Modify {transaction}", "description": "The system shall allow a {buyer} to request a change to an unconfirmed or upcoming {transaction} (e.g. date/time), subject to {seller} availability and the modification policy.", "priority": "P2"},
        ],
        "entities": {"{transaction}": ["{transaction} ID", "{buyer} ID", "{seller} ID", "{item} ID", "Date/time", "Amount", "Status", "Created date"]},
        "notifications": ["{transaction} created", "{transaction} confirmed", "{transaction} status changed", "{transaction} cancelled", "{transaction} completed"],
    },
    {
        "key": "scheduling", "name": "Scheduling & Availability", "domains": ("booking_platform", "marketplace"),
        "purpose": "Manages when a {item} can actually be delivered — {seller} availability windows, slot capacity, and conflict prevention — so a {buyer} only ever sees and books slots that are genuinely open.",
        "actors": ["{seller}", "{buyer}", "Admin"],
        "inputs": ["{seller} working hours/availability windows", "Existing bookings", "Buffer/lead-time rules"],
        "processing": ["Compute open slots from {seller} availability minus existing bookings", "Apply buffer/lead-time rules", "Lock a slot briefly during {buyer} checkout to prevent double-booking", "Release the lock if checkout is abandoned"],
        "outputs": ["List of open slots", "Confirmed slot assignment"],
        "business_rules": [
            "A {seller} may not have two confirmed {transaction}s that overlap in time.",
            "A slot is held for the {buyer} for a limited window during checkout; if payment is not completed in that window, the slot is released.",
        ],
        "fr": [
            {"name": "Set Availability", "description": "The system shall allow a {seller} to define recurring or one-off availability windows, which determine which slots are offered to {buyer}s.", "priority": "P0"},
            {"name": "View Open Slots", "description": "The system shall compute and display only currently open slots to a {buyer}, excluding any slot already booked or outside {seller} availability.", "priority": "P0"},
            {"name": "Prevent Double-Booking", "description": "The system shall prevent two {buyer}s from confirming the same slot, using a short hold during checkout and a final availability check at confirmation.", "priority": "P0"},
            {"name": "Reschedule", "description": "The system shall allow a {buyer} or {seller} to reschedule an upcoming {transaction} to another open slot, subject to the active rescheduling policy.", "priority": "P2"},
        ],
        "entities": {"AvailabilityWindow": ["Window ID", "{seller} ID", "Day/date", "Start time", "End time", "Recurrence rule"]},
        "notifications": ["Slot held", "Slot released", "{transaction} rescheduled"],
    },
    {
        "key": "payments", "name": "Payments & Billing", "always": True,
        "purpose": "Handles the movement of money for every {transaction} — capturing payment, tracking its status, issuing refunds, and keeping a reliable financial record for reconciliation.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Payment method details", "{transaction} amount", "Refund requests"],
        "processing": [
            "Tokenize and validate the payment method via the payment processor",
            "Capture (or authorize then capture) payment for the {transaction} amount",
            "Record the resulting payment status and processor reference",
            "Process refunds against the original payment method where applicable",
            "Reconcile processor records against internal {transaction} records",
        ],
        "outputs": ["Payment confirmation", "Payment status", "Refund confirmation", "Transaction record for reconciliation"],
        "business_rules": [
            "Raw payment card details must never be stored directly by the platform; only a processor-issued token/reference is retained.",
            "A refund may not exceed the original captured amount for that {transaction}.",
            "A {transaction} is not considered confirmed until payment capture succeeds.",
        ],
        "fr": [
            {"name": "Capture Payment", "description": "The system shall capture payment for a {transaction} via an integrated payment processor at the moment of {buyer} confirmation, handling both successful and declined outcomes distinctly.", "priority": "P0"},
            {"name": "Retry Failed Payment", "description": "The system shall allow a {buyer} to retry payment with the same or a different method if the initial attempt fails, without duplicating the underlying {transaction}.", "priority": "P1"},
            {"name": "Prevent Duplicate Charges", "description": "The system shall ensure that a single {buyer} confirmation action results in at most one successful charge, even if the request is retried due to a network issue.", "priority": "P0"},
            {"name": "Process Refunds", "description": "The system shall allow an authorized role to issue a full or partial refund against a completed payment, applying the active cancellation/refund policy and recording the refund status.", "priority": "P1"},
            {"name": "Payment & Payout Records", "description": "The system shall maintain an auditable record of every payment and (where applicable) {seller} payout, including status, amount, and processor reference, for reconciliation and support use.", "priority": "P1"},
        ],
        "entities": {"Payment": ["Payment ID", "{transaction} ID", "Amount", "Method", "Status", "Processor reference", "Created date"],
                      "Refund": ["Refund ID", "Payment ID", "Amount", "Reason", "Status", "Created date"]},
        "notifications": ["Payment succeeded", "Payment failed", "Refund issued", "Payout sent"],
    },
    {
        "key": "provider_management", "name": "{seller} Management", "domains": ("booking_platform", "marketplace"),
        "purpose": "Covers how a {seller} joins the platform, gets verified, and manages their standing — the supply side of the marketplace that makes {item}s available to {buyer}s in the first place.",
        "actors": ["{seller}", "Admin"],
        "inputs": ["{seller} application details", "Verification documents (if applicable)", "Performance history"],
        "processing": ["Collect {seller} application/onboarding details", "Run verification checks per the active vetting policy", "Approve, reject, or request more information", "Monitor ongoing {seller} performance (ratings, cancellation rate, response time)"],
        "outputs": ["{seller} approval/rejection decision", "{seller} status (active, suspended, under review)"],
        "business_rules": [
            "Only an approved, active {seller} may publish {item}s or accept {transaction}s.",
            "A {seller} whose rating or cancellation rate falls below the platform's minimum threshold is flagged for review.",
        ],
        "fr": [
            {"name": "{seller} Onboarding", "description": "The system shall guide a prospective {seller} through an application flow capturing the information the active vetting policy requires, and shall track application status.", "priority": "P0"},
            {"name": "{seller} Verification", "description": "The system shall support an Admin (or automated check, where configured) reviewing and approving or rejecting a {seller} application before that {seller} can publish {item}s.", "priority": "P0"},
            {"name": "{seller} Performance Monitoring", "description": "The system shall track {seller}-level metrics (average rating, cancellation rate, response time) and flag {seller}s that fall below configured thresholds for Admin review.", "priority": "P2"},
            {"name": "Suspend / Reinstate {seller}", "description": "The system shall allow an Admin to suspend a {seller} (hiding their {item}s and blocking new {transaction}s) and later reinstate them, recording the reason and timestamps for both actions.", "priority": "P1"},
        ],
        "entities": {"{seller}Profile": ["{seller} ID", "Account ID", "Verification status", "Rating", "Cancellation rate", "Status"]},
        "notifications": ["Application received", "{seller} approved", "{seller} rejected", "{seller} suspended"],
    },
    {
        "key": "reviews", "name": "Reviews & Ratings", "domains": ("booking_platform", "e_commerce", "marketplace"),
        "purpose": "Captures {buyer} feedback after a {transaction} completes, giving future {buyer}s a trust signal and giving {seller}s (and Admins) a feedback loop on quality.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Star rating", "Written review text", "{transaction} reference"],
        "processing": ["Prompt the {buyer} to review after {transaction} completion", "Validate the review is tied to a genuine completed {transaction}", "Publish the review to the {item}/{seller} page", "Allow moderation of flagged reviews"],
        "outputs": ["Published review", "Updated average rating for the {item}/{seller}"],
        "business_rules": [
            "A {buyer} may only review a {transaction} they actually completed, and only once per {transaction}.",
            "A {seller} may publicly respond to a review but may not delete a review outright; disputed reviews go through Admin moderation.",
        ],
        "fr": [
            {"name": "Submit Review", "description": "The system shall allow a {buyer} to submit a star rating and optional written review for a completed {transaction}, within a configured window after completion.", "priority": "P1"},
            {"name": "Display Reviews", "description": "The system shall display published reviews and the computed average rating on the relevant {item}/{seller} page, ordered by recency by default.", "priority": "P1"},
            {"name": "{seller} Response", "description": "The system shall allow a {seller} to post a single public response to a review they have received.", "priority": "P3"},
            {"name": "Flag & Moderate Review", "description": "The system shall allow a {buyer} or {seller} to flag a review as inappropriate, routing it to an Admin queue for moderation before any removal.", "priority": "P2"},
        ],
        "entities": {"Review": ["Review ID", "{transaction} ID", "Rating", "Text", "Status", "Created date"]},
        "notifications": ["Review requested", "Review received", "Review flagged"],
    },
    {
        "key": "trust_safety", "name": "Trust & Safety", "domains": ("marketplace",),
        "purpose": "Provides the verification and dispute-handling mechanisms that let two strangers transact with confidence — identity checks, secure payment handling, and a clear path to resolve disagreements.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Identity verification documents", "Dispute details and evidence"],
        "processing": ["Verify identity per the active verification policy", "Hold funds in escrow where applicable until {transaction} completion", "Intake and triage disputes between {buyer} and {seller}", "Resolve disputes per policy, including refund or payout adjustments"],
        "outputs": ["Verification status", "Dispute resolution outcome"],
        "business_rules": [
            "Funds held in escrow are only released to the {seller} once the completion criteria for the {transaction} are met.",
            "A dispute must be resolved by an Admin within the platform's published service-level target.",
        ],
        "fr": [
            {"name": "Identity Verification", "description": "The system shall support collecting and verifying {buyer}/{seller} identity documents where the platform's trust policy requires it, blocking {transaction}s until verification succeeds.", "priority": "P1"},
            {"name": "Escrow Handling", "description": "The system shall hold {transaction} funds until agreed completion criteria are met, then release them to the {seller}, or return them to the {buyer} if the {transaction} is cancelled per policy.", "priority": "P1"},
            {"name": "Raise a Dispute", "description": "The system shall allow either party to raise a dispute against a {transaction}, attaching evidence, and shall route it to an Admin queue.", "priority": "P1"},
            {"name": "Resolve a Dispute", "description": "The system shall allow an Admin to review dispute evidence and record a resolution (e.g. full/partial refund, payout release), notifying both parties of the outcome.", "priority": "P1"},
        ],
        "entities": {"Dispute": ["Dispute ID", "{transaction} ID", "Raised by", "Reason", "Evidence", "Status", "Resolution"]},
        "notifications": ["Verification approved", "Verification rejected", "Dispute opened", "Dispute resolved"],
    },
    {
        "key": "fulfilment", "name": "Fulfilment & Delivery", "domains": ("e_commerce",),
        "purpose": "Tracks a {item} from confirmed order through to the {buyer}'s door — packing, handoff to a carrier, and delivery confirmation — so both sides know where an order stands at any time.",
        "actors": ["{seller}", "Admin", "{buyer}"],
        "inputs": ["Order details", "Shipping address", "Carrier/tracking information"],
        "processing": ["Generate a fulfilment task once an order is confirmed", "Record packing and hand-off to carrier", "Ingest tracking updates from the carrier (or manual status updates)", "Confirm delivery and close out the order"],
        "outputs": ["Shipment tracking reference", "Delivery confirmation"],
        "business_rules": [
            "An order may not be marked delivered without either a carrier delivery event or explicit {buyer}/Admin confirmation.",
            "A {seller} must ship a confirmed order within the platform's published fulfilment SLA or the order is flagged for Admin attention.",
        ],
        "fr": [
            {"name": "Generate Fulfilment Task", "description": "The system shall automatically create a fulfilment task for the {seller} once an order's payment is confirmed, including the shipping address and order contents.", "priority": "P0"},
            {"name": "Update Shipment Status", "description": "The system shall allow a {seller} (or an integrated carrier webhook) to update shipment status (packed, shipped, out for delivery, delivered), visible to the {buyer} in real time.", "priority": "P0"},
            {"name": "Track Shipment", "description": "The system shall display current shipment status and, where a carrier integration provides it, a tracking link/reference to the {buyer}.", "priority": "P1"},
            {"name": "Delivery Confirmation", "description": "The system shall close out an order as delivered based on carrier confirmation or explicit {buyer} acknowledgement, triggering the review-request notification.", "priority": "P1"},
        ],
        "entities": {"Shipment": ["Shipment ID", "Order ID", "Carrier", "Tracking reference", "Status", "Shipped date", "Delivered date"]},
        "notifications": ["Order shipped", "Out for delivery", "Delivered", "Fulfilment delayed"],
    },
    {
        "key": "notifications_module", "name": "Notifications", "always": True,
        "purpose": "Keeps every party informed of state changes that matter to them — {transaction} updates, account events, and operational alerts — through the right channel at the right time.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Triggering system event", "User notification preferences"],
        "processing": ["Match the triggering event to its notification template", "Resolve the recipient(s) and their preferred channel(s)", "Render and send the notification", "Record delivery status for support/debugging"],
        "outputs": ["Sent notification (email/SMS/push/in-app)", "Delivery status"],
        "business_rules": [
            "A user may opt out of non-essential notification categories, but not out of security- and {transaction}-critical notifications (e.g. payment confirmation).",
            "Notifications must be sent within a short, bounded delay of the triggering event to remain useful.",
        ],
        "fr": [
            {"name": "Event-Triggered Notifications", "description": "The system shall send a notification to the relevant party whenever a defined triggering event occurs (see the Notifications matrix), via that user's preferred channel where configurable.", "priority": "P0"},
            {"name": "Notification Preferences", "description": "The system shall allow a user to manage which non-essential notification categories they receive and through which channel.", "priority": "P3"},
            {"name": "In-App Notification Center", "description": "The system shall maintain a chronological, readable log of a user's recent notifications within the product, independent of email/SMS delivery.", "priority": "P2"},
        ],
        "entities": {"Notification": ["Notification ID", "Recipient ID", "Event type", "Channel", "Status", "Sent date"]},
        "notifications": [],
    },
    {
        "key": "support", "name": "Customer Support & Help", "always": True,
        "purpose": "Gives a {buyer} or {seller} a way to get help and gives Support staff the tools to resolve issues — from self-service help content to a tracked ticket when something needs a human.",
        "actors": ["{buyer}", "{seller}", "Support agent", "Admin"],
        "inputs": ["Help request/ticket details", "{transaction} reference (if related)", "Support agent responses"],
        "processing": ["Offer self-service help content matched to common questions", "Capture a support ticket when self-service isn't enough", "Route the ticket to a support agent", "Track ticket status through to resolution"],
        "outputs": ["Ticket confirmation", "Ticket resolution", "Help content"],
        "business_rules": [
            "Every support ticket must be linked to the requesting user's account and, where relevant, the associated {transaction}.",
            "A ticket may not be closed without a recorded resolution note.",
            "A ticket that references a {transaction} must be visible to the agent alongside that {transaction}'s current status and history.",
        ],
        "fr": [
            {"name": "Submit Support Ticket", "description": "The system shall allow a {buyer} or {seller} to submit a support ticket describing their issue, optionally linked to a specific {transaction}.", "priority": "P1"},
            {"name": "Track Ticket Status", "description": "The system shall allow the ticket submitter to see current ticket status (open, in progress, resolved) and any agent responses.", "priority": "P1"},
            {"name": "Agent Ticket Queue", "description": "The system shall present Support agents with a queue of open tickets, sortable/filterable by status, age, and urgency.", "priority": "P1"},
            {"name": "Self-Service Help Content", "description": "The system shall surface relevant help articles/FAQs to a user before they submit a ticket, based on keyword or context.", "priority": "P3"},
            {"name": "Escalate Ticket", "description": "The system shall allow a Support agent to escalate a ticket to a senior agent or Admin when it cannot be resolved at the first level, preserving the full ticket history.", "priority": "P2"},
        ],
        "entities": {"SupportTicket": ["Ticket ID", "Requester ID", "Related {transaction} ID", "Subject", "Status", "Created date", "Resolved date"]},
        "notifications": ["Ticket received", "Agent responded", "Ticket resolved"],
    },
    {
        "key": "admin_ops", "name": "Admin & Operations Console", "always": True,
        "purpose": "Gives internal Operations and Admin users the tools to run the platform day to day — managing users, {item}s, and {transaction}s, and stepping in when something needs manual attention.",
        "actors": ["Admin", "Operations"],
        "inputs": ["Search/filter criteria across users, {item}s, {transaction}s", "Manual override actions"],
        "processing": ["Provide searchable views of core entities", "Support manual status overrides with a recorded reason", "Surface flagged/exception items needing attention", "Log every admin action for audit purposes"],
        "outputs": ["Updated entity state", "Audit log entry"],
        "business_rules": [
            "Every manual override performed by Admin/Operations must be recorded with the acting user, timestamp, and reason.",
            "Destructive actions (e.g. removing a {seller}, cancelling a {transaction}) require explicit confirmation before executing.",
            "Admin/Operations views must never expose raw payment credentials, even to resolve a support case.",
        ],
        "fr": [
            {"name": "Manage Users", "description": "The system shall allow Admin to search, view, and manage {buyer} and {seller} accounts, including suspending or reinstating an account with a recorded reason.", "priority": "P0"},
            {"name": "Manage {item}s", "description": "The system shall allow Admin to search, view, and moderate {item} listings, including unpublishing a listing that violates policy.", "priority": "P1"},
            {"name": "Manage {transaction}s", "description": "The system shall allow Admin to search, view, and, where necessary, manually override the status of a {transaction} (e.g. force-cancel), recording the reason.", "priority": "P1"},
            {"name": "Exception Queue", "description": "The system shall surface {transaction}s and accounts flagged as exceptions (failed payments, disputed reviews, suspended {seller}s) in a single operational queue.", "priority": "P2"},
            {"name": "Audit Log", "description": "The system shall maintain an append-only log of every Admin/Operations action, viewable by authorized roles for accountability.", "priority": "P2"},
        ],
        "entities": {"AuditLogEntry": ["Entry ID", "Actor", "Action", "Target entity", "Reason", "Timestamp"]},
        "notifications": [],
    },
    {
        "key": "reporting", "name": "Reporting & Analytics", "always": True,
        "purpose": "Turns raw product activity into the numbers the business needs to run itself — {transaction} volume and revenue for Finance, activity and quality metrics for Operations, and usage trends for Product.",
        "actors": ["Admin", "Operations", "Business sponsor"],
        "inputs": ["Underlying {transaction}, payment, user, and {item} data"],
        "processing": ["Aggregate underlying event and entity data on a scheduled or on-demand basis", "Compute the defined KPIs and report views", "Present reports with filtering by date range and (where relevant) {seller}/category"],
        "outputs": ["Report views/dashboards", "Exportable data (e.g. CSV) where required"],
        "business_rules": [
            "Financial reports must reconcile to the underlying payment records — no report may show a different total than the sum of its source transactions.",
            "A report or export must only include data the requesting role is authorized to see (e.g. Support sees ticket data, not full financial detail).",
        ],
        "fr": [
            {"name": "Operational Dashboard", "description": "The system shall present an at-a-glance operational dashboard (active {transaction}s, exceptions, recent activity) for Admin/Operations.", "priority": "P1"},
            {"name": "Revenue & {transaction} Reports", "description": "The system shall provide {transaction} volume and revenue reports filterable by date range, exportable for Finance use.", "priority": "P1"},
            {"name": "{seller}/Product Performance Reports", "description": "The system shall provide {seller}- and {item}-level performance views (volume, rating, cancellation rate) to support operational decisions.", "priority": "P2"},
            {"name": "Export Report Data", "description": "The system shall allow an authorized user to export a report's underlying data (e.g. CSV) for offline analysis, respecting the same access restrictions as the report itself.", "priority": "P3"},
        ],
        "entities": {},
        "notifications": [],
    },
    {
        "key": "security", "name": "Security & Access Control", "always": True,
        "purpose": "Ensures that every action in the product is performed by an authorized party and that sensitive data is protected — the cross-cutting layer every other module depends on.",
        "actors": ["All roles"],
        "inputs": ["Authenticated session/role", "Requested action/resource"],
        "processing": ["Check the acting user's role against the permission required for the requested action", "Deny and log unauthorized attempts", "Encrypt sensitive data in transit and at rest", "Rate-limit sensitive endpoints (login, payment) to reduce abuse"],
        "outputs": ["Allow/deny decision", "Security audit log entry"],
        "business_rules": [
            "Every state-changing action must check the acting user's role/permission before executing, not only hide the option in the UI.",
            "Sensitive data (payment details, identity documents) must be encrypted at rest and only decrypted for authorized processing.",
            "A security audit log entry must never itself contain the raw sensitive data (e.g. full card numbers, passwords) involved in the event it records.",
        ],
        "fr": [
            {"name": "Role-Based Access Control", "description": "The system shall enforce role-based permissions server-side for every state-changing action, independent of what the client UI happens to display.", "priority": "P0"},
            {"name": "Rate Limiting", "description": "The system shall rate-limit sensitive endpoints (login, password reset, payment submission) to reduce brute-force and abuse risk.", "priority": "P1"},
            {"name": "Data Encryption", "description": "The system shall encrypt sensitive data (credentials, payment tokens, identity documents) in transit (TLS) and at rest.", "priority": "P0"},
            {"name": "Security Audit Logging", "description": "The system shall log authentication events and authorization failures for later security review.", "priority": "P2"},
            {"name": "Session Invalidation on Risk Signal", "description": "The system shall invalidate active sessions and require re-authentication when a high-risk signal is detected (e.g. password change, suspected credential compromise).", "priority": "P2"},
        ],
        "entities": {},
        "notifications": ["Suspicious activity detected"],
    },
    {
        "key": "onboarding", "name": "Onboarding & Activation", "always": True,
        "purpose": "Guides a newly-registered {buyer} or {seller} from account creation to their first successful core action, so the value of the product is obvious quickly instead of requiring them to figure it out unassisted.",
        "actors": ["{buyer}", "{seller}"],
        "inputs": ["Newly created account", "Role selected at signup"],
        "processing": ["Determine the correct onboarding path for the account's role", "Track completion of each onboarding step", "Surface the next best action until the first core action is completed"],
        "outputs": ["Onboarding progress state", "Completed/activated account"],
        "business_rules": [
            "Onboarding must be skippable/dismissible and must never block access to the core product.",
            "An account's onboarding state must persist across sessions and devices.",
        ],
        "fr": [
            {"name": "Guided First-Run Walkthrough", "description": "The system shall present a short, dismissible guided walkthrough of the core workflow the first time a new {buyer} or {seller} account signs in.", "priority": "P1"},
            {"name": "Onboarding Progress Checklist", "description": "The system shall show a role-appropriate checklist of setup steps (e.g. complete profile, add first {item}, set availability) and track which are completed.", "priority": "P2"},
            {"name": "Skip / Resume Onboarding", "description": "The system shall allow a user to skip onboarding at any point and resume it later from account settings without losing progress already made.", "priority": "P2"},
        ],
        "entities": {"OnboardingProgress": ["Account ID", "Step", "Status", "Completed date"]},
        "notifications": ["Onboarding step reminder"],
    },
    {
        "key": "privacy_consent", "name": "Privacy, Consent & Data Retention", "always": True,
        "purpose": "Gives users control over their own data — requesting a copy of it, deleting their account, and managing consent for optional data uses — and ensures the platform actually enforces its stated retention policy rather than only describing one.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Account deletion request", "Data export/access request", "Consent choices"],
        "processing": [
            "Authenticate the requesting user before acting on a deletion or export request",
            "Delete or irreversibly anonymize personal data not otherwise required to be retained, within the published retention window",
            "Package a machine-readable export of the user's own data on request",
            "Record and honor granular consent choices for optional (non-essential) data uses",
        ],
        "outputs": ["Deletion confirmation", "Data export file", "Updated consent record"],
        "business_rules": [
            "A user-initiated account deletion request must be honored within the platform's published retention/deletion window; data required for legal/financial record-keeping may be retained only as long as that obligation requires, clearly separate from the rest of the deleted account.",
            "A user may withdraw consent for any optional (non-essential) data use at any time, without needing to delete their entire account.",
            "Withdrawing optional consent or requesting deletion must never be harder to do than the original opt-in/signup action.",
        ],
        "fr": [
            {"name": "Request Account Deletion", "description": "The system shall allow a {buyer} or {seller} to request deletion of their account and associated personal data, confirm the request, and receive confirmation once it has been processed.", "priority": "P1"},
            {"name": "Data Export / Right to Access", "description": "The system shall allow a user to request and receive a machine-readable export of the personal data the platform holds about them.", "priority": "P2"},
            {"name": "Consent Management", "description": "The system shall let a user view and change their consent choices for optional (non-essential) data uses, separate from the notification-preferences settings.", "priority": "P2"},
            {"name": "Data Retention Enforcement", "description": "The system shall automatically enforce the platform's data retention policy, removing or anonymizing personal data once its retention period has elapsed, independent of an explicit deletion request.", "priority": "P2"},
        ],
        "entities": {"PrivacyRequest": ["Request ID", "Account ID", "Type", "Status", "Requested date", "Completed date"]},
        "notifications": ["Deletion request received", "Deletion completed", "Data export ready"],
    },
    {
        "key": "ai_features", "name": "AI-Powered Features",
        "keywords": ("artificial intelligence", "machine learning", " ai ", " ai-", "ai-powered", "ai powered",
                     "recommend", "personali", "predict", "smart match", "auto-generat", "autogenerat",
                     "generat", "chatbot", " nlp", "assistant", "matching algorithm", "smart suggest"),
        "purpose": "Applies an AI/ML component to the core workflow to produce a {buyer}-facing recommendation, generated content, or prediction — specified as concrete product behavior (defined input, trigger, output, confidence handling, and a safe fallback), not just \"AI\" as an unspecified add-on.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["User/behavioral data the user has consented to use", "The specific triggering event or user action", "Relevant {catalog_name} data"],
        "processing": [
            "Assemble the defined input data at the defined trigger point",
            "Run the AI/ML component to produce a recommendation, generated content, or prediction",
            "Attach a confidence signal and route low-confidence output to the defined fallback instead of presenting it as authoritative",
            "Log the input summary, output, and user action taken on it (accepted, edited, dismissed) for quality review",
        ],
        "outputs": ["AI-generated recommendation, content, or prediction, clearly labeled as such", "Fallback (non-AI) result when confidence is low or the component fails"],
        "business_rules": [
            "Every AI-generated recommendation or content item must be clearly labeled as AI-generated and must be reviewable and overridable by the user before it has any binding effect.",
            "If the AI component's confidence falls below the configured threshold, or the component fails or times out, the system must fall back to the defined non-AI default rather than presenting a low-confidence or absent result as authoritative.",
            "AI input data usage must be disclosed to the user, and the user must be able to opt out of AI-personalized features, falling back to the non-personalized experience rather than losing access to the product.",
        ],
        "fr": [
            {"name": "Generate AI Recommendation / Output", "description": "The system shall generate an AI-produced recommendation, piece of content, or prediction for the {buyer} based on defined input data and a defined trigger, and shall present it as a suggestion the user can accept, edit, or dismiss rather than an automatic action taken on their behalf.", "priority": "P1"},
            {"name": "Explain AI Result", "description": "The system shall provide a short, human-readable explanation of why a given AI output was produced whenever that output affects something the user must decide on.", "priority": "P2"},
            {"name": "Override / Edit AI Output", "description": "The system shall allow the user to edit or fully override any AI-generated content or recommendation before it is acted upon, saved, or published.", "priority": "P1"},
            {"name": "AI Failure & Low-Confidence Fallback", "description": "If the AI component fails, times out, or returns a result below the configured confidence threshold, the system shall fall back to a clearly labeled non-AI default (e.g. manual search/browse, a neutral empty state with guidance) rather than blocking the user or silently presenting a guess as fact.", "priority": "P1"},
            {"name": "AI Data Usage & Opt-Out Controls", "description": "The system shall disclose what user data is used as AI input and shall let the user opt out of AI-personalized features, reverting to the non-personalized experience.", "priority": "P2"},
        ],
        "entities": {"AIRecommendation": ["Recommendation ID", "User ID", "Input summary", "Output", "Confidence score", "Model/version", "User action (accepted/edited/dismissed)", "Created date"]},
        "notifications": [],
    },
    {
        "key": "data_export_import", "name": "Data Export & Import",
        "keywords": ("export", "import their", "bulk upload", "csv", "download my data", "download their data",
                     "backup my data", "backup their data", "spreadsheet upload", "bulk import"),
        "purpose": "Lets a user or Admin move data into or out of the platform in bulk — importing existing records so they don't have to be re-entered one at a time, and exporting data for reporting, backup, or migration.",
        "actors": ["{seller}", "Admin"],
        "inputs": ["Source file (CSV/spreadsheet)", "Export filter/date-range selection"],
        "processing": ["Validate an uploaded file's structure and required fields before importing", "Report row-level import errors without discarding the rows that succeeded", "Assemble the requested export within the requesting user's access scope", "Generate a downloadable export file"],
        "outputs": ["Import result summary (succeeded/failed rows)", "Downloadable export file"],
        "business_rules": [
            "An import must validate every row before committing any of them, and must report exactly which rows failed and why rather than failing the whole batch silently.",
            "An export may only include data the requesting user/role is authorized to see.",
        ],
        "fr": [
            {"name": "Export Data", "description": "The system shall allow an authorized user to export a filtered set of their data (e.g. {item}s, {transaction}s) to a common file format (CSV), respecting the same access restrictions as viewing that data in-app.", "priority": "P2"},
            {"name": "Bulk Import Data", "description": "The system shall allow an authorized user to bulk-import records from a CSV/spreadsheet file, validating required fields and reporting row-level errors before committing successful rows.", "priority": "P2"},
            {"name": "Import Validation & Error Report", "description": "The system shall produce a clear, row-referenced error report for any import rows that failed validation, so the user can correct and re-submit just those rows.", "priority": "P2"},
        ],
        "entities": {"ImportExportJob": ["Job ID", "Type", "Requested by", "Status", "Row count", "Error count", "Created date"]},
        "notifications": ["Export ready", "Import completed", "Import completed with errors"],
    },
    {
        "key": "integrations_module", "name": "Third-Party Integrations",
        "keywords": ("integrat", "connect your", "connect to", "connect their", "sync with", "sync their",
                     "calendar", "webhook", "zapier", "slack", "google calendar", "third-party", "third party",
                     "plug in to", "api access"),
        "purpose": "Lets a user connect an external, third-party service to the platform so data or actions stay in sync without manual re-entry (e.g. a calendar, a messaging tool, or another business system).",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Third-party account authorization (OAuth or API key)", "Sync/connection settings"],
        "processing": ["Authenticate and authorize the connection to the third-party service", "Sync data between the platform and the connected service on the defined schedule/trigger", "Detect and surface sync failures rather than failing silently", "Allow the connection to be revoked"],
        "outputs": ["Active connection status", "Sync result/log", "Disconnected status"],
        "business_rules": [
            "A third-party connection must be re-authorizable and revocable by the user at any time from within the product.",
            "A sync failure must be surfaced to the user with a clear next step, never silently dropped.",
        ],
        "fr": [
            {"name": "Connect Third-Party Account", "description": "The system shall allow a user to authorize a connection to a supported third-party service and confirm the connection succeeded.", "priority": "P2"},
            {"name": "Manage Connected Integrations", "description": "The system shall let a user view their currently connected integrations and the data each one syncs.", "priority": "P2"},
            {"name": "Integration Sync Failure Handling", "description": "The system shall detect a failed sync with a connected third-party service and notify the affected user with a clear explanation and next step.", "priority": "P2"},
            {"name": "Disconnect Integration", "description": "The system shall allow a user to revoke/disconnect a previously connected third-party integration at any time.", "priority": "P2"},
        ],
        "entities": {"IntegrationConnection": ["Connection ID", "Account ID", "Provider", "Status", "Last synced", "Scopes granted"]},
        "notifications": ["Integration connected", "Sync failed", "Integration disconnected"],
    },
    {
        "key": "offline_sync", "name": "Offline Access & Synchronization",
        "keywords": ("offline", "no internet", "airplane mode", "works without", "local cache", "poor connectivity",
                     "low connectivity", "spotty connection"),
        "purpose": "Lets a user keep working when connectivity drops and reconciles their changes once the connection returns, so a temporary loss of network access doesn't block or lose their work.",
        "actors": ["{buyer}", "{seller}"],
        "inputs": ["Locally cached data", "Queued offline actions"],
        "processing": ["Cache the data a user needs for their core workflow for offline access", "Queue state-changing actions performed while offline", "Detect connectivity restoration and replay the queued actions", "Detect and surface conflicts between an offline change and a newer server-side change"],
        "outputs": ["Synced/up-to-date data", "Conflict requiring user resolution, where one exists"],
        "business_rules": [
            "An action performed offline must never be silently lost; it is either applied on reconnect or surfaced to the user as a conflict to resolve.",
            "The user must always be able to see whether the data they're viewing is fully synced or reflects a pending/queued state.",
        ],
        "fr": [
            {"name": "Offline Data Access", "description": "The system shall let a user view previously loaded, relevant data while offline, clearly indicating that the view may not reflect the latest server state.", "priority": "P2"},
            {"name": "Queue Actions While Offline", "description": "The system shall queue state-changing actions performed while offline and automatically attempt to apply them once connectivity is restored.", "priority": "P2"},
            {"name": "Conflict Resolution on Sync", "description": "The system shall detect a conflict between a queued offline change and a newer server-side change, and shall surface it to the user for resolution rather than silently overwriting either version.", "priority": "P2"},
            {"name": "Sync Status Indicator", "description": "The system shall show the user a clear, always-visible indicator of current sync status (synced, syncing, offline/pending).", "priority": "P3"},
        ],
        "entities": {"SyncQueueItem": ["Item ID", "Account ID", "Action type", "Payload summary", "Status", "Queued date", "Synced date"]},
        "notifications": ["Sync completed", "Sync conflict needs your attention"],
    },
    {
        "key": "subscription_billing", "name": "Subscription & Plan Management",
        "keywords": ("subscription", "recurring billing", "membership plan", "monthly plan", "annual plan",
                     "plan tier", "upgrade plan", "downgrade plan", "free trial", "premium plan", "pricing tier"),
        "purpose": "Lets a user choose, change, and pay for a recurring subscription plan, and gives the business a reliable way to gate premium functionality by the user's current plan/entitlement.",
        "actors": ["{buyer}", "{seller}", "Admin"],
        "inputs": ["Selected plan/tier", "Billing cycle", "Payment method"],
        "processing": ["Start a subscription on the selected plan and billing cycle", "Charge the recurring amount on each billing cycle via the payment processor", "Apply an upgrade/downgrade at the correct proration/effective point", "Handle a failed recurring charge with a defined retry and grace period", "Gate premium functionality based on the account's current entitlement"],
        "outputs": ["Active subscription status", "Updated entitlement", "Invoice/receipt"],
        "business_rules": [
            "A user's access to premium functionality must always reflect their current entitlement, re-evaluated on every relevant action, not just at login.",
            "A failed recurring charge must not immediately revoke access; the account enters a defined grace period with a clear notification before downgrade.",
            "Cancelling a subscription must be no more difficult than starting one, and must clearly state what happens to access and data at cancellation.",
        ],
        "fr": [
            {"name": "Select / Start Subscription Plan", "description": "The system shall let a user choose a subscription plan and billing cycle, review the price, and confirm to start the subscription.", "priority": "P1"},
            {"name": "Upgrade / Downgrade Plan", "description": "The system shall let a subscribed user change to a different plan, applying the platform's proration policy and updating entitlement at the correct effective point.", "priority": "P2"},
            {"name": "Cancel Subscription", "description": "The system shall let a user cancel their subscription, clearly stating what happens to access and data at cancellation and confirming the cancellation.", "priority": "P1"},
            {"name": "Failed Recurring Payment Handling", "description": "The system shall detect a failed recurring charge, notify the user, and apply the platform's grace-period policy before restricting access.", "priority": "P1"},
            {"name": "Entitlement Gating", "description": "The system shall gate access to plan-specific functionality based on the account's current entitlement, evaluated on each relevant action.", "priority": "P1"},
        ],
        "entities": {"Subscription": ["Subscription ID", "Account ID", "Plan", "Billing cycle", "Status", "Current period end", "Created date"]},
        "notifications": ["Subscription started", "Payment failed — grace period", "Subscription cancelled", "Plan changed"],
    },
]


def _idea_and_answers_text(context) -> str:
    parts = [context.business_idea_raw or ""]
    for q in context.discovery_questions:
        if q.answer:
            parts.append(str(q.answer))
    return (" " + " ".join(parts).lower() + " ")


def select_modules(context) -> list[dict]:
    """Pick the modules relevant to this project's domain and resolve every
    {buyer}/{seller}/{item}/.../placeholder against the domain vocabulary,
    returning fully-formatted module dicts ready to render.

    A module is included if it's always-on, if it's gated to this specific
    domain, OR if the raw business idea / discovery answers contain one of
    its trigger keywords — so a capability the idea clearly calls for (AI
    features, offline support, integrations, bulk import/export,
    subscriptions) is never silently dropped just because it isn't part of
    the fixed domain template, per the platform's completeness rules."""
    domain = context.domain_classification
    vocab = get_vocab(domain)
    idea_text = _idea_and_answers_text(context)
    selected = []
    for m in MODULE_LIBRARY:
        include = bool(m.get("always")) or domain in m.get("domains", ())
        if not include and m.get("keywords"):
            include = any(kw in idea_text for kw in m["keywords"])
        if not include:
            continue
        resolved = {
            "key": m["key"],
            "name": _fmt(m["name"], vocab),
            "purpose": _fmt(m["purpose"], vocab),
            "actors": _fmt(m["actors"], vocab),
            "inputs": _fmt(m["inputs"], vocab),
            "processing": _fmt(m["processing"], vocab),
            "outputs": _fmt(m["outputs"], vocab),
            "business_rules": _fmt(m["business_rules"], vocab),
            "fr": [{"name": _fmt(f["name"], vocab), "description": _fmt(f["description"], vocab), "priority": f["priority"]} for f in m["fr"]],
            "entities": {_fmt(ename, vocab): _fmt(fields, vocab) for ename, fields in m["entities"].items()},
            "notifications": _fmt(m["notifications"], vocab),
        }
        selected.append(resolved)
    return selected


# ---------------------------------------------------------------------------
# Personas, stakeholders, roles
# ---------------------------------------------------------------------------

def build_personas(context) -> list[dict]:
    vocab = get_vocab(context.domain_classification)
    answers = {q.category: q.answer for q in context.discovery_questions if q.answer}
    personas = [{
        "name": f"Primary {vocab['buyer']}",
        "role": answers.get("users", f"{vocab['buyer']} using the platform"),
        "occupation": "Represents the platform's core demand-side user",
        "goals": f"Find and complete a {vocab['transaction']} for the right {vocab['item']} with minimal friction",
        "needs": "A fast, trustworthy way to find, evaluate, and commit to the right option",
        "pain_points": "Today this requires manual effort, scattered information, or an unreliable ad-hoc process",
        "behaviors": "Compares a small number of options before committing; abandons if the process feels slow or untrustworthy",
        "expectations": "Clear pricing, fast confirmation, and visibility into status after committing",
    }]
    if any(m.get("domains") and context.domain_classification in m["domains"] and m["key"] in ("provider_management",) for m in MODULE_LIBRARY):
        personas.append({
            "name": f"Active {vocab['seller']}",
            "role": f"{vocab['seller']} offering {vocab['item']}s on the platform",
            "occupation": "Represents the platform's core supply-side user",
            "goals": f"Get discovered, win {vocab['transaction']}s, and get paid reliably",
            "needs": "Simple listing management, predictable payouts, and manageable operational overhead",
            "pain_points": "Manual coordination today is time-consuming and makes it hard to grow volume",
            "behaviors": f"Actively manages availability/listings; monitors ratings and {vocab['transaction']} requests closely",
            "expectations": "Low-friction onboarding, fair visibility, and timely payment",
        })
    personas.append({
        "name": "Operations / Admin User",
        "role": "Internal team member responsible for day-to-day platform operation",
        "occupation": "Operations or platform support staff",
        "goals": "Keep the platform running smoothly and resolve exceptions quickly",
        "needs": "A single place to see and act on flagged items, disputes, and support tickets",
        "pain_points": "Without dedicated tooling, exception-handling relies on ad-hoc manual work",
        "behaviors": "Monitors dashboards and exception queues; intervenes when automated flows break down",
        "expectations": "Accurate, real-time visibility and clear audit trails for every action taken",
    })
    return personas


def build_stakeholders() -> list[dict]:
    return [
        {"stakeholder": "Business Sponsor / Product Owner", "interest": "Accountable for the product's business outcomes and ROI", "authority": "Final sign-off on scope and priorities"},
        {"stakeholder": "Product Management", "interest": "Owns the product requirements and roadmap", "authority": "Decides feature scope and priority within budget"},
        {"stakeholder": "Design / UX", "interest": "Owns the user experience translating requirements into screens and flows", "authority": "Approves UX approach; escalates conflicts with requirements"},
        {"stakeholder": "Engineering", "interest": "Builds and maintains the system described in this document", "authority": "Approves technical feasibility and estimates"},
        {"stakeholder": "Operations", "interest": "Runs the platform day to day once live", "authority": "Input on admin/operations tooling requirements"},
        {"stakeholder": "Finance", "interest": "Cares about revenue, payment reconciliation, and payout accuracy", "authority": "Approves payment and reporting requirements"},
        {"stakeholder": "Customer Support", "interest": "Handles user-facing issues after launch", "authority": "Input on support tooling and escalation paths"},
        {"stakeholder": "Security / Compliance", "interest": "Ensures the product meets security and data-protection expectations", "authority": "Can block launch on unresolved security findings"},
        {"stakeholder": "QA", "interest": "Validates the product meets its documented requirements", "authority": "Sign-off on test coverage before release"},
        {"stakeholder": "End Users (Customers/Providers)", "interest": "Use the product to accomplish their goal", "authority": "Indirect — feedback informs prioritization"},
    ]


def build_roles(modules, context) -> list[dict]:
    vocab = get_vocab(context.domain_classification)
    roles = [{
        "role": vocab["buyer"], "purpose": f"The demand-side user who searches for and completes {vocab['transaction']}s.",
        "responsibilities": f"Search, evaluate, and commit to {vocab['item']}s; manage their own account and {vocab['transaction']} history.",
        "capabilities": f"Search/browse, create {vocab['transaction']}s, manage own profile, submit reviews, raise support tickets.",
        "permissions": "Full access to own data only", "restricted": "Cannot view or edit other users' data; cannot access Admin tooling.",
    }]
    if any(m["key"] == "provider_management" for m in modules):
        roles.append({
            "role": vocab["seller"], "purpose": f"The supply-side user who publishes {vocab['item']}s and fulfils {vocab['transaction']}s.",
            "responsibilities": f"Maintain {vocab['item']} listings, manage availability, fulfil {vocab['transaction']}s.",
            "capabilities": f"Create/edit own {vocab['item']}s, manage own availability, view own {vocab['transaction']}s and payouts.",
            "permissions": "Full access to own listings and transactions only", "restricted": f"Cannot view other {vocab['seller']}s' data; cannot moderate {vocab['item']}s or access Admin tooling.",
        })
    roles.append({
        "role": "Support Agent", "purpose": "Resolves user-reported issues and tickets.",
        "responsibilities": "Respond to and resolve support tickets; escalate where necessary.",
        "capabilities": f"View relevant {vocab['transaction']}/account context for a ticket; respond to and close tickets.",
        "permissions": "Read access to user/{transaction} data relevant to open tickets".format(**vocab),
        "restricted": "Cannot perform destructive admin overrides without escalation.",
    })
    roles.append({
        "role": "Admin", "purpose": "Operates and moderates the platform.",
        "responsibilities": f"Manage users, {vocab['item']}s, and {vocab['transaction']}s; moderate content; resolve disputes/exceptions.",
        "capabilities": "Full read access; manual overrides with recorded reason; access to reporting and audit logs.",
        "permissions": "Broadest access in the system", "restricted": "All actions are logged; destructive actions require explicit confirmation.",
    })
    return roles


# ---------------------------------------------------------------------------
# Flat requirement / rule lists with sequential IDs
# ---------------------------------------------------------------------------

def build_functional_requirements(modules) -> list[dict]:
    frs = []
    n = 1
    for m in modules:
        module_actor = _module_primary_actor(m, "Admin")
        prior_id_in_module = None
        for f in m["fr"]:
            fr_id = f"FR-{n:03d}"
            bucket = _classify_fr(f["name"], f["description"])
            # Dependencies: an edit/admin/browse/detail/settings action on a
            # module's own record generally can't happen before that
            # module's own "create" (or first) requirement exists; the
            # authentication module has no such prerequisite.
            if bucket != "create" and prior_id_in_module and m["key"] != "authentication":
                dependencies = [prior_id_in_module]
            elif m["key"] != "authentication" and n > 1:
                dependencies = ["FR-002"]  # Login — every other module requires an authenticated session
            else:
                dependencies = []
            frs.append({
                "id": fr_id, "name": f["name"], "description": f["description"],
                "actor": module_actor if bucket != "admin" else "Admin",
                "module": m["name"], "module_key": m["key"], "priority": f["priority"],
                "rationale": f"Directly supports this module's purpose: {m['purpose']}",
                "dependencies": dependencies,
                "acceptance_consideration": f"Considered met when the acting user can complete \"{f['name']}\" end-to-end and receives an explicit success or a specific, actionable error — not a silent failure.",
                "status": "Draft — pending stakeholder confirmation",
                "source": "Derived from discovery answers and the {} module baseline".format(m["name"]),
            })
            if bucket == "create":
                prior_id_in_module = fr_id
            n += 1
    return frs


def build_business_rules(modules) -> list[dict]:
    rules = []
    n = 1
    for m in modules:
        for r in m["business_rules"]:
            rules.append({"id": f"BR-{n:03d}", "rule": r, "module": m["name"]})
            n += 1
    return rules


NFR_BANK = [
    ("Performance", "The system shall respond to standard user-facing actions within 2 seconds under normal load.", "P0",
     "P95 response time for standard actions, measured via APM/monitoring tooling", "2 seconds (P95)", "Load testing prior to launch; ongoing APM monitoring in production", "All user-facing modules"),
    ("Performance", "Search and listing pages shall return results within 1.5 seconds for catalogs up to 100,000 items.", "P1",
     "P95 response time for search/listing queries", "1.5 seconds (P95) at up to 100,000 catalog items", "Load testing against a representative dataset size", "Search & Discovery"),
    ("Scalability", "The system shall support horizontal scaling of stateless application components as transaction volume grows.", "P1",
     "Ability to add application instances without a code change", "TBD — Requires Technical Confirmation (depends on chosen hosting/architecture)", "Architecture review; scaling/load test", "Platform / Infrastructure"),
    ("Scalability", "The data layer shall support at least 10x current expected launch volume without architectural rework.", "P2",
     "Headroom between launch volume and data-layer capacity", "10x launch volume", "Capacity planning review; load testing", "Platform / Infrastructure"),
    ("Availability", "Core user-facing functionality shall target 99.5% monthly uptime post-launch.", "P0",
     "Monthly uptime percentage for core user-facing functionality", "99.5% monthly", "Uptime monitoring against an SLO dashboard", "All user-facing modules"),
    ("Reliability", "A failed payment or network error shall never leave a transaction in an ambiguous or double-charged state.", "P0",
     "Rate of transactions left in an ambiguous/duplicate state after a failure", "0 duplicate-charge incidents", "Failure-injection/chaos testing on the transaction and payment flow", "Payments & Transactions"),
    ("Security", "All traffic between client and server shall be encrypted using TLS 1.2 or higher.", "P0",
     "Minimum TLS version accepted by the server", "TLS 1.2 or higher on all endpoints", "Automated TLS configuration scan", "Platform / Infrastructure"),
    ("Security", "The system shall enforce role-based access control on every state-changing server endpoint.", "P0",
     "Percentage of state-changing endpoints with a server-side permission check", "100% of state-changing endpoints", "Security code review; automated authorization test suite", "Authentication & Account Management"),
    ("Privacy", "Personally identifiable information shall be encrypted at rest and access-logged.", "P1",
     "Coverage of PII fields under encryption-at-rest and access logging", "100% of identified PII fields", "Data classification audit; access-log review", "Data Layer / All modules handling PII"),
    ("Accessibility", "All primary user flows shall meet WCAG 2.2 AA where applicable.", "P1",
     "WCAG 2.2 AA conformance across primary user flows", "WCAG 2.2 AA", "Automated accessibility scan plus manual keyboard/screen-reader pass", "All user-facing screens"),
    ("Usability", "First-time users shall be able to complete the core workflow without external instructions.", "P2",
     "First-time task success rate without external help in usability testing", "TBD — Requires Business Confirmation (target success rate)", "Moderated usability testing with representative users", "Core workflow screens"),
    ("Maintainability", "The codebase shall follow a documented architecture and coding standard to support ongoing maintenance.", "P2",
     "Adherence to the documented coding/architecture standard", "TBD — Requires Technical Confirmation", "Code review checklist; static analysis", "Engineering / All modules"),
    ("Compatibility", "The system shall support the latest two major versions of common desktop and mobile browsers.", "P1",
     "Browser/version coverage tested pre-release", "Latest 2 major versions of common desktop/mobile browsers", "Cross-browser test pass before each release", "All user-facing screens"),
    ("Monitoring", "The system shall emit structured logs and metrics sufficient to diagnose production incidents.", "P1",
     "Presence of structured logs/metrics on critical paths", "100% of critical paths instrumented", "Observability review during implementation", "Platform / Infrastructure"),
    ("Logging", "Security-relevant events (login, permission denial, payment) shall be logged with actor, timestamp, and outcome.", "P1",
     "Coverage of security-relevant events with actor/timestamp/outcome fields", "100% of identified security-relevant events", "Security/audit log review", "Authentication & Account Management, Payments & Transactions"),
    ("Backup", "Production data shall be backed up on a regular, automated schedule with tested restore procedures.", "P1",
     "Backup frequency and successful restore-test frequency", "TBD — Requires Technical Confirmation (backup cadence and retention)", "Scheduled restore drill", "Platform / Infrastructure"),
    ("Disaster Recovery", "A documented recovery plan shall define target recovery time and recovery point objectives.", "P2",
     "Existence and currency of a documented DR plan with RTO/RPO", "TBD — Requires Business/Technical Confirmation (RTO/RPO targets)", "DR plan review; recovery drill", "Platform / Infrastructure"),
    ("Localization", "Text content shall be externalized to support future localization, even if only one language ships at launch.", "P3",
     "Percentage of user-facing text externalized from code", "100% of user-facing strings externalized", "Code review; i18n lint check", "All user-facing screens"),
]


def build_nfrs() -> list[dict]:
    return [{
        "id": f"NFR-{i:03d}", "category": cat, "requirement": req, "description": req, "priority": pri,
        "measurement": measurement, "target": target, "verification_method": verification, "related_module": related_module,
        "dependencies": ["Hosting/infrastructure decision"] if related_module == "Platform / Infrastructure" else [],
        "source": "Non-functional baseline for platforms of this type; targets marked TBD require business/technical confirmation.",
        "status": "Draft — pending confirmation of any TBD targets",
    } for i, (cat, req, pri, measurement, target, verification, related_module) in enumerate(NFR_BANK, start=1)]


def build_data_model(modules, context) -> tuple[list[dict], list[str]]:
    vocab = get_vocab(context.domain_classification)
    entities = []
    for m in modules:
        for ename, fields in m["entities"].items():
            entities.append({"entity": ename, "fields": fields})
    relationships = [
        f"{vocab['buyer']} → {vocab['transaction']}s (one-to-many)",
        f"{vocab['seller']} → {vocab['item']}s (one-to-many)" if any(m["key"] == "catalog" for m in modules) else None,
        f"{vocab['item']} → {vocab['transaction']}s (one-to-many)",
        f"{vocab['transaction']} → Payment (one-to-one)" if any(m["key"] == "payments" for m in modules) else None,
        f"{vocab['transaction']} → Review (one-to-one, post-completion)" if any(m["key"] == "reviews" for m in modules) else None,
        f"{vocab['transaction']} → SupportTicket (one-to-many, optional)",
    ]
    return entities, [r for r in relationships if r]


def build_notifications_matrix(modules, context) -> list[dict]:
    vocab = get_vocab(context.domain_classification)
    rows = []
    for m in modules:
        for event in m["notifications"]:
            rows.append({
                "event": event,
                "buyer": "Yes" if any(k in m["key"] for k in ("authentication", "user_profile", "transaction", "payments", "reviews", "support", "scheduling", "notifications_module", "onboarding", "privacy_consent", "subscription_billing", "offline_sync", "integrations_module", "data_export_import")) else "—",
                "seller": "Yes" if m["key"] in ("catalog", "transaction", "provider_management", "payments", "scheduling", "reviews", "trust_safety", "fulfilment", "authentication", "support", "onboarding", "subscription_billing", "data_export_import", "integrations_module") else "—",
                "admin": "Yes" if m["key"] in ("provider_management", "trust_safety", "security", "admin_ops", "support", "privacy_consent", "data_export_import") else "—",
                "channel": "Email + In-app" if m["key"] in ("authentication", "payments", "subscription_billing", "privacy_consent") else "In-app + Push",
            })
    return rows


RISK_BANK = [
    ("Low initial adoption if onboarding friction is too high", "Business", "High", "Slower-than-planned growth and delayed ROI", "Streamline onboarding; measure and iterate on drop-off points"),
    ("Payment processor outage or integration failure", "Technical", "High", "Transactions cannot complete; direct revenue impact", "Select a processor with strong uptime SLAs; design graceful failure/retry handling"),
    ("Supply-demand imbalance (not enough sellers, or not enough buyers)", "Business", "Medium", "Poor marketplace liquidity undermines the core value proposition", "Sequence go-to-market to seed supply before scaling demand marketing, or vice versa"),
    ("Data breach exposing personal or payment information", "Security", "High", "Regulatory exposure, reputational damage, user trust loss", "Encrypt sensitive data, minimize retention, follow the security requirements in this document"),
    ("Regulatory/compliance requirements not yet confirmed for launch geography", "Compliance", "Medium", "Potential rework or launch delay if requirements surface late", "Confirm applicable regulations early with legal/compliance review"),
    ("Fraudulent transactions or fake accounts", "Operational", "Medium", "Financial loss and erosion of trust between parties", "Identity verification, rate limiting, anomaly monitoring on transactions"),
    ("Key third-party dependency (payments, notifications, maps) changes pricing or terms", "Operational", "Medium", "Unexpected cost or forced re-integration", "Abstract third-party integrations behind an internal interface where practical"),
    ("Scope creep beyond MVP during build", "Business", "Medium", "Delayed launch, diluted focus", "Enforce the MVP prioritization (P0/P1) in this document as the build contract"),
]


def build_risks() -> list[dict]:
    return [{"risk": r, "category": cat, "impact": i, "consequence": c, "mitigation": m} for r, cat, i, c, m in RISK_BANK]


def build_glossary(modules, context) -> list[dict]:
    vocab = get_vocab(context.domain_classification)
    terms = [
        {"term": vocab["buyer"], "definition": f"The demand-side user who searches for and completes a {vocab['transaction'].lower()}."},
        {"term": vocab["seller"], "definition": f"The supply-side user or party who offers a {vocab['item'].lower()} on the platform."},
        {"term": vocab["item"], "definition": "The core offering being discovered and transacted on the platform."},
        {"term": vocab["transaction"], "definition": f"A confirmed commitment between {vocab['buyer']} and {vocab['seller']} for a given {vocab['item'].lower()}."},
        {"term": "MVP", "definition": "Minimum Viable Product — the smallest release that delivers real value and validates the core hypothesis."},
        {"term": "P0 / P1 / P2 / P3", "definition": "Priority tiers used throughout this document: P0 = critical/blocking, P1 = must-have for MVP, P2 = should-have, P3 = could-have/future."},
        {"term": "RBAC", "definition": "Role-Based Access Control — restricting system actions based on a user's assigned role."},
        {"term": "SLA", "definition": "Service-Level Agreement/Target — a measurable commitment such as response time or uptime."},
        {"term": "TBD", "definition": "To Be Determined — a value intentionally left open pending further input, rather than invented."},
        {"term": "NFR", "definition": "Non-Functional Requirement — a quality attribute (performance, security, etc.) rather than a feature."},
    ]
    for m in modules:
        terms.append({"term": m["name"], "definition": m["purpose"]})
    return terms


def build_integrations(modules, context) -> list[dict]:
    integrations = [
        {"integration": "Payment Gateway", "purpose": "Processes payments, refunds, and (where applicable) seller payouts.", "requirements": "PCI-compliant; tokenized card storage; webhook support for async status updates. Vendor not assumed unless specified by the business."},
        {"integration": "Email Delivery", "purpose": "Sends transactional and account-related email notifications.", "requirements": "Reliable delivery, template support, bounce/complaint handling."},
        {"integration": "SMS / OTP Provider", "purpose": "Sends verification codes and time-sensitive SMS notifications.", "requirements": "Global delivery coverage as needed; delivery status callbacks."},
    ]
    if any(m["key"] == "scheduling" for m in modules) or "location" in _answers_text(context):
        integrations.append({"integration": "Maps / Geolocation", "purpose": "Address entry, distance/location-based search and display.", "requirements": "Geocoding and map display; vendor TBD."})
    integrations.append({"integration": "Analytics", "purpose": "Captures product usage events for the metrics defined in this document.", "requirements": "Event-based tracking; vendor TBD."})
    if any(m["key"] == "trust_safety" for m in modules):
        integrations.append({"integration": "Identity Verification", "purpose": "Verifies user-submitted identity documents.", "requirements": "Document capture and verification; vendor TBD."})
    if any(m["key"] == "ai_features" for m in modules):
        integrations.append({"integration": "AI / ML Provider", "purpose": "Supplies the recommendation/generation/prediction model behind the AI-Powered Features module.", "requirements": "Confidence score per response; bounded latency with a timeout; vendor/model TBD."})
    if any(m["key"] == "integrations_module" for m in modules):
        integrations.append({"integration": "Third-Party Connections (user-configured)", "purpose": "Supports the externally-connected services users link from the Third-Party Integrations module.", "requirements": "OAuth-based authorization where the provider supports it; revocable per user; specific providers TBD."})
    if any(m["key"] == "subscription_billing" for m in modules):
        integrations.append({"integration": "Recurring Billing Provider", "purpose": "Processes recurring subscription charges, retries, and dunning for the Subscription & Plan Management module.", "requirements": "Webhook support for payment success/failure events; PCI-compliant; vendor TBD."})
    return integrations


# ---------------------------------------------------------------------------
# User stories derived from functional requirements
# ---------------------------------------------------------------------------

def build_epics(modules) -> list[dict]:
    return [{"id": f"EPIC-{i:03d}", "name": m["name"], "description": m["purpose"]} for i, m in enumerate(modules, start=1)]


_STORY_FLOW_TEMPLATES = {
    "create": {
        "main_flow": lambda actor, clause: [
            f"{actor} opens the create/add action to {clause}",
            f"{actor} fills in the required fields",
            "System validates each required field as it is entered and again on submit",
            "System saves the new record (as Draft or Pending where the module defines that status)",
            "System confirms creation and displays the newly created record",
        ],
        "extra_ac": "Given {actor_l} submits the form with all required fields valid, when they confirm, then a new record is created and is immediately visible to {actor_l}.",
    },
    "edit": {
        "main_flow": lambda actor, clause: [
            f"{actor} opens the existing record they want to {clause}",
            f"{actor} changes the relevant field(s)",
            "System validates the changed field(s)",
            "System saves the update and reflects it immediately everywhere the record is shown",
        ],
        "extra_ac": "Given {actor_l} has unsaved changes, when they attempt to navigate away, then the system warns them before the changes are discarded.",
    },
    "admin": {
        "main_flow": lambda actor, clause: [
            f"{actor} opens the queue of items awaiting a decision",
            f"{actor} reviews the relevant details before deciding whether to {clause}",
            f"{actor} confirms the decision, optionally with a reason/note",
            "System applies the decision, updates the record's status, and records the action in the audit log",
            "System notifies the affected user(s) of the outcome",
        ],
        "extra_ac": "Given the action is destructive or high-impact, when {actor_l} confirms it, then the system records {actor_l}, a timestamp, and the stated reason in the audit log before applying it.",
    },
    "browse": {
        "main_flow": lambda actor, clause: [
            f"{actor} opens the relevant list/search screen",
            f"{actor} enters a query or applies filters/sort to {clause}",
            "System returns matching results, updating as the query or filters change",
            "System shows a clear empty state with guidance if no results match",
        ],
        "extra_ac": "Given no records match the current query or filters, when results are returned, then the system shows an explicit empty state rather than a blank screen.",
    },
    "settings": {
        "main_flow": lambda actor, clause: [
            f"{actor} opens their settings/preferences area",
            f"{actor} changes the relevant setting to {clause}",
            "System validates and saves the change",
            "System confirms the setting has been updated",
        ],
        "extra_ac": "Given {actor_l} changes a setting, when they navigate away and return, then the changed value has persisted.",
    },
    "detail": {
        "main_flow": lambda actor, clause: [
            f"{actor} navigates to the relevant screen",
            f"{actor} provides the information required to {clause}",
            "System validates the input",
            "System completes the action and confirms the result",
        ],
        "extra_ac": "Given {actor_l} meets the preconditions, when they {clause} with valid input, then the system completes the action and confirms it clearly.",
    },
}


def build_stories(frs, modules, context) -> list[dict]:
    vocab = get_vocab(context.domain_classification)
    module_to_epic = {m["key"]: f"EPIC-{i:03d}" for i, m in enumerate(modules, start=1)}
    module_actor = {m["key"]: (m["actors"][0] if m["actors"] else vocab["buyer"]) for m in modules}
    stories = []
    for i, fr in enumerate(frs, start=1):
        raw_actor = module_actor.get(fr["module_key"], vocab["buyer"])
        bucket = _classify_fr(fr["name"], fr["description"])
        # Cross-cutting FRs (security, RBAC) are attributed to "All roles"
        # for requirements purposes, but a user story needs a concrete
        # actor. Admin decisions (approve/reject/suspend/moderate) are
        # always actioned by Admin regardless of the module's usual actor
        # (e.g. suspending a Provider is something Admin does TO a
        # Provider, not something a Provider does to themselves).
        actor = "Admin" if (raw_actor == "All roles" or bucket == "admin") else raw_actor
        article = _article(actor)
        clause = _story_clause(fr["name"], fr["description"])
        # For admin/moderation actions, "their"/"them" in the FR description
        # refers to the target of the action (e.g. the Provider being
        # suspended), not to Admin — so it must stay third person rather
        # than being folded into a first-person "I/my" story statement.
        first_person_clause = clause if bucket == "admin" else _first_person_clause(clause)
        sid = f"US-{i:03d}"
        preconditions = f"{actor} is authenticated and has the permissions required for this action"
        if fr["module_key"] == "authentication":
            name_lower = fr["name"].lower()
            if "registration" in name_lower:
                preconditions = f"{actor} does not already have an account"
            elif "login" in name_lower:
                preconditions = f"{actor} has a registered, verified account"
            elif "password reset" in name_lower:
                preconditions = f"{actor} has a registered account with a verified identifier"
            elif "logout" in name_lower or "session" in name_lower:
                preconditions = f"{actor} currently has an active session"
            elif "verification" in name_lower:
                preconditions = f"{actor} has a registered account pending verification"
        template = _STORY_FLOW_TEMPLATES[bucket]
        stories.append({
            "id": sid, "epic_id": module_to_epic.get(fr["module_key"], "EPIC-001"),
            "feature": fr["name"], "role": actor,
            "story": f"As {article} {actor}, I want to {first_person_clause}, so that I can do so quickly, reliably, and with confidence the result is correct.",
            "business_value": fr["description"],
            "preconditions": preconditions,
            "trigger": f"{actor} initiates the '{fr['name']}' action",
            "main_flow": template["main_flow"](actor, clause),
            "alternative_flow": "None" if fr["priority"] in ("P0", "P1") else f"{actor} saves as draft and returns later, where applicable",
            "exception_flow": ("System rejects the decision if the record's state has since changed (e.g. already actioned by another Admin), and does not apply a partial update"
                               if bucket == "admin" else
                               "System displays a clear, specific error message and preserves the user's input for correction"),
            "business_rules": [b for b in next((m["business_rules"] for m in modules if m["key"] == fr["module_key"]), [])],
            "dependencies": list(fr.get("dependencies", [])),
            "acceptance_criteria": [
                template["extra_ac"].format(actor_l=actor.lower(), clause=clause),
                f"Given invalid or incomplete input, when {actor.lower()} attempts to {clause}, then the system rejects the action with a specific, actionable error message.",
                f"Given {actor.lower()} lacks the permissions required for this action, when they attempt to {clause}, then the system denies the action and does not reveal data beyond what {actor.lower()} is authorized to see.",
            ],
            "related_fr_ids": [fr["id"]],
        })

    # Second pass: derive cross-story dependencies for backlog planning, in
    # addition to the FR-level dependency each story already carries above.
    # ASSUMPTION: every story's own preconditions already require an
    # authenticated actor, so — beyond that module's own stories — every
    # story depends on the authentication module's "Login" story being
    # completed first. This is the one dependency we can derive reliably
    # from the generated content itself; anything more specific (e.g. a
    # payment story depending on a particular catalog story) would be an
    # invented sequencing decision, so it is left for the team to confirm
    # rather than guessed here.
    login_story = next(
        (s for s in stories
         if s["epic_id"] == module_to_epic.get("authentication") and "login" in s["feature"].lower()),
        None,
    )
    fr_to_story = {s["related_fr_ids"][0]: s["id"] for s in stories if s.get("related_fr_ids")}
    if login_story:
        for s in stories:
            if s["id"] == login_story["id"] or s["epic_id"] == login_story["epic_id"]:
                continue
            deps = {fr_to_story.get(d, d) for d in s["dependencies"]}
            deps.add(login_story["id"])
            s["dependencies"] = sorted(deps)
        # Translate the remaining same-module FR-level dependencies (e.g. an
        # Edit story depending on that module's Create FR) into story IDs too.
    for s in stories:
        s["dependencies"] = sorted({fr_to_story.get(d, d) for d in s["dependencies"]} - {s["id"]})

    return stories


def build_priorities(stories, frs) -> list[dict]:
    fr_priority = {fr["id"]: fr["priority"] for fr in frs}
    notes = {"P0": "Critical — required for core product operation", "P1": "Must-have for a usable MVP",
             "P2": "Should-have — important but can follow MVP", "P3": "Could-have — future enhancement"}
    out = []
    for s in stories:
        pri = fr_priority.get(s["related_fr_ids"][0], "P2") if s.get("related_fr_ids") else "P2"
        label = {"P0": "High", "P1": "High", "P2": "Medium", "P3": "Low"}[pri]
        out.append({"story_id": s["id"], "priority": label, "notes": notes[pri]})
    return out


# ---------------------------------------------------------------------------
# Screens and flows derived from modules + stories, for the UX spec
# ---------------------------------------------------------------------------

def build_screens(modules, stories, roles, context) -> list[dict]:
    vocab = get_vocab(context.domain_classification)
    role_names = [r["role"] for r in roles]
    screens = [{
        "id": "SCR-001", "name": "Sign Up / Log In", "purpose": "Authenticate the user or create a new account",
        "primary_role": role_names[0], "entry_points": ["First visit", "Logged-out state"], "exit_points": ["Dashboard"],
        "related_story_ids": [s["id"] for s in stories if s["epic_id"] == "EPIC-001"][:2],
        "related_requirement_ids": [s["related_fr_ids"][0] for s in stories if s["epic_id"] == "EPIC-001"][:2],
        "primary_actions": ["Sign up", "Log in"], "secondary_actions": ["Forgot password"],
        "navigation": "Entry point before any authenticated screen", "information_displayed": ["Sign-up/login form"],
        "data_required": ["Email/identifier", "Password"], "ui_elements_required": ["Text input", "Password input", "Submit button"],
        "permissions": "Public — no authentication required", "business_rules": ["Requires a valid, unique identifier"], "dependencies": [],
    }, {
        "id": "SCR-002", "name": "Dashboard / Home", "purpose": "Primary landing screen after authentication, orienting the user to their next action",
        "primary_role": role_names[0], "entry_points": ["Post sign-up/login"], "exit_points": [f"SCR-{i:03d}" for i in range(3, min(len(modules) + 2, 6))],
        "related_story_ids": [s["id"] for s in stories][:5], "related_requirement_ids": [s["related_fr_ids"][0] for s in stories][:5],
        "primary_actions": ["Navigate to core workflow"], "secondary_actions": ["Access settings"],
        "navigation": "Reached immediately after authentication; primary hub for navigation", "information_displayed": ["Summary of recent/upcoming activity"],
        "data_required": [f"{vocab['buyer']}'s recent {vocab['transaction']}s"], "ui_elements_required": ["Navigation menu", "Activity summary", "Primary call-to-action"],
        "permissions": f"Authenticated {role_names[0]}", "business_rules": [], "dependencies": ["SCR-001"],
    }]

    # A module with several distinct kinds of requirement (browse vs. create
    # vs. admin decision, etc.) genuinely needs several distinct screens —
    # collapsing them into one generic screen is exactly the kind of
    # under-specified UX spec this builder exists to avoid. Each screen
    # below is scoped to one bucket of that module's actual requirements, so
    # its content (actions, data, UI elements) comes from those specific
    # requirements and entity fields rather than a generic filler sentence.
    frs = build_functional_requirements(modules)
    fr_by_module: dict[str, list] = {}
    for fr in frs:
        fr_by_module.setdefault(fr["module_key"], []).append(fr)
    story_by_fr = {s["related_fr_ids"][0]: s["id"] for s in stories if s.get("related_fr_ids")}

    screen_labels = {"browse": "Browse & Search", "create": "Create / Edit", "detail": "Detail / Overview",
                      "settings": "Settings", "admin": "Admin / Moderation"}
    ui_elements = {
        "browse": ["Search input", "Filter controls", "Sort dropdown", "Results list/grid", "Empty state"],
        "create": ["Form fields", "Save button", "Cancel button", "Inline validation messages"],
        "detail": ["Detail/summary layout", "Primary action button(s)", "Related information panel"],
        "settings": ["Form fields", "Toggle controls", "Save button"],
        "admin": ["Data table / queue", "Approve/Reject controls", "Filter controls", "Audit trail panel"],
    }

    i = 3
    for idx, m in enumerate(modules, start=1):
        if m["key"] in ("authentication", "security", "notifications_module"):
            continue
        module_frs = fr_by_module.get(m["key"], [])
        buckets: dict[str, list] = {}
        for fr in module_frs:
            b = _classify_fr(fr["name"], fr["description"])
            key = "create" if b == "edit" else b
            buckets.setdefault(key, []).append(fr)
        if not buckets:
            buckets["detail"] = module_frs
        multi = len(buckets) > 1
        entity_items = list(m["entities"].items())

        for key in ("browse", "create", "detail", "settings", "admin"):
            if key not in buckets:
                continue
            group = buckets[key]
            label = screen_labels[key]
            screen_name = f"{m['name']} — {label}" if multi else m["name"]
            related_story_ids = [story_by_fr[fr["id"]] for fr in group if fr["id"] in story_by_fr]
            related_requirement_ids = [fr["id"] for fr in group]
            actor_here = "Admin" if key == "admin" else _module_primary_actor(m, role_names[0])
            info_displayed = [f"{fr['name']}: {fr['description']}" for fr in group][:4]
            if entity_items:
                ename, fields = entity_items[0]
                data_required = [f"{ename} — {', '.join(fields[:5])}"]
            else:
                data_required = [f"Input required for: {', '.join(fr['name'] for fr in group)}"]
            screens.append({
                "id": f"SCR-{i:03d}", "name": screen_name,
                "purpose": f"{label} for {m['name']}: " + "; ".join(fr["name"] for fr in group),
                "primary_role": actor_here,
                "entry_points": ["SCR-002"] if key != "admin" else ["Admin-only navigation menu"],
                "exit_points": ["SCR-002"],
                "related_story_ids": related_story_ids, "related_requirement_ids": related_requirement_ids,
                "primary_actions": [fr["name"] for fr in group],
                "secondary_actions": ["Clear filters"] if key == "browse" else ["Cancel", "Go back"],
                "navigation": (f"Reached from the Dashboard via {m['name']} navigation" if key != "admin"
                               else "Reached from the Admin-only navigation area; not shown to other roles"),
                "information_displayed": info_displayed,
                "data_required": data_required,
                "ui_elements_required": ui_elements[key],
                "permissions": f"Authenticated {actor_here}" if key != "admin" else "Admin role only",
                "business_rules": m["business_rules"][:3],
                "dependencies": ["SCR-002"],
            })
            i += 1
    return screens


def build_flows(stories, screens, context) -> list[dict]:
    story_screen = {}
    for sc in screens:
        for sid in sc.get("related_story_ids", []):
            story_screen.setdefault(sid, sc["id"])
    flows = []
    for i, s in enumerate(stories, start=1):
        target_screen = story_screen.get(s["id"], "SCR-002")
        flows.append({
            "id": f"FLOW-{i:03d}", "name": f"Flow: {s['feature']}", "actor": s["role"], "goal": s["business_value"],
            "starting_point": "Dashboard", "preconditions": s["preconditions"],
            "main_path": [f"{step} ({target_screen})" if idx == 1 else step for idx, step in enumerate(s["main_flow"], start=1)],
            "alternative_paths": [s["alternative_flow"]], "error_paths": [s["exception_flow"]],
            "decision_points": [], "completion_state": "Action completed and confirmed to the user",
            "related_screen_ids": ["SCR-002", target_screen], "related_requirement_ids": s["related_fr_ids"], "related_story_ids": [s["id"]],
        })
    return flows
