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

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            # Start with Schema.org fallback or empty dict
            res = self.extract_schema_job_data(html, url)
            if not res:
                res = {
                    "job_link": url,
                    "job_name": "",
                    "job_department": "",
                    "job_location": "",
                    "job_description": "",
                    "minimum_qualifications": "",
                    "preferred_qualifications": "",
                    "job_responsibilities": "",
                    "about_company": "",
                    "eeo": "",
                    "additional_links": ""
                }

            # Job title from h2 with class 'p1N2lc'
            title_elem = soup.find('h2', class_='p1N2lc')
            if title_elem:
                res["job_name"] = title_elem.get_text().strip()

            # Try to extract JS data for qualifications and responsibilities
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
                                if (rawData && rawData[0] && rawData[0][0] && rawData[0][0].length > 5) {
                                    return rawData;
                                }
                            }
                        } catch (e) {}
                    }
                }
                return null;
            }""")

            if job_data and len(job_data) > 0:
                raw = job_data[0]
                if not res.get("job_name") and len(raw) > 1:
                    res["job_name"] = raw[1]
                
                # Qualifications and responsibilities
                if len(raw) > 3 and raw[3]:
                    res['job_responsibilities'] = self.clean_html_field(raw[3][1])
                
                quals_html = raw[4][1] if len(raw) > 4 and raw[4] else ""
                q_soup = BeautifulSoup(quals_html, 'html.parser')
                min_quals, pref_quals = [], []
                current_section = None
                for element in q_soup.children:
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
                if min_quals:
                    res['minimum_qualifications'] = "\n".join(min_quals)
                if pref_quals:
                    res['preferred_qualifications'] = "\n".join(pref_quals)

            # --- DOM-based parsing using specific CSS classes ---
            
            # Department: extract from the child <span> inside '.RP7SMd'
            # (The outer RP7SMd also contains an icon; the actual text is in a nested span)
            dept_elem = soup.find(class_='RP7SMd')
            if dept_elem:
                child_span = dept_elem.find('span')
                if child_span:
                    res['job_department'] = child_span.get_text().strip()
                else:
                    res['job_department'] = dept_elem.get_text().strip()

            # Location: inside span with class 'pwO9Dc vo5qdf',
            # iterate each child span with class 'r0wTof' for clean location text
            loc_container = soup.find(class_='pwO9Dc vo5qdf')
            if loc_container:
                loc_spans = loc_container.find_all('span', class_='r0wTof')
                locations = [s.get_text().strip() for s in loc_spans if s.get_text().strip()]
                # Remove duplicates while preserving order
                unique_locs = []
                for loc in locations:
                    if loc not in unique_locs:
                        unique_locs.append(loc)
                if unique_locs:
                    res['job_location'] = ", ".join(unique_locs)

            # Collect all additional links from multiple sections
            all_links = []

            # Job description: div with class 'aG5W3'
            # Remove the leading <h3>About the job</h3> header before cleaning
            desc_elem = soup.find('div', class_='aG5W3')
            if desc_elem:
                # Remove the "About the job" heading so it doesn't end up in the stored description
                about_heading = desc_elem.find('h3')
                if about_heading and 'about the job' in about_heading.get_text().lower():
                    about_heading.decompose()
                
                # Check <p> tags for compensation/salary details
                # Pattern: "salary range for this full-time position is $120,000-$172,000 + bonus + equity + benefits"
                for p_tag in desc_elem.find_all('p'):
                    p_text = p_tag.get_text().strip()
                    if re.search(r'salary\s+range', p_text, re.IGNORECASE):
                        res['compensation_details'] = p_text
                        # Also try to extract the raw salary string for the salary column
                        salary_match = re.search(r'\$[\d,]+\s*[-–]\s*\$[\d,]+', p_text)
                        if salary_match:
                            res['salary'] = salary_match.group(0)
                        # Remove this paragraph from description so it isn't duplicated
                        p_tag.decompose()
                        break

                desc_html = str(desc_elem)
                res['job_description'] = self.clean_html_field(desc_html)
                
                # Hyperlinks from the description div
                all_links.extend(self.extract_links_from_field(desc_html))

            # Responsibilities: <li> tags inside div with class 'BDNOWe'
            resp_elem = soup.find('div', class_='BDNOWe')
            if resp_elem:
                li_items = resp_elem.find_all('li')
                if li_items:
                    responsibilities = [f"• {li.get_text().strip()}" for li in li_items if li.get_text().strip()]
                    if responsibilities:
                        res['job_responsibilities'] = "\n".join(responsibilities)

            # EEO statement & additional links from div with class 'XS9rpb'
            eeo_container = soup.find('div', class_='XS9rpb')
            if eeo_container:
                p_tags = eeo_container.find_all('p')
                # Second <p> tag is the EEO statement
                if len(p_tags) >= 2:
                    res['eeo'] = self.clean_html_field(str(p_tags[1]))
                elif len(p_tags) == 1:
                    res['eeo'] = self.clean_html_field(str(p_tags[0]))
                
                # Iterate all p.ciFk0 tags and extract their hyperlinks
                cif_p_tags = eeo_container.find_all('p', class_='ciFk0')
                for p_tag in cif_p_tags:
                    all_links.extend(self.extract_links_from_field(str(p_tag)))

            # Deduplicate links while preserving order, store as comma-separated string
            unique_links = []
            for link in all_links:
                if link not in unique_links:
                    unique_links.append(link)
            res['additional_links'] = ", ".join(unique_links)

            return res

        except Exception as e:
            print(f"Error scraping Google job {url}: {e}")
            return None
