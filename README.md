<!-- Setup, security, operations, and development guide for Prestizni Web. -->
# Prestizni Web

A private community for the students of SPŠE Ostrava. Members can share memes, quotes, study resources, and class pages. The site is unofficial and is not operated by the school.

## Requirements

- Docker Engine and Docker Compose v2
- A supported Docker host; production deployment requires a public hostname for automatic HTTPS

## Local setup

1. Create the local environment file:

   ```sh
   cp .env.example .env
   ```

2. Fill in `SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and a matching `DATABASE_URL`. Generate the app secret with:

   ```sh
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

   The database URL format is `postgresql+psycopg://USER:PASSWORD@db:5432/DB_NAME`. URL-encode special characters in the password. For local development, leave `SMTP_HOST` empty; in `ENV=dev`, login links and codes are printed to the web container logs.

3. Set `SUPER_ADMIN_EMAILS` to at least one address you control. Set `ADMIN_EMAILS` only for accounts that should be administrators. Any syntactically valid email domain may log in; each person must be able to receive mail at their address.
4. Build and start the stack:

   ```sh
   docker compose up --build
   ```

5. Open `http://localhost`. The first login for an address in `SUPER_ADMIN_EMAILS` creates a superadmin. The first login for an address in `ADMIN_EMAILS` creates an admin.

Run tests with:

```sh
docker compose run --rm web pytest
```

The tests use a separate PostgreSQL database named `<POSTGRES_DB>_test`; the configured database user needs permission to create and drop databases.

## Roles and account access

There are three roles: `user`, `admin`, and `super_admin`. Regular users can use community features. Admins can moderate reports and content. Superadmins can additionally assign roles. The last superadmin cannot be demoted. Configure role bootstrap addresses with `ADMIN_EMAILS` and `SUPER_ADMIN_EMAILS`; these are comma-separated, normalized email addresses.

Login is passwordless. The user receives a one-use link and a six-digit code. Links expire after 15 minutes; opening the link does not consume it, so email security scanners cannot use it before the person does. Session cookies are HttpOnly and SameSite=Lax, Secure when `BASE_URL` uses HTTPS, and expire after 30 days.

## Abuse controls and privacy

Login attempts are limited per IP and normalized email using PostgreSQL-backed counters shared across web workers. Defaults are 20 requests per IP per hour and 5 per email per hour. Code verification is also limited per IP/email. Exceeding a limit triggers a 15-minute cooldown. Subject identifiers in the limiter table are HMAC-hashed and stale entries are purged after seven days.

An optional Cloudflare Turnstile challenge appears after repeated IP login attempts. To enable it, set both `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` in `.env`; without both, rate limits and cooldowns remain active but no CAPTCHA is shown. Turnstile can be used without Cloudflare DNS or proxying. It is not Google reCAPTCHA.

Other write limits include meme and resource uploads (10 per hour per account), quote submissions (10 per hour), reports (20 per hour), class requests (3 per day), and takedown requests (3 per hour per IP). Reports can automatically hide supported content at the configured threshold; this does not automatically ban users.

The app rejects cross-origin unsafe requests using Origin/Referer checks. Caddy sets a restrictive Content Security Policy and security headers. Uploaded media is served only after an authenticated forward-auth check. The audit log records moderation/admin actions; it is not a complete log of every post or historical username. Content rows retain the author’s user ID, but a username snapshot is not recorded for every post.

## Uploads

Meme and profile-photo uploads accept JPEG, PNG, WebP, and GIF up to `MAX_IMAGE_MB` (default 8 MB), with a 40-megapixel safety limit. Images are decoded, orientation-corrected, stripped of metadata, and stored as WebP. Animated GIF uploads use the first frame. Meme images are resized to fit within 1600 by 1600 pixels and receive a 480-pixel thumbnail. Profile photos are center-cropped to 256 by 256 pixels.

Study-resource files have a separate `MAX_RESOURCE_MB` limit (default 25 MB), extension and content checks, and are downloaded through the authenticated application route. The upload directory is a persistent Docker volume.

## Production deployment

1. Use an Ubuntu Oracle Cloud VM with an eligible Always Free shape. A 1 GB AMD micro is tight; an A1 Flex VM with at least 2 GB is preferable when available.
2. Allow inbound TCP ports 80 and 443 in both the VCN security list/security group and the VM firewall (`ufw` or `iptables`). Install Docker Engine and the Compose plugin.
3. On a 1 GB AMD VM, add a 2 GB swapfile before building:

   ```sh
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

4. Copy `.env.example` to `.env`. Set strong unique secrets and database credentials, SMTP settings, contact email, and role addresses. Use a real hostname for `DOMAIN` and `BASE_URL`, for example `DOMAIN=community.example.cz` and `BASE_URL=https://community.example.cz`. Set `ENV=prod` to disable API docs. Configure DNS so the hostname points to the VM. Caddy obtains and renews TLS certificates automatically. Cloudflare proxying is optional; if enabled, use Full (strict) mode.
5. Start and inspect the services:

   ```sh
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail=100 caddy web db
   ```

6. Confirm HTTPS, `/healthz`, email delivery, login, authenticated media, role assignments, and the admin dashboard. Keep the superadmin mailbox accessible. Rotate secrets before production if they were ever committed or shared.

Only Caddy publishes ports. PostgreSQL, the web app, and backup service are on the internal Docker network. Default memory limits are 300 MB for PostgreSQL, 350 MB for the web app, 60 MB for Caddy, and 50 MB for backup; tune the `*_MEM_LIMIT` variables only to fit the host.

## Backups and restore

The backup service saves a compressed PostgreSQL dump every 24 hours and an uploads archive every seven days, retaining seven days in the Docker `backups` volume. Copy backups off-host regularly; a volume on the same VM is not disaster recovery. Test restores on an isolated instance.

Restore a database dump into the configured database with this one-line command, replacing the filename:

```sh
docker compose exec -T backup sh -c 'gunzip -c /backups/db-YYYYMMDD-HHMM.sql.gz | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Restore uploads separately with:

```sh
docker compose exec -T backup cat /backups/uploads-YYYYMMDD.tar.gz | docker compose exec -T web tar -xzf - -C /data
```

The uploads archive contains an `uploads/` directory, which restores to the web container's `/data/uploads` volume. Back up the database and uploads before restoring or updating. Never test a restore by overwriting production data.

## Updates and operations

Before updating, take and verify a database and uploads backup. Then run:

```sh
git pull && docker compose up -d --build
docker compose ps
docker compose logs --tail=100 web db caddy
```

The web entrypoint waits for PostgreSQL and applies Alembic migrations before starting workers. After updates, check `/healthz`, login, feeds, uploads/downloads, reports, `/admin`, and the audit log. See [docs/OPERATIONS.md](docs/OPERATIONS.md) for moderator routines, incident response, and restore drills.
