import asyncio
import json
import re
from bs4 import BeautifulSoup
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
            
            # Get total job count from the page text (e.g., "2954 jobs")
            total_count = 0
            try:
                # Try to find the "X jobs" text displayed at the top of the listing
                count_text = await page.evaluate("""() => {
                    const bodyText = document.body.innerText;
                    const match = bodyText.match(/(\\d[\\d,]+)\\s*jobs?/i);
                    if (match) return match[1].replace(/,/g, '');
                    // Fallback: try "X of Y" pagination text (Y * 10 = approx total)
                    const pageMatch = bodyText.match(/\\d+\\s*of\\s*(\\d+)/i);
                    if (pageMatch) return String(parseInt(pageMatch[1]) * 10);
                    return '0';
                }""")
                total_count = int(count_text) if count_text else 0
            except:
                pass
            
            if total_count == 0:
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
            
            # Step 3: Scrape job details in staggered batches (handled by base class)
            self.jobs = await self.scrape_jobs_in_batches(context, job_links, "microsoft")
            
            # Final Save
            self.save_to_formats("microsoft")
            if start_time:
                self.save_to_rag_json("microsoft", "Microsoft Corporation", "careers.microsoft.com", start_time)
            
            await browser.close()
            print(f"Microsoft scraping complete. Found {len(self.jobs)} jobs.")

    async def scrape_job_details(self, page, url):
        try:
            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(5000)

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            # --- Expand hidden locations by clicking "+X more" button ---
            try:
                more_btn = await page.query_selector('button[class*="moreLocationButton"]')
                if more_btn:
                    await more_btn.click()
                    await page.wait_for_timeout(1000)
                    # Re-grab HTML after expansion
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
            except Exception:
                pass  # If button not found or click fails, continue with original HTML

            res = {
                "job_link": url,
                "job_name": "",
                "job_location": "",
                "job_department": "",
                "job_description": "",
                "job_responsibilities": "",
                "minimum_qualifications": "",
                "preferred_qualifications": "",
                "about_company": "",
                "salary": "",
                "compensation_details": "",
                "eeo": "",
                "additional_links": ""
            }

            # --- Extract Schema.org JSON-LD (JobPosting) data as primary source ---
            schema_data = None
            for script_tag in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script_tag.string)
                    if isinstance(data, dict) and data.get('@type') == 'JobPosting':
                        schema_data = data
                        break
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                                schema_data = item
                                break
                except (json.JSONDecodeError, TypeError):
                    continue

            if schema_data:
                # Title from schema
                if schema_data.get('title'):
                    res['job_name'] = self.clean_html_field(schema_data['title'])
                
                # Description from schema — this is the cleanest source
                if schema_data.get('description'):
                    res['job_description'] = self.clean_html_field(schema_data['description'])
                
                # Posted date from schema
                if schema_data.get('datePosted'):
                    res['posted_date'] = schema_data['datePosted']
                
                # Locations from schema — gives us ALL locations without clicking "+X more"
                if schema_data.get('jobLocation'):
                    job_locations = schema_data['jobLocation']
                    if not isinstance(job_locations, list):
                        job_locations = [job_locations]
                    loc_strings = []
                    for loc in job_locations:
                        addr = loc.get('address', {})
                        city = addr.get('addressLocality', '')
                        region = addr.get('addressRegion', '').split(',')[0] if addr.get('addressRegion') else ''
                        country = addr.get('addressCountry', {})
                        country_name = country.get('name', '') if isinstance(country, dict) else str(country)
                        parts = [p for p in [city, region, country_name] if p]
                        if parts:
                            loc_strings.append(", ".join(parts))
                    if loc_strings:
                        res['job_location'] = "; ".join(loc_strings)

                # About Company from schema description — Microsoft descriptions often end with
                # "Microsoft's mission is to empower every person and every organization..."
                if schema_data.get('description'):
                    desc_text = schema_data['description']
                    # Look for the mission statement paragraph
                    mission_match = re.search(
                        r"(Microsoft[''']?s mission is to empower[\s\S]*?)$",
                        desc_text, re.IGNORECASE
                    )
                    if mission_match:
                        res['about_company'] = mission_match.group(1).strip()

            # --- Fallback: title from DOM if schema didn't provide it ---
            if not res['job_name']:
                title_elem = soup.find('h2', class_='position-title-3TPtN')
                if title_elem:
                    res['job_name'] = self.clean_html_field(title_elem.get_text())
                else:
                    h_elem = soup.find('h1') or soup.find('h2')
                    if h_elem:
                        res['job_name'] = self.clean_html_field(h_elem.get_text())

            if not res['job_name'] or res['job_name'] == 'N/A':
                return None

            # --- Fallback: location from DOM if schema didn't provide it ---
            if not res['job_location']:
                # Expand hidden locations by clicking "+X more" button
                try:
                    more_btn = await page.query_selector('button[class*="moreLocationButton"]')
                    if more_btn:
                        await more_btn.click()
                        await page.wait_for_timeout(1000)
                        html = await page.content()
                        soup = BeautifulSoup(html, 'html.parser')
                except Exception:
                    pass

                locations = []
                loc_elems = soup.find_all(class_=re.compile(r'position-location'))
                for elem in loc_elems:
                    loc_text = elem.get_text().strip()
                    if re.match(r'^\+\d+ more$', loc_text):
                        continue
                    if loc_text and loc_text not in locations:
                        locations.append(loc_text)
                
                cleaned_locations = []
                for loc in locations:
                    loc = re.sub(r'\+\d+\s*more', '', loc).strip()
                    if loc and loc not in cleaned_locations:
                        cleaned_locations.append(loc)
                if cleaned_locations:
                    res['job_location'] = ", ".join(cleaned_locations)

            # --- Parse sections by finding bold headers or strong text ---
            # Microsoft pages structure: bold/strong text headers followed by content
            # IMPORTANT: Scope parsing to the job description container to avoid
            # capturing sidebar job cards and footer/nav content
            desc_container = soup.find('div', class_=re.compile(r'position-description'))
            parse_scope = desc_container if desc_container else soup
            
            # Helper: find <li> tags after a header element containing specific text
            def extract_section_items(header_keywords):
                """Find a p/div/strong/b tag containing header_keywords, then get li items from the next ul."""
                items = []
                for tag in parse_scope.find_all(['p', 'div', 'strong', 'b', 'h2', 'h3', 'h4']):
                    tag_text = tag.get_text().strip()
                    if any(kw.lower() in tag_text.lower() for kw in header_keywords):
                        # If the header is a <strong>/<b> inside a <p>, we need to start
                        # from the parent <p>'s next sibling, not the <strong>'s sibling
                        search_from = tag
                        if tag.name in ('strong', 'b') and tag.parent and tag.parent.name == 'p':
                            search_from = tag.parent
                        
                        # Look for the next sibling ul/ol
                        sibling = search_from.find_next_sibling()
                        while sibling:
                            if sibling.name in ('ul', 'ol'):
                                for li in sibling.find_all('li'):
                                    li_text = li.get_text().strip()
                                    if li_text:
                                        items.append(f"• {li_text}")
                                break
                            elif sibling.name in ('p', 'div', 'h2', 'h3', 'h4'):
                                # Check if this is a section header (contains bold text)
                                strong = sibling.find(['strong', 'b'])
                                if strong:
                                    break
                            sibling = sibling.find_next_sibling()
                        if items:
                            break
                return items

            # --- Preferred/Additional Qualifications ---
            pref_quals = extract_section_items(['Preferred Qualifications', 'Additional Qualifications', 'Preferred/Additional Qualifications'])
            if pref_quals:
                res['preferred_qualifications'] = "\n".join(pref_quals)

            # --- Required/Minimum Qualifications ---
            min_quals = extract_section_items(['Required Qualifications', 'Minimum Qualifications', 'Required/Minimum Qualifications'])
            if min_quals:
                res['minimum_qualifications'] = "\n".join(min_quals)

            # --- Responsibilities ---
            resp_items = extract_section_items(['Responsibilities'])
            if resp_items:
                res['job_responsibilities'] = "\n".join(resp_items)

            # --- Overview / Description (fallback if schema didn't provide it) ---
            if not res['job_description']:
                for tag in parse_scope.find_all(['strong', 'b', 'p', 'div', 'h2', 'h3', 'h4']):
                    tag_text = tag.get_text().strip().lower()
                    if tag_text == 'overview':
                        search_from = tag
                        if tag.name in ('strong', 'b') and tag.parent and tag.parent.name == 'p':
                            search_from = tag.parent
                        
                        desc_parts = []
                        sibling = search_from.find_next_sibling()
                        while sibling:
                            sib_text = sibling.get_text().strip()
                            if sibling.name in ('p',):
                                strong_child = sibling.find(['strong', 'b'])
                                if strong_child and strong_child.get_text().strip().lower() in (
                                    'responsibilities', 'qualifications', 'benefits',
                                    'required qualifications', 'required/minimum qualifications'
                                ):
                                    break
                                if sib_text:
                                    desc_parts.append(sib_text)
                            elif sibling.name in ('h2', 'h3', 'h4', 'strong', 'b'):
                                if sibling.get_text().strip().lower() in ('responsibilities', 'qualifications', 'benefits'):
                                    break
                            elif sibling.name in ('ul', 'ol'):
                                for li in sibling.find_all('li'):
                                    li_text = li.get_text().strip()
                                    if li_text:
                                        desc_parts.append(f"• {li_text}")
                            sibling = sibling.find_next_sibling()
                        if desc_parts:
                            res['job_description'] = "\n\n".join(desc_parts)
                        break
                
                # Last resort fallback
                if not res['job_description']:
                    if desc_container:
                        res['job_description'] = self.clean_html_field(str(desc_container))
                    else:
                        full_text = self.clean_html_field(html)
                        res['job_description'] = full_text[:5000] if len(full_text) > 5000 else full_text

            # --- Compensation details: look for paragraphs mentioning salary/pay range ---
            comp_parts = []
            for p_tag in soup.find_all('p'):
                p_text = p_tag.get_text().strip()
                if re.search(r'(base pay range|typical base pay|salary range|USD\s*\$[\d,]+)', p_text, re.IGNORECASE):
                    comp_parts.append(p_text)
                    # Extract salary figures
                    salary_match = re.search(r'\$[\d,]+\s*[-–]\s*\$[\d,]+', p_text)
                    if salary_match and not res['salary']:
                        res['salary'] = salary_match.group(0)
            if comp_parts:
                res['compensation_details'] = "\n".join(comp_parts)

            # --- EEO Statement: look for "equal opportunity employer" text ---
            for p_tag in soup.find_all('p'):
                p_text = p_tag.get_text().strip()
                if 'equal opportunity employer' in p_text.lower():
                    res['eeo'] = p_text
                    break

            # --- Additional links: collect all href links from the job detail area ---
            all_links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.startswith('http') and 'microsoft.com' in href and href not in all_links:
                    all_links.append(href)
            res['additional_links'] = ", ".join(all_links)

            # --- Department: extract from page metadata (Profession / Discipline) ---
            page_text = soup.get_text()
            prof_match = re.search(r'Profession\s*[\n:]+\s*(.+?)(?:\n|$)', page_text)
            disc_match = re.search(r'Discipline\s*[\n:]+\s*(.+?)(?:\n|$)', page_text)
            if prof_match:
                res['job_department'] = prof_match.group(1).strip()
            elif disc_match:
                res['job_department'] = disc_match.group(1).strip()

            # --- Apply URL: extract from "Apply now" button/link ---
            apply_link = soup.find('a', attrs={'aria-label': re.compile(r'apply', re.IGNORECASE)})
            if not apply_link:
                apply_link = soup.find('a', string=re.compile(r'apply', re.IGNORECASE))
            if apply_link and apply_link.get('href'):
                href = apply_link['href']
                if href.startswith('/'):
                    res['apply_url'] = f"https://apply.careers.microsoft.com{href}"
                else:
                    res['apply_url'] = href

            # --- Posted Date: fallback from DOM if schema didn't provide it ---
            if not res.get('posted_date'):
                date_match = re.search(r'Date posted\s*[\n:]+\s*(.+?)(?:\n|$)', page_text)
                if date_match:
                    raw_date = date_match.group(1).strip()
                    try:
                        from datetime import datetime
                        parsed_date = datetime.strptime(raw_date, '%b %d, %Y')
                        res['posted_date'] = parsed_date.isoformat()
                    except (ValueError, ImportError):
                        res['posted_date'] = raw_date

            # --- About Company: extract dynamically, fall back to standard text ---
            if not res['about_company']:
                # Try to find mission statement from page text
                mission_match = re.search(
                    r"(Microsoft[''']?s mission is to empower[\s\S]*?(?:at work and beyond\.|to achieve more\.))",
                    page_text, re.IGNORECASE
                )
                if mission_match:
                    res['about_company'] = mission_match.group(1).strip()
                else:
                    # Standard text from Microsoft's careers page — used when the job page
                    # doesn't include the mission statement (varies by posting)
                    res['about_company'] = (
                        "Microsoft's mission is to empower every person and every organization "
                        "on the planet to achieve more. As employees we come together with a growth "
                        "mindset, innovate to empower others, and collaborate to realize our shared goals. "
                        "Each day we build on our values of respect, integrity, and accountability to "
                        "create a culture of inclusion where everyone can thrive at work and beyond."
                    )

            return res
        except Exception as e:
            print(f"Error scraping Microsoft job {url}: {e}")
            return None
