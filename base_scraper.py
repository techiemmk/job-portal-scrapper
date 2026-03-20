import asyncio
import os
import re
import html
import json
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
try:
    from job_models import RAGJobPosting, ScraperRunBatch
except ImportError:
    RAGJobPosting, ScraperRunBatch = None, None

class BaseJobScraper:
    def __init__(self, base_url, concurrency=5):
        self.base_url = base_url
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self.jobs = []

    async def scrape_single_job(self, context, url, max_retries=2, **kwargs):
        """Scrape a single job with retry logic, page lifecycle management.
        
        Subclasses should implement scrape_job_details(page, url, **kwargs).
        """
        async with self.semaphore:
            for attempt in range(max_retries + 1):
                page = None
                try:
                    page = await context.new_page()
                    result = await self.scrape_job_details(page, url, **kwargs)
                    await page.close()
                    return result
                except Exception as e:
                    if page:
                        try:
                            await page.close()
                        except:
                            pass
                    if attempt < max_retries:
                        wait = 3 * (attempt + 1)
                        print(f"    ↻ Retry {attempt+1}/{max_retries} for {url} (waiting {wait}s): {e}")
                        await asyncio.sleep(wait)
                    else:
                        raise

    async def scrape_jobs_in_batches(self, context, job_items, portal_name,
                                     batch_size=10, delay_between_batches=2,
                                     save_interval=50):
        """Process job URLs/IDs in staggered batches with progress tracking.
        
        Args:
            context: Playwright browser context
            job_items: List of (url, kwargs_dict) tuples, or just a list of URLs.
                       Each item will be passed to scrape_single_job.
            portal_name: Name for logging and intermediate saves (e.g., "microsoft")
            batch_size: Number of jobs per batch (default 10)
            delay_between_batches: Seconds to wait between batches (default 2)
            save_interval: Save progress every N successful jobs (default 50)
        
        Returns:
            List of successfully scraped job dicts.
        """
        # Normalize job_items to list of (url, kwargs) tuples
        normalized = []
        for item in job_items:
            if isinstance(item, tuple):
                normalized.append(item)
            else:
                normalized.append((item, {}))
        
        all_results = []
        total = len(normalized)
        
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = normalized[batch_start:batch_end]
            batch_num = (batch_start // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            print(f"  Batch {batch_num}/{total_batches}: scraping jobs {batch_start+1}-{batch_end} of {total}...")
            
            # Create tasks for this batch
            tasks = [
                self.scrape_single_job(context, url, **kwargs)
                for url, kwargs in batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Collect results, log failures
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    print(f"    ⚠ Job {batch_start+i+1} failed: {result}")
                elif result is not None:
                    all_results.append(result)
            
            # Intermediate save to avoid data loss
            if len(all_results) > 0 and len(all_results) % save_interval < batch_size:
                self.jobs = all_results
                self.save_to_formats(portal_name)
                print(f"    💾 Intermediate save: {len(all_results)} jobs saved so far.")
            
            # Stagger: delay between batches
            if batch_end < total:
                cooldown = delay_between_batches
                if batch_num % 100 == 0:
                    cooldown = 10
                    print(f"    ⏳ Extended cooldown ({cooldown}s) after {batch_num} batches...")
                await asyncio.sleep(cooldown)
        
        return all_results

    def clean_html_field(self, field_val):
        """Cleans HTML content and preserves formatting like bullet points."""
        if not field_val: return ""
        if isinstance(field_val, str) and field_val.strip().startswith('{'):
            try:
                field_val = json.loads(field_val)
            except: pass
        if isinstance(field_val, dict) and '__html' in field_val:
            field_val = field_val['__html']
        if not isinstance(field_val, str): return str(field_val)
        
        # Replace common tags with newlines or spaces to preserve lists
        # Add bullet AT THE FRONT of li, not the end
        content = field_val.replace('<li>', '• ').replace('</li>', '\n').replace('<ul>', '\n').replace('</ul>', '\n')
        content = content.replace('<br>', '\n').replace('<br/>', '\n').replace('</p>', '\n\n')
        
        # Remove remaining tags
        clean_text = re.sub('<[^<]+?>', '', content)
        
        # Decode all HTML entities (&#43; → +, &amp; → &, &quot; → ", etc.)
        clean_text = html.unescape(clean_text)
        
        # De-duplicate identical lines (fixes platforms like Eightfold which embed plaintext + HTML of the same description)
        seen = set()
        deduped_lines = []
        for line in clean_text.split('\n'):
            stripped = line.strip()
            if stripped and len(stripped) > 15:
                # Remove leading bullets for identity check so '• text' and 'text' match
                identity = re.sub(r'^[*•-]\s*', '', stripped).lower()
                if identity in seen:
                    continue
                seen.add(identity)
            deduped_lines.append(stripped)
            
        return "\n".join(deduped_lines).strip()

    def extract_links_from_field(self, field_val):
        """Extracts all hyperlinks from an HTML string."""
        if not field_val: return []
        if isinstance(field_val, str) and field_val.strip().startswith('{'):
            try:
                field_val = json.loads(field_val)
            except: pass
        if isinstance(field_val, dict) and '__html' in field_val:
            field_val = field_val['__html']
        if not isinstance(field_val, str): return []
        
        soup = BeautifulSoup(field_val, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/'):
                href = self.base_url + href
            if href not in links:
                links.append(href)
        return links

    def extract_schema_job_data(self, html_content, url):
        """Extract data from application/ld+json with type JobPosting"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            scripts = soup.find_all('script', type='application/ld+json')
            
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    # Handle both single object and list of objects
                    if isinstance(data, list):
                        items = data
                    else:
                        items = [data]
                    
                    for item in items:
                        if item.get('@type') == 'JobPosting' or 'JobPosting' in str(item.get('@type')):
                            return self.map_schema_to_job(item, url)
                except:
                    continue
        except Exception as e:
            print(f"Error extracting schema: {e}")
        return None

    def map_schema_to_job(self, schema, url):
        """Map Schema.org JobPosting fields to our internal format"""
        # Location handling
        location = schema.get('jobLocation', '')
        
        def _parse_addr(addr):
            if not isinstance(addr, dict):
                return str(addr)
            locality = addr.get('addressLocality', '')
            region = addr.get('addressRegion', '')
            country = addr.get('addressCountry', '')
            if isinstance(country, dict):
                country = country.get('name', str(country))
            parts = [p for p in [locality, region, country] if p]
            return ", ".join(parts)

        if isinstance(location, list):
            locs = []
            for l in location:
                if isinstance(l, dict):
                    locs.append(_parse_addr(l.get('address', l)))
                else:
                    locs.append(str(l))
            location = "; ".join(locs)
        elif isinstance(location, dict):
            location = _parse_addr(location.get('address', location))

        # Description cleaning
        desc = schema.get('description', '')
        
        # Salary handling
        salary_info = ""
        base_salary = schema.get('baseSalary')
        if base_salary:
            if isinstance(base_salary, dict):
                value = base_salary.get('value', {})
                if isinstance(value, dict):
                    salary_info = f"{value.get('minValue', '')} - {value.get('maxValue', '')} {base_salary.get('currency', '')}"
                else:
                    salary_info = str(value)
            else:
                salary_info = str(base_salary)

        return {
            "job_link": url,
            "job_name": html.unescape(schema.get('title', '')),
            "job_location": location,
            "job_department": html.unescape(schema.get('industry', '')),
            "job_description": self.clean_html_field(desc),
            "job_responsibilities": self.clean_html_field(schema.get('responsibilities', '')),
            "minimum_qualifications": self.clean_html_field(schema.get('experienceRequirements', '')),
            "preferred_qualifications": self.clean_html_field(schema.get('educationRequirements', '')),
            "about_company": schema.get('hiringOrganization', {}).get('name', '') if isinstance(schema.get('hiringOrganization'), dict) else "",
            "salary": salary_info,
            "compensation_details": "",
            "eeo": "",
            "additional_links": ""
        }


    def detect_work_mode(self, text):
        """Heuristic to detect work mode (Remote/Hybrid/Onsite) from text."""
        if not text: return "onsite"
        text = text.lower()
        if "remote" in text or "work from home" in text or "wfh" in text:
            if "hybrid" in text: return "hybrid"
            return "remote"
        if "hybrid" in text:
            return "hybrid"
        return "onsite"

    def detect_travel(self, text):
        """Heuristic to detect travel requirements from text."""
        if not text: return "No travel"
        # Look for percentages
        travel_match = re.search(r'(\d+%\s*(travel|traveling))', text, re.I)
        if travel_match:
            return travel_match.group(1)
        if "no travel" in text.lower():
            return "No travel"
        if "travel required" in text.lower() or "willingness to travel" in text.lower():
            return "Travel required"
        return "Not specified"

    def detect_languages(self, text):
        """Heuristic to detect language requirements from text."""
        if not text: return ["English"]
        languages = ["English"]
        common_languages = ["Spanish", "French", "German", "Chinese", "Mandarin", "Japanese", "Korean", "Hindi", "Arabic", "Portuguese", "Italian", "Russian"]
        for lang in common_languages:
            if re.search(rf'\b{lang}\b', text, re.I):
                if lang not in languages:
                    languages.append(lang)
        return languages

    def translate_to_rag_schema(self, job):
        """Translate internal job dict to a granular, RAG-friendly schema."""
        full_text = f"{job.get('job_description', '')} {job.get('job_responsibilities', '')} {job.get('minimum_qualifications', '')} {job.get('preferred_qualifications', '')}"
        
        # Location handling: split by comma if it's a string, or use as is if it's already a list
        locations_raw = job.get("job_location", "")
        if isinstance(locations_raw, str):
            locations = [loc.strip() for loc in locations_raw.split(",") if loc.strip()]
        elif isinstance(locations_raw, list):
            locations = locations_raw
        else:
            locations = []

        # Additional links handling: convert comma-separated string to list
        links_raw = job.get("additional_links", "")
        if isinstance(links_raw, str):
            links = [link.strip() for link in links_raw.split(",") if link.strip()]
        else:
            links = []

        data_dict = {
            "metadata": {
                "job_id": str(job.get("job_id") or job.get("job_link", "")).split("/")[-1].split("?")[0],
                "job_title": job.get("job_name", ""),
                "organization_name": job.get("about_company", "N/A"),
                "job_department": job.get("job_department", ""),
                "job_link": job.get("job_link", ""),
                "posted_date": datetime.now().strftime("%Y-%m-%d")
            },
            "logistics": {
                "job_locations": locations,
                "work_mode": self.detect_work_mode(full_text),
                "travel_requirement": self.detect_travel(full_text),
                "job_type": "Full-time"
            },
            "role_details": {
                "job_description": job.get("job_description", ""),
                "job_responsibilities": job.get("job_responsibilities", ""),
                "minimum_qualifications": job.get("minimum_qualifications", ""),
                "preferred_qualifications": job.get("preferred_qualifications", ""),
                "language_requirements": self.detect_languages(full_text),
                "job_details_metadata": ""
            },
            "compensation": {
                "salary_range": job.get("salary", ""),
                "compensation_details": job.get("compensation_details", ""),
                "benefits_and_perks": ""
            },
            "legal_and_company": {
                "about_company": job.get("about_company", ""),
                "equal_employment_opportunity": job.get("eeo", ""),
                "additional_links": links
            }
        }
        
        if RAGJobPosting:
            try:
                validated = RAGJobPosting(**data_dict)
                return validated.model_dump()
            except Exception as e:
                print(f"Validation error for job {data_dict['metadata']['job_id']}: {e}")
                return data_dict
        return data_dict

    def save_to_rag_json(self, portal_name, company_name, website_name, start_time, status="completed"):
        """Saves scraped jobs to a granular, RAG-friendly JSON format."""
        if not self.jobs:
            return

        rag_jobs = [self.translate_to_rag_schema(job) for job in self.jobs]
        
        output_dict = {
            "startTime": start_time.isoformat() if hasattr(start_time, 'isoformat') else str(start_time),
            "endTime": datetime.now().isoformat(),
            "status": status,
            "companyName": company_name,
            "websiteName": website_name,
            "data": rag_jobs
        }

        if ScraperRunBatch:
            try:
                validated_batch = ScraperRunBatch(**output_dict)
                output_data = validated_batch.model_dump()
            except Exception as e:
                print(f"Batch validation error: {e}")
                output_data = output_dict
        else:
            output_data = output_dict

        os.makedirs("data", exist_ok=True)
        timestamp = datetime.now().strftime("%H%M_%d-%b-%Y")
        filename = f"data/{portal_name}_rag_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
            
        print(f"RAG JSON results saved to {filename}", flush=True)

    def save_to_formats(self, portal_name):
        """Saves scraped jobs to CSV, XLSX, and ODS formats."""
        if not self.jobs:
            print(f"No jobs found for {portal_name}.")
            return
        
        df = pd.DataFrame(self.jobs)
        
        # Standardize columns (can be overridden by subclasses)
        cols = ["job_name", "job_location", "job_department", "job_description", 
                "job_responsibilities", "minimum_qualifications", "preferred_qualifications",
                "about_company", "salary", "compensation_details", "eeo", "additional_links", "job_link"]
        
        # Ensure all columns exist
        for col in cols:
            if col not in df.columns:
                df[col] = ""
        
        # Reorder or select columns
        df = df[cols]
        
        # Create data directory if it doesn't exist
        os.makedirs("data", exist_ok=True)
        
        # Generate timestamped filename
        timestamp = datetime.now().strftime("%H%M_%d-%b-%Y")
        base_filename = f"data/{portal_name}_jobs_{timestamp}"
        
        # Save formats
        df.to_excel(f"{base_filename}.xlsx", index=False)
        df.to_excel(f"{base_filename}.ods", index=False, engine='odf')
        df.to_csv(f"{base_filename}.csv", index=False)
        
        print(f"Results saved to {base_filename}.[xlsx, ods, csv]", flush=True)

    def save_to_db(self, portal_name, company_name=None):
        """Saves scraped jobs to PostgreSQL database using incremental sync."""
        try:
            from db import sync_jobs
            summary = sync_jobs(portal_name, company_name or portal_name.capitalize(), self.jobs)
            return summary
        except ImportError:
            print("Error: psycopg2 is not installed. Run: pip install psycopg2-binary")
            return None
        except Exception as e:
            print(f"Error saving to database: {e}")
            return None

    async def run(self, max_pages=None, start_time=None):
        """Abstract run method to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement the run method")
