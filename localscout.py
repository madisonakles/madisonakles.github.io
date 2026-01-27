import requests
import json
import time
import re
import io
from pypdf import PdfReader

# --- CONFIGURATION ---
TOPIC = "Social Priming"
YEAR_RANGE = "2010-2025"
MAX_PAPERS = 50           # You can crank this up now (e.g., 500)
WAIT_TIME = 1             # Faster since we aren't writing to disk

# --- ANALYSIS ENGINE ---
def analyze_text_in_memory(pdf_bytes):
    """Reads PDF from RAM and finds N."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        # Scan first 7 pages (Methods usually here)
        for i in range(min(7, len(reader.pages))):
            text += reader.pages[i].extract_text()
        
        text = text.lower().replace('\n', ' ')
        
        # 1. Look for Stats (t(28)=...)
        stat_patterns = [
            (r't\s?\(\s?(\d+)\s?\)\s?=', 2, 't-test'),
            (r'f\s?\(\s?\d+\s?,\s?(\d+)\s?\)\s?=', 2, 'ANOVA'),
            (r'r\s?\(\s?(\d+)\s?\)\s?=', 2, 'Corr')
        ]
        
        candidates = []
        for pat, offset, src in stat_patterns:
            matches = re.findall(pat, text)
            for val in matches:
                est = int(val) + offset
                if 5 < est < 2000:
                    candidates.append({'n': est, 'source': src})

        # 2. Look for explicit "N ="
        if not candidates:
             explicit = re.search(r'\bn\s?=\s?(\d+)', text)
             if explicit:
                 val = int(explicit.group(1))
                 if 5 < val < 2000:
                    candidates.append({'n': val, 'source': 'Explicit N'})

        # Sort: Smallest valid N is usually the key experiment
        if candidates:
            candidates.sort(key=lambda x: x['n'])
            return candidates[0]['n'], candidates[0]['source']
            
    except Exception:
        pass
    return None, None

def get_method(title):
    # Simple heuristic based on title/concepts since we aren't keeping text
    t = title.lower()
    if 'fmri' in t: return "fMRI"
    if 'replication' in t: return "Replication"
    if 'meta-analysis' in t: return "Meta-Analysis"
    return "Unknown"

# --- MAIN LOOP ---
def harvest():
    print(f"🕵️  Starting 'Catch & Release' Scan for: {TOPIC}")
    print(f"    (Scanning {MAX_PAPERS} papers. No PDFs will be saved to disk.)\n")
    
    url = f"https://api.openalex.org/works?filter=title.search:{TOPIC},publication_year:{YEAR_RANGE},concepts.id:C15744967&sort=cited_by_count:desc&per-page={MAX_PAPERS}"
    results = requests.get(url).json().get('results', [])
    
    database = []

    for i, work in enumerate(results):
        title = work['title']
        doi = work['doi']
        pdf_url = work['open_access']['oa_url']
        
        print(f"[{i+1}] {title[:50]}...")

        n_val = None
        n_source = None
        
        # 1. DOWNLOAD TO RAM
        if pdf_url:
            try:
                print(f"    ⚡ Fetching PDF...", end='')
                r = requests.get(pdf_url, timeout=10)
                if r.status_code == 200 and 'application/pdf' in r.headers.get('Content-Type',''):
                    # 2. ANALYZE INSTANTLY
                    print(" Scanning...", end='')
                    n_val, n_source = analyze_text_in_memory(r.content)
                    print(f" Done. (N={n_val or '?'})")
                else:
                    print(" Failed (Link dead).")
            except:
                print(" Error.")
        else:
            print("    ❌ No Direct PDF Link.")

        # 3. SAVE DATA (BUT DROP PDF)
        database.append({
            'title': title,
            'year': work['publication_year'],
            'cited': work['cited_by_count'],
            'doi': doi,
            'pdf_link': pdf_url if pdf_url else (doi or "#"),
            'n_val': n_val,
            'n_source': n_source,
            'method': get_method(title)
        })
        
        # Be nice to the server
        time.sleep(WAIT_TIME)

    # Save lightweight DB
    with open("db.js", "w", encoding="utf-8") as f:
        f.write(f"const DATABASE = {json.dumps(database, indent=2)};")
    
    print("\n✅ Done! Open 'dashboard.html' to see your lightweight archive.")

if __name__ == "__main__":
    harvest()
