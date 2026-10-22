# Project Status

## Phase 1 — Scaffold
- [x] Initial Django project structure
- [x] Local development settings
- [x] Basic homepage
- [x] Health endpoint
- [x] Custom user model (buyer and seller roles)
- [x] Registration, login and logout
- [x] Seller product listings with image upload and owner-only editing
- [x] Public listing search, category filtering and product detail pages
- [x] All 16 Ghana regions on account and listing forms, plus homepage and listing filters
- [x] Listing sorting by recency or price and responsive marketplace browsing
- [x] Seller listings are private until an admin approves them; edits return to review
- [x] Admin approve, reject, remove and user account controls with visible review queues
- [x] Buyer reporting for suspicious listings and admin report handling
- [x] Listing-specific buyer and seller messaging with participant-only inbox and threads
- [x] Idempotent demo catalogue seed with clearly marked representative photography and non-contactable listings
- [x] Automated account, listing, report and admin approval tests
- [x] Initial database migration generated and applied locally
- [x] Messaging database migration generated and applied locally
- [x] Django system check and full automated test suite (63 tests at the latest admin-dashboard update)
- [ ] PostgreSQL production configuration

## Next phases
1. Email and seller identity/phone verification
2. Decide listing fee, launch-period policy and payment provider before enabling charges
3. Orders and checkout
4. React Native + Expo mobile app
5. Security, deployment, backups and launch readiness

## Marketplace experience update — 2026-10-20
- [x] Refreshed shared navigation and marketplace colours to emerald, black, white, and neutral grey; updated homepage headline and supporting copy
- [x] Added database-backed saved listings with unique per-user favourites, a saved-items page, and CSRF-protected toggle actions
- [x] Added combined minimum/maximum GHS price and condition filters to browse; query parameters remain in pagination links
- [x] Added regression coverage for combined price/condition filters and saving/removing listings
- [ ] Seller verification, verified-seller filters, ratings, and trusted storefront claims remain unavailable because the current account model has no verification or rating data
- [ ] Category-specific specifications, mobile money/card checkout, delivery, and formal legal/help pages remain future integrations; no payment or trust status is implied in the interface

The saved-listings feature adds migration `0009_favorite`. The local SQLite database has been migrated. No other database changes are required for this update.

## Launch-readiness audit update — 2026-10-20
- [x] Reject listing photo uploads larger than 5 MB each; Django/Pillow continues to validate image content and the existing eight-photo maximum remains in force
- [x] Add regression coverage for oversized and invalid image uploads
- [x] Replace silent PostgreSQL-to-SQLite fallback with standard-library PostgreSQL URL parsing and explicit configuration errors
- [x] Add regression coverage for PostgreSQL URL credentials, port, SSL mode, required fields, and unsupported options
- [x] Require a non-placeholder production secret key and explicit production host list; enable HTTPS redirect when `DEBUG=False`
- [x] Add seller-owned listing deactivation and resubmission for admin review without deleting associated records
- [x] Test seller status changes and reject access to another seller's listing
- [x] Add account settings for user name, email, phone, city, and Ghana region, with login and seller profile validation
- [x] Test profile settings access, saving, and required seller location fields
- [ ] Permanent seller listing deletion, upload aggregate request limits, throttling, expanded category-specific fields, and production deployment checks remain outstanding

The upload limit, database URL parsing, and seller status actions require no migration. PostgreSQL support continues to use the existing `psycopg` dependency; no new package was added. Local run commands remain unchanged. PostgreSQL connectivity and a production deployment were not tested in this local environment.

## Admin control-centre update — 2026-10-20
- [x] Add a permission-filtered admin sidebar, review/report queue alerts, and live marketplace overview metrics
- [x] Add 7/30/90-day listing, registration, and report charts with current category and Ghana-region counts; preview listings are excluded
- [x] Add read-only Django audit-log access and record listing moderation, report resolution, and member suspension/reactivation actions
- [x] Add protected, reversible member account suspension/reactivation and reviewed restoration of moderation-removed listings
- [x] Add tests for dashboard permissions, analytics periods and data, account-action protections, audit history, listing restoration, and admin search/filters/pagination
- [ ] Orders, payments, refunds, promotions, and database-managed categories remain unavailable because the project does not contain those models or integrations

The admin improvements require no database migration or new package. The complete local Django suite passes 63 tests. Deployment-mode security checks still require production secrets, HTTPS, secure cookies, and a deliberate HSTS policy.

The marketplace foundation and sample preview catalogue are implemented and verified locally. Sample products and photos are illustrative, not real inventory. The platform is not ready for production or real payments.

