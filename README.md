# as-pizeta-dashboard

A full-stack project utilizing React (Vite) and Python (Flask) for tracking and visualizing Pharma Analytics.
The backend relies on Google OAuth for authentication, issues a 2FA token using TOTP logic, and relies on `pdfplumber` for scraping and persisting sales data.

## Deployment
Refer to `DEPLOY_GUIDE.md` for information on deployment. The app is set up to be run locally in Podman and proxied behind Nginx. 
It operates under the subpath `/pizeta/dashboard`.

## Usage
1. Authenticate using Google OAuth
2. Enter the 2FA Code
3. View existing entries or supply new Sales PDF data.
