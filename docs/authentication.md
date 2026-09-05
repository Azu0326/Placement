# Scrapos authentication

Scrapos has two ways in. AWS Cognito is the identity provider for everyone;
a single bootstrap superadmin exists outside Cognito for setup and recovery.

```text
Browser
   |
   v
Scrapos Django
   |
   +---- Cognito authentication          identity lives in the shared user pool
   |        /login/          password form, verified server-side
   |        /auth/login/     hosted UI, OAuth2 authorization code + PKCE
   |
   +---- Bootstrap superadmin            never present in Cognito
   |        /login/          same form, resolved before Cognito is contacted
   |
   v
Scrapos server-side session
   |
   v
Authorization  ──>  Custom Scrapos dashboard (/dashboard/)
```

Administrative operations run entirely server-side:

```text
Browser -> Scrapos dashboard -> Django authorization check
                             -> CognitoService -> boto3 -> AWS Cognito
```

AWS credentials come from the ECS task role and never reach the browser.

## Why Cognito passwords are not stored locally

The local `ScraposUser` row is a *mirror*, not a credential store. It carries
application metadata — role, display name, activity — keyed on the Cognito
`sub`, which is stable even when an email address is reassigned.

`AbstractBaseUser.password` is deliberately left permanently unusable on every
row. There is no code path that writes a password to the database, so:

* there is no local credential to steal if the database is exposed;
* a password changed or revoked in Cognito takes effect immediately, because
  Scrapos has no stale copy to fall back on;
* Cognito's password policy, reset flow and lockout remain the only ones.

Tokens are treated the same way. Scrapos validates the Cognito ID token, reads
the claims it needs, and discards it. No access or refresh token is written to
the session or the database.

## How Cognito groups map to roles

Group membership is read from the signed `cognito:groups` claim on the ID
token, so the mapping cannot be forged by the client.

| Cognito group    | Scrapos role    | Can                                                     |
|------------------|-----------------|---------------------------------------------------------|
| `SCRAPOS_VIEWER` | `viewer`        | View permitted content pages                             |
| `SCRAPOS_EDITOR` | `editor`        | The above, plus create and edit content                  |
| `SCRAPOS_ADMIN`  | `administrator` | The above, plus user, role, audit and settings administration |
| *(none)*         | `viewer`        | Signing in alone never confers write access              |

Roles are a rank ladder: `viewer < editor < administrator < superadmin`. The
`superadmin` role is reserved for the bootstrap account and cannot be granted
by any Cognito group, so no directory change can mint one.

The role is recalculated on every sign-in. Changing someone's group in Cognito
— or from the Scrapos dashboard, which does the same thing — takes effect the
next time they sign in.

Authorisation is enforced server-side by `authentication.permissions`. The
sidebar hides links a user cannot use, but that is presentation only; every
protected view carries its own check.

## The bootstrap superadmin

**This is an emergency and development mechanism, not a production account.**

It exists to:

* perform first-run setup before any Cognito user has been granted `SCRAPOS_ADMIN`;
* administer Cognito from the Scrapos dashboard;
* recover access when Cognito is misconfigured or unreachable;
* support administrative testing.

Its guarantees:

* exactly one username — the configured one — can use this path, compared in
  constant time and case-insensitively;
* the password reaches the container **only as a Django PBKDF2 hash**. No
  setting accepts a plaintext bootstrap password;
* it is never created in, looked up in, or written to Cognito. A wrong password
  on the bootstrap username fails outright rather than falling through to the
  directory;
* it is subject to the same login throttle as any Cognito user;
* it cannot be created, disabled or deleted from the dashboard, and it is
  labelled `Bootstrap Superadmin` wherever it appears;
* every sign-in is audited as `bootstrap_admin_login`, distinct from a normal
  `authentication_success`.

### Hardening

`SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=false` removes the path entirely — the
username stops being recognised and the account can no longer sign in. Do this
once at least two Cognito users hold `SCRAPOS_ADMIN`. Until then:

* rotate the password regularly (below);
* keep the credential in a password manager, not in a ticket or chat message;
* watch for `bootstrap_admin_login` in the audit log — it should be rare.

A `manage.py check` warning is raised whenever the account is enabled outside
DEBUG, as a standing reminder.

### Rotating the bootstrap password

No code change and no commit. From a checkout:

```bash
python manage.py hash_bootstrap_password --generate
```

That prints a new strong password (once) and its Django hash. Then:

1. Store the password in your password manager.
2. Update the secret, preserving the other keys:

```bash
aws secretsmanager put-secret-value \
  --secret-id outvier-scrapos-django-production \
  --secret-string '{"secret_key":"<existing>","bootstrap_admin_username":"superadmin","bootstrap_admin_password_hash":"<new hash>"}'
```

