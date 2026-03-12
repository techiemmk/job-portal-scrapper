"""
Tests for db.py — incremental job storage with snake_case schema.

Requires a PostgreSQL instance running with a test database.
Run: DB_NAME=job_scraper_test DB_USER=$(whoami) DB_PASSWORD="" python -m pytest test_db.py -v
"""
import os
import pytest

os.environ.setdefault("DB_NAME", "job_scraper_test")

from db import (
    get_connection, init_db, compute_content_hash, sync_jobs,
    extract_source_job_id, parse_salary, extract_keywords,
)


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Create tables before each test and clean up after."""
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM closed_jobs")
    cur.execute("DELETE FROM jobs")
    conn.commit()
    cur.close()
    conn.close()
    yield
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM closed_jobs")
    cur.execute("DELETE FROM jobs")
    conn.commit()
    cur.close()
    conn.close()


def make_job(name="Software Engineer", location="NYC", link="https://www.metacareers.com/profile/job_details/123456"):
    return {
        "job_name": name,
        "job_location": location,
        "job_department": "Engineering",
        "job_description": "Build amazing products",
        "job_responsibilities": "Write clean code",
        "minimum_qualifications": "3+ years of experience",
        "preferred_qualifications": "5+ years of experience",
        "about_company": "Great tech company",
        "salary": "$130,000 to $175,000 + bonus + equity + benefits",
        "compensation_details": "Comprehensive package",
        "eeo": "Equal opportunity employer",
        "additional_links": "https://example.com, https://example.org",
        "job_link": link,
    }


# --- Source Job ID Extraction ---

class TestExtractSourceJobId:
    def test_meta(self):
        assert extract_source_job_id("meta", "https://www.metacareers.com/profile/job_details/123456") == "123456"

    def test_google(self):
        assert extract_source_job_id("google", "https://google.com/about/careers/applications/jobs/results/789-software-engineer") == "789-software-engineer"

    def test_amazon(self):
        assert extract_source_job_id("amazon", "https://www.amazon.jobs/en/jobs/2839189/software-dev") == "2839189"

    def test_apple(self):
        assert extract_source_job_id("apple", "https://jobs.apple.com/en-us/details/200590322/ios-engineer") == "200590322"

    def test_nvidia(self):
        assert extract_source_job_id("nvidia", "https://nvidia.eightfold.ai/careers/job/12345") == "12345"

    def test_openai(self):
        assert extract_source_job_id("openai", "https://jobs.ashbyhq.com/openai/abc-def-123") == "abc-def-123"

    def test_microsoft(self):
        assert extract_source_job_id("microsoft", "https://apply.careers.microsoft.com/careers/job/67890?lang=en") == "67890"

    def test_netflix(self):
        assert extract_source_job_id("netflix", "https://explore.jobs.netflix.net/careers/job/99999") == "99999"

    def test_generic_fallback(self):
        assert extract_source_job_id("unknown", "https://example.com/careers/job-42") == "job-42"

    def test_none_link(self):
        assert extract_source_job_id("meta", None) is None


# --- Salary Parsing ---

class TestParseSalary:
    def test_full_salary_string(self):
        result = parse_salary("$130,000 to $175,000 + bonus + equity + benefits")
        assert result["salary_min"] == 130000
        assert result["salary_max"] == 175000
        assert result["salary_has_bonus"] is True
        assert result["salary_has_equity"] is True
        assert result["salary_has_benefits"] is True
        assert result["salary_range_display"] == "$130,000 - $175,000"

    def test_single_amount(self):
        result = parse_salary("$150,000")
        assert result["salary_min"] == 150000
        assert result["salary_max"] == 150000

    def test_empty_salary(self):
        result = parse_salary("")
        assert result["salary_min"] is None
        assert result["salary_has_bonus"] is False

    def test_no_bonus_equity_benefits(self):
        result = parse_salary("$100,000 to $200,000")
        assert result["salary_has_bonus"] is False
        assert result["salary_has_equity"] is False
        assert result["salary_has_benefits"] is False


# --- Keywords ---

class TestExtractKeywords:
    def test_basic(self):
        keywords = extract_keywords({"job_name": "Senior Software Engineer", "job_department": "Engineering"})
        assert "senior" in keywords
        assert "software" in keywords
        assert "engineer" in keywords
        assert "engineering" in keywords

    def test_empty(self):
        assert extract_keywords({}) == []


# --- Content Hash ---

class TestComputeContentHash:
    def test_same_input_same_hash(self):
        job = make_job()
        assert compute_content_hash(job) == compute_content_hash(job)

    def test_different_input_different_hash(self):
        assert compute_content_hash(make_job(name="A")) != compute_content_hash(make_job(name="B"))

    def test_hash_ignores_non_key_fields(self):
        job1, job2 = make_job(), make_job()
        job2["eeo"] = "Different"
        assert compute_content_hash(job1) == compute_content_hash(job2)


# --- Sync: Insert ---

class TestSyncJobsInsert:
    def test_insert_new_jobs(self):
        jobs = [
            make_job(name="Job A", link="https://www.metacareers.com/profile/job_details/111"),
            make_job(name="Job B", link="https://www.metacareers.com/profile/job_details/222"),
        ]
        result = sync_jobs("meta", "Meta", jobs)
        assert result["inserted"] == 2

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs WHERE platform = %s", ("meta",))
        assert cur.fetchone()[0] == 2
        cur.close()
        conn.close()

    def test_job_fields_mapped_correctly(self):
        sync_jobs("meta", "Meta", [make_job(link="https://www.metacareers.com/profile/job_details/333")])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, company, location, platform, source_job_id,
                   salary_min, salary_max, salary_has_bonus, is_active
            FROM jobs WHERE source_job_id = '333'
        """)
        row = cur.fetchone()
        assert row == ("Software Engineer", "Meta", "NYC", "meta", "333", 130000, 175000, True, True)
        cur.close()
        conn.close()


