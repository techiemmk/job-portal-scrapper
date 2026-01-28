import asyncio
import re
import json
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class GoogleScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://www.google.com/about/careers/applications", concurrency=concurrency)
        self.search_url = f"{self.base_url}/jobs/results/"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            # Step 1: Collect all job links
            job_links = await self.get_all_job_links(context, max_pages)
            print(f"Total Google jobs to scrape: {len(job_links)}")
            
            # Step 2: Scrape job details in parallel
            tasks = []
            for link in job_links:
                tasks.append(self.scrape_job_with_semaphore(context, link))
            
            # Execute tasks
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
            # Final Save
            self.save_to_formats("google")
            if start_time:
                self.save_to_rag_json("google", "Google LLC", "google.com/about/careers", start_time)
            
            await browser.close()
            print(f"Google scraping complete. Found {len(self.jobs)} jobs.")

    async def get_all_job_links(self, context, max_pages):
        page = await context.new_page()
        print(f"Opening Google Careers to collect job links...")
        
        all_links = []
        limit_pages = max_pages if max_pages else 999 # Google usually has many pages
        
        for i in range(1, limit_pages + 1):
            url = f"{self.search_url}?page={i}"
            print(f"Scraping Google index page {i}...")
            try:
                await page.goto(url)
                await page.wait_for_timeout(3000)
                
                # Check if we've reached the end
                no_results = await page.query_selector('text="No results found"')
                if no_results:
                    print("Reached end of Google job results.")
                    break
                
                # Extract jobs from Script Data
                page_jobs = await page.evaluate(r"""() => {
                    const scripts = Array.from(document.querySelectorAll('script'));
                    const target = scripts.find(s => s.textContent.includes("AF_initDataCallback") && s.textContent.includes("ds:1"));
                    if (!target) return [];
                    
                    try {
                        const content = target.textContent;
                        const match = content.match(/AF_initDataCallback\(([\s\S]*)\)/);
                        if (!match) return [];
                        
                        const config = eval("(" + match[1] + ")");
                        const jobs = config.data[0]; 
                        return jobs.map(j => {
                            const jobId = j[0];
                            const slug = j[1] ? j[1].toLowerCase().replace(/[^a-z0-9]+/g, '-') : 'job';
                            // Return the full path
                            return `/about/careers/applications/jobs/results/${jobId}-${slug}`;
                        });
                    } catch (e) {
                        return [];
                    }
                }""")
                
                if not page_jobs:
                    # Fallback to DOM with more specific selector and NATIVE RESOLUTION
                    page_jobs = await page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a[aria-label^="Learn more about"]'))
                                    .map(a => a.href);
                    }""")

                if not page_jobs:
                    break
                    
                for link in page_jobs:
                    if not link: continue
                    if '/jobs/results/' in link and link not in all_links:
                        all_links.append(link)
                
            except Exception as e:
                print(f"Error scraping Google index page {i}: {e}")
                break
        
        await page.close()
        return all_links

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

            # Try to find the data in any script tag that might contain it
            job_data = await page.evaluate(r"""() => {
                const scripts = Array.from(document.querySelectorAll('script'));
                for (const script of scripts) {
                    const content = script.textContent;
                    if (content.includes('AF_initDataCallback')) {
                        try {
                            const match = content.match(/AF_initDataCallback\(([\s\S]*)\)/);
                            if (match) {
                                const config = eval("(" + match[1] + ")");
                                const rawData = config.data;
                                // On detail pages, rawData is often [ [job_details] ]
                                if (rawData && rawData[0] && rawData[0][0] && rawData[0][0].length > 5) {
                                    return rawData;
                                }
                            }
                        } catch (e) {}
                    }
                }
                return null;
            }""")

            if not job_data:
                # Fallback to Schema.org JobPosting
                html = await page.content()
                return self.extract_schema_job_data(html, url)

            if job_data and len(job_data) > 0:
                # rawData is [ [job_details] ]
                raw = job_data[0]
                res = {
                    "job_link": url,
                    "job_name": raw[1] if len(raw) > 1 else "",
                }
                
                # Responsibilities
                res['job_responsibilities'] = self.clean_html_field(raw[3][1] if len(raw) > 3 and raw[3] else "")
                
                # Qualifications (Minimum and Preferred are often in raw[4][1])
                quals_html = raw[4][1] if len(raw) > 4 and raw[4] else ""
                soup = BeautifulSoup(quals_html, 'html.parser')
                
                min_quals = []
                pref_quals = []
                
                current_section = None
                for element in soup.children:
                    text = element.get_text().lower()
                    if 'minimum' in text:
                        current_section = 'min'
                    elif 'preferred' in text:
                        current_section = 'pref'
                    
                    if element.name == 'ul':
                        items = [f"• {li.get_text().strip()}" for li in element.find_all('li')]
                        if current_section == 'min':
                            min_quals.extend(items)
                        elif current_section == 'pref':
                            pref_quals.extend(items)
                
                res['minimum_qualifications'] = "\n".join(min_quals)
                res['preferred_qualifications'] = "\n".join(pref_quals)
                
                # Description (often in raw[2][1] or raw[5][1])
                # Based on observation, raw[2] or raw[5] contains description parts
                desc_parts = []
                for idx in [2, 5]:
                    if len(raw) > idx and raw[idx] and isinstance(raw[idx], list) and len(raw[idx]) > 1:
                        val = self.clean_html_field(raw[idx][1])
                        if val:
                            desc_parts.append(str(val))
                res['job_description'] = "\n\n".join(desc_parts)
                
                # Locations (often in raw[14])
                locations = []
                if len(raw) > 14 and raw[14]:
                    for loc in raw[14]:
                        if isinstance(loc, list) and len(loc) > 1:
                            locations.append(loc[1])
                res['job_location'] = ", ".join([str(l) for l in locations])
                
                # About Company - Standard Google blurb
                res['about_company'] = "Google is proud to be an equal opportunity workplace and is an affirmative action employer."
                
                # EEO Statement - Standard Google EEO
                res['eeo'] = "Google is an Equal Opportunity Employer. All qualified applicants will receive consideration for employment without regard to race, color, religion, sex, sexual orientation, gender identity, national origin, disability, or protected veteran status."
                
                # Links from description
                res['additional_links'] = ", ".join(self.extract_links_from_field(quals_html))
                
                return res

            return None

        except Exception as e:
            print(f"Error scraping Google job {url}: {e}")
            return None
