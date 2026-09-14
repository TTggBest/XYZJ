# Tencent Cloud Independent Deployment Plan

**Goal:** Deploy the current management system at `https://xyzj.chronaraxy.com` on the new Tencent Cloud Ubuntu server with an empty, independent MySQL database and independent file storage, without changing or accessing Studio production data.

**Architecture:** Nginx terminates HTTPS and proxies the same-origin Web/API traffic to one Uvicorn process on `127.0.0.1:19732`. MySQL listens only locally. The cloud service reads application-only configuration from `/etc/zhiju/zhiju-app.env`; one-time administration reads the separately protected `/etc/zhiju/zhiju-admin.env`. Application and migration database users are separate. Runtime files live under `/var/lib/zhiju`. Studio launchers, database switching, macOS Keychain, Finder, and app-icon tooling retain their existing local behavior and are not used by the cloud deployment.

## Global constraints

- Do not connect to, migrate, query, write, restart, package, or reconfigure Studio or `zhiju_prod` on Studio.
- The cloud database starts empty and never synchronizes Studio data.
- Do not commit passwords, private keys, tokens, `.env` files, generated runtime data, or certificates.
- Do not expose MySQL `3306` or Uvicorn `19732` publicly.
- Keep existing product behavior unchanged except where a cloud/Linux runtime must clearly report an unsupported local-machine operation.
- Use one application worker until the realtime event broker is externalized.

## Task 1: Add the cloud deployment contract

- Add versioned templates/scripts for Ubuntu provisioning, systemd, Nginx, environment validation, database initialization, and the initial super-admin bootstrap.
- Add focused tests that prove cloud configuration cannot target the Studio database/host, secrets are not embedded, Uvicorn is loopback-only, and upload/SSE proxy settings are present.
- Document deployment, update, rollback, backup, and the macOS-only feature boundary.

## Task 2: Prepare the clean cloud host

- Install OS packages, Python runtime, MySQL, Nginx, and Certbot.
- Create the `zhiju` service account and restricted application/config/data directories.
- Create a new local-only MySQL database and separate app/migration users using generated credentials.

## Task 3: Deploy and initialize the application

- Transfer only tracked source from this feature branch to a versioned release directory.
- Create the server-only environment file and run Alembic against the new cloud database.
- Bootstrap the single cloud super administrator from a password supplied out-of-band, never from source control or process arguments.
- Start and verify the systemd service and local health endpoint.

## Task 4: Publish HTTPS

- Install the Nginx site for `xyzj.chronaraxy.com` with same-origin `/api`, SSE buffering disabled, and a batch-upload-safe body limit.
- Obtain a free Let's Encrypt certificate and verify renewal.
- Verify HTTP redirect, HTTPS health, login, static assets, session cookie behavior, and SSE connectivity.

## Task 5: Acceptance and handoff

- Run focused deployment tests and the full test suite on the branch.
- Confirm cloud DB identity and empty business data without inspecting Studio.
- Confirm Studio worktree, service, and data were not changed.
- Commit the deployment branch; do not merge it into `dev` until the cloud instance passes acceptance and the user requests merge.