# --- Sync: Update ---

class TestSyncJobsUpdate:
    def test_update_when_content_changes(self):
        jobs = [make_job(name="Original", link="https://www.metacareers.com/profile/job_details/444")]
        sync_jobs("meta", "Meta", jobs)
        jobs[0]["job_name"] = "Updated"
        result = sync_jobs("meta", "Meta", jobs)
        assert result["updated"] == 1

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT title FROM jobs WHERE source_job_id = '444'")
        assert cur.fetchone()[0] == "Updated"
        cur.close()
        conn.close()

    def test_reactivates_closed_job(self):
        jobs = [make_job(link="https://www.metacareers.com/profile/job_details/555")]
        sync_jobs("meta", "Meta", jobs)
        sync_jobs("meta", "Meta", [])  # close it

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT is_active FROM jobs WHERE source_job_id = '555'")
        assert cur.fetchone()[0] is False

        sync_jobs("meta", "Meta", jobs)  # reactivate
        cur.execute("SELECT is_active, closed_at FROM jobs WHERE source_job_id = '555'")
        row = cur.fetchone()
        assert row[0] is True and row[1] is None
        cur.close()
        conn.close()


# --- Sync: Soft Delete ---

class TestSyncJobsSoftDelete:
    def test_soft_delete_missing_jobs(self):
        jobs = [
            make_job(name="A", link="https://www.metacareers.com/profile/job_details/601"),
            make_job(name="B", link="https://www.metacareers.com/profile/job_details/602"),
            make_job(name="C", link="https://www.metacareers.com/profile/job_details/603"),
        ]
        sync_jobs("meta", "Meta", jobs)
        result = sync_jobs("meta", "Meta", [jobs[0], jobs[2]])  # B removed
        assert result["closed"] == 1

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT is_active, closed_at FROM jobs WHERE source_job_id = '602'")
        row = cur.fetchone()
        assert row[0] is False and row[1] is not None
        cur.close()
        conn.close()

    def test_soft_delete_does_not_affect_other_platforms(self):
        sync_jobs("meta", "Meta", [make_job(link="https://www.metacareers.com/profile/job_details/700")])
        sync_jobs("google", "Google", [make_job(link="https://google.com/about/careers/applications/jobs/results/800-eng")])
        sync_jobs("meta", "Meta", [])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT is_active FROM jobs WHERE platform = 'google'")
        assert cur.fetchone()[0] is True
        cur.close()
        conn.close()


# --- Edge Cases ---

class TestEdgeCases:
    def test_empty_jobs_list(self):
        assert sync_jobs("meta", "Meta", [])["inserted"] == 0

    def test_job_without_link_is_skipped(self):
        assert sync_jobs("meta", "Meta", [{"job_name": "No Link"}])["inserted"] == 0

    def test_uuid_format(self):
        sync_jobs("meta", "Meta", [make_job(link="https://www.metacareers.com/profile/job_details/900")])
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM jobs WHERE source_job_id = '900'")
        import re
        assert re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', cur.fetchone()[0])
        cur.close()
        conn.close()

    def test_additional_links_stored_as_array(self):
        sync_jobs("meta", "Meta", [make_job(link="https://www.metacareers.com/profile/job_details/950")])
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT additional_links FROM jobs WHERE source_job_id = '950'")
        links = cur.fetchone()[0]
        assert isinstance(links, list) and len(links) == 2
        cur.close()
        conn.close()
