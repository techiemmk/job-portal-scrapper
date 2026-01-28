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
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            print(f"Starting Netflix Jobs scraping via Eightfold API...")
            
            # Step 1: Collect job IDs
            job_ids = await self.get_all_job_ids(page, max_pages)
            print(f"Collected {len(job_ids)} Netflix job IDs.")
            
            # Step 2: Scrape job details in parallel
            tasks = []
            for i, jid in enumerate(job_ids):
                tasks.append(self.scrape_job_with_semaphore(context, jid, i+1, len(job_ids)))
            
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
            # Final Save
            self.save_to_formats("netflix")
            if start_time:
                # We removed save_to_json_schema per user request, only save RAG
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
            await page.goto(url)
            content = await page.evaluate("() => document.body.innerText")
            data = json.loads(content)
            total_count = data.get('count', 0)
            print(f"Netflix site reports {total_count} total jobs.")
        except Exception as e:
            print(f"Error getting total count: {e}")
            total_count = 1000 # Fallback
            
        to_fetch = total_count
        if max_pages:
            to_fetch = min(total_count, max_pages * 10) # Assuming 10 per page if max_pages was used traditionally
            # But the user asked for ~50 jobs or 5 pages, so if max_pages is 5, we'll fetch 50.
            # Let's just use max_pages * 10 as a heuristic.
            
        while current_offset < to_fetch:
            print(f"Fetching Netflix index offset {current_offset}...")
            url = f"{self.search_api_url}?domain=netflix.com&num={limit_per_batch}&start={current_offset}"
            
            try:
                await page.goto(url)
                content = await page.evaluate("() => document.body.innerText")
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

    async def scrape_job_with_semaphore(self, context, jid, index, total):
        async with self.semaphore:
            if index % 20 == 0:
                print(f"Scraping Netflix job {index} of {total}...")
            page = await context.new_page()
            url = f"{self.search_api_url}/{jid}?domain=netflix.com"
            result = await self.scrape_job_details(page, url, jid)
            await page.close()
            return result

    async def scrape_job_details(self, page, url, jid):
        try:
            await page.goto(url)
            await page.wait_for_timeout(1000)
            
            content = await page.evaluate("() => document.body.innerText")
            data = json.loads(content)
            
            # Extract fields
            res = {
                "job_link": f"https://explore.jobs.netflix.net/careers/job/{jid}",
                "job_name": data.get('name', ''),
                "job_location": ", ".join(data.get('locations', [])),
                "job_department": data.get('department', ''),
                "about_company": "Netflix is one of the world's leading entertainment services with over 230 million paid memberships in over 190 countries.",
                "salary": "",
                "compensation_details": "",
                "eeo": "Netflix is an equal opportunity employer and celebrates diversity, recognizing that it is critical to our success.",
                "additional_links": ""
            }
            
            # Map req ID
            req_id = ""
            if 'custom_JD' in data and 'data_fields' in data['custom_JD']:
                req_id = data['custom_JD']['data_fields'].get('job_req_id', '')
            if req_id:
                res["additional_links"] = f"Job Request ID: {req_id}"

            # Parse Description
            html_desc = data.get('job_description', '')
            parsed_sections = self.parse_netflix_html(html_desc)
            res.update(parsed_sections)
            
            return res
        except Exception as e:
            print(f"Error scraping Netflix job {jid}: {e}")
            return None

    def parse_netflix_html(self, html):
        """Splits Netflix's HTML description into RAG fields."""
        if not html:
            return {"job_description": "", "job_responsibilities": "", "minimum_qualifications": "", "preferred_qualifications": ""}
            
        # Standard cleaning
        text = self.clean_html_field(html)
        
        # Heuristic splitting by headers
        # Netflix often uses headers like "The Role", "Responsibilities", "Qualifications"
        sections = {
            "job_description": text,
            "job_responsibilities": "",
            "minimum_qualifications": "",
            "preferred_qualifications": ""
        }
        
        # Try to find Responsibility section
        resp_match = re.search(r'(Responsibilities|What you will do|What you\'ll do):?\s*(.*)', text, re.I | re.DOTALL)
        if resp_match:
            sections["job_responsibilities"] = resp_match.group(2).split('\n\n')[0].strip()
            
        # Try to find Qualifications section
        qual_match = re.search(r'(Qualifications|What we are looking for|Requirements):?\s*(.*)', text, re.I | re.DOTALL)
        if qual_match:
            sections["minimum_qualifications"] = qual_match.group(2).split('\n\n')[0].strip()
            
        return sections
