<!-- Operations handbook for moderators and operators. -->
# Operations handbook

## Daily moderator routine

1. Open `/admin` and review open reports first.
2. Inspect the reported item and the report reasons/details without exposing reporter identity to ordinary users.
3. Use **hide** when content needs to be removed from normal feeds while a decision is pending; use **delete** when removal is final; use **restore** when a hidden item is cleared.
4. Use **ban author** only when the evidence supports action against the account. Do not ban yourself or an administrator.
5. Review pending quotes and classes.
6. Review open takedown requests and record the action taken.
7. Check `/admin/audit` for unexpected or repeated moderation activity.

## Takedown requests

Treat every request as a human review item. Verify the target URL, identify the affected content, and record the outcome. Do not disclose the reporter's contact information to ordinary users. For urgent privacy or safety concerns, preserve the relevant audit trail and follow the operator's escalation process.

## Backup and restore test

1. Create a fresh PostgreSQL backup with the repository backup script.
2. Verify the backup file is non-empty and readable.
3. On an isolated PostgreSQL instance, restore the database into a temporary database.
4. Run `alembic upgrade head` and application smoke tests against the restored database.
5. Verify representative users, reports, content metadata, and audit records.
6. Verify uploaded files separately from PostgreSQL: the database stores paths, while the upload directory stores the file bytes.
7. Record the restore date, database version, backup identifier, and result.

Never test restores by overwriting the production database.

## Updating the application

1. Review the change and its migration requirements.
2. Take a verified database and upload backup.
3. Pull/build the new image.
4. Run migrations before routing traffic to code that requires them.
5. Start the stack with `docker compose up -d --build`.
6. Check `/healthz`, login, media authentication, a normal feed, report submission, and `/admin`.
7. Review logs for startup, migration, database, and SMTP failures.

## User deletion request

Use the account's own deletion flow where available. For an operator-assisted request, verify the requester's authority, identify the account, preserve records that must be retained for security/audit obligations, remove or anonymize account-linked content according to the operator's reviewed retention policy, invalidate active sessions, and record the administrative action in the audit log.

## Incident checklist

### Leaked content

- Hide the content immediately if necessary.
- Preserve the URL, target ID, timestamps, and audit trail.
- Assess whether personal information was exposed.
- Handle takedown/privacy requests promptly.
- Invalidate or remove affected access where appropriate.
- Document the incident and operator decision.

### Spam wave

- Identify the common accounts/content pattern.
- Ban confirmed abusive accounts in batches through the moderation workflow.
- Hide or remove the associated content.
- Increase application or edge rate limits if required.
- At Cloudflare, apply a temporary rate-limit or challenge rule appropriate to the attack pattern.
- Monitor login, report, and database load.

## Manual checks after first deployment

- `docker compose up --build` completes without manual steps.
- TLS/security headers are present through Caddy.
- Anonymous users can open `/`, `/login`, `/rules`, `/privacy`, `/takedown`, and `/healthz`.
- Anonymous users are redirected from private routes.
- A valid `@spseiostrava.cz` login works; an outside domain does not.
- `/media/*` requires the authenticated forward-auth check.
- Meme upload, quote submission, resource creation, and class creation work.
- A normal user can report content and cannot report their own content.
- The configured report threshold hides supported content without banning users automatically.
- Moderators can resolve reports and every administrative action appears in the audit log.
- The last administrator cannot be demoted.
- Takedown submissions appear in `/admin/takedowns`.
- A database backup can be restored in an isolated environment.
