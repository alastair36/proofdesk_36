# Deploying ProofDesk to Vercel

## The #1 cause of a 404 after deploy
`vercel.json`, `api/`, `app.py` and `requirements.txt` must sit at the **root of the GitHub repo**.
If you uploaded the whole `proofdesk` *folder*, they are one level down and Vercel finds nothing -> 404.

Fix (either one):
- **Re-upload** the *contents* of the `proofdesk` folder (open it, select everything inside, drag into GitHub), or
- In Vercel: Project -> Settings -> General -> **Root Directory** -> set to `proofdesk` -> Save -> Redeploy.

## Steps
1. Create a GitHub repo and upload the CONTENTS of this folder. Check that on the repo's front page you can see
   `vercel.json`, `api`, `app.py`, `public` (hidden files like `.gitignore` are fine to include).
2. vercel.com -> Add New -> Project -> import the repo. Framework Preset: **Other**.
   Leave Build/Output/Install settings at their defaults (do not override). Click Deploy.
3. (Recommended) Settings -> Environment Variables -> `SECRET_KEY` = long random string, then Redeploy.
4. Open the link. Log in with `customer@proofdesk.demo`, `provider@proofdesk.demo` or `admin@proofdesk.demo` (password `Demo@1234`).

## Still a 404 / error?
- Vercel -> Deployments -> latest -> **Functions / Runtime Logs**. A Python traceback means an app error (not routing).
- Settings -> General: Framework must be "Other", Root Directory empty (or `proofdesk` if you uploaded the folder).
- Vercel dashboard -> Domains: open the `*.vercel.app` URL shown on the deployment, not an old/other domain.

## Notes
- Demo data is rebuilt automatically whenever the serverless function starts cold. Data you create
  lasts while the function stays warm, then resets (SQLite lives in /tmp).
- Photo uploads are limited to 4 MB on Vercel.