## Public UI/UX redesign — 2026-10-22
- [x] Rebuilt the public site in a Jiji/Tonaton-style classifieds layout: sticky green header with region + keyword search and gold SELL button, scrolling category strip, and account dropdown
- [x] Homepage: compact hero, category tiles (mobile) / category sidebar with counts (desktop), dense "Trending in Ghana" grid, region chips, shop row, trust strip, and sell banner
- [x] Listing cards lead with price (whole cedis shown without `.00`), 2-line titles, condition tag, photo count, heart overlay, and short "2d ago" ages (`marketplace/templatetags/market.py`)
- [x] Browse: scrollable category chips, collapsible filters on mobile, price range, condition pills, sort-on-change, removable active-filter chips, and breadcrumbs
- [x] Listing page: gallery, sticky price/seller column, member-since and active-ad count, quick-reply chat prompts, safety tips, similar ads, and a sticky mobile Chat bar
- [x] Restyled post-an-ad (3 steps, sticky submit), seller dashboard, storefront, inbox and chat thread (bubble layout), sign-in, register, and settings pages
- [x] Fixed the broken listing grid: UTF-8 byte-order marks at the start of `_product_card.html` and `home.html` rendered as an empty grid cell before every card. Save templates as UTF-8 **without BOM**
- [x] Listing-page context is built in one `_detail_context` helper so form-error re-renders keep the gallery, chat and similar ads
- [x] `sell_url` and `nav_categories` are provided by the `marketplace_nav` context processor
- [x] Django test suite passes (64 tests)

No migrations or new packages. The previous stylesheet was replaced in full; admin styling (`admin-review.css`) is unchanged.

## Full marketplace build-out — 2026-10-22 (stages 1–10)
Database backups taken before each migration batch (kept outside the project). Test suite: 64 → 163 tests, all passing. `check --deploy` clean apart from opt-in HSTS subdomain/preload.

**Stage 2 – Security**
- [x] Login lockout per account and per IP, rate limits on password reset, registration, messages, reports, support requests and new listings (cache-backed; set `REDIS_URL` in production)
- [x] Password reset flow (no account enumeration); production email, CSRF trusted origins, proxy/HSTS settings, referrer policy, upload limits, logging
- [x] Safe permanent listing deletion (refused when conversations or reports exist; files removed)
- [x] Tests no longer write into the real `media/` or `private_media/` folders

**Stage 4/5 – Categories, search, discovery**
- [x] Admin-managed `Category` tree (17 launch categories, 63 subcategories) and `CategoryAttribute` fields; existing listings migrated in place
- [x] Category-first listing flow with category-specific fields, price labels and validation
- [x] Attribute filters (number ranges, choices, yes/no, text), subcategory chips, removable filter chips, verified-seller filter
- [x] Multi-word search with relevance sort, header suggestions (categories + titles + on-device recent searches), popular searches, recently viewed, all-categories page, 24 per page, database indexes

**Stage 6 – Commerce (`commerce` app)**
- [x] Per-listing selling methods (chat, online checkout, or both) and stock; checkout disabled per category where inappropriate
- [x] Cart, checkout split into one order per seller, saved addresses, admin-defined delivery options (only free collection seeded)
- [x] Stock reservation with row locks; expiry via `expire_checkouts`
- [x] Payment provider layer: Paystack (Mobile Money + card, signed webhooks, verify, refund) and a DEBUG-only test provider
- [x] Paid status only from server verification; amount/currency checks; idempotent and duplicate-safe; late payments flagged for refund
- [x] Order state machine with audit trail, seller fulfilment pages, buyer confirmation, seller cancellation with automatic refund and restock, partial/full refunds, cancellation/return/refund/dispute requests
- [x] In-app notifications with email copies

**Stage 7 – Trust and safety**
- [x] Seller verification (Ghana Card or business) with private document storage, staff-only viewing, approve/reject with notifications; badge only after approval
- [x] Reviews limited to completed orders, one per order; ratings shown only when earned
- [x] Block users (both directions), report users, banned/flagged terms, duplicate and copied-listing flags, restricted categories
- [x] Help centre (buying, selling, safety, prohibited items, refunds, fees, privacy, terms), support/appeal form, account deletion with anonymisation

**Stage 8 – Admin control room**
- [x] Permission-aware queues for verifications, user reports, support, order issues, failed refunds and flagged payments; 30-day verified sales metrics
- [x] Analytics: paid value, average order, refunds, payment success rate, daily paid orders, fulfilment status, payment methods
- [x] Read-only financial records, reconciliation and refund actions with permissions and audit log entries

**Stage 9 – Performance and mobile**
- [x] Uploaded photos auto-rotated, capped at 1600px and re-encoded (removes EXIF/GPS); 480px card and 160px list thumbnails
- [x] Double-submit protection, hashed static files in production, lazy images, mid-width header layout

**Outstanding (needs credentials or decisions)** — see README "Known limitations" and `DEPLOYMENT.md`: Paystack keys and live testing, seller payouts, SMTP, SMS provider, legal review of policy pages, delivery fees, PostgreSQL/Redis hosting.
