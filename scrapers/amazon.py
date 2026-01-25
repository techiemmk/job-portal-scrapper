import asyncio
import json
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class AmazonScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://www.amazon.jobs", concurrency=concurrency)
        self.api_url = f"{self.base_url}/en/search.json"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            page = await context.new_page()
            
            print(f"Starting Amazon Jobs scraping via API...")
            
            # Use a higher limit per request for efficiency
            limit_per_page = 100
            current_offset = 0
            pages_to_fetch = max_pages if max_pages else 10 # Default to 1000 jobs if not specified
            
            for i in range(pages_to_fetch):
                url = f"{self.api_url}?offset={current_offset}&result_limit={limit_per_page}&sort=recent"
                print(f"Fetching Amazon index {i+1} (offset {current_offset})...")
                
                try:
                    await page.goto(url)
                    await page.wait_for_timeout(2000)
                    
                    content = await page.evaluate("() => document.body.innerText")
                    data = json.loads(content)
                    
                    jobs_list = data.get('jobs', [])
                    if not jobs_list:
                        print("No more Amazon jobs found.")
                        break
                        
                    for job in jobs_list:
                        job_res = self.parse_amazon_job(job)
                        self.jobs.append(job_res)
                    
                    current_offset += limit_per_page
                    
                    # Check if we hit the total
                    total = data.get('hits', 0)
                    if current_offset >= total:
                        break
                        
                except Exception as e:
                    print(f"Error fetching Amazon API at offset {current_offset}: {e}")
                    break
            
            # Final Save
            self.save_to_formats("amazon")
            if start_time:
                self.save_to_json_schema("amazon", "Amazon.com, Inc.", "amazon.jobs", start_time)
                self.save_to_rag_json("amazon", "Amazon.com, Inc.", "amazon.jobs", start_time)
            
            await browser.close()
            print(f"Amazon scraping complete. Found {len(self.jobs)} jobs.")

    def parse_amazon_job(self, job):
        res = {
            "job_link": self.base_url + job.get('job_path', ''),
            "job_name": job.get('title', ''),
            "job_location": f"{job.get('city', '')}, {job.get('state', '')}, {job.get('country_code', '')}".strip(', '),
            "job_department": job.get('job_category', ''),
            "job_description": self.clean_html_field(job.get('description', '')),
            "job_responsibilities": "", # Often included in description for Amazon
            "minimum_qualifications": self.clean_html_field(job.get('basic_qualifications', '')),
            "preferred_qualifications": self.clean_html_field(job.get('preferred_qualifications', '')),
            "about_company": "Amazon is an equal opportunity employer and does not discriminate on the basis of race, national origin, gender, gender identity, sexual orientation, protected veteran status, disability, age, or other legally protected status.",
            "salary": "", # Amazon API usually doesn't provide salary unless required by law
            "compensation_details": "",
            "eeo": "Amazon is an Equal Opportunity Employer \u2013 Minority / Women / Disability / Veteran / Gender Identity / Sexual Orientation / Age.",
            "additional_links": ""
        }
        return res
