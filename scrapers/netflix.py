import asyncio
import json
import re
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class NetflixScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://explore.jobs.netflix.net", concurrency=concurrency)
        self.search_api_url = f"{self.base_url}/api/apply/v2/jobs"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                java_script_enabled=False
            )
            page = await context.new_page()
            
            print(f"Starting Netflix Jobs scraping via Eightfold API index...")
            
            # Step 1: Collect job IDs
            job_ids = await self.get_all_job_ids(page, max_pages)
            print(f"Collected {len(job_ids)} Netflix job IDs.")
            
            # Map IDs to URLs for the HTML pages containing Schema.org
            job_urls = [f"https://explore.jobs.netflix.net/careers/job/{jid}" for jid in job_ids]
            
            await page.close()
            
            # Step 2: Use Base Scraper's robust batching logic to fetch details
            self.jobs = await self.scrape_jobs_in_batches(context, job_urls, "netflix")
            
            # Final Save
            self.save_to_formats("netflix")
            if start_time:
                # Save just RAG JSON format, skipping detailed custom formats per instructions
                self.save_to_rag_json("netflix", "Netflix", "explore.jobs.netflix.net", start_time)
            
            await browser.close()
            print(f"Netflix scraping complete. Found {len(self.jobs)} jobs.")

    async def get_all_job_ids(self, page, max_pages):
        job_ids = []
        limit_per_batch = 10
        current_offset = 0
        
        # Determine total count first
        try:
            url = f"{self.search_api_url}?domain=netflix.com&num=1&start=0"
            response = await page.goto(url)
            content = await response.text() if response else "{}"
            data = json.loads(content)
            total_count = data.get('count', 0)
            print(f"Netflix API reports {total_count} total jobs.")
        except Exception as e:
            print(f"Error getting total count: {e}")
            total_count = 1000 # Fallback
            
        to_fetch = total_count
        if max_pages:
            to_fetch = min(total_count, max_pages * 10)
            
        while current_offset < to_fetch:
            print(f"Fetching Netflix index offset {current_offset}...")
            url = f"{self.search_api_url}?domain=netflix.com&num={limit_per_batch}&start={current_offset}"
            
            try:
                response = await page.goto(url)
                content = await response.text() if response else "{}"
                data = json.loads(content)
                
                positions = data.get('positions', [])
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
                print(f"Error at offset {current_offset}: {e}")
                break
        
        return job_ids[:to_fetch] if max_pages else job_ids

    async def scrape_job_details(self, page, url):
        """Extract job details by loading the actual job posting HTML and parsing Schema.org JSON-LD."""
        try:
            await page.goto(url)
            # Since JS is disabled globally, the SSR'd JobPosting schema is instantly
            # intact and React won't wipe it out. We don't need any complex waits!
            html = await page.content()
            
            # Extract standard schema mapping
            res = self.extract_schema_job_data(html, url)
            
            if not res:
                print(f"Could not extract Schema.org data for {url}")
                return None
                
            # Parse the text into RAG sections
            raw_desc = res.get("job_description", "")
            parsed_sections = self.parse_netflix_description(raw_desc)
            res.update(parsed_sections)
            
            # Additional cleanups and explicit URL definitions
            res['job_link'] = url
            res['apply_url'] = url
            
            # Extract Req ID from URL string
            match = re.search(r'/job/(\d+)', url)
            if match:
                 res['additional_links'] = f"Req ID: {match.group(1)}"
            
            return res
        except Exception as e:
            print(f"Error scraping Netflix job {url}: {e}")
            return None

    def parse_netflix_description(self, text):
        """Splits Netflix's plain-text description (with newlines) into RAG fields."""
        if not text:
            return {
                "about_company": "", "job_description": "", 
                "job_responsibilities": "", "minimum_qualifications": "", 
                "preferred_qualifications": "", "eeo": ""
            }
            
        sections = {
            "about_company": "",
            "job_description": "",
            "job_responsibilities": "",
            "minimum_qualifications": "",
            "preferred_qualifications": "",
            "eeo": ""
        }
        
        # Split text into blocks delimited by double newlines
        blocks = [b.strip() for b in text.split('\n\n') if b.strip()]
        
        current_section = "about_company"
        
        for block in blocks:
            lower_block = block.lower()
            
            # Identify standard headers
            if "inclusion is a netflix value" in lower_block or "equal-opportunity employer" in lower_block or "equal opportunity employer" in lower_block:
                current_section = "eeo"
            elif re.match(r'^(?:the\s+)?role:?$', block, re.I):
                current_section = "job_description"
                continue # Skip the header
            elif re.match(r'^(?:key\s+)?responsibilities:?$', block, re.I) or re.match(r'^what you(?:\'ll| will) do:?$', block, re.I):
                current_section = "job_responsibilities"
                continue # Skip the header
            elif re.match(r'^(?:necessary\s+)?(?:skills\s*&?\s*experience|qualifications|what we(?:\'re| are) looking for):?$', block, re.I) or re.match(r'^requirements:?$', block, re.I):
                current_section = "minimum_qualifications"
                continue # Skip the header
            elif re.match(r'^preferred\s+(?:qualifications|experience):?$', block, re.I):
                current_section = "preferred_qualifications"
                continue # Skip the header
                
            # Append block to current section
            if sections[current_section]:
                sections[current_section] += "\n\n" + block
            else:
                sections[current_section] = block
                
        # Fallbacks: If no explicit ROLE: header was found, the role might be lumped in with about_company.
        # Netflix usually has the first paragraph as the company blurb, and subsequent paragraphs as the role description until responsibilities.
        if not sections["job_description"] and sections["about_company"]:
            parts = sections["about_company"].split('\n\n', 1)
            sections["about_company"] = parts[0] # Keep only the first paragraph as about_company
            if len(parts) > 1:
                sections["job_description"] = parts[1] # Rest flows into job_description
                
        return sections
