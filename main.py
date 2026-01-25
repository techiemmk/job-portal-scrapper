import argparse
import asyncio
import sys
from scrapers.meta import MetaScraper
from scrapers.google import GoogleScraper
from scrapers.amazon import AmazonScraper
from scrapers.nvidia import NvidiaScraper
from scrapers.apple import AppleScraper

from datetime import datetime

async def main():
    start_time = datetime.now()
    parser = argparse.ArgumentParser(description="Multi-Portal Job Scraper")
    parser.add_argument("--portal", type=str, choices=["meta", "google", "amazon", "nvidia", "apple"], default="meta", help="Job portal to scrape")
    parser.add_argument("--max_pages", type=int, help="Maximum number of pages to scrape")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent browser pages")
    
    args = parser.parse_args()

    if args.max_pages is not None and args.max_pages <= 0:
        print(f"Error: --max_pages must be greater than 0. Received: {args.max_pages}")
        sys.exit(1)

    scraper = None
    if args.portal == "meta":
        scraper = MetaScraper(concurrency=args.concurrency)
    elif args.portal == "google":
        scraper = GoogleScraper(concurrency=args.concurrency)
    elif args.portal == "amazon":
        scraper = AmazonScraper(concurrency=args.concurrency)
    elif args.portal == "nvidia":
        scraper = NvidiaScraper(concurrency=args.concurrency)
    elif args.portal == "apple":
        scraper = AppleScraper(concurrency=args.concurrency)

    if scraper:
        await scraper.run(max_pages=args.max_pages, start_time=start_time)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScraping interrupted by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
