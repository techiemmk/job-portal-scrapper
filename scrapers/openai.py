import asyncio
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
            
            # Step 1: Collect job links from the Ashby page
            job_links = await self.get_all_job_links(context)
            if max_pages:
                # Ashby has one single page, so 'max_pages' for them might just mean a limit on jobs
                job_links = job_links[:max_pages * 20] 
                
            print(f"Total OpenAI (Ashby) jobs to scrape: {len(job_links)}")
            
            # Step 2: Scrape job details in parallel
            tasks = []
            for link in job_links:
                tasks.append(self.scrape_job_with_semaphore(context, link))
            
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
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
            # Wait for any job link to appear
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

    async def scrape_job_with_semaphore(self, context, url):
        async with self.semaphore:
            page = await context.new_page()
            result = await self.scrape_job_details(page, url)
            await page.close()
            return result

    async def scrape_job_details(self, page, url):
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            
            # Extract data using Ashby selectors
            data = await page.evaluate("""() => {
                const title = document.querySelector('h1.ashby-job-posting-heading') ? 
                              document.querySelector('h1.ashby-job-posting-heading').innerText.trim() : "";
                
                // Location search
                let location = "";
                const allDivs = Array.from(document.querySelectorAll('div, p, span'));
                const locLabel = allDivs.find(el => el.innerText.trim() === 'Location');
                if (locLabel && locLabel.nextElementSibling) {
                    location = locLabel.nextElementSibling.innerText.trim();
                }

                // Main content
                const contentEl = document.querySelector('[role="tabpanel"]#overview') || 
                                  document.querySelector('._descriptionText_oj0x8_198') ||
                                  document.querySelector('main');
                
                return {
                    title: title,
                    location: location,
                    html: contentEl ? contentEl.innerHTML : document.body.innerHTML
                };
            }""")

            if not data['title']:
                return None

            full_content = self.clean_html_field(data['html'])
            
            res = {
                "job_link": url,
                "job_name": data['title'],
                "job_location": data['location'],
                "job_department": "", 
                "job_description": full_content,
                "job_responsibilities": "",
                "minimum_qualifications": "",
                "preferred_qualifications": "",
                "about_company": "OpenAI is an AI research and deployment company. Our mission is to ensure that artificial general intelligence benefits all of humanity.",
                "salary": "",
                "compensation_details": "",
                "eeo": "OpenAI is an equal opportunity employer. We do not discriminate on the basis of race, religion, color, national origin, gender, sexual orientation, age, marital status, veteran status, or disability status.",
                "additional_links": ""
            }
            
            return res
        except Exception as e:
            print(f"Error scraping OpenAI job {url}: {e}")
            return None