3. Force a new deployment so tasks pick the value up:

```bash
aws ecs update-service --cluster outvier-ecs-cluster-production \
  --service outvier-scrapos-production --force-new-deployment
```

4. Verify by signing in at <https://scrapos.dncouncil.org/login/>.
5. Remove the superseded secret version once the new one is confirmed, per the
   existing secret-management policy.

The application only ever sees the hash, so the plaintext exists solely in your
password manager.

## Configuration

Supplied to the container by `deploy/ecs/web-task-definition.json`. Plain
environment variables are non-secret; the rest come from Secrets Manager.

| Variable | Source | Required |
|---|---|---|
| `COGNITO_REGION` | env | yes in production |
| `COGNITO_USER_POOL_ID` | env | yes in production |
| `COGNITO_CLIENT_ID` | secret `outvier-scrapos-cognito-production:client_id` | yes in production |
| `COGNITO_CLIENT_SECRET` | secret `outvier-scrapos-cognito-production:client_secret` | hosted UI only |
| `COGNITO_DOMAIN` | env | hosted UI only |
| `COGNITO_REDIRECT_URI` | env | hosted UI only |
| `COGNITO_LOGOUT_REDIRECT_URI` | env | hosted UI only |
| `COGNITO_GROUP_ADMIN` / `_EDITOR` / `_VIEWER` | env | defaults shown above |
| `SCRAPOS_BOOTSTRAP_ADMIN_ENABLED` | env | defaults to true |
| `SCRAPOS_SUPERADMIN_USERNAME` | secret `outvier-scrapos-django-production:bootstrap_admin_username` | if enabled |
| `SCRAPOS_SUPERADMIN_PASSWORD_HASH` | secret `outvier-scrapos-django-production:bootstrap_admin_password_hash` | if enabled |

`authentication/checks.py` runs under `manage.py check`, which the container
executes before gunicorn binds. **With `DEBUG=False` and Cognito unconfigured
the application refuses to start.** Production never silently degrades to
bootstrap-only sign-in because a variable was dropped.

## Which Cognito flow, and why

Two are supported and both end at the same verification code.

**Password form (primary).** The browser posts to `/login/`; Django calls
`AdminInitiateAuth` with `ADMIN_USER_PASSWORD_AUTH`. That flow needs both the
confidential client secret *and* signed IAM credentials, so unlike
`USER_PASSWORD_AUTH` it is not something a browser could call. It is what lets
one Scrapos-branded form serve both providers.

**Hosted UI (`/auth/login/`).** OAuth2 authorization code flow with PKCE
against `auth.dncouncil.org`, matching every other DNC property. The implicit
flow is not implemented anywhere.

**Social (`/auth/social/<provider>/`).** The same authorization-code flow with
Cognito's `identity_provider` parameter added, which skips the hosted login form
and goes straight to the provider. Slugs and the Cognito identity-provider names
they map to live in `authentication/identity.py` and are identical to the member
portal's `SOCIAL_PROVIDERS`, because it is the same user pool:

| Slug | Cognito identity provider |
|---|---|
| `google` | `Google` |
| `facebook` | `Facebook` |
| `apple` | `SignInWithApple` |

Cognito Facebook Login is sign-in only. Publishing Scrapos content to a
Facebook Page uses a separate Meta app and a Page access token — see
`docs/facebook-publishing.md`.

The provider slug is a routing hint only. Which identity actually signed in is
read back from the verified ID token, never from the parameter.

Whichever path is used, the ID token is verified before a session exists:
RS256 signature against the pool JWKS, issuer, audience (this client only),
`token_use == "id"`, expiry, and — for the hosted UI — the nonce. The key set
is cached for an hour and refetched when a token arrives with an unknown key
id, so signing-key rotation needs no intervention.

## One person, one Scrapos account

Scrapos and member.dncouncil.org share user pool `ap-southeast-2_8MQhnosSO`
(different app clients). A person in that pool can hold several Cognito
records — `Google_…`, `Facebook_…`, `SignInWithApple_…`, plus a native
email/password account — and Cognito issues a **`sub` per record, not per
person**. Keying the Scrapos account on `sub` therefore produced a separate
account per provider, which is the bug `authentication/services/identity_service.py`
removes.

The canonical application identity is the `ScraposUser` row. Provider identities
hang off it as `LinkedIdentity` rows keyed on `(provider, provider_subject)` —
the provider's own subject, the only identifier stable across Cognito records.
This mirrors the member portal's `LinkedIdentity`/`Person` split
(`apps/pages/services/identity_linking.py`), deliberately: two applications on
one pool must not disagree about who someone is.

