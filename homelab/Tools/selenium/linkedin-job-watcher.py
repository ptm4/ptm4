#!/usr/bin/env python3
"""
linkedin-job-watcher.py — Selenium scraper for LinkedIn job listings.

Logs into LinkedIn with your credentials, runs a saved job search with your filters,
and extracts new listings since the last run. Writes a JSON report compatible with
the homelab webapp /api/reports endpoint.

First-run setup:
  1. pip install selenium
  2. Set credentials as env vars:
       set LINKEDIN_USER=you@example.com
       set LINKEDIN_PASS=yourpassword
  3. Edit config/linkedin-search.json (auto-created on first run) to set your filters.

Usage:
  python linkedin-job-watcher.py
  python linkedin-job-watcher.py --no-headless  # watch the browser drive itself
  python linkedin-job-watcher.py --reset        # forget all seen jobs

Notes:
  - Uses your own LinkedIn credentials and account — no scraping of restricted data.
  - LinkedIn may rate-limit aggressive scraping. Default schedule: 1x/day is plenty.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
except ImportError:
    print("ERROR: selenium not installed. Run: pip install selenium", file=sys.stderr)
    sys.exit(1)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR  = os.path.join(BASE_DIR, "..", "config")
DATA_DIR    = os.path.join(BASE_DIR, "..", "data")
REPORTS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
CONFIG_PATH = os.path.join(CONFIG_DIR, "linkedin-search.json")
DB_PATH     = os.path.join(DATA_DIR, "linkedin-jobs.db")
REPORT_PATH = os.path.join(REPORTS_DIR, "linkedin-jobs-latest.json")

DEFAULT_CONFIG = {
    "keywords":          "homelab OR devops OR sre",
    "location":          "United States",
    "geoId":             "103644278",   # United States
    "posted_within_sec": 86400,         # last 24h
    "remote":            True,
    "experience_levels": ["2", "3", "4"],  # 2=entry, 3=associate, 4=mid-senior
    "max_results":       40,
}


def ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, REPORTS_DIR):
        os.makedirs(d, exist_ok=True)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        print(f"Default config created at {CONFIG_PATH}. Edit it and re-run.")
        sys.exit(0)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_id      TEXT PRIMARY KEY,
            title       TEXT,
            company     TEXT,
            location    TEXT,
            url         TEXT,
            posted_text TEXT,
            first_seen  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def build_search_url(cfg):
    params = {
        "keywords":      cfg["keywords"],
        "location":      cfg["location"],
        "geoId":         cfg.get("geoId", ""),
        "f_TPR":         f"r{cfg.get('posted_within_sec', 86400)}",
        "f_E":           ",".join(cfg.get("experience_levels", [])),
        "sortBy":        "DD",   # most recent first
    }
    if cfg.get("remote"):
        params["f_WT"] = "2"   # 2 = remote
    qs = urlencode({k: v for k, v in params.items() if v})
    return f"https://www.linkedin.com/jobs/search/?{qs}"


def make_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=opts)


def linkedin_login(driver, username, password):
    driver.get("https://www.linkedin.com/login")
    wait = WebDriverWait(driver, 15)
    wait.until(EC.presence_of_element_located((By.ID, "username")))

    driver.find_element(By.ID, "username").send_keys(username)
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for the feed page or any post-login redirect
    try:
        wait.until(lambda d: "feed" in d.current_url or "checkpoint" in d.current_url or "challenge" in d.current_url)
    except TimeoutException:
        pass

    if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
        raise RuntimeError("LinkedIn is asking for a security challenge. Run with --no-headless and complete it manually.")


def parse_job_listings(driver, max_results):
    """Returns list of job dicts from the search results page."""
    wait = WebDriverWait(driver, 15)

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.jobs-search__results-list, .jobs-search-results__list")))
    except TimeoutException:
        return []

    # Scroll the results panel to load more jobs
    for _ in range(4):
        driver.execute_script(
            "var list = document.querySelector('.jobs-search-results-list, .jobs-search__results-list');"
            "if (list) list.scrollTop = list.scrollHeight;"
        )
        time.sleep(1.5)

    # Try both legacy and current selectors
    cards = driver.find_elements(By.CSS_SELECTOR, ".jobs-search-results__list-item, .job-card-container, li.jobs-search-results__list-item")
    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, "[data-job-id]")

    jobs = []
    for card in cards[:max_results]:
        try:
            job_id = card.get_attribute("data-job-id") or card.get_attribute("data-occludable-job-id") or ""
            if not job_id:
                # Try inner element
                inner = card.find_elements(By.CSS_SELECTOR, "[data-job-id]")
                if inner:
                    job_id = inner[0].get_attribute("data-job-id")

            title_elem = card.find_elements(By.CSS_SELECTOR, ".job-card-list__title, .base-search-card__title, a.job-card-container__link")
            company_elem = card.find_elements(By.CSS_SELECTOR, ".job-card-container__primary-description, .base-search-card__subtitle, .job-card-container__company-name")
            location_elem = card.find_elements(By.CSS_SELECTOR, ".job-card-container__metadata-item, .job-search-card__location")
            posted_elem = card.find_elements(By.CSS_SELECTOR, "time, .job-search-card__listdate")
            link_elem = card.find_elements(By.CSS_SELECTOR, "a.job-card-container__link, a.base-card__full-link")

            title    = title_elem[0].text.strip() if title_elem else ""
            company  = company_elem[0].text.strip() if company_elem else ""
            location = location_elem[0].text.strip() if location_elem else ""
            posted   = posted_elem[0].text.strip() if posted_elem else ""
            url      = link_elem[0].get_attribute("href") if link_elem else ""

            if not job_id and url and "/view/" in url:
                # Extract job_id from URL: /jobs/view/123456/
                parts = url.split("/jobs/view/")
                if len(parts) > 1:
                    job_id = parts[1].split("/")[0].split("?")[0]

            if not job_id or not title:
                continue

            jobs.append({
                "job_id":      job_id,
                "title":       title,
                "company":     company,
                "location":    location,
                "url":         url.split("?")[0] if url else "",
                "posted_text": posted,
            })
        except Exception:
            continue

    return jobs


def main():
    parser = argparse.ArgumentParser(description="LinkedIn job listings watcher")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window (useful for debugging)")
    parser.add_argument("--reset", action="store_true", help="Clear seen-jobs database")
    args = parser.parse_args()

    ensure_dirs()
    cfg = load_config()
    conn = get_db()

    if args.reset:
        conn.execute("DELETE FROM seen_jobs")
        conn.commit()
        print("Seen-jobs database cleared.")
        return

    username = os.environ.get("LINKEDIN_USER")
    password = os.environ.get("LINKEDIN_PASS")
    if not username or not password:
        print("ERROR: Set LINKEDIN_USER and LINKEDIN_PASS environment variables.", file=sys.stderr)
        sys.exit(1)

    url = build_search_url(cfg)
    print(f"Searching: {url}")

    driver = make_driver(headless=not args.no_headless)
    new_jobs = []
    error = None

    try:
        print("Logging in...")
        linkedin_login(driver, username, password)

        print("Loading job search...")
        driver.get(url)
        time.sleep(3)

        print("Parsing listings...")
        all_jobs = parse_job_listings(driver, cfg.get("max_results", 40))
        print(f"Found {len(all_jobs)} job(s) on page.")

        # Filter to only new (unseen) jobs
        now = datetime.now(timezone.utc).isoformat()
        for job in all_jobs:
            cur = conn.execute("SELECT 1 FROM seen_jobs WHERE job_id = ?", (job["job_id"],))
            if cur.fetchone():
                continue
            new_jobs.append(job)
            conn.execute("""
                INSERT INTO seen_jobs (job_id, title, company, location, url, posted_text, first_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (job["job_id"], job["title"], job["company"], job["location"],
                  job["url"], job["posted_text"], now))
        conn.commit()

    except Exception as e:
        error = str(e)
        print(f"ERROR: {e}", file=sys.stderr)
    finally:
        driver.quit()

    if new_jobs:
        print(f"\n{len(new_jobs)} NEW job(s):")
        for j in new_jobs:
            print(f"  [{j['company']}] {j['title']} — {j['location']}")
            print(f"      {j['url']}")
    else:
        print("\nNo new jobs since last run.")

    status = "critical" if error else ("warn" if new_jobs else "ok")
    summary = (
        f"ERROR: {error}" if error
        else f"{len(new_jobs)} new job(s) since last run" if new_jobs
        else "No new jobs since last run"
    )

    report = {
        "tool":     "linkedin-job-watcher",
        "run_at":   datetime.now(timezone.utc).isoformat(),
        "status":   status,
        "summary":  summary,
        "findings": [
            {
                "severity": "info",
                "message":  f"[{j['company']}] {j['title']} ({j['location']})",
                "detail":   j,
            }
            for j in new_jobs
        ],
        "new_jobs": new_jobs,
        "search_url": url,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport: {REPORT_PATH}")


if __name__ == "__main__":
    main()
