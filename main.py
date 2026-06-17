import argparse
import asyncio
import sys
from scrapers.meta import MetaScraper
from scrapers.google import GoogleScraper
from scrapers.amazon import AmazonScraper
from scrapers.nvidia import NvidiaScraper
from scrapers.apple import AppleScraper
from scrapers.openai import OpenAIScraper
from scrapers.microsoft import MicrosoftScraper
from scrapers.netflix import NetflixScraper
from scrapers.kumaran import KumaranScraper

from datetime import datetime

PORTAL_MAP = {
    "meta":      ("Meta",      MetaScraper),
    "google":    ("Google",    GoogleScraper),
    "amazon":    ("Amazon",    AmazonScraper),
    "nvidia":    ("NVIDIA",    NvidiaScraper),
    "apple":     ("Apple",     AppleScraper),
    "openai":    ("OpenAI",    OpenAIScraper),
    "microsoft": ("Microsoft", MicrosoftScraper),
    "netflix":   ("Netflix",   NetflixScraper),
    "kumaran":   ("Kumaran Systems", KumaranScraper),
}

async def main():
    start_time = datetime.now()
    parser = argparse.ArgumentParser(description="Multi-Portal Job Scraper")
    parser.add_argument("--portal", type=str, choices=list(PORTAL_MAP.keys()), default="meta", help="Job portal to scrape")
    parser.add_argument("--max_pages", type=int, help="Maximum number of pages to scrape")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent browser pages")
    parser.add_argument("--save-to-db", action="store_true", help="Save scraped jobs to PostgreSQL database")
    parser.add_argument("--db-only", action="store_true", help="Save to database only, skip file exports (implies --save-to-db)")
    parser.add_argument("--env", type=str, choices=["LOCAL", "PROD"], default="LOCAL",
                        help="Environment: LOCAL (default PostgreSQL) or PROD (Supabase DB)")
    
    args = parser.parse_args()

    if args.max_pages is not None and args.max_pages <= 0:
        print(f"Error: --max_pages must be greater than 0. Received: {args.max_pages}")
        sys.exit(1)

    # --db-only implies --save-to-db
    if args.db_only:
        args.save_to_db = True

    # --env PROD implies --save-to-db (no point connecting to Supabase without saving)
    if args.env == "PROD":
        args.save_to_db = True

    # Initialize database if needed
    if args.save_to_db:
        try:
            from db import init_db, set_env_mode
            set_env_mode(args.env)
            init_db()
        except Exception as e:
            print(f"Error initializing database: {e}")
            sys.exit(1)

    company_name, scraper_class = PORTAL_MAP[args.portal]
    scraper = scraper_class(concurrency=args.concurrency)

    # Override save_to_formats if --db-only is set
    if args.db_only:
        scraper.save_to_formats = lambda portal_name: print(f"Skipping file export for {portal_name} (--db-only mode)")

    await scraper.run(max_pages=args.max_pages, start_time=start_time)

    # Save to database if flag is set
    if args.save_to_db:
        scraper.save_to_db(args.portal, company_name)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScraping interrupted by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
