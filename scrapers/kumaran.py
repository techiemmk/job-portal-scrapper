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

            # Extract all job links
            job_links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href*="/jobs/Careers/"]'))
                    .map(a => a.href)
                    .filter(href => href.includes('/jobs/Careers/') && !href.includes('?'))
                    .filter((href, index, self) => self.indexOf(href) === index);  // Remove duplicates
            }""")

            print(f"Extracted {len(job_links)} job links from listing page")
            return job_links

        except Exception as e:
            print(f"Error extracting job links: {e}")
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

            # Extract header information
            job_data = await page.evaluate("""() => {
                const data = {};

                // Job Title (from h1 or main heading)
                const titleEl = document.querySelector('h1, .cw-job-title, [data-test="job-title"]');
                data.job_name = titleEl ? titleEl.innerText.trim() : '';

                // Company (static)
                data.about_company = 'Kumaran Systems Pvt Ltd';

                // Job Type (from header - "Full time" or "Contract")
                const headerText = document.body.innerText;
                data.job_type = 'Full time';
                if (headerText.includes('Contract')) {
                    data.job_type = 'Contract';
                }

                // Posted Date (format: "Posted on DD/MM/YYYY")
                const dateMatch = headerText.match(/Posted on (\\d{2}\\/\\d{2}\\/\\d{4})/);
                if (dateMatch) {
                    const [day, month, year] = dateMatch[1].split('/');
                    data.posted_date = `${year}-${month}-${day}`;
                } else {
                    data.posted_date = new Date().toISOString().split('T')[0];
                }

                return data;
            }""")

            # Extract sidebar metadata
            sidebar_data = await page.evaluate("""() => {
                const data = {};

                // Department Name
                const deptEl = Array.from(document.querySelectorAll('*')).find(el =>
                    el.innerText.includes('Department Name')
                );
                if (deptEl) {
                    data.job_department = deptEl.nextElementSibling?.innerText ||
                                         deptEl.parentElement?.innerText.split('Department Name')[1].trim() || '';
                }

                // Work Experience (e.g., "4-5 years")
                const expEl = Array.from(document.querySelectorAll('*')).find(el =>
                    el.innerText.includes('Work Experience')
                );
                let experience = '';
                if (expEl) {
                    experience = expEl.nextElementSibling?.innerText ||
                                expEl.parentElement?.innerText.split('Work Experience')[1].split('\\n')[0].trim() || '';
                }
                data.experience = experience;

                // Location fields (City, State, Country, Postal Code)
                let city = '', state = '', country = '', postal = '';

                const cityEl = Array.from(document.querySelectorAll('*')).find(el =>
                    el.innerText.includes('City') && !el.innerText.includes('State')
                );
                if (cityEl) {
                    city = cityEl.nextElementSibling?.innerText ||
                          cityEl.parentElement?.innerText.split('City')[1].split('\\n')[0].trim() || '';
                }

                const stateEl = Array.from(document.querySelectorAll('*')).find(el =>
                    el.innerText.includes('State/Province')
                );
                if (stateEl) {
                    state = stateEl.nextElementSibling?.innerText ||
                           stateEl.parentElement?.innerText.split('State/Province')[1].split('\\n')[0].trim() || '';
                }

                const countryEl = Array.from(document.querySelectorAll('*')).find(el =>
                    el.innerText.includes('Country') && !el.innerText.includes('State')
                );
                if (countryEl) {
                    country = countryEl.nextElementSibling?.innerText ||
                             countryEl.parentElement?.innerText.split('Country')[1].split('\\n')[0].trim() || '';
                }

                const postalEl = Array.from(document.querySelectorAll('*')).find(el =>
                    el.innerText.includes('Zip/Postal Code')
                );
                if (postalEl) {
                    postal = postalEl.nextElementSibling?.innerText ||
                            postalEl.parentElement?.innerText.split('Zip/Postal Code')[1].split('\\n')[0].trim() || '';
                }

                // Build location string
                const parts = [city, state, country].filter(p => p);
                data.job_location = parts.join(', ');

                return data;
            }""")

            # Extract main content sections
            content_data = await page.evaluate("""() => {
                const data = {};
                const bodyText = document.body.innerText;

                // Helper function to extract section content
                function extractSection(sectionTitle) {
                    const startIndex = bodyText.indexOf(sectionTitle);
                    if (startIndex === -1) return '';

                    const nextSectionIndex = bodyText.indexOf('\\n\\n', startIndex + sectionTitle.length);
                    if (nextSectionIndex === -1) {
                        return bodyText.substring(startIndex + sectionTitle.length).trim();
                    }
                    return bodyText.substring(startIndex + sectionTitle.length, nextSectionIndex).trim();
                }

                // Job Description
                data.job_description = extractSection('Job Description');
                if (data.job_description.startsWith('\\n')) {
                    data.job_description = data.job_description.substring(1).trim();
                }

                // Requirements section
                const requirementsStart = bodyText.indexOf('Requirements');
                let requirements = '';
                if (requirementsStart !== -1) {
                    const responsibilitiesStart = bodyText.indexOf('Responsibilities');
                    if (responsibilitiesStart !== -1) {
                        requirements = bodyText.substring(requirementsStart, responsibilitiesStart).trim();
                    } else {
                        requirements = bodyText.substring(requirementsStart).substring(0, 1000).trim();
                    }
                }
                data.requirements = requirements;

                // Responsibilities section
                const respStart = bodyText.indexOf('Responsibilities');
                let responsibilities = '';
                if (respStart !== -1) {
                    const skillsStart = bodyText.indexOf('Must-Have Skills');
                    if (skillsStart !== -1) {
                        responsibilities = bodyText.substring(respStart, skillsStart).trim();
                    } else {
                        responsibilities = bodyText.substring(respStart).substring(0, 1000).trim();
                    }
                }
                data.responsibilities = responsibilities;

                // Must-Have Skills
                const mustHaveStart = bodyText.indexOf('Must-Have Skills');
                let mustHaveSkills = '';
                if (mustHaveStart !== -1) {
                    const softSkillsStart = bodyText.indexOf('Soft Skills');
                    if (softSkillsStart !== -1) {
                        mustHaveSkills = bodyText.substring(mustHaveStart, softSkillsStart).trim();
                    } else {
                        mustHaveSkills = bodyText.substring(mustHaveStart).substring(0, 1500).trim();
                    }
                }
                data.must_have_skills = mustHaveSkills;

                // Hard Skills
                const hardSkillsStart = bodyText.indexOf('Hard Skills');
                let hardSkills = '';
                if (hardSkillsStart !== -1) {
                    const softSkillsStart = bodyText.indexOf('Soft Skills');
                    if (softSkillsStart !== -1) {
                        hardSkills = bodyText.substring(hardSkillsStart, softSkillsStart).trim();
                    } else {
                        hardSkills = bodyText.substring(hardSkillsStart).substring(0, 1000).trim();
                    }
                }
                data.hard_skills = hardSkills;

                // Soft Skills
                const softSkillsStart = bodyText.indexOf('Soft Skills');
                let softSkills = '';
                if (softSkillsStart !== -1) {
                    const eeoStart = bodyText.indexOf('Equal Opportunity');
                    if (eeoStart !== -1) {
                        softSkills = bodyText.substring(softSkillsStart, eeoStart).trim();
                    } else {
                        softSkills = bodyText.substring(softSkillsStart).substring(0, 1500).trim();
                    }
                }
                data.soft_skills = softSkills;

                // EEO Statement
                const eeoStart = bodyText.indexOf('Equal Opportunity');
                let eeo = '';
                if (eeoStart !== -1) {
                    eeo = bodyText.substring(eeoStart, eeoStart + 500).trim();
                }
                data.eeo = eeo;

                // About Company (from About Us section)
                const aboutStart = bodyText.indexOf('About Us');
                let aboutCompany = '';
                if (aboutStart !== -1) {
                    const whyStart = bodyText.indexOf('Why Kumaran');
                    if (whyStart !== -1) {
                        aboutCompany = bodyText.substring(aboutStart + 8, whyStart).trim();
                    }
                }
                data.about_company_desc = aboutCompany;

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
