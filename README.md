<!-- Project setup, deployment, backup, and upgrade instructions. -->
# Spolužáci

Private, unofficial community site for SPŠE Ostrava students. The application is server-rendered with FastAPI/Jinja and PostgreSQL; Caddy provides TLS and gates uploaded media behind login.

## Local development

1. Copy `.env.example` to `.env` and set a random `SECRET_KEY` (for example, `python3 -c "import secrets; print(secrets.token_hex(32))"`). Set `SMTP_HOST=` to use the development console login link/code.
2. Start the stack: `cp .env.example .env && docker compose up --build`.
3. Open `http://localhost`. The first successful login for an address in `ADMIN_EMAILS` creates an administrator.
4. Run tests with `docker compose run --rm web pytest`.

Only Caddy publishes host ports. PostgreSQL, the web app, and backups remain on the internal Compose network.

## Oracle Cloud deployment

1. Create an Ubuntu VM in an Oracle Cloud region with an eligible Always Free shape. A 1 GB AMD micro is tight; an A1 Flex ARM VM with at least 2 GB is preferable when available.
2. In the VCN security list or network security group, allow inbound TCP 80 and 443. Also open TCP 80 and 443 in the instance firewall (`ufw` or `iptables`); both layers must permit traffic.
3. On a 1 GB AMD instance, add swap before building the Python image:

   ```sh
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

4. Install Docker Engine and the Docker Compose plugin using Docker's official Ubuntu instructions. Add your deployment account to the `docker` group, then reconnect.
5. Clone the repository, copy `.env.example` to `.env`, and set a strong `SECRET_KEY`, unique database password, real `DOMAIN` and matching `BASE_URL`, contact address, SMTP settings, and `ADMIN_EMAILS`. `DOMAIN` should be the public hostname (for example `community.example.cz`); `BASE_URL` should be `https://community.example.cz`.
6. Create an `A` record pointing the hostname to the VM's reserved public IP. If using Cloudflare proxying, start with DNS-only until Caddy has obtained a certificate. When proxying is enabled, use Full (strict) TLS mode and ensure Cloudflare reaches the origin on 80/443. Set `DOMAIN=:80` only when TLS terminates at a trusted external proxy and `BASE_URL` remains the public HTTPS URL.
7. Start and check the services:

   ```sh
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail=100 caddy web db
   ```

8. Confirm `https://your-domain/`, `/healthz`, login email delivery, authenticated `/media/` access, and the initial admin account. Keep the admin mailbox operational: there is no password reset path independent of that mailbox.

The default memory caps are intentionally small for a 1 GB VM (`db` 300 MB, `web` 350 MB, `caddy` 60 MB, `backup` 50 MB). Change the corresponding `*_MEM_LIMIT` values in `.env` only when the VM has additional memory. Leave PostgreSQL connection and worker counts aligned with the available RAM.

## Backups and restore

The backup service writes a compressed PostgreSQL dump every 24 hours and an uploads archive every seven days into the `backups` volume, retaining seven days. Backups in a Docker volume are not off-site; periodically copy them to independent storage and test a restore.

Restore a database dump into the configured database with this one-line command (replace the filename with the desired dump):

```sh
docker compose exec -T db sh -c 'gunzip -c /backups/db-YYYYMMDD-HHMM.sql.gz | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Restore uploaded files separately by extracting the chosen `uploads-YYYYMMDD.tar.gz` archive into the uploads volume. Do not restore over a running production database without first making a fresh backup.

## Updating

```sh
git pull && docker compose up -d --build
```

The web entrypoint waits for PostgreSQL and applies Alembic migrations before starting workers. Review release notes and take a database and uploads backup before deploying schema changes. Check `/healthz`, login, feeds, downloads, reports, and `/admin` after the update.
