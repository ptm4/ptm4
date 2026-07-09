# TV Series Backlog — deferred Sonarr adds

**Status: NOT EXECUTED — re-evaluate against opti's free space.** (Noted 2026-07-06.)

Adding this list was originally deferred because it didn't fit on noblenumbat's local NVMe. The
full list is ~55 series / ~4,000+ episodes ≈ **4–8 TB at 1080p** (~2 TB at 720p).

Update 2026-07-07: the **movie library moved to opti** (`/srv/pool/ptm/Media/Movies`), freeing
~268 GB on noblenumbat's NVMe.

Update 2026-07-08: **the existing TV library also moved to opti** (`/srv/pool/ptm/Media/Shows`,
bind-mounted at `/data/tvshows` for jellyfin/sonarr/bazarr — see `homelab-techdoc.md`). TV is no
longer constrained by noblenumbat's local disk at all; the relevant capacity question is now
**opti's free space** (751 GB free at time of this migration, of a 1.1 TB mergerfs pool), not
noblenumbat's NVMe. That's still short of the 4–8 TB backlog at 1080p, so the 18–24 TB drive
purchase remains the prerequisite for running the *full* list — but the constraint moved from
"noblenumbat's ~400 GB NVMe" to "opti's pool," which has meaningfully more headroom for
cherry-picking a larger batch than before. Re-check `df -h /srv/pool` on opti before greenlighting
any batch, since Media-Import and movies both grow independently of this backlog.

## How to execute (when ready)

Pipe the list below into the sonarr-add skill (see `.claude/skills/sonarr-add/SKILL.md`):

```bash
python3 .claude/skills/sonarr-add/scripts/add_series.py <<'EOF'
<paste titles below>
EOF
```

Consider adding a `--no-search` / unmonitored mode first to avoid indexer rate-limit backoffs
(saw 429s from LimeTorrents/1337x/TPB during the 2026-07-06 movie mass-add) and disk blowout.

## The list

### Animated (viewing order; BTAS skipped — already owned via Blu-ray box set)

```
Avatar: The Last Airbender (2005)
Cowboy Bebop (1998)
Arcane (2021)
BoJack Horseman (2014)
Fullmetal Alchemist: Brotherhood (2009)
Monster (2004)
Death Note (2006)
Batman Beyond (1999)
Neon Genesis Evangelion (1995)
Justice League (2001)
Justice League Unlimited (2004)
Samurai Jack (2001)
X-Men: The Animated Series (1992)
Ghost in the Shell: Stand Alone Complex (2002)
Superman: The Animated Series (1996)
```

### List 1 — 1980–2000, by critical standing

```
The Sopranos (1999)
Seinfeld (1989)
Cheers (1982)
Twin Peaks (1990)
The Larry Sanders Show (1992)
Freaks and Geeks (1999)
Buffy the Vampire Slayer (1997)
The X-Files (1993)
Oz (1997)
Hill Street Blues (1981)
Homicide: Life on the Street (1993)
Frasier (1993)
Star Trek: The Next Generation (1987)
Dekalog (1988)
Prime Suspect (1991)
ER (1994)
NYPD Blue (1993)
The Wonder Years (1988)
Blackadder (1983)
Friends (1994)
```

### List 2 — 2001–modern, by critical standing

```
The Wire (2002)
Mad Men (2007)
Breaking Bad (2008)
Fleabag (2016)
The Leftovers (2014)
The Americans (2013)
Succession (2018)
Atlanta (2016)
Curb Your Enthusiasm (2000)
Veep (2012)
Six Feet Under (2001)
Better Call Saul (2015)
Deadwood (2004)
The Office (US) (2005)
Lost (2004)
Boardwalk Empire (2010)
Barry (2018)
Friday Night Lights (2006)
Battlestar Galactica (2004)
Rome (2005)
```

### Size-heavy offenders (for planning)

ER (331 eps), Cheers (275), NYPD Blue (261), Frasier (264), Friends (236), The X-Files (218),
Seinfeld (180), Star Trek: TNG (178), Buffy (144). These nine alone are likely >2 TB at 1080p.
