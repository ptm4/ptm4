# Production Deployment Guide — wp-jammylab → prod (jobs.jammylab.com)

## Context

- **This folder (`wp-jammylab`)** is the `test-it` deployment used to build and validate
  the architecture. It is NOT the prod deployment folder.
- **For prod:** Copy this entire folder, rename it (e.g. `wp-jammylab-prod`), and update
  the values listed in Step 1 below. Almost everything else stays the same.
- **Current prod site:** Running on **Kinsta** at `jammylab.com` / `jobs.jammylab.com`.
  All content (DB + uploads/media) will be exported from Kinsta and imported into the
  new Azure infrastructure. There is no existing Azure storage or MySQL to copy from —
  all Azure infra is freshly deployed via Terraform.

---

## Prerequisites

- Access to the `prod-it` Azure subscription
- Azure DevOps service connection pointing to `prod-it`
- Kinsta dashboard access (for DB export + media/uploads download)
- HubSpot portal credentials (to reconnect after cutover)
- WP Rocket license key (domain-locked, needs activation on `jobs.jammylab.com`)

---

## Step 0 — Update the Docker image with prod plugin/theme versions

The Docker image bakes in plugins and themes. The Kinsta prod site may have different
or newer versions than what's in the current test image. Do this before running any pipeline.

