import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
from base_scraper import BaseJobScraper


class KumaranScraper(BaseJobScraper):
    def __init__(self, concurrency=5):
        super().__init__(base_url="https://careers.kumaran.com", concurrency=concurrency)
        self.listing_url = f"{self.base_url}/jobs/Careers"

    async def run(self, max_pages=None, start_time=None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )

            # Step 1: Collect all job links from listing page
            job_links = await self.get_all_job_links(context)
            print(f"Total Kumaran jobs to scrape: {len(job_links)}")

            # Step 2: Scrape job details in batches
            self.jobs = await self.scrape_jobs_in_batches(
                context,
                job_links,
                portal_name="kumaran",
                batch_size=10,
                delay_between_batches=2,
                save_interval=50
            )

            # Final Save
            self.save_to_formats("kumaran")
            if start_time:
                self.save_to_rag_json("kumaran", "Kumaran Systems Pvt Ltd", "careers.kumaran.com", start_time)

            await browser.close()
            print(f"Kumaran scraping complete. Found {len(self.jobs)} jobs.")

    async def get_all_job_links(self, context):
        """Extract all job links from the listing page."""
        page = await context.new_page()
        try:
            print(f"Opening Kumaran listing page: {self.listing_url}")
            await page.goto(self.listing_url)
            await page.wait_for_timeout(5000)

            # Scroll to load all job listings
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)

            # Extract all job links - try multiple selectors
            job_links = await page.evaluate("""() => {
                const links = [];

                // Strategy 1: Look for all links with /jobs/Careers/ in href
                const allLinks = Array.from(document.querySelectorAll('a[href*="/jobs/Careers/"]'))
                    .map(a => a.href)
                    .filter(href => href.includes('/jobs/Careers/') && href.match(/\\/jobs\\/Careers\\/\\d+\\//))
                    .filter((href, index, self) => self.indexOf(href) === index);

                // Strategy 2: Look for job cards/containers and extract links
                const jobCards = document.querySelectorAll('[class*="job"], [data-job*=""], article, .cw-job-card');
                jobCards.forEach(card => {
                    const link = card.querySelector('a[href*="/jobs/Careers/"]');
                    if (link && link.href) {
                        links.push(link.href);
                    }
                });

                // Combine and deduplicate
                const combined = [...new Set([...allLinks, ...links])];
                return combined.filter(href => href.match(/\\/jobs\\/Careers\\/\\d+\\//));
            }""")

            print(f"Extracted {len(job_links)} job links from listing page")
            if len(job_links) > 0:
                print(f"Sample URLs: {job_links[:3]}")
            return job_links

        except Exception as e:
            print(f"Error extracting job links: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            await page.close()

    async def scrape_job_details(self, page, url, **kwargs):
        """Scrape job details from individual job page."""
        try:
            await page.goto(url)
            await page.wait_for_timeout(3000)

            # Extract job ID from URL
            job_id = url.split("/jobs/Careers/")[1].split("/")[0] if "/jobs/Careers/" in url else ""

            # Extract header information using better selectors
            job_data = await page.evaluate("""() => {
                const data = {};
                const pageText = document.body.innerText;

                // Job Title - look for the large heading (usually appears early)
                let jobTitle = '';
                const headings = document.querySelectorAll('h1, h2, h3');
                for (let h of headings) {
                    const text = h.innerText.trim();
                    // Avoid short headings like "About Us", look for title-like headings
                    if (text.length > 15 && text.length < 200 && !text.includes('\\n')) {
                        jobTitle = text;
                        break;
                    }
                }
                data.job_name = jobTitle;

                // Company (static)
                data.about_company = 'Kumaran Systems Pvt Ltd';

                // Job Type - look for "Full time" or "Contract" in the page
                data.job_type = 'Full time';
                if (pageText.includes('Contract')) {
                    const contractMatch = pageText.match(/Contract\\s*\\((\\d+)\\)/);
                    if (contractMatch) data.job_type = 'Contract';
                }

                // Posted Date - extract from "Posted on DD/MM/YYYY"
                const dateMatch = pageText.match(/Posted on (\\d{2}\\/(\\d{2})\\/(\\d{4}))/);
                if (dateMatch) {
                    const [_, dateStr, month, year] = dateMatch;
                    const [day, , ] = dateStr.split('/');
                    data.posted_date = `${year}-${month}-${day}`;
                } else {
                    data.posted_date = new Date().toISOString().split('T')[0];
                }

                return data;
            }""")

            # Extract sidebar metadata using text parsing
            sidebar_data = await page.evaluate("""() => {
                const data = {};
                const pageText = document.body.innerText;

                // Department Name - extract from text
                const deptMatch = pageText.match(/Department Name\\s*([^\\n]+)/);
                data.job_department = deptMatch ? deptMatch[1].trim() : '';

                // Work Experience (e.g., "4-5 years")
                const expMatch = pageText.match(/Work Experience\\s*([^\\n]+)/);
                let experience = '';
                if (expMatch) {
                    experience = expMatch[1].trim();
                    if (experience.toLowerCase() === 'work experience') {
                        experience = '';
                    }
                }
                data.experience = experience;

                // Location fields using regex extraction
                let city = '', state = '', country = '', postal = '';

                // City
                const cityMatch = pageText.match(/\\bCity\\s*([^\\n]+)/);
                if (cityMatch) city = cityMatch[1].trim();

                // State/Province
                const stateMatch = pageText.match(/State\\/Province\\s*([^\\n]+)/);
                if (stateMatch) state = stateMatch[1].trim();

                // Country
                const countryMatch = pageText.match(/\\bCountry\\s*([^\\n]+)/);
                if (countryMatch) {
                    country = countryMatch[1].trim();
                    if (country.toLowerCase() === 'country') country = '';
                }

                // Postal Code
                const postalMatch = pageText.match(/Zip\\/Postal Code\\s*([^\\n]+)/);
                if (postalMatch) postal = postalMatch[1].trim();

                // Build location string
                const parts = [city, state, country].filter(p => p && p.length > 0);
                data.job_location = parts.join(', ');

                return data;
            }""")

            # Extract main content sections using improved text parsing
            content_data = await page.evaluate("""() => {
                const data = {};
                const bodyText = document.body.innerText;

                // Helper function to extract section between two markers
                function extractBetween(startMarker, endMarker) {
                    const startIdx = bodyText.indexOf(startMarker);
                    if (startIdx === -1) return '';

                    let endIdx;
                    if (endMarker) {
                        endIdx = bodyText.indexOf(endMarker, startIdx + startMarker.length);
                        if (endIdx === -1) {
                            endIdx = bodyText.length;
                        }
                    } else {
                        endIdx = bodyText.length;
                    }

                    return bodyText.substring(startIdx + startMarker.length, endIdx).trim();
                }

                // Job Description - look for the first paragraph after "Job Description" and before "Requirements"
                const descStart = bodyText.indexOf('Job Description');
                const reqStart = bodyText.indexOf('Requirements');
                let description = '';
                if (descStart !== -1 && reqStart !== -1) {
                    description = bodyText.substring(descStart + 'Job Description'.length, reqStart).trim();
                    // Remove just the first line if it's a title repeat
                    const lines = description.split('\\n');
                    if (lines[0].length < 100) {
                        description = lines.slice(1).join('\\n').trim();
                    }
                }
                data.job_description = description.substring(0, 500); // Limit to first 500 chars

                // Requirements section (just the bullet points)
                let requirements = extractBetween('Requirements:', 'Responsibilities:');
                data.requirements = requirements.substring(0, 1000);

                // Responsibilities section
                let responsibilities = extractBetween('Responsibilities:', 'Must-Have Skills');
                data.responsibilities = responsibilities.substring(0, 1000);

                // Must-Have Skills
                let mustHaveSkills = extractBetween('Must-Have Skills:', 'Soft Skills');
                data.must_have_skills = mustHaveSkills.substring(0, 800);

                // Hard Skills
                let hardSkills = extractBetween('Hard Skills:', 'Equal Opportunity');
                if (!hardSkills) {
                    hardSkills = extractBetween('Hard Skills:', 'I\\'m interested');
                }
                data.hard_skills = hardSkills.substring(0, 800);

                // Soft Skills
                let softSkills = extractBetween('Soft Skills:', 'Hard Skills');
                if (!softSkills) {
                    softSkills = extractBetween('Soft Skills:', 'Equal Opportunity');
                }
                data.soft_skills = softSkills.substring(0, 800);

                // EEO Statement
                const eeoMatch = bodyText.match(/Equal Opportunity[^]*?(?=I\\'m interested|View all jobs|$)/);
                let eeo = eeoMatch ? eeoMatch[0].trim() : '';
                data.eeo = eeo.substring(0, 500);

                // About Company (from About Us section)
                let aboutCompany = extractBetween('About Us', 'Why Kumaran');
                data.about_company_desc = aboutCompany.substring(0, 800);

                return data;
            }""")

            # Merge all extracted data
            job_data.update(sidebar_data)
            job_data.update(content_data)
            job_data['job_link'] = url
            job_data['job_id'] = job_id

            # Clean HTML fields
            for field in ['job_description', 'job_department', 'requirements', 'responsibilities', 'eeo']:
                if field in job_data:
                    job_data[field] = self.clean_html_field(job_data[field])

            # Consolidate requirements: combine "Requirements" + "Must-Have Skills" + "Hard Skills"
            req_parts = []
            if job_data.get('requirements'):
                req_parts.append(f"Requirements:\n{job_data['requirements']}")
            if job_data.get('must_have_skills'):
                req_parts.append(f"\nMust-Have Skills:\n{job_data['must_have_skills']}")
            if job_data.get('hard_skills'):
                req_parts.append(f"\nHard Skills:\n{job_data['hard_skills']}")

            job_data['requirements'] = "\n".join(req_parts) if req_parts else ""

            # Consolidate min_qualifications: combine "Experience" + "Soft Skills"
            qual_parts = []
            if job_data.get('experience'):
                qual_parts.append(f"Experience: {job_data['experience']}")
            if job_data.get('soft_skills'):
                qual_parts.append(f"Soft Skills:\n{job_data['soft_skills']}")

            job_data['minimum_qualifications'] = "\n".join(qual_parts) if qual_parts else ""
            job_data['preferred_qualifications'] = ""

            # Handle optional fields
            job_data['compensation_details'] = ""
            job_data['additional_links'] = ""
            job_data['apply_url'] = url

            return job_data

        except Exception as e:
            print(f"Error scraping job details from {url}: {e}")
            return None
