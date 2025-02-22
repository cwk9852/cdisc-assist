"""
Simple LexJansen CDISC papers collector - Downloads PDFs in parallel
"""
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

OUTPUT_DIR = Path(__file__).parent.parent / "data/lexjansen/pdfs"

# Add browser-like headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def download_pdf(url):
    """Download a single PDF"""
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            filename = url.split('/')[-1]
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path = OUTPUT_DIR / filename
            with open(pdf_path, 'wb') as f:
                f.write(response.content)
            print(f'Downloaded {filename}')
    except Exception as e:
        print(f'Error downloading {url}: {e}')

def get_pdfs(url='https://www.lexjansen.com/cdisc'):
    """Get and download all PDFs from the page"""
    # Get the page
    print(f'Fetching {url}...')
    response = requests.get(url, headers=HEADERS)
    print(f'Status code: {response.status_code}')
    
    # Debug: Print first part of HTML
    print("First 500 chars of HTML:")
    print(response.text[:500])
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find all PDF links with more detailed debugging
    all_links = soup.find_all('a')
    print(f'\nFound {len(all_links)} total links')
    print("First few links:")
    for link in all_links[:5]:
        print(f"  href: {link.get('href', 'NO HREF')} - text: {link.text}")
    
    pdf_links = [link.get('href') for link in all_links 
                 if link.get('href', '').lower().endswith('.pdf')]
    
    # Make full URLs using urljoin to handle both relative and absolute paths
    pdf_links = [urljoin(url, link) for link in pdf_links]
    
    print(f'\nFound {len(pdf_links)} PDFs')
    if pdf_links:
        print(f'First few PDF links found:')
        for link in pdf_links[:3]:
            print(f'  {link}')
    print(f'Downloading to {OUTPUT_DIR}')
    
    # Download PDFs in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(download_pdf, pdf_links)

if __name__ == '__main__':
    get_pdfs()