1. Download the latest `wp-content/plugins/` and `wp-content/themes/` from Kinsta
   (via Kinsta's SFTP or their backup download)
2. Replace the contents of `wp-content/plugins/` and `wp-content/themes/` in this repo
3. Verify versions match what's activated in the Kinsta WordPress database
4. Commit the changes to the repo

---

## Step 1 — Create the prod deployment folder

Copy this folder (`wp-jammylab`) and adjust the following for prod:

### `providers.tf`
- Update `subscription_id` to the `prod-it` subscription ID
- Update the Terraform backend block to point to a state storage account in `prod-it`
  (or a shared infra state account if one exists)

### `variables.tf` / `terraform.tfvars`
- Update resource names — replace any `test`/`dev` identifiers with `prod`
- Storage account name must be globally unique in Azure
- Update environment tags

### `main.tf`
- Review for any hardcoded test resource group names, ACR names, or Key Vault names
- `WORDPRESS_CONFIG_EXTRA` is fine as-is — no environment-specific values in there

### AFD deployment folder (`AFD/deployments/`)
- Copy `aca-wp-jammylab` and create a prod equivalent, then update `terraform.tfvars`:
  - `frontdoor_endpoint_name` → prod value
  - `backend_host_name` → prod ACA FQDN (known after first Terraform apply)
  - `origin_host_header` → prod ACA FQDN
  - Custom domain → `jobs.jammylab.com`

### Pipelines
- Create a prod version of `pipeline.yml` pointing to the `prod-it` service connection
- Create a prod version of `wp-jammylab-docker-pipeline.yml` pointing to the prod ACR
- Update any variable groups to prod equivalents

---

## Step 2 — Add the PHP upload size override to the Docker image

The All-in-One WP Migration unlimited plugin removes the UI cap, but PHP itself still
limits upload size. Add a `php.ini` override so it's permanently baked in and never
needs to be thought about again.

Create `docker/php-uploads.ini`:
```ini
upload_max_filesize = 2G
post_max_size = 2G
```

Add to `docker/Dockerfile`:
```dockerfile
COPY docker/php-uploads.ini /usr/local/etc/php/conf.d/php-uploads.ini
```

---

## Step 3 — Terraform first pass (infrastructure only)

Run the prod Terraform pipeline. This provisions everything fresh:
- ACR
- Storage shares (`wp-uploads`, `wp-cache`)
- MySQL Flexible Server
- Container App Environment + Container App
- Key Vault
- AFD resources

> **Note:** The ACR is created in this same Terraform run. The Container App will fail
> to start on first apply because the image doesn't exist in ACR yet — this is expected.
> The second pass (Step 5) resolves it.

---

## Step 4 — Run the Docker pipeline

Run the prod Docker build pipeline to build and push the image to the prod ACR.

- Builds from `wp-content/plugins/`, `wp-content/themes/`, `docker/`
- Tags and pushes to the prod ACR
- Confirm the image is visible in ACR before continuing

> **Tip for prod:** Use an explicit image tag tied to the pipeline build number rather
> than `latest`. This avoids the `latest` tag ambiguity issue where ACA doesn't detect
> a new image and doesn't create a new revision.

---

## Step 5 — Terraform second pass (wire up Container App image)

If `ignore_changes` was used on the ACA template in the first pass, remove it and
re-run the Terraform pipeline. The Container App will now pull the correct image from
ACR and start successfully.

> **Site is accessible here.** Once the Container App is healthy, wp-admin is reachable
> via the ACA direct URL (`*.azurecontainerapps.io`) — no AFD or DNS required. Log in
> with the default WordPress credentials and verify the fresh install. The front-end will
> show a blank default WordPress site until the DB is imported in Step 7. This is the
> right time to poke around wp-admin and confirm everything looks right before importing.

---

## Step 6 — Copy uploads from Kinsta to the prod `wp-uploads` share

This is the most critical manual step. Missing uploads = broken images sitewide
(learned from test-it — AFD caches 404s as HTML and serves them until purged).

**Download from Kinsta:**
Use Kinsta's SFTP or backup download to get the full `wp-content/uploads/` directory.

**Upload to Azure Files:**
```powershell
azcopy copy `
  "<local-path-or-kinsta-source>" `
  "https://<prod-storage>.file.core.windows.net/wp-uploads/<SAS>" `
  --recursive
```

Verify file counts match after the copy completes before moving on.

---

## Step 7 — Import the WordPress database from Kinsta (All-in-One WP Migration)

### Export from Kinsta

In Kinsta wp-admin → All-in-One WP Migration → Export, use these settings:

**Compression:** GZip — no risk, smaller file, decompresses automatically on import.

**Check all of the following** (reduces file size significantly, all safe to exclude):

| Option | Why |
|---|---|
| Exclude media library | Uploads already copied in Step 6 via Kinsta SFTP |
| Exclude plugins | Baked into Docker image |
| Exclude themes | Baked into Docker image |
| Exclude inactive plugins | Baked into Docker image |
| Exclude inactive themes | Baked into Docker image |
| Exclude cache files | Never needed |
| Exclude spam comments | Reduces DB size, safe |
| Exclude post revisions | Reduces DB size, safe |

**Leave unchecked:** `Exclude database` — the DB is the entire point of this export.

With media, plugins, and themes excluded the `.wpress` file will be dramatically smaller
and far less likely to timeout during import.

### Import to Azure

In the Azure WordPress wp-admin → All-in-One WP Migration → Import, upload the `.wpress` file.

What happens in the container during import:

| Content | Where it lands | Persistent? |
|---|---|---|
| Database | MySQL Flexible Server | Yes ✓ |
| Uploads (if included) | Azure Files `wp-uploads` mount | Yes ✓ |
| Plugins / themes | Ephemeral container layer — lost on restart, image versions take over | Fine ✓ |

---

## Step 8 — Pre-DNS-cutover testing (temporary URL override)

The prod domain is `jammylab.com` — the same domain Kinsta currently serves. **No
URL search-replace is needed.** The imported DB already has the correct domain.

However, before DNS cutover, WordPress will redirect the front-end to `jammylab.com`
(still pointing at Kinsta) if you access the Azure site via the ACA URL. To test the
Azure front-end without touching DNS, temporarily add these to `WORDPRESS_CONFIG_EXTRA`
in `main.tf`:

```hcl
define('WP_HOME','https://<aca-url>.azurecontainerapps.io');
define('WP_SITEURL','https://<aca-url>.azurecontainerapps.io');
```

Apply via Terraform and force a new ACA revision. The Azure site will now render
correctly at the ACA URL while Kinsta continues serving `jammylab.com` to real users.

**Remove these two lines before DNS cutover** — leave them in and the prod site will
serve from the ACA URL instead of `jammylab.com` after cutover.

---

## Step 9 — Post-import configuration

These settings are stored in the WordPress database and won't carry over automatically
or need to be re-done after import:

- **HubSpot** — Reconnect the HubSpot plugin to the HubSpot portal in wp-admin.
  This restores the correct cookie consent banner and all HubSpot tracking/chatbot features.
- **WP Rocket** — Activate the license on `jammylab.com` (domain-locked).
  Re-verify JS exclusion settings if the DB doesn't carry them over:
  - Delay JS Execution exclusions: `ssba`, `simple-share-buttons`, `bb-powerpack`
  - Never Cache Cookies: `cookie_notice_accepted`, `cookielawinfo-checkbox-necessary`

---

## Step 10 — Run the AFD pipeline (create prod route)

Run the AFD pipeline to create the prod Azure Front Door route for `jammylab.com`.
This wires up the origin (prod ACA), route rules, and custom domain in Front Door.

No manual cache purge is needed — the route is brand new so there is no stale cache.

> Make sure the `backend_host_name` and `origin_host_header` in the AFD `terraform.tfvars`
> are updated to the prod ACA FQDN before running. You can get the FQDN from the Azure
> portal or from the Terraform output after Step 5.

---

## Step 11 — DNS cutover and Kinsta shutdown

### Before cutting DNS

1. Confirm the Azure site is fully working at the ACA URL (from Step 8 testing)
2. Remove the temporary `WP_HOME` / `WP_SITEURL` overrides from `WORDPRESS_CONFIG_EXTRA`
   in `main.tf` and apply via Terraform — the site must be pointing to `jammylab.com`
   before DNS is changed

### DNS cutover

Point `jammylab.com` (and `www.jammylab.com`) at the AFD endpoint.

`jobs.jammylab.com` does not need a manual DNS change — it will self-correct once
`jammylab.com` resolves to Azure, as it is configured as a redirect or CNAME that
follows the primary domain.

Verify SSL is provisioning correctly in the AFD custom domain settings. SSL provisioning
can take a few minutes after the DNS record is live.

### When to shut off Kinsta

**Do not shut off Kinsta immediately.** Keep it running as a safety net.

The right sequence:

| Time | Action |
|---|---|
| T+0 | DNS records updated, pointing at AFD |
| T+0 to T+1h | DNS propagating — some users may still hit Kinsta |
| T+1h | Verify Azure site is serving correctly for real users |
| T+24-48h | DNS fully propagated globally, no traffic hitting Kinsta |
| T+48h | Confirm no issues, then shut down / suspend the Kinsta environment |

> **Important:** Between DB import (Step 7) and DNS cutover, the live Kinsta site is
> still taking real user traffic. Any content created on Kinsta during that window (new
> posts, form submissions, etc.) will NOT be on Azure. Minimize this gap — ideally
> import and cut over in the same maintenance window.

---

## What is baked in (nothing to do at deploy time)

| What | How |
|---|---|
| Plugins & themes | Baked into Docker image via pipeline |
| OPcache | `docker/opcache.ini` in image |
| PHP upload limits | `docker/php-uploads.ini` in image |
| WordPress config (SSL, memory limits, `FS_METHOD`) | `WORDPRESS_CONFIG_EXTRA` in `main.tf` |
| Auth keys/salts | `entrypoint.sh` — auto-generated on first boot, persisted to `wp-uploads` share |
| Plugin writable dir symlinks | `entrypoint.sh` — runs on every container start |
| Storage shares, ACA, AFD, Key Vault, MySQL | Terraform |
| AFD caching rules & bypass | Terraform (`afd-site` module) |

---

## Key lessons from test-it

- **Missing uploads = broken images sitewide.** Always verify `wp-uploads` is fully
  populated before testing. AFD will cache the 404 HTML response for any missing file URL
  and serve it until explicitly purged.
- **AFD caches aggressively.** After any file restoration or migration, always purge `/*`.
- **`latest` tag doesn't force a new ACA revision.** Use an explicit image tag (e.g. build
  number) for prod so Terraform always deploys a known image.
- **HubSpot and WP Rocket require manual reconnection.** Neither is auto-configured from
  the image or Terraform — both need to be set up in wp-admin after first boot.
- **The ACR is created inside the main Terraform.** First pass creates it, Docker pipeline
  runs next, second Terraform pass wires the image to the Container App.
