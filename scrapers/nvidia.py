import asyncio
import json
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class NvidiaScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        # NVIDIA uses Eightfold (like Netflix)
        super().__init__(base_url="https://nvidia.eightfold.ai", concurrency=concurrency)
        self.search_api_url = f"{self.base_url}/api/pcsx/search"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Disable JS globally so Eightfold React app doesn't wipe SSR Schema or hog CPU
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                java_script_enabled=False
            )
            page = await context.new_page()
            
            print(f"Starting NVIDIA Jobs scraping via Eightfold API index...", flush=True)
            
            # Step 1: Collect job IDs
            job_ids = await self.get_all_job_ids(page, max_pages)
            print(f"Collected {len(job_ids)} NVIDIA job IDs.", flush=True)
            
            # Convert to full URLs for schema.org extraction
            job_urls = [f"{self.base_url}/careers/job/{jid}" for jid in job_ids]
            
            # Step 2: Scrape job details in staggered batches using Base class natively
            self.jobs = await self.scrape_jobs_in_batches(context, job_urls, "nvidia")
            
            # Final Save
            self.save_to_formats("nvidia")
            if start_time:
                self.save_to_rag_json("nvidia", "NVIDIA Corporation", "nvidia.eightfold.ai", start_time)
            
            await browser.close()
            print(f"NVIDIA scraping complete. Found {len(self.jobs)} jobs.", flush=True)

    async def get_all_job_ids(self, page, max_pages):
        job_ids = []
        limit_per_batch = 10
        current_offset = 0
        
        # Determine total count first
        try:
            url = f"{self.search_api_url}?domain=nvidia.com&num=1&start=0"
            response = await page.goto(url)
            content = await response.text() if response else "{}"
            data = json.loads(content)
            # Eightfold uses nested data object sometimes
            inner_data = data.get('data', data)
            total_count = inner_data.get('count', 0)
            print(f"NVIDIA API reports {total_count} total jobs.", flush=True)
        except Exception as e:
            print(f"Error getting total count: {e}", flush=True)
            total_count = 1000 # Fallback
            
        to_fetch = total_count
        if max_pages:
            to_fetch = min(total_count, max_pages * limit_per_batch)
            
        while current_offset < to_fetch:
            print(f"Fetching NVIDIA index offset {current_offset}...", flush=True)
            url = f"{self.search_api_url}?domain=nvidia.com&num={limit_per_batch}&start={current_offset}"
            
            try:
                response = await page.goto(url)
                content = await response.text() if response else "{}"
                data = json.loads(content)
                
                inner_data = data.get('data', data)
                positions = inner_data.get('positions', [])
                
                if not positions:
                    break
                    
                for pos in positions:
                    jid = pos.get('id')
                    if jid and jid not in job_ids:
                        job_ids.append(jid)
                
                current_offset += len(positions)
                if len(positions) < limit_per_batch:
                    break
                    
            except Exception as e:
                print(f"Error at offset {current_offset}: {e}", flush=True)
                break
        
        return job_ids[:to_fetch] if max_pages else job_ids

    async def scrape_job_details(self, page, url):
        """Extract job details by loading the static HTML and parsing Schema.org JSON-LD."""
        try:
            await page.goto(url, timeout=30000)
            # No JS = No Hydration = Instant SSR HTML loaded safely!
            html = await page.content()
            
            res = self.extract_schema_job_data(html, url)
            if not res:
                print(f"Could not extract Schema.org data for {url}", flush=True)
                return None
                
            # NVIDIA Text splitting
            raw_desc = res.get("job_description", "")
            if raw_desc:
                parsed = self.parse_nvidia_description(raw_desc)
                res.update(parsed)
                
            res["job_link"] = url
            res["additional_links"] = f"{url}/application"
            
            return res
            
        except Exception as e:
            print(f"Error scraping NVIDIA job {url}: {e}", flush=True)
            return None

    def parse_nvidia_description(self, desc_text):
        """Splits NVIDIA's structured plain text description into logical fields."""
        sections = {
            "job_description": "",
            "job_responsibilities": "",
            "minimum_qualifications": "",
            "preferred_qualifications": "",
            "eeo": ""
        }
        
        # Clean text gives double newlines between conceptual tags
        blocks = [b.strip() for b in desc_text.split('\n\n') if b.strip()]
        if len(blocks) <= 1:
            blocks = [b.strip() for b in desc_text.split('\n') if b.strip()]
            
        current_section = "job_description"
        
        for block in blocks:
            lower = block.lower()
            is_header = len(lower) < 80
            
            if is_header and any(h in lower for h in ["what you will be doing", "what you'll be doing", "what you'll do", "responsibilities"]):
                current_section = "job_responsibilities"
                continue
                
            elif is_header and any(h in lower for h in ["what we need to see", "minimum qualifications"]):
                current_section = "minimum_qualifications"
                continue
                
            elif is_header and any(h in lower for h in ["ways to stand out", "preferred qualifications", "ways to stand out from the crowd"]):
                current_section = "preferred_qualifications"
                continue
            
            elif any(h in lower for h in ["equal opportunity", "diversity", "accommodation"]):
                current_section = "eeo"
                
            sections[current_section] += block + "\n\n"

        for k in sections:
            sections[k] = sections[k].strip()
            
        return sections
