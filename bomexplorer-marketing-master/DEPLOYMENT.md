# Cloudflare Pages Deployment Guide

## Quick Deploy

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Navigate to **Workers & Pages** → **Pages**
3. Click **Create a project** → **Connect to Git**
4. Select this repo: `futureshocked/bomexplorer-marketing`
5. Configure:
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Node.js version:** `22` (or latest)
6. Click **Save and Deploy**

Site will be live at: `bomexplorer-marketing.pages.dev` (or custom domain if configured)

## IP Restriction (Cloudflare Zero Trust)

Since this is a static site, use Cloudflare Zero Trust Access for IP restriction:

1. Go to [Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to **Access** → **Applications** → **Add an application**
3. Select **Self-hosted**
4. **Application domain:** `bomexplorer-marketing.pages.dev`
5. **Session duration:** desired length
6. **Policy:** Create rule → **Allow** by **IP** → Add your IP(s)
7. Save

Free tier supports up to 50 users.

## Going Public

To remove access restriction:
1. Go to Zero Trust Dashboard
2. Delete the Access policy for this application
3. Site is now public

---

## Notes
- Pure static site deployment - no workers or runtime dependencies
- Cloudflare caches and serves globally
- Zero Trust is separate from Pages (can add/remove independently)