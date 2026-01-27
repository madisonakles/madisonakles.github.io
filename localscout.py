import requests
import json
import time
import re
import io
import random
from pypdf import PdfReader

# --- CONFIGURATION ---
TOPIC = "Social Priming"
YEAR_RANGE = "2010-2025"
MAX_PAPERS = 20           # Start small to test Sci-Hub speed
WAIT_TIME = 3             # Sci-Hub blocks you if you go too fast. Keep this at 3+.

# --- SCAPING ENGINES ---
def get_pdf_from_scihub(doi):
    """
    Tries to find a PDF via Sci-Hub mirrors.
    Returns: PDF bytes (or None)
    """
    mirrors = ['https://sci-hub.se', 'https://sci-hub.ru', 'https://sci-hub.st']
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
    }

    clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')

    for mirror in mirrors:
        target_url = f"{mirror}/{clean_doi}"
        try:
            # 1. Go to the Sci-Hub page
            r = requests.get(target_url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue

            # 2. Find the actual PDF link inside the HTML (it's usually in an <embed> or <button>)
            # Pattern: src='//zero.sci-hub.se/123/456.pdf'
            match = re.search(r'src=[\'"](.*?)[\'"]', r.text)
            
            if match:
                pdf_url = match.group(1)
                # Fix URL if it starts with //
                if pdf_url.startswith('//'):
                    pdf_url = 'https:' + pdf_url
                elif pdf_url.startswith('/'):
                    pdf_url = mirror + pdf_url
                
                # 3. Download the actual PDF data
                pdf_r = requests.get(pdf_url, headers=headers, timeout=15)
                if pdf_r.status_code == 200 and 'application/pdf' in pdf_r.headers.get('Content-Type', ''):
                    return pdf_r.content, mirror # Success!

        except Exception as e:
            pass # Try next mirror
            
    return None, None

def analyze_pdf_bytes(pdf_bytes):
    """Reads PDF from RAM and finds N."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        # Scan first 10 pages (increased for robustness)
        for i in range(min(10, len(reader.pages))):
            text += reader.pages[i].extract_text()
        
        text = text.lower().replace('\n', ' ')
        
        # Priority 1: Statistics (The smoking gun)
        # t(28)=..., F(1, 30)=...
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
                if 5 < est < 5000:
                    candidates.append({'n': est, 'source': src})

        # Priority 2: Explicit "N ="
        if not candidates:
             explicit = re.search(r'\bn\s?=\s?(\d+)', text)
             if explicit:
                 val = int(explicit.group(1))
                 if 5 < val < 5000:
                    candidates.append({'n': val, 'source': 'Explicit N'})

        # Priority 3: "Participants" count word search
        if not candidates:
            # Look for "X participants were recruited"
            part_match = re.search(r'(\d+)\s?(?:participants|undergraduates|students)', text)
            if part_match:
                val = int(part_match.group(1))
                if 5 < val < 5000:
                    candidates.append({'n': val, 'source': 'Text Count'})

        if candidates:
            # Sort: Smallest valid N is usually the key experiment
            candidates.sort(key=lambda x: x['n'])
            return candidates[0]['n'], candidates[0]['source']
            
    except Exception:
        pass
    return None, None

def get_method_from_title(title):
    t = title.lower()
    if 'fmri' in t: return "fMRI"
    if 'meta-analysis' in t: return "Meta-Analysis"
    if 'replication' in t: return "Replication"
    if 'review' in t: return "Review"
    return "Unknown"

# --- MAIN LOOP ---
def harvest():
    print(f"🕵️  Starting Heavy Scout (OpenAccess + Sci-Hub Fallback)")
    print(f"    Topic: {TOPIC} | Limit: {MAX_PAPERS} papers")
    print(f"    Note: This is slower because we must be polite to Sci-Hub.\n")
    
    url = f"https://api.openalex.org/works?filter=title.search:{TOPIC},publication_year:{YEAR_RANGE},concepts.id:C15744967&sort=cited_by_count:desc&per-page={MAX_PAPERS}"
    results = requests.get(url).json().get('results', [])
    
    database = []

    for i, work in enumerate(results):
        title = work['title']
        doi = work['doi']
        oa_url = work['open_access']['oa_url']
        
        print(f"[{i+1}] {title[:40]}...")

        n_val = None
        n_source = None
        pdf_source = "None"
        
        # STEP 1: Try Open Access (Fastest/Legal)
        pdf_bytes = None
        if oa_url:
            try:
                print(f"    Trying OpenAccess...", end='')
                r = requests.get(oa_url, timeout=10)
                if r.status_code == 200 and 'application/pdf' in r.headers.get('Content-Type',''):
                    pdf_bytes = r.content
                    pdf_source = "OpenAccess"
                    print(" ✅ Success.")
                else:
                    print(" ❌ Failed.")
            except:
                print(" ❌ Error.")

        # STEP 2: Try Sci-Hub (Fallback)
        if not pdf_bytes and doi:
            print(f"    Trying Sci-Hub...", end='')
            # Add a random delay to look human
            time.sleep(random.uniform(1.0, 3.0)) 
            pdf_bytes, mirror_used = get_pdf_from_scihub(doi)
            if pdf_bytes:
                pdf_source = f"Sci-Hub ({mirror_used})"
                print(" ✅ Unlocked.")
            else:
                print(" ❌ Blocked/Not Found.")

        # STEP 3: Analyze
        if pdf_bytes:
            n_val, n_source = analyze_pdf_bytes(pdf_bytes)
            if n_val:
                print(f"    🎯 Found N = {n_val} ({n_source})")
            else:
                print(f"    ⚠️  PDF read, but no N found.")

        # STEP 4: Save Data
        database.append({
            'title': title,
            'year': work['publication_year'],
            'cited': work['cited_by_count'],
            'doi': doi,
            'pdf_link': oa_url if oa_url else (doi or "#"),
            'n_val': n_val,
            'n_source': n_source,
            'method': get_method_from_title(title),
            'access_type': pdf_source
        })
        
        print("-" * 50)
        time.sleep(WAIT_TIME)

    # Export
    with open("db.js", "w", encoding="utf-8") as f:
        f.write(f"const DATABASE = {json.dumps(database, indent=2)};")
    
    print("\n✅ Harvest Complete. Open 'localscout.html' to view.")

if __name__ == "__main__":
    harvest()
