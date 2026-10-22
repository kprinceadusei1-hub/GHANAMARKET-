# Production deployment checklist

This checklist covers what must be in place before GhanaMarket takes real users or real money.
Items marked **(you)** need accounts, credentials or decisions only the business can provide.

## 1. Infrastructure
- [ ] Linux server or PaaS running Python 3.12 behind a web server/proxy (e.g. Nginx) with HTTPS.
- [ ] PostgreSQL database; set `DATABASE_URL` (include `?sslmode=require` for managed databases).
- [ ] Redis; set `REDIS_URL` so login, messaging and report rate limits apply across all workers.
- [ ] Run the app with a WSGI server (e.g. `gunicorn config.wsgi`), not `runserver`.
- [ ] Serve `STATIC_ROOT` (after `collectstatic`) and `MEDIA_ROOT` from the web server.
- [ ] Put `PRIVATE_MEDIA_ROOT` **outside** any web-served directory. Identity documents are only served through the staff-only view.
- [ ] Automated daily database backups plus backups of `MEDIA_ROOT` and `PRIVATE_MEDIA_ROOT`, with a tested restore.

## 2. Environment
- [ ] `DJANGO_DEBUG=False`, unique `DJANGO_SECRET_KEY` (50+ characters), `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`.
- [ ] Behind a proxy: `DJANGO_SECURE_PROXY_SSL_HEADER=True`, and `DJANGO_TRUST_X_FORWARDED_FOR=True` only if the proxy overwrites that header.
- [ ] HSTS: set `DJANGO_SECURE_HSTS_SECONDS` once HTTPS is confirmed everywhere; consider subdomains/preload deliberately.
- [ ] Email: `EMAIL_HOST`, credentials and `DEFAULT_FROM_EMAIL` **(you)**. Password reset and notifications depend on it.
- [ ] `python manage.py check --deploy` shows no unexpected warnings.

## 3. Payments (Paystack) **(you)**
- [ ] Create and verify a Paystack business account for Ghana and enable Mobile Money and card channels.
- [ ] Start with test keys: `PAYMENT_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY=sk_test_...`.
- [ ] In the Paystack dashboard set the webhook URL to `https://<your-domain>/payments/webhooks/paystack/`.
- [ ] Run end-to-end test payments (Mobile Money and card): success, failure, abandoned payment, webhook arriving before and after the browser returns, a partial and a full refund.
- [ ] Decide how sellers receive their money. **Seller payouts are not automated in this codebase**: payments land in the platform's Paystack balance. Either settle with sellers manually from the paid order records, or implement Paystack subaccounts/split payments before launch.
- [ ] Switch to live keys only after the above passes. The `test` provider is refused automatically when `DEBUG=False`.

## 4. Scheduled jobs
- [ ] Every 5 minutes: `python manage.py expire_checkouts` (releases stock held by unpaid checkouts).
- [ ] Daily: review the admin "Payments needing attention" and "Failed refunds" queues; use the **Re-verify with provider** action to reconcile.

## 5. Launch content and operations **(you)**
- [ ] Have a lawyer review the Terms, Privacy, Refunds and Prohibited Items pages under `templates/help/`, including Ghana's Data Protection Act, 2012 (Act 843) registration requirements.
- [ ] Add paid delivery options and fees in **Admin → Delivery options** (only free collection is seeded).
- [ ] Add blocked and flagged words in **Admin → Prohibited terms**.
- [ ] Review categories and category fields in **Admin → Categories**; mark regulated ones as restricted.
- [ ] Create staff groups with least-privilege permissions (moderators, support, finance). Only finance staff should have `Can add refund`.
- [ ] Remove the preview catalogue (`is_demo` listings and the `marketplace-preview-seller` account).
- [ ] Set `SUPPORT_EMAIL` and staff the support and verification queues.

## 6. Release steps
```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test
```
