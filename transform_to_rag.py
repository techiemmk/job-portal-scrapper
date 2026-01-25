import os
import json
import pandas as pd
from datetime import datetime
from base_scraper import BaseJobScraper

def transform_latest_data():
    scraper = BaseJobScraper(base_url="")
    data_dir = "data"
    
    # Map company name to its most recent jobs file and metadata
    companies = {
        "meta": {"name": "Meta Platforms, Inc.", "web": "metacareers.com"},
        "nvidia": {"name": "NVIDIA Corporation", "web": "nvidia.eightfold.ai"},
        "amazon": {"name": "Amazon.com, Inc.", "web": "amazon.jobs"},
        "apple": {"name": "Apple Inc.", "web": "jobs.apple.com"},
        "google": {"name": "Google LLC", "web": "google.com/about/careers"}
    }
    
    for portal, info in companies.items():
        # Find largest CSV for this portal (favors full datasets over small tests)
        files = [f for f in os.listdir(data_dir) if f.startswith(f"{portal}_jobs_") and f.endswith(".csv")]
        if not files:
            print(f"No data found for {portal}")
            continue
            
        # Select by file size instead of just timestamp
        latest_file = max(files, key=lambda f: os.path.getsize(os.path.join(data_dir, f)))
        file_path = os.path.join(data_dir, latest_file)
        print(f"Transforming {file_path}...")
        
        try:
            df = pd.read_csv(file_path).fillna("")
            jobs = df.to_dict('records')
            
            # Use scraper to translate
            rag_jobs = [scraper.translate_to_rag_schema(job) for job in jobs]
            
            output_data = {
                "startTime": datetime.now().isoformat(), # We don't have original start time easily
                "endTime": datetime.now().isoformat(),
                "status": "completed",
                "companyName": info["name"],
                "websiteName": info["web"],
                "data": rag_jobs
            }
            
            timestamp = datetime.now().strftime("%H%M_%d-%b-%Y")
            filename = f"data/{portal}_rag_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
                
            print(f"Created RAG JSON: {filename} ({len(rag_jobs)} jobs)")
            
        except Exception as e:
            print(f"Error transforming {portal}: {e}")

if __name__ == "__main__":
    transform_latest_data()