Resolution order, for claims that have already passed token verification:

1. a `LinkedIdentity` on `(provider, provider_subject)`, then on a previously
   seen Cognito `sub` or `Username`;
2. an existing account with the same **verified** normalised email;
3. otherwise a new account.

Every sign-in also records *all* identities in the token's `identities` claim.
A record linked with `AdminLinkProviderForUser` carries every linked provider,
so the next sign-in through any of them is an exact match at step 1 — this is
how Cognito-side linking is consumed rather than worked around.

Rules that must not be relaxed:

* email matching only for verified addresses, in normalised form (strip and
  lowercase, **no** Gmail dot-stripping or plus-address folding);
* `email_verified` decides it when present. When absent it is trusted only for
  Facebook (its Cognito mapping carries no such attribute and it only releases
  verified addresses) and for native accounts (an UNCONFIRMED user cannot
  authenticate). For Google and Apple an absent claim means *not verified*;
* an unverified address that collides with an existing account gets an isolated
  account, never that one;
* two accounts sharing a verified email are **never** merged automatically. The
  sign-in resolves to a deterministic choice, `identity_duplicate_detected` is
  audited, and no link is persisted against the guess;
* Apple "Hide My Email" relay addresses only ever match themselves, and never
  overwrite a real address on an existing account;
* the bootstrap superadmin is never a resolution target.

The Scrapos username is a label assigned once at provisioning. It is never the
resolution key and is never reassigned from `cognito:username`, which would
otherwise rename an account to `Google_1234…` on the first social sign-in and
collide on the unique column between two identities of one person.

Nothing here calls `AdminLinkProviderForUser`, `AdminCreateUser` or any Cognito
write during sign-in, and no Lambda trigger is required — same as the member
portal.

## Sessions

* Server-side database sessions; the cookie holds only an opaque key.
* `HttpOnly` on both the session and CSRF cookies, `Secure` in production,
  `SameSite=Lax` — `Strict` would drop the cookie on the hosted-UI redirect back.
* `django.contrib.auth.login` cycles the session key, preventing session fixation.
* Logout destroys the server session, and for Cognito users also ends the
  hosted-UI session so the next attempt genuinely re-authenticates.
* Signed-in Cognito users are re-checked against the directory every
  `SCRAPOS_COGNITO_REVALIDATE_SECONDS` (default 300). Disabling someone in
  Cognito ends their Scrapos session without waiting for expiry. This check
  fails *open* on a Cognito outage — an unreachable directory must not sign out
  every administrator at exactly the moment they need the dashboard.

## Audit log

`authentication.audit.record` writes an `AuditEvent` row and a structured log
line for: login success and failure, bootstrap login, logout, throttling,
permission denied, session revoked, user created, enabled, disabled, role
changed, and password reset initiated.

Metadata is scrubbed before it is written: any key whose name looks like a
credential (`password`, `secret`, `token`, `hash`, `credential`, …) is
**dropped**, not redacted. A mistake at a call site cannot leak a secret into
the database or CloudWatch.

Passwords, access tokens, refresh tokens, client secrets and AWS credentials
are never logged.

## Local development

```bash
cp .env.example .env          # then fill in (Windows: copy .env.example .env)
python manage.py hash_bootstrap_password --generate
```

Django loads `.env` from the project root automatically. You do not need to
`source` or `set` the file. Values already in the process environment win, so
production Secrets Manager injection is unchanged.

Put the hash in `SCRAPOS_SUPERADMIN_PASSWORD_HASH` and sign in with the
bootstrap account. Cognito settings can be left blank locally: with `DEBUG=True`
Cognito sign-in is simply unavailable and the form says so.

```bash
python manage.py test authentication dashboard
python tools/smoke_routes.py
```

Neither touches AWS.

## Known limitation: ephemeral storage

Production runs SQLite on the container's ephemeral disk
(`DB_NAME=/tmp/scrapos.sqlite3`), which predates this work. Sessions, the local
user mirror and **the audit log reset on every deployment and container
restart**.

Sign-in is unaffected — Cognito is the source of truth for identity, and the
mirror is rebuilt on each login. But the audit log is not durable, which
matters if it is ever needed as evidence.

To make it durable, point the app at the shared `outvier-postgres-production`
instance that every other DNC Django service uses. Settings are already fully
environment-driven, so this is a task-definition change plus a database and
role: set `DB_ENGINE=django.db.backends.postgresql` with `DB_HOST`, `DB_NAME`,
`DB_USER` and `DB_PASSWORD`. No application code change is required.
