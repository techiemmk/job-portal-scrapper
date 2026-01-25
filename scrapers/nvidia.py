import asyncio
import json
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class NvidiaScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://nvidia.eightfold.ai", concurrency=concurrency)
        self.search_api_url = f"{self.base_url}/api/pcsx/search"
        self.details_api_url = f"{self.base_url}/api/pcsx/position_details"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            page = await context.new_page()
            
            print(f"Starting NVIDIA Jobs scraping...", flush=True)
            
            # Step 1: Initialize session and get total count
            print("Navigating to NVIDIA Careers...", flush=True)
            await page.goto(f"{self.base_url}/careers?start=0")
            
            # Wait for job count to appear
            print("Waiting for job count...", flush=True)
            total_count = 0
            for _ in range(10):
                try:
                    await page.wait_for_selector("[data-testid='job-count']", timeout=5000)
                    total_count_text = await page.get_attribute("[data-testid='job-count']", "innerText") or "0"
                    total_count = int(''.join(filter(str.isdigit, total_count_text)))
                    if total_count > 0: break
                except:
                    pass
                await asyncio.sleep(2)

            if total_count == 0:
                print("Warning: Site failed to load count. Trying API fallback...", flush=True)
                try:
                    await page.goto(f"{self.search_api_url}?domain=nvidia.com&start=0&num=1")
                    content = await page.evaluate("() => document.body.innerText")
                    data = json.loads(content)
                    total_count = data.get('data', {}).get('count', 0)
                except: pass

            print(f"NVIDIA site reports {total_count} total jobs.", flush=True)
            
            # Step 2: Collect all job IDs
            job_ids = await self.get_all_job_ids(page, total_count, max_pages)
            print(f"Collected {len(job_ids)} NVIDIA job IDs.", flush=True)
            
            # Step 3: Scrape job details in parallel
            tasks = []
            for i, jid in enumerate(job_ids):
                tasks.append(self.scrape_job_with_semaphore(context, jid, i+1, len(job_ids)))
            
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
            # Final Save
            self.save_to_formats("nvidia")
            if start_time:
                self.save_to_json_schema("nvidia", "NVIDIA Corporation", "nvidia.eightfold.ai", start_time)
                self.save_to_rag_json("nvidia", "NVIDIA Corporation", "nvidia.eightfold.ai", start_time)
            
            await browser.close()
            print(f"NVIDIA scraping complete. Found {len(self.jobs)} jobs.", flush=True)

    async def get_all_job_ids(self, page, total_count, max_pages):
        job_ids = []
        limit_per_step = 10 
        current_offset = 0
        
        # Determine how many items to fetch
        to_fetch = total_count
        if max_pages:
            to_fetch = min(total_count, max_pages * limit_per_step)
            
        print(f"Fetching up to {to_fetch} job IDs...", flush=True)
        
        while current_offset < to_fetch:
            url = f"{self.search_api_url}?domain=nvidia.com&query=&location=&start={current_offset}&num={limit_per_step}"
            print(f"Fetching index offset {current_offset}...", flush=True)
            
            try:
                await page.goto(url)
                content = await page.evaluate("() => document.body.innerText")
                data = json.loads(content)
                
                inner_data = data.get('data', {})
                positions = inner_data.get('positions', [])
                if not positions:
                    break
                    
                for pos in positions:
                    jid = pos.get('id')
                    if jid and jid not in job_ids:
                        job_ids.append(jid)
                
                current_offset += len(positions)
                if len(positions) == 0: break
                    
            except Exception as e:
                print(f"Error at offset {current_offset}: {e}", flush=True)
                break
        
        return job_ids

    async def scrape_job_with_semaphore(self, context, jid, index, total):
        async with self.semaphore:
            if index % 50 == 0:
                print(f"Scraping NVIDIA job {index} of {total}...", flush=True)
            page = await context.new_page()
            # Visit the job portal once for this page to Ensure session
            # Actually, per-job fetch might be better via evaluate too
            url = f"{self.details_api_url}?position_id={jid}&domain=nvidia.com&hl=en"
            result = await self.scrape_job_details(page, url, jid)
            await page.close()
            return result

    async def scrape_job_details(self, page, url, jid):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await page.goto(url)
                # Shorter wait for API response
                await page.wait_for_timeout(2000)
                
                content = await page.evaluate("() => document.body.innerText")
                if not content or content.strip() == "":
                    raise ValueError("Empty response")
                    
                data = json.loads(content).get('data', {})
                if not data:
                    raise ValueError("No data in JSON")
                    
                res = {
                    "job_link": f"{self.base_url}/careers/job/{jid}",
                    "job_name": data.get('name', ''),
                    "job_location": ", ".join(data.get('locations', [])),
                    "job_department": data.get('department', ''),
                    "about_company": "NVIDIA is a leader in accelerated computing.",
                    "salary": "",
                    "compensation_details": "",
                    "eeo": "NVIDIA is committed to fostering a diverse work environment and proud to be an equal opportunity employer.",
                    "additional_links": ""
                }
                
                # Parse the combined jobDescription HTML
                html_content = data.get('jobDescription', '')
                parsed_sections = self.parse_nvidia_description(html_content)
                
                res.update(parsed_sections)
                return res
                
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"Retry {attempt + 1} for job {jid} due to: {e}. Waiting {wait_time}s...", flush=True)
                    await asyncio.sleep(wait_time)
                else:
                    print(f"Failed to scrape NVIDIA job {jid} after {max_retries} attempts: {e}", flush=True)
                    return None
        return None

    def parse_nvidia_description(self, html):
        """Splits NVIDIA's unified HTML description into structured fields."""
        if not html:
            return {
                "job_description": "",
                "job_responsibilities": "",
                "minimum_qualifications": "",
                "preferred_qualifications": ""
            }
            
        soup = BeautifulSoup(html, 'html.parser')
        
        sections = {
            "overview": [],
            "responsibilities": [],
            "minimum": [],
            "preferred": []
        }
        
        current_section = "overview"
        
        # NVIDIA typically uses <h2> or <b>/<strong> as section headers
        for elem in soup.find_all(['h1', 'h2', 'h3', 'p', 'ul']):
            text = elem.get_text().strip().lower()
            
            if not text: continue
            
            # Identify headers
            if any(h in text for h in ["what you will be doing", "what you'll be doing"]):
                current_section = "responsibilities"
            elif any(h in text for h in ["what we need to see", "minimum qualifications"]):
                current_section = "minimum"
            elif any(h in text for h in ["ways to stand out", "preferred qualifications"]):
                current_section = "preferred"
            else:
                # If it's not a header, add to the current section
                if elem.name == 'ul':
                    items = [f"• {li.get_text().strip()}" for li in elem.find_all('li')]
                    sections[current_section].extend(items)
                else:
                    sections[current_section].append(elem.get_text().strip())
                    
        return {
            "job_description": "\n".join(sections["overview"]),
            "job_responsibilities": "\n".join(sections["responsibilities"]),
            "minimum_qualifications": "\n".join(sections["minimum"]),
            "preferred_qualifications": "\n".join(sections["preferred"])
        }
