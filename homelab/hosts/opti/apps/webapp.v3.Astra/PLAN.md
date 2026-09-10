# RPI Webapp — Development Plan

## Goal
A private local dashboard with sidebar navigation. Cockpit already handles system monitoring — this app focuses on productivity and integrations.

## Pages

| Page | Description |
|---|---|
| Home | Widget cards: Weather, Steam, Spotify Now Playing, Discord send |
| Notes | OneNote-style notebook with pages/sections |

## Architecture

**Stack:** Express.js (existing) + plain HTML/CSS/JS SPA (no framework)  
**Layout:** Fixed sidebar (200px) + scrollable main content  
**Storage:** Flat JSON files under `backend/data/` (gitignored)  
**Config:** `backend/.env` for API keys (gitignored), `dotenv` npm package

---

## Phase 1: Sidebar Shell

Redesign `frontend/index.html`, `style.css`, `app.js`:
- Sidebar with nav links (Home, Notes)
- Plain JS router: nav clicks swap `<main>` content
- Keep health-check polling

---

## Phase 2: Home Screen Widgets

**Backend proxy routes** (add to `backend/index.js`):
```
GET  /api/integrations/weather    — OpenWeatherMap proxy
GET  /api/integrations/steam      — Steam Web API proxy (summary + recent games)
GET  /api/integrations/spotify    — Spotify currently playing (OAuth token refresh)
POST /api/integrations/discord    — Post message to Discord webhook
```

**Frontend:** Card grid, each card auto-polls. Discord card has text input + send button.

**Poll intervals:** Spotify 30s, Steam 2min, Weather 10min

**New npm dep:** `dotenv`

**Env vars needed in `.env`:**
```
OPENWEATHER_API_KEY=
OPENWEATHER_CITY=
STEAM_API_KEY=
STEAM_USER_ID=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REFRESH_TOKEN=
DISCORD_WEBHOOK_URL=
```

---

## Phase 3: Notes Page

**TipTap v2** editor via CDN.

**Backend routes:**
```
GET    /api/notes/sections
POST   /api/notes/sections              { name }
GET    /api/notes/pages/:pageId
POST   /api/notes/pages                 { sectionId, title }
PUT    /api/notes/pages/:pageId         { title, content }
DELETE /api/notes/pages/:pageId
DELETE /api/notes/sections/:sectionId
```

**Storage:**
```
backend/data/notes/
  index.json            ← section + page metadata (ids, titles, order)
  pages/<pageId>.json   ← TipTap JSON content
```

IDs = `Date.now().toString()`. Uses `fs` module only.

**Frontend UX:**
- Section/page tree in sidebar sub-panel
- TipTap editor in main area
- Toolbar: bold, italic, headings, bullets, checklist, table, image, code block, color

---

## File Changelist

| File | Action |
|---|---|
| `frontend/index.html` | Sidebar shell, TipTap CDN |
| `frontend/style.css` | Sidebar + editor + widget card styles |
| `frontend/app.js` | SPA router + page renderers |
| `backend/index.js` | Notes CRUD + integrations proxy routes |
| `backend/package.json` | Add `dotenv` |
| `backend/.env` | API keys (gitignored) |
| `backend/.env.example` | Key template |
| `backend/data/notes/` | Auto-created at runtime |
| `.gitignore` | Add `backend/data/`, `backend/.env` |

---

## Verification

1. `cd backend && npm install && node index.js`
2. `http://localhost:3000` — sidebar + nav works
3. Home page: all widget cards render with live data
4. Discord: send a message → appears in Discord channel
5. Notes: create section/page → write rich text → reload → data persists
