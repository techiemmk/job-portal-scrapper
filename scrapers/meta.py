import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
from base_scraper import BaseJobScraper

class MetaScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://www.metacareers.com", concurrency=concurrency)
        self.search_url = f"{self.base_url}/jobsearch"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            # Step 1: Collect all job links
            job_links = await self.get_all_job_links(context, max_pages)
            print(f"Total Meta jobs to scrape: {len(job_links)}")
            
            # Step 2: Scrape job details in parallel
            tasks = []
            for link in job_links:
                tasks.append(self.scrape_job_with_semaphore(context, link))
            
            # Execute tasks
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
            # Final Save
            self.save_to_formats("meta")
            if start_time:
                self.save_to_rag_json("meta", "Meta Platforms, Inc.", "metacareers.com", start_time)
            
            await browser.close()
            print(f"Meta scraping complete. Found {len(self.jobs)} jobs.")

    async def get_all_job_links(self, context, max_pages):
        page = await context.new_page()
        print(f"Opening Meta first page to determine total pages...")
        await page.goto(self.search_url)
        await page.wait_for_timeout(5000)
        
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        
        total_pages_info = await page.evaluate(r"""() => {
            const match = document.body.innerText.match(/Page \d+ of (\d+)/);
            return match ? parseInt(match[1]) : 1;
        }""")
        print(f"Total Meta pages available: {total_pages_info}")
        
        limit_pages = min(total_pages_info, max_pages) if max_pages else total_pages_info
        print(f"Scraping links from first {limit_pages} pages...")
        
        async def scrape_index_page(page_num):
            async with self.semaphore:
                p = await context.new_page()
                url = f"{self.search_url}?page={page_num}"
                try:
                    await p.goto(url)
                    await p.wait_for_timeout(3000)
                    page_links = await p.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a[href*="/profile/job_details/"]'))
                                    .map(a => a.href);
                    }""")
                    await p.close()
                    return page_links
                except Exception as e:
                    print(f"Error scraping Meta index page {page_num}: {e}")
                    await p.close()
                    return []

        index_tasks = [scrape_index_page(i) for i in range(1, limit_pages + 1)]
        results = await asyncio.gather(*index_tasks)
        
        ordered_links = []
        seen = set()
        for r in results:
            if r:
                for link in r:
                    if link not in seen:
                        ordered_links.append(link)
                        seen.add(link)
        
        await page.close()
        return ordered_links

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

            json_data = await page.evaluate("""() => {
                const scripts = Array.from(document.querySelectorAll('script[type="application/json"]'));
                for (const script of scripts) {
                    const content = script.textContent;
                    if (content.includes('xcp_requisition_job_description')) {
                        try {
                            const parsed = JSON.parse(content);
                            let jobData = null;
                            const findKey = (obj, key) => {
                                if (obj && typeof obj === 'object') {
                                    if (obj[key]) return obj[key];
                                    for (const k in obj) {
                                        const res = findKey(obj[k], key);
                                        if (res) return res;
                                    }
                                }
                                return null;
                            };
                            jobData = findKey(parsed, 'xcp_requisition_job_description');
                            if (jobData) return jobData;
                        } catch (e) {}
                    }
                }
                return null;
            }""")

            if json_data:
                res = {}
                res['job_link'] = url
                res['job_name'] = json_data.get('title', '')
                
                # Departments
                depts = json_data.get('internal_departments', []) + json_data.get('departments', [])
                seen_depts = set()
                final_depts = []
                for d in depts:
                    if d not in seen_depts:
                        final_depts.append(d)
                        seen_depts.add(d)
                res['job_department'] = ", ".join(final_depts)
                
                res['job_location'] = ", ".join(json_data.get('locations', []))
                
                # Split Qualifications
                min_quals = [f"• {item.get('item', '')}" for item in json_data.get('minimum_qualifications', [])]
                res['minimum_qualifications'] = "\n".join(min_quals)
                
                pref_quals = [f"• {item.get('item', '')}" for item in json_data.get('preferred_qualifications', [])]
                res['preferred_qualifications'] = "\n".join(pref_quals)

                # Descriptions
                res['job_description'] = self.clean_html_field(json_data.get('description', ''))
                
                res_list = [f"• {item.get('item', '')}" for item in json_data.get('responsibilities', [])]
                res['job_responsibilities'] = "\n".join(res_list)
                
                res['about_company'] = self.clean_html_field(json_data.get('boiler_plate_intro', ''))
                
                # Salary and Compensation
                comp_list = json_data.get('public_compensation', [])
                if comp_list:
                    c = comp_list[0]
                    sal_str = f"{c.get('compensation_amount_minimum', '')} to {c.get('compensation_amount_maximum', '')}"
                    if c.get('has_bonus'): sal_str += " + bonus"
                    if c.get('has_equity'): sal_str += " + equity"
                    sal_str += " + benefits"
                    res['salary'] = sal_str
                    res['compensation_details'] = self.clean_html_field(c.get('error_apology_note', ''))
                
                # EEO
                eeo_msg = json_data.get('equal_opportunity_message', '')
                acc_msg = json_data.get('accommodations_message', '')
                res['eeo'] = self.clean_html_field(eeo_msg) + "\n\n" + self.clean_html_field(acc_msg)
                
                # Links
                all_links = set()
                sections_with_html = [
                    json_data.get('boiler_plate_intro', ''),
                    json_data.get('equal_opportunity_message', ''),
                    json_data.get('accommodations_message', ''),
                    json_data.get('description', '')
                ]
                if comp_list:
                    sections_with_html.append(comp_list[0].get('error_apology_note', ''))
                
                for section in sections_with_html:
                    all_links.update(self.extract_links_from_field(section))
                
                res['additional_links'] = ", ".join(sorted(list(all_links)))
                return res

            return None # Fallback logic could be added here if needed

        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None
