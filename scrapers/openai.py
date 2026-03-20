import asyncio
import re
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class OpenAIScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        # Using Ashby portal as it's more reliable and contains the actual job data
        super().__init__(base_url="https://jobs.ashbyhq.com", concurrency=concurrency)
        self.search_url = f"{self.base_url}/openai"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            
            print(f"Starting OpenAI Jobs scraping...")
            
            # Step 1: Collect job links
            job_links = await self.get_all_job_links(context)
            if max_pages:
                job_links = job_links[:max_pages * 20] 
                
            print(f"Total OpenAI jobs to scrape: {len(job_links)}")
            
            # Step 2: Scrape job details in staggered batches using BaseJobScraper logic
            self.jobs = await self.scrape_jobs_in_batches(context, job_links, "openai")
            
            # Final Save
            self.save_to_formats("openai")
            if start_time:
                self.save_to_rag_json("openai", "OpenAI", "openai.com", start_time)
            
            await browser.close()
            print(f"OpenAI scraping complete. Found {len(self.jobs)} jobs.")

    async def get_all_job_links(self, context):
        page = await context.new_page()
        print(f"Opening OpenAI Ashby Portal to collect job links...")
        
        try:
            await page.goto(self.search_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector('a[href*="/openai/"]', timeout=30000)
            
            # Scroll to end to ensure all jobs are loaded
            last_height = await page.evaluate("document.body.scrollHeight")
            while True:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href*="/openai/"]'))
                            .filter(a => a.href.includes('/openai/') && !a.href.endsWith('/openai'))
                            .map(a => a.href);
            }""")
            
            await page.close()
            return sorted(list(set(links)))
        except Exception as e:
            print(f"Error collecting OpenAI links: {e}")
            await page.close()
            return []

    async def scrape_job_details(self, page, url):
        """Extract job details by loading the job posting HTML and parsing Schema.org JSON-LD."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = await page.content()
            
            res = self.extract_schema_job_data(html, url)
            if not res:
                print(f"Could not extract Schema.org data for {url}")
                return None
                
            # Refine description parsing
            raw_desc = res.get("job_description", "")
            if raw_desc:
                parsed = self.parse_openai_description(raw_desc)
                res.update(parsed)
                
            # If about_company is empty via schema mapping, fallback
            if not res.get("about_company"):
                res["about_company"] = "OpenAI is an AI research and deployment company. Our mission is to ensure that artificial general intelligence benefits all of humanity."

            res["job_link"] = url
            if "apply" not in res.get("additional_links", ""):
                res["additional_links"] = f"{url}/application"
            
            return res
            
        except Exception as e:
            print(f"Error scraping OpenAI job {url}: {e}")
            return None

    def parse_openai_description(self, desc_text):
        """
        Parses text based on common OpenAI/Ashby headers.
        """
        sections = {
            "job_description": "",
            "job_responsibilities": "",
            "minimum_qualifications": "",
            "about_company": "",
            "eeo": ""
        }
        
        # Split by blocks. We assume headers are somewhat isolated.
        # But wait, BaseJobScraper's clean_html_field already splits `p` and `li` via newlines,
        # BaseJobScraper's clean_html_field converts <p> and <li> to use actual newlines
        blocks = [b.strip() for b in desc_text.split('\n\n') if b.strip()]
        if len(blocks) <= 1:
            blocks = [b.strip() for b in desc_text.split('\n') if b.strip()]
            
        current_section = "job_description"
        
        for block in blocks:
            lower_block = block.lower().strip()
            
            # Identify section transitions based on headers (ensuring block is short to be a header)
            is_header = len(lower_block) < 80

            if is_header and ("about the team" in lower_block or "about the role" in lower_block):
                current_section = "job_description"
                continue # Skip the header itself
                
            elif is_header and ("thrive in this role" in lower_block or "looking for" in lower_block or "minimum qualifications" in lower_block or "what you'll need" in lower_block):
                current_section = "minimum_qualifications"
                continue
                
            elif is_header and ("responsibilities" in lower_block or "in this role, you will" in lower_block):
                current_section = "job_responsibilities"
                continue
                
            elif is_header and ("about openai" in lower_block):
                current_section = "about_company"
                continue
                
            elif is_header and ("equal opportunity" in lower_block or "affirmative action" in lower_block or "to notify openai" in lower_block or "reasonable accommodation" in lower_block):
                current_section = "eeo"

            sections[current_section] += block + "\n\n"

        for k in sections:
            sections[k] = sections[k].strip()
            
        return sections
