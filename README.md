# GhanaMarket (Africa Marketplace, Ghana-first)

A Django marketplace that combines classified ads (chat with the seller, negotiate, meet) with online
checkout (cart, Mobile Money/card payment, orders, delivery). Built for Ghana first, with country,
currency, categories, delivery options and payment provider all configurable.

## Architecture
- **Backend:** Python 3.12, Django 5.2, server-rendered templates, plain CSS and small vanilla JS files (no build step).
- **Apps:**
  - `marketplace`: accounts, categories, listings, search, messaging, favourites, notifications, trust and safety, help centre, admin control room.
  - `commerce`: cart, checkout, orders, delivery options, payments (provider layer in `commerce/payments/`), refunds, order issues.
- **Business rules** live in service modules, not views: `commerce/services.py` (stock, checkout, payment confirmation, order states, refunds), `marketplace/catalog.py` (search and filters), `marketplace/trust.py` (risk checks, ratings, account deletion), `marketplace/images.py` (photo processing).
- **Database:** SQLite locally; PostgreSQL in production via `DATABASE_URL`.

## Quick start (Windows PowerShell)
Open a terminal in this folder (the one containing `manage.py`). In VS Code you can also run **Terminal → Run Task → Run Africa Marketplace (Django)**.

```powershell
copy .env.example .env          # DEBUG is off unless .env says DJANGO_DEBUG=True
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```
Open http://127.0.0.1:8000/ (site) and http://127.0.0.1:8000/admin/ (control room).

- `manage.py seed_demo_marketplace`: optional preview catalogue, clearly labelled "Preview example" and never buyable; remove with `--delete` or the admin button.
- `manage.py seed_categories`: restores any missing launch categories (already run by migrations).
- `manage.py expire_checkouts`: releases stock from unpaid checkouts. Schedule it every few minutes in production.

### Trying online checkout locally
With `DEBUG=True`, the payment provider defaults to **test mode**: the "Pay" button opens a clearly labelled in-app page where you choose *Simulate successful payment* or *Simulate failed payment*. No money moves, and the same server-side verification path as a real provider is used. To sell online, a seller ticks **Sell online with checkout** on a listing (not available in property, jobs, services or vehicles by default) and sets the units available.

## Features
**New since the first release:** live chat (instant send, new messages every few seconds, "Seen" receipts) open to any signed-in user; call / text / WhatsApp the seller after an authenticated "Show contact" (sellers can hide their number); request a call back; Jiji-style seller box (time on GhanaMarket, Verified ID, real reply speed, feedback); Ghana Card step for new sellers with a staff verification desk (card photo in the panel, automatic warnings such as a card number reused on another account, one-step approve + badge); "Near me" filter and sort; Ghana town suggestions; two-pane category menu and sidebar with live counts and category search; full-screen photo viewer.

**Buyers:** search with suggestions, recent and popular searches; category, subcategory, region, price, condition and category-specific filters (e.g. year/mileage for cars, bedrooms for property); verified-seller filter; listing pages with gallery, seller rating and verification, safety tips and similar ads; recently viewed; favourites; private chat with quick replies; cart and checkout split by seller; saved addresses; order tracking; confirm receipt; return/refund/dispute requests; seller reviews after completed orders; block and report users; notifications; password reset; account deletion.

**Sellers:** guided category-first listing form with category-specific fields; up to 8 photos (auto-rotated, resized, location metadata removed); choose chat, online checkout or both; stock; dashboard with status filters; deactivate, resubmit and delete; paid order queue with status updates and tracking reference; cancel with automatic full refund; identity/business verification; storefront with reviews.

**Staff (admin control room):**
- Live queues: listing review, listing and user reports, verifications, support requests and appeals, order issues, failed refunds, and payments needing attention.
- 7/30/90-day analytics covering listings, users, reports, verified sales, refunds, payment success rate and payment methods.
- Category and attribute management, delivery options with fees, banned and flagged terms, and search-term moderation.
- Payment reconciliation ("re-verify with provider") and full refunds through the provider. Both are permission-gated and recorded in the audit log.

## Security and integrity
- Orders are marked paid **only** after server-side verification with the provider (API verify or signed webhook). Browser redirects never mark anything as paid. Amount and currency must match, duplicate webhooks are ignored, payments arriving after expiry are flagged for refund, and stock is reserved with row locks.
- Rate limits on login (per account and IP), password reset, registration, messages, reports, support requests and new listings.
- Identity documents are stored outside `MEDIA_ROOT` and served only to staff with permission. Uploads are type- and signature-checked.
- Owner checks on every seller, buyer and order view; safe redirects; CSRF on all forms except the signature-verified webhook.
- Production settings refuse placeholder secrets, require explicit hosts and SMTP, enable secure cookies and HTTPS redirect, and refuse the test payment provider.

## Tests
```powershell
.\.venv\Scripts\python.exe manage.py test
```
290 tests cover accounts, permissions (including admin privilege escalation), listings, categories and attribute filters, search, messaging, live chat and blocking, reports, checkout and stock (including reservations during seller edits), payment verification, webhooks, duplicates and provider outages, late/duplicate-payment refunds, refund reconciliation, order state rules, verification and the Ghana Card step, reviews, image processing (including oversized images), admin queues and analytics, rate limits, account deletion and accessibility of form errors. Tests write uploads to a temporary folder, never to `media/`.

Browser checks (Edge, desktop and phone sizes) were also run for the header, category menu and sidebar, photo viewer, live chat and a complete purchase with the test payment provider.

## Configuration
See `.env.example` for every setting and `DEPLOYMENT.md` for the production checklist.

## Known limitations (not implemented yet)
- **Seller payouts** are not automated. Payments arrive in the platform's Paystack balance; settle manually or add Paystack subaccounts/split payments.
- **Paystack** is implemented against its documented API and tested with mocked responses only. No live or sandbox Paystack calls have been made, because there are no credentials yet.
- **SMS** (OTP phone verification, SMS notifications) needs an SMS provider; email and in-app notifications work.
- **Product variants** (size/colour stock), product comparison, and paid promotions/boosted ads are not built.
- **Delivery** uses admin-defined flat fees per region with a free-text tracking reference; no courier API integration.
- **Search** uses database matching with relevance ranking; PostgreSQL full-text or a search engine can be added behind `marketplace/catalog.py` when traffic needs it.
- **Ghana regions** are a code enum (`GhanaRegion`); adding countries needs a region model.
- The help and policy pages are plain-language drafts and need legal review before launch.
- Paystack **refund webhooks** are not processed; refunds still "requested" are reconciled with the admin action "Re-check selected refunds with the provider".
- "Buy now" adds the item to the existing cart, so other cart items are bought too.
- Staff decisions on order issues (e.g. accepting a cancellation request) do not change the order automatically; staff cancel or refund it separately.
- Chat messages of a deleted account are kept for the other person; identity documents are deleted.
