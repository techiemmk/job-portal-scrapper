import asyncio
import json
import re
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class MicrosoftScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://apply.careers.microsoft.com", concurrency=concurrency)
        self.search_base_url = f"{self.base_url}/careers"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            print(f"Starting Microsoft Jobs scraping...")
            
            # Step 1: Initialize session and get PID and total count
            await page.goto(self.search_base_url)
            await page.wait_for_timeout(5000)
            
            # The URL typically updates to something like:
            # https://apply.careers.microsoft.com/careers?start=0&pid=1970393556642939&sort_by=timestamp
            current_url = page.url
            pid_match = re.search(r'pid=(\d+)', current_url)
            pid = pid_match.group(1) if pid_match else "1970393556642939" # Fallback to a known PID if not found
            
            # Get total job count
            total_count = 0
            try:
                await page.wait_for_selector('b[data-testid="job-count"]', timeout=10000)
                count_text = await page.get_attribute('b[data-testid="job-count"]', 'innerText')
                total_count = int(re.sub(r'[^\d]', '', count_text))
            except:
                print("Warning: Could not find job count. Defaulting to 100.")
                total_count = 100

            print(f"Microsoft reports {total_count} total jobs. PID: {pid}")

            # Step 2: Collect job links via pagination
            job_links = []
            max_start = min(total_count, max_pages * 10) if max_pages else total_count
            
            for start in range(0, max_start, 10):
                p_url = f"{self.search_base_url}?start={start}&pid={pid}&sort_by=timestamp"
                print(f"Fetching Microsoft jobs from offset {start}...")
                try:
                    await page.goto(p_url)
                    await page.wait_for_timeout(3000)
                    
                    batch_links = await page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a[id*="job-card-"]'))
                                    .map(a => a.href);
                    }""")
                    
                    if not batch_links:
                        break
                        
                    for link in batch_links:
                        if link not in job_links:
                            job_links.append(link)
                except Exception as e:
                    print(f"Error at offset {start}: {e}")
                    break

            print(f"Collected {len(job_links)} Microsoft job links.")
            
            # Step 3: Scrape job details in parallel
            tasks = []
            for link in job_links:
                tasks.append(self.scrape_job_with_semaphore(context, link))
            
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
            # Final Save
            self.save_to_formats("microsoft")
            if start_time:
                self.save_to_rag_json("microsoft", "Microsoft Corporation", "careers.microsoft.com", start_time)
            
            await browser.close()
            print(f"Microsoft scraping complete. Found {len(self.jobs)} jobs.")

    async def scrape_job_with_semaphore(self, context, url):
        async with self.semaphore:
            page = await context.new_page()
            result = await self.scrape_job_details(page, url)
            await page.close()
            return result

    async def scrape_job_details(self, page, url):
        try:
            await page.goto(url)
            await page.wait_for_timeout(5000)
            
            # Microsoft job pages are dynamic. We'll use evaluate to pull relevant sections.
            data = await page.evaluate("""() => {
                const getTxt = (sel) => {
                    const el = document.querySelector(sel);
                    return el ? el.innerText.trim() : "";
                };
                
                // Title
                const title = document.querySelector('h1') ? document.querySelector('h1').innerText.trim() : 
                              document.querySelector('h2[class*="title"]') ? document.querySelector('h2[class*="title"]').innerText.trim() : "N/A";
                
                // Location
                // Usually in a div with some icons
                const locEl = Array.from(document.querySelectorAll('div, span')).find(el => el.textContent.includes(',') && /\\w+, \\w+/.test(el.textContent));
                const location = locEl ? locEl.innerText.trim() : "N/A";

                // Content Sections
                // Headers are usually <b> tags in a container
                const sections = {};
                const headers = Array.from(document.querySelectorAll('b')).filter(b => 
                    ['overview', 'responsibilities', 'qualifications', 'benefits'].includes(b.textContent.trim().toLowerCase())
                );

                headers.forEach(h => {
                    const key = h.textContent.trim().toLowerCase();
                    // The content is usually in siblings that follow
                    let content = "";
                    let curr = h.nextSibling;
                    while (curr && curr.tagName !== 'B') {
                        content += curr.textContent || "";
                        curr = curr.nextSibling;
                    }
                    sections[key] = content.trim();
                });

                return {
                    title,
                    location,
                    sections,
                    full_html: document.body.innerHTML
                };
            }""")

            if data['title'] == "N/A":
                return None

            res = {
                "job_link": url,
                "job_name": data['title'],
                "job_location": data['location'],
                "job_department": "", 
                "job_description": data['sections'].get('overview', ''),
                "job_responsibilities": data['sections'].get('responsibilities', ''),
                "minimum_qualifications": data['sections'].get('qualifications', ''),
                "preferred_qualifications": "",
                "about_company": "Microsoft is a global leader in software, services, devices, and solutions.",
                "salary": "",
                "compensation_details": "",
                "eeo": "Microsoft is an equal opportunity employer. All qualified applicants will receive consideration for employment without regard to age, ancestry, color, family or medical care leave, gender identity or expression, genetic information, marital status, medical condition, national origin, physical or mental disability, political affiliation, protected veteran status, race, religion, sex (including pregnancy), sexual orientation, or any other characteristic protected by applicable laws, regulations and ordinances.",
                "additional_links": ""
            }
            
            # If description is empty, fallback to cleaning the full text
            if not res["job_description"]:
                 res["job_description"] = self.clean_html_field(data['full_html'])
            
            return res
        except Exception as e:
            print(f"Error scraping Microsoft job {url}: {e}")
            return None
