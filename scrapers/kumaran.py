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

            job_data = await page.evaluate("""() => {
                const data = {};
                const pageText = document.body.innerText;

                // Job Title - extract from div.cw-jobheader-info h1
                let jobTitle = '';
                const headerDiv = document.querySelector('div.cw-jobheader-info h1');
                if (headerDiv) {
                    jobTitle = headerDiv.innerText.trim();
                }

                // Fallback: look for h1 that's not a section heading
                if (!jobTitle) {
                    const allH1s = document.querySelectorAll('h1');
                    for (let h1 of allH1s) {
                        const text = h1.innerText.trim();
                        // Skip section headings
                        if (!text.includes('Key Responsibilities') &&
                            !text.includes('About Us') &&
                            !text.includes('Responsibilities')) {
                            jobTitle = text;
                            break;
                        }
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

                // Posted Date - extract from "Posted on MM/DD/YYYY" (American format)
                const dateMatch = pageText.match(/Posted on (\\d{2})\\/(\\d{2})\\/(\\d{4})/);
                if (dateMatch) {
                    const month = dateMatch[1];  // MM
                    const day = dateMatch[2];    // DD
                    const year = dateMatch[3];   // YYYY
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

            # Extract main content sections using DOM traversal (handles both headings and bold/strong tags)
            content_data = await page.evaluate("""() => {
                const data = {};

                // Helper: extract content after a section marker (heading or bold tag)
                function getContentAfterSection(sectionText, maxLength = 2000) {
                    // Try to find as heading first
                    let marker = Array.from(document.querySelectorAll('h2, h3, h4'))
                        .find(h => h.innerText.includes(sectionText));

                    // If not found as heading, try bold/strong tags
                    if (!marker) {
                        marker = Array.from(document.querySelectorAll('strong, b'))
                            .find(el => el.innerText.trim() === sectionText);
                    }

                    if (!marker) return '';

                    let content = '';
                    let sibling = marker.nextElementSibling;
                    let elementCount = 0;
                    const maxElements = 20;

                    while (sibling && elementCount < maxElements) {
                        const text = sibling.innerText ? sibling.innerText.trim() : '';

                        // Stop if we hit another section marker (bold/strong with text or heading)
                        if (sibling.tagName.match(/H[1-6]/) ||
                            (sibling.tagName === 'STRONG' || sibling.tagName === 'B') && text.length < 50) {
                            break;
                        }

                        if (text) {
                            // For lists, add bullet points
                            if (sibling.tagName === 'UL' || sibling.tagName === 'OL') {
                                Array.from(sibling.querySelectorAll('li')).forEach(li => {
                                    content += '• ' + li.innerText.trim() + '\\n';
                                });
                            } else if (sibling.tagName !== 'STRONG' && sibling.tagName !== 'B') {
                                content += text + '\\n';
                            }
                        }

                        sibling = sibling.nextElementSibling;
                        elementCount++;
                    }

                    return content.substring(0, maxLength).trim();
                }

                // Extract each section
                data.job_description = getContentAfterSection('Job Description', 600);
                data.requirements = getContentAfterSection('Requirements', 2000);
                data.responsibilities = getContentAfterSection('Responsibilities', 2000);
                data.must_have_skills = getContentAfterSection('Must-Have Skills', 1500);
                data.soft_skills = getContentAfterSection('Soft Skills', 1500);
                data.hard_skills = getContentAfterSection('Hard Skills', 1500);
                data.eeo = getContentAfterSection('Equal Opportunity', 600);
                data.about_company_desc = getContentAfterSection('About Us', 1000);

                return data;
            }""")

            # Merge all extracted data
            job_data.update(sidebar_data)
            job_data.update(content_data)
            job_data['job_link'] = url
            job_data['job_id'] = job_id

            # Fallback: Extract job title from URL slug if not found on page
            if not job_data.get('job_name') or job_data['job_name'] == '':
                try:
                    # URL format: /jobs/Careers/{JOB_ID}/{JOB_SLUG}?source=CareerSite
                    url_parts = url.split('/jobs/Careers/')
                    if len(url_parts) > 1:
                        slug_part = url_parts[1].split('?')[0]  # Remove query params
                        slug_parts = slug_part.split('/')
                        if len(slug_parts) > 1:
                            job_slug = slug_parts[1]  # Get the slug part
                            # Convert from kebab-case to Title Case
                            job_title = ' '.join(word.capitalize() for word in job_slug.split('-'))
                            job_data['job_name'] = job_title
                except:
                    pass

            # Clean HTML fields
            for field in ['job_description', 'job_department', 'requirements', 'responsibilities', 'eeo',
                         'must_have_skills', 'soft_skills', 'hard_skills']:
                if field in job_data:
                    job_data[field] = self.clean_html_field(job_data[field])

            # FIX 1: Map responsibilities field to correct database column name
            # Extract and clean responsibilities
            resp_text = job_data.get('responsibilities', '')
            if not resp_text:
                # Fallback: If no responsibilities section found, try to extract from requirements if available
                if job_data.get('requirements'):
                    # Use first part of requirements as fallback
                    resp_text = job_data['requirements'][:500]

            job_data['job_responsibilities'] = resp_text

            # FIX 2: Properly consolidate requirements (Requirements + Must-Have + Hard Skills)
            req_parts = []
            if job_data.get('requirements'):
                req_parts.append(f"Requirements:\n{job_data['requirements']}")
            if job_data.get('must_have_skills'):
                req_parts.append(f"\nMust-Have Skills:\n{job_data['must_have_skills']}")
            if job_data.get('hard_skills'):
                req_parts.append(f"\nHard Skills:\n{job_data['hard_skills']}")

            job_data['requirements'] = "\n".join(req_parts) if req_parts else ""

            # FIX 3: Better consolidation of qualifications
            # min_qualifications = Experience + Hard Requirements
            min_qual_parts = []
            if job_data.get('experience'):
                min_qual_parts.append(f"Experience: {job_data['experience']}")
            if job_data.get('requirements') and not job_data.get('must_have_skills'):
                # Only add if we don't have structured requirements
                min_qual_parts.append(f"\nRequirements:\n{job_data['requirements']}")

            job_data['minimum_qualifications'] = "\n".join(min_qual_parts) if min_qual_parts else ""

            # preferred_qualifications = Soft Skills + Hard Skills
            pref_qual_parts = []
            if job_data.get('soft_skills'):
                pref_qual_parts.append(f"Soft Skills:\n{job_data['soft_skills']}")
            if job_data.get('hard_skills'):
                pref_qual_parts.append(f"\nHard Skills:\n{job_data['hard_skills']}")

            job_data['preferred_qualifications'] = "\n".join(pref_qual_parts) if pref_qual_parts else ""

            # Handle optional fields
            job_data['compensation_details'] = ""
            job_data['additional_links'] = ""
            job_data['apply_url'] = url

            return job_data

        except Exception as e:
            print(f"Error scraping job details from {url}: {e}")
            return None
