// Minimal iCalendar reader for the Status page's "Today" card: VEVENTs with DTSTART/
// DTEND/SUMMARY/LOCATION, TZID-aware, and the recurrence rules a personal calendar
// actually uses (DAILY / WEEKLY with BYDAY / MONTHLY / YEARLY, INTERVAL, COUNT, UNTIL,
// EXDATE). Anything fancier is skipped rather than guessed.
'use strict';

const DAY = 86_400_000;
const BYDAY = { SU: 0, MO: 1, TU: 2, WE: 3, TH: 4, FR: 5, SA: 6 };

function unfold(text) {
  return text.replace(/\r\n/g, '\n').replace(/\n[ \t]/g, '');
}

// UTC ms for a wall-clock time in an IANA zone (no dependencies: two Intl passes).
function zonedToUtc(y, mo, d, h, mi, s, tz) {
  const guess = Date.UTC(y, mo - 1, d, h, mi, s);
  const offset = (t) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(new Date(t)).map((x) => [x.type, x.value]));
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - t;
  };
  const first = guess - offset(guess);
  return guess - offset(first);
}

// "20260927T090000Z" | "20260927T090000" (+TZID) | "20260927" (all-day)
function parseDate(value, params, defaultTz) {
  const m = /^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$/.exec(value.trim());
  if (!m) return null;
  const [, y, mo, d, h, mi, s, z] = m;
  if (h === undefined) return { t: Date.UTC(+y, +mo - 1, +d), allDay: true };
  if (z) return { t: Date.UTC(+y, +mo - 1, +d, +h, +mi, +s), allDay: false };
  let tz = /TZID=([^;:]+)/.exec(params || '')?.[1] || defaultTz;
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); } catch (_) { tz = defaultTz; }
  return { t: zonedToUtc(+y, +mo, +d, +h, +mi, +s, tz), allDay: false };
}

function parseEvents(text, defaultTz) {
  const events = [];
  let cur = null;
  for (const line of unfold(text).split('\n')) {
    if (line === 'BEGIN:VEVENT') { cur = { exdates: [] }; continue; }
    if (line === 'END:VEVENT') { if (cur?.start) events.push(cur); cur = null; continue; }
    if (!cur) continue;
    const idx = line.indexOf(':');
    if (idx < 0) continue;
    const [name, ...rest] = line.slice(0, idx).split(';');
    const params = rest.join(';');
    const value = line.slice(idx + 1);
    if (name === 'DTSTART') cur.start = parseDate(value, params, defaultTz);
    else if (name === 'DTEND') cur.end = parseDate(value, params, defaultTz);
    else if (name === 'SUMMARY') cur.summary = value.replace(/\\([,;\\])/g, '$1').replace(/\\n/gi, ' ');
    else if (name === 'LOCATION') cur.location = value.replace(/\\([,;\\])/g, '$1').replace(/\\n/gi, ' ');
    else if (name === 'RRULE') cur.rrule = Object.fromEntries(value.split(';').map((kv) => kv.split('=')));
    else if (name === 'EXDATE') for (const v of value.split(',')) { const p = parseDate(v, params, defaultTz); if (p) cur.exdates.push(p.t); }
    else if (name === 'STATUS') cur.status = value;
  }
  return events.filter((e) => e.status !== 'CANCELLED');
}

// All occurrences of one event that start inside [from, to).
function occurrences(ev, from, to) {
  const dur = ev.end ? ev.end.t - ev.start.t : ev.start.allDay ? DAY : 0;
  const hit = (t) => t + Math.max(dur, 1) > from && t < to && !ev.exdates.includes(t);
  const r = ev.rrule;
  if (!r) return hit(ev.start.t) ? [ev.start.t] : [];
  const freq = r.FREQ;
  const interval = Math.max(1, Number(r.INTERVAL) || 1);
  const until = r.UNTIL ? parseDate(r.UNTIL, '', 'UTC')?.t ?? Infinity : Infinity;
  const count = Number(r.COUNT) || Infinity;
  const out = [];
  let n = 0;
  const start = new Date(ev.start.t);
  for (let i = 0; i < 5000 && n < count; i++) {
    let times = [];
    if (freq === 'DAILY') times = [ev.start.t + i * interval * DAY];
    else if (freq === 'WEEKLY') {
      const weekStart = ev.start.t + i * interval * 7 * DAY - start.getUTCDay() * DAY;
      const days = r.BYDAY ? r.BYDAY.split(',').map((d) => BYDAY[d.slice(-2)]).filter((d) => d !== undefined) : [start.getUTCDay()];
      times = days.sort().map((d) => weekStart + d * DAY).filter((t) => t >= ev.start.t);
    } else if (freq === 'MONTHLY') {
      const d = new Date(start); d.setUTCMonth(start.getUTCMonth() + i * interval); times = [d.getTime()];
    } else if (freq === 'YEARLY') {
      const d = new Date(start); d.setUTCFullYear(start.getUTCFullYear() + i * interval); times = [d.getTime()];
    } else {
      return hit(ev.start.t) ? [ev.start.t] : [];
    }
    for (const t of times) {
      if (t > until || n >= count) return out;
      n++;
      if (t >= to) return out;
      if (hit(t)) out.push(t);
    }
  }
  return out;
}

function eventsBetween(text, from, to, defaultTz = 'America/New_York') {
  const rows = [];
  for (const ev of parseEvents(text, defaultTz)) {
    const dur = ev.end ? ev.end.t - ev.start.t : ev.start.allDay ? DAY : 0;
    for (const t of occurrences(ev, from, to)) {
      rows.push({
        title: ev.summary || '(no title)', location: ev.location || null, all_day: ev.start.allDay,
        start: new Date(t).toISOString(), end: new Date(t + dur).toISOString(),
      });
    }
  }
  return rows.sort((a, b) => a.start.localeCompare(b.start));
}

module.exports = { eventsBetween, parseEvents, zonedToUtc };
