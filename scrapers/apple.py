import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from base_scraper import BaseJobScraper

class AppleScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://jobs.apple.com", concurrency=concurrency)

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            print(f"Opening Apple Careers to collect job links...", flush=True)
            
            # Step 1: Collect all job links
            all_links = await self.get_all_job_links(context, max_pages)
            print(f"Total Apple jobs to scrape: {len(all_links)}", flush=True)
            
            # Step 2: Scrape job details in parallel
            tasks = []
            for i, url in enumerate(all_links):
                tasks.append(self.scrape_job_with_semaphore(context, url, i+1, len(all_links)))
            
            # Execute tasks
            results = await asyncio.gather(*tasks)
            self.jobs = [r for r in results if r]
            
            # Final Save
            self.save_to_formats("apple")
            if start_time:
                self.save_to_json_schema("apple", "Apple Inc.", "jobs.apple.com", start_time)
                self.save_to_rag_json("apple", "Apple Inc.", "jobs.apple.com", start_time)
            
            await browser.close()
            print(f"Apple scraping complete. Found {len(self.jobs)} jobs.", flush=True)

    async def get_all_job_links(self, context, max_pages):
        all_links = []
        page = await context.new_page()
        
        base_search_url = f"{self.base_url}/en-us/search"
        print(f"Opening Apple Careers search: {base_search_url}", flush=True)
        await page.goto(base_search_url)
        await page.wait_for_timeout(5000)
        
        # Step 1: Ensure global scope by clearing location filters
        try:
            print("Clearing all filters to ensure global scope...", flush=True)
            # 1. Try Clear all button by ID
            clear_btn = await page.query_selector("button#search-filters-clear-all-button")
            if clear_btn:
                await clear_btn.click()
                print("Clicked Clear All button (ID).", flush=True)
            else:
                # 2. Try Clear all by text if ID not found
                # Often it's a button or an anchor
                try:
                    await page.click('button:has-text("Clear all")', timeout=5000)
                    print("Clicked Clear All button (Text).", flush=True)
                except:
                    # 3. Try checkbox uncheck
                    try:
                        await page.click('button#title-search-location-filter-accordion-0', timeout=5000)
                        await page.wait_for_timeout(1000)
                        await page.evaluate('document.querySelector(\'input[aria-labelledby="filter-location-postLocation-USA_label"]\').click()')
                        print("Unchecked USA checkbox.", flush=True)
                    except:
                        pass
            
            await page.wait_for_timeout(5000)
            # Scroll down to ensure pagination elements are rendered/loaded
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Filter clearing interaction failed: {e}", flush=True)

        # Step 2: Get total pages from data-autom="paginationTotalPages"
        total_pages = 0
        print("Waiting for total pages count to appear...", flush=True)
        for _ in range(5):
            try:
                # Re-scroll
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_selector('span[data-autom="paginationTotalPages"]', timeout=5000)
                total_pages_text = await page.get_attribute('span[data-autom="paginationTotalPages"]', 'innerText')
                if total_pages_text:
                    total_pages = int(total_pages_text.strip())
                    if total_pages > 1: break
            except:
                pass
            await page.wait_for_timeout(2000)
            
        if total_pages <= 1:
            print("Warning: Site still reporting 1 page. Using high default for global crawl.", flush=True)
            total_pages = 315 # Recent check showed ~310
        else:
            print(f"Site reports {total_pages} total pages available.", flush=True)

        # Determine how many pages to fetch
        pages_to_fetch = min(total_pages, max_pages) if max_pages else total_pages
        print(f"Traversing {pages_to_fetch} pages for job links...", flush=True)
        
        for i in range(1, pages_to_fetch + 1):
            url = f"{base_search_url}?page={i}"
            print(f"Scraping Apple index page {i} of {pages_to_fetch}...", flush=True)
            
            try:
                await page.goto(url)
                # Wait for any detailed results list item to appear
                await page.wait_for_selector('a.link-inline', timeout=15000)
                
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a.link-inline'))
                                .map(a => a.href)
                                .filter(href => href.includes('/details/'));
                }""")
                
                if not links:
                    print(f"No jobs found on Apple page {i}", flush=True)
                    if i > 1: break
                    
                for link in links:
                    if link not in all_links:
                        all_links.append(link)
                        
            except Exception as e:
                print(f"Error scraping Apple index page {i}: {e}", flush=True)
                continue
        
        await page.close()
        return all_links

    async def scrape_job_with_semaphore(self, context, url, index, total):
        async with self.semaphore:
            if index % 10 == 0:
                print(f"Scraping Apple job {index} of {total}...", flush=True)
            page = await context.new_page()
            result = await self.scrape_job_details(page, url)
            await page.close()
            return result

    async def scrape_job_details(self, page, url):
        max_retries = 2
        for attempt in range(max_retries):
            try:
                await page.goto(url)
                # Wait for any H1 to appear, suggesting the page header has loaded
                try:
                    await page.wait_for_selector('h1', timeout=10000)
                except:
                    pass
                
                # Additional wait for dynamic sections
                await page.wait_for_timeout(3000)
                
                # Extract data using evaluate for efficiency
                data = await page.evaluate("""() => {
                    const getTxt = (id) => {
                        const el = document.getElementById(id);
                        return el ? el.innerText.trim() : "";
                    };
                    
                    // Try multiple selectors for the job name
                    let name = getTxt("jd-job-summary");
                    if (!name) {
                        const h1 = document.querySelector('h1.jd-header-title') || 
                                   document.querySelector('.job-detail-header h1') || 
                                   document.querySelector('h1#jobdetails-jobtitle') || 
                                   document.querySelector('h1');
                        name = h1 ? h1.innerText.trim() : "";
                    }
                    
                    const location = getTxt("jobdetails-joblocation") || getTxt("job-location") || "";
                    const roleNum = getTxt("jobdetails-rolenumber") || "";
                    const team = getTxt("jobdetails-teamname") || "";
                    
                    // Sections can have different structures
                    const getSection = (baseId) => {
                        return getTxt(baseId) || getTxt(baseId + "-content-row") || getTxt("jobdetails-" + baseId);
                    };

                    return {
                        "name": name,
                        "location": location,
                        "roleNum": roleNum,
                        "team": team,
                        "summary": getSection("jobsummary"),
                        "description": getSection("jobdescription"),
                        "responsibilities": getSection("responsibilities"),
                        "min_quals": getSection("minimumqualifications"),
                        "pref_quals": getSection("preferredqualifications"),
                        "education": getSection("education-experience")
                    };
                }""")
                
                if (not data["name"] or data["name"].lower() == "careers") and attempt < max_retries - 1:
                    raise ValueError("Failed to load job details")
                    
                if not data["name"] or data["name"].lower() == "careers":
                    print(f"Warning: Could not extract job name from {url}", flush=True)
                    return None
                    
                # Assemble job description from available parts
                full_desc = data["summary"]
                if data["description"]:
                    full_desc += "\\n\\nDescription:\\n" + data["description"]
                if data["responsibilities"]:
                    full_desc += "\\n\\nResponsibilities:\\n" + data["responsibilities"]
                if data["education"]:
                    full_desc += "\\n\\nEducation & Experience:\\n" + data["education"]

                res = {
                    "job_link": url,
                    "job_name": data["name"],
                    "job_location": data["location"] or "Global", 
                    "job_department": data["team"],
                    "job_description": full_desc.strip(),
                    "job_responsibilities": data["responsibilities"] or data["description"],
                    "minimum_qualifications": data["min_quals"],
                    "preferred_qualifications": data["pref_quals"],
                    "about_company": "Apple is a leader in consumer electronics, software and services.",
                    "salary": "",
                    "compensation_details": "",
                    "eeo": "Apple is an equal opportunity employer that is committed to inclusion and diversity.",
                    "additional_links": f"Role Number: {data['roleNum']}" if data['roleNum'] else ""
                }
                
                return res
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Retry {attempt + 1} for Apple job {url}: {e}", flush=True)
                    await asyncio.sleep(2)
                else:
                    print(f"Error scraping Apple job {url}: {e}", flush=True)
                    return None
        return None
