-- Run this in Supabase: Project → SQL Editor → New Query → paste → Run.
-- Fully idempotent — safe to re-run this whole file anytime (e.g. after
-- pulling an update that adds a new table), even if some of it already
-- exists. Every CREATE is guarded, and policies are dropped-then-recreated
-- rather than using a bare CREATE POLICY, since Postgres doesn't support
-- "CREATE POLICY IF NOT EXISTS" reliably.
-- Creates the `domains` table backing SupabaseKnowledgeStore.

create table if not exists domains (
  slug text primary key,
  name text not null,
  description text not null,
  typical_modules jsonb not null default '[]'::jsonb,
  seed_questions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

-- Row Level Security: Supabase enables this by default on new projects,
-- and with no policy, ALL access is blocked — the app would fail to read
-- or write anything. This policy opens read/write to anyone holding the
-- anon key, which is fine for a POC using the anon key server-side, but
-- NOT something to carry into a real multi-user product (that needs
-- per-user policies, most likely tied to Supabase Auth).
alter table domains enable row level security;

drop policy if exists "poc demo — allow all" on domains;
create policy "poc demo — allow all"
  on domains
  for all
  using (true)
  with check (true);

-- Optional: seed the 3 starter domains directly in SQL, so a fresh
-- Supabase project has them without needing to run bootstrap_seed_data.py
-- first. The Python bootstrap() function does the same thing and is
-- idempotent either way, so running both is harmless.
insert into domains (slug, name, description, typical_modules, seed_questions)
values
  ('booking_platform', 'Booking Platform',
   'A service where customers schedule appointments or reservations with providers (e.g. home services, salons, consultations).',
   '["provider/vendor profiles", "availability & scheduling", "booking & cancellation flow", "payments", "reviews & ratings", "notifications/reminders"]'::jsonb,
   '[{"id":"bp_users","text":"Who books — individuals, businesses, or both?","category":"users"},
     {"id":"bp_providers","text":"How do service providers get onboarded — self-signup or vetted by you?","category":"operations"},
     {"id":"bp_scheduling","text":"Do providers set their own availability, or is it assigned?","category":"scheduling"},
     {"id":"bp_payment","text":"Is payment taken at booking, after service, or both?","category":"payments"},
     {"id":"bp_cancellation","text":"What is your cancellation/refund policy?","category":"policy"}]'::jsonb),

  ('e_commerce', 'E-Commerce',
   'A platform for browsing and purchasing physical or digital products online.',
   '["product catalog", "cart & checkout", "payments", "inventory management", "shipping/fulfilment", "order tracking"]'::jsonb,
   '[{"id":"ec_catalog_size","text":"Roughly how many products, and do you manage your own inventory?","category":"catalog"},
     {"id":"ec_fulfilment","text":"Who handles shipping — you, a third party, or dropshipping?","category":"fulfilment"},
     {"id":"ec_payment","text":"What payment methods do you need to support?","category":"payments"},
     {"id":"ec_returns","text":"What is your returns/refunds process?","category":"policy"}]'::jsonb),

  ('marketplace', 'Marketplace',
   'A two-sided platform connecting independent buyers and sellers, where the platform does not own the inventory/service itself.',
   '["buyer & seller profiles", "listing management", "search & discovery", "messaging between parties", "payments & payouts", "trust & safety"]'::jsonb,
   '[{"id":"mk_sides","text":"Who are the two sides of your marketplace?","category":"users"},
     {"id":"mk_revenue","text":"How does the platform make money — commission, subscription, listing fees?","category":"business_model"},
     {"id":"mk_trust","text":"How will you build trust between strangers transacting?","category":"trust_safety"},
     {"id":"mk_matching","text":"How do buyers and sellers find each other?","category":"discovery"}]'::jsonb)
on conflict (slug) do nothing;

-- ---------------------------------------------------------------------
-- Projects table: persists completed projects so they survive server
-- restarts (Render's free tier definitely doesn't guarantee memory
-- persistence) and can be browsed later from the History view.
-- ---------------------------------------------------------------------

create table if not exists projects (
  id text primary key,
  business_idea text not null,
  domain text,
  domain_confidence real,
  stage text not null default 'complete',
  qa_readiness text,
  consistency_notes jsonb not null default '[]'::jsonb,
  artefacts jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

alter table projects enable row level security;

drop policy if exists "poc demo — allow all" on projects;
create policy "poc demo — allow all"
  on projects
  for all
  using (true)
  with check (true);

create index if not exists projects_created_at_idx on projects (created_at desc);
