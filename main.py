#!/usr/bin/env python3
"""
AAAI Knowledge Graph Papers Crawler (Updated)
Downloads papers from multiple sources including DBLP, arXiv, and AAAI
Handles access restrictions and finds alternative sources
"""

import requests
from bs4 import BeautifulSoup
import os
import time
import re
from urllib.parse import urljoin, quote, urlparse
import json
from typing import List, Dict, Optional
from datetime import datetime

class AAIKnowledgeGraphCrawler:
    def __init__(self, output_dir: str = "aaai_kg_papers"):
        """Initialize the crawler with output directory"""
        self.output_dir = output_dir
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Track failed downloads
        self.failed_downloads = []
        
    def search_dblp(self, keyword: str = "knowledge graph", venue: str = "AAAI", year: int = 2025) -> List[Dict]:
        """Search DBLP for papers with keyword in title from specific venue and year"""
        papers = []
        
        # DBLP API endpoint
        base_url = "https://dblp.org/search/publ/api"
        
        # Try both the specified year and the previous year
        years_to_search = [year, year - 1]
        
        for search_year in years_to_search:
            # Search query
            query = f'{keyword} venue:{venue} year:{search_year}'
            params = {
                'q': query,
                'format': 'json',
                'h': 1000,  # max results
                'f': 0      # start from
            }
            
            try:
                print(f"\nSearching DBLP for '{keyword}' papers from {venue} {search_year}...")
                response = self.session.get(base_url, params=params)
                response.raise_for_status()
                
                data = response.json()
                
                if 'result' in data and 'hits' in data['result']:
                    hits = data['result']['hits'].get('hit', [])
                    
                    for hit in hits:
                        info = hit.get('info', {})
                        title = info.get('title', '')
                        
                        # Filter by keyword in title (case-insensitive)
                        if keyword.lower() in title.lower():
                            paper = {
                                'title': title,
                                'authors': self._extract_authors(info.get('authors', {})),
                                'year': info.get('year', ''),
                                'venue': info.get('venue', ''),
                                'url': info.get('url', ''),
                                'ee': info.get('ee', ''),  # Electronic edition (often PDF link)
                                'key': info.get('key', ''),
                                'doi': info.get('doi', ''),
                                'source': 'DBLP'
                            }
                            
                            # Ensure it's from AAAI
                            if venue.lower() in paper['venue'].lower():
                                papers.append(paper)
                                print(f"Found: {paper['title']} ({search_year})")
                
                print(f"Found {len([p for p in papers if p['year'] == str(search_year)])} papers from {search_year}")
                
            except Exception as e:
                print(f"Error searching DBLP for year {search_year}: {e}")
        
        return papers
    
    def _extract_authors(self, authors_data: Dict) -> List[str]:
        """Extract author names from DBLP author data"""
        if isinstance(authors_data, dict) and 'author' in authors_data:
            authors = authors_data['author']
            if isinstance(authors, list):
                return [a if isinstance(a, str) else a.get('text', '') for a in authors]
            elif isinstance(authors, str):
                return [authors]
            elif isinstance(authors, dict):
                return [authors.get('text', '')]
        return []
    
    def search_arxiv_for_paper(self, title: str, authors: List[str] = None) -> Optional[str]:
        """Search arXiv for a specific paper by title and return PDF URL if found"""
        try:
            # Clean title for search
            search_title = re.sub(r'[^\w\s]', ' ', title)
            search_title = ' '.join(search_title.split())[:100]  # Limit length
            
            # arXiv API search
            base_url = "http://export.arxiv.org/api/query"
            
            # Try different search strategies
            search_queries = [
                f'ti:"{search_title}"',  # Exact title search
                f'ti:{search_title}',    # Title words search
            ]
            
            if authors and len(authors) > 0:
                # Add author to search for better precision
                first_author = authors[0].split()[-1]  # Last name
                search_queries.append(f'ti:{search_title} AND au:{first_author}')
            
            for query in search_queries:
                params = {
                    'search_query': query,
                    'max_results': 5,
                    'sortBy': 'relevance'
                }
                
                response = self.session.get(base_url, params=params)
                response.raise_for_status()
                
                # Parse XML response
                soup = BeautifulSoup(response.content, 'xml')
                entries = soup.find_all('entry')
                
                for entry in entries:
                    arxiv_title = entry.find('title').text.strip()
                    
                    # Check if titles match (fuzzy matching)
                    if self._titles_match(title, arxiv_title):
                        # Get PDF link
                        links = entry.find_all('link')
                        for link in links:
                            if link.get('title') == 'pdf':
                                pdf_url = link.get('href')
                                # Ensure it's a PDF URL
                                if '/pdf/' not in pdf_url:
                                    pdf_url = pdf_url.replace('/abs/', '/pdf/') + '.pdf'
                                
                                print(f"  Found on arXiv: {pdf_url}")
                                return pdf_url
                
                time.sleep(0.5)  # Be polite to arXiv
            
        except Exception as e:
            print(f"  Error searching arXiv: {e}")
        
        return None
    
    def _titles_match(self, title1: str, title2: str) -> bool:
        """Check if two titles are similar enough to be the same paper"""
        # Normalize titles
        def normalize(s):
            s = s.lower()
            s = re.sub(r'[^\w\s]', ' ', s)
            s = ' '.join(s.split())
            return s
        
        t1 = normalize(title1)
        t2 = normalize(title2)
        
        # Check exact match
        if t1 == t2:
            return True
        
        # Check if one is substring of another (common with arXiv titles)
        if t1 in t2 or t2 in t1:
            return True
        
        # Check word overlap
        words1 = set(t1.split())
        words2 = set(t2.split())
        
        # Remove common words
        common_words = {'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'and', 'or', 'with'}
        words1 = words1 - common_words
        words2 = words2 - common_words
        
        if len(words1) > 0 and len(words2) > 0:
            overlap = len(words1 & words2) / min(len(words1), len(words2))
            return overlap > 0.7
        
        return False
    
    def download_paper(self, paper: Dict, index: int) -> bool:
        """Download a single paper PDF, trying multiple sources"""
        print(f"\n[{index}] Processing: {paper['title']}")
        
        # Create safe filename
        safe_title = re.sub(r'[^\w\s-]', '', paper['title'])[:80]
        safe_title = re.sub(r'[-\s]+', '-', safe_title)
        filename = f"{index:03d}_{safe_title}.pdf"
        filepath = os.path.join(self.output_dir, filename)
        
        # Skip if already downloaded
        if os.path.exists(filepath):
            print(f"  Already downloaded: {filename}")
            return True
        
        # Try different sources
        pdf_url = None
        source = None
        
        # 1. First try arXiv
        print("  Searching arXiv...")
        arxiv_url = self.search_arxiv_for_paper(paper['title'], paper.get('authors', []))
        if arxiv_url:
            pdf_url = arxiv_url
            source = "arXiv"
        
        # 2. Try direct URL from DBLP if arXiv fails
        if not pdf_url and paper.get('ee'):
            # Check if it's already a direct PDF link
            if paper['ee'].endswith('.pdf') or 'arxiv.org/pdf' in paper['ee']:
                pdf_url = paper['ee']
                source = "DBLP direct link"
            # Skip AAAI OJS links as they require authentication
            elif 'ojs.aaai.org' in paper['ee'] or 'doi.org/10.1609' in paper['ee']:
                print("  Skipping AAAI OJS link (requires authentication)")
            else:
                pdf_url = paper['ee']
                source = "DBLP EE link"
        
        if not pdf_url:
            print(f"  No accessible PDF found")
            self.failed_downloads.append({
                'index': index,
                'title': paper['title'],
                'reason': 'No accessible PDF URL found'
            })
            return False
        
        # Try to download
        try:
            print(f"  Downloading from {source}: {pdf_url}")
            
            response = self.session.get(pdf_url, stream=True, timeout=30, allow_redirects=True)
            
            # Check if we got a 403 or other error
            if response.status_code == 403:
                print(f"  Access forbidden (403)")
                self.failed_downloads.append({
                    'index': index,
                    'title': paper['title'],
                    'reason': f'403 Forbidden from {source}',
                    'url': pdf_url
                })
                return False
            
            response.raise_for_status()
            
            # Check if it's actually a PDF
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower() and not pdf_url.endswith('.pdf'):
                print(f"  Warning: Content might not be PDF (content-type: {content_type})")
            
            # Download the file
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"  Downloaded successfully: {filename}")
            
            # Save metadata
            metadata = paper.copy()
            metadata['download_source'] = source
            metadata['download_url'] = pdf_url
            metadata['download_date'] = datetime.now().isoformat()
            
            metadata_file = os.path.join(self.output_dir, f"{index:03d}_metadata.json")
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            # Be polite - add delay between downloads
            time.sleep(2)
            
            return True
            
        except Exception as e:
            print(f"  Error downloading: {e}")
            self.failed_downloads.append({
                'index': index,
                'title': paper['title'],
                'reason': str(e),
                'url': pdf_url
            })
            return False
    
    def save_results(self, papers: List[Dict]):
        """Save all results including successful downloads and failures"""
        # Save complete paper list
        papers_file = os.path.join(self.output_dir, "all_papers.json")
        with open(papers_file, 'w', encoding='utf-8') as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        print(f"\nSaved complete paper list to: {papers_file}")
        
        # Save failed downloads
        if self.failed_downloads:
            failed_file = os.path.join(self.output_dir, "failed_downloads.json")
            with open(failed_file, 'w', encoding='utf-8') as f:
                json.dump(self.failed_downloads, f, ensure_ascii=False, indent=2)
            print(f"Saved failed downloads list to: {failed_file}")
            
            # Also create a simple text report
            report_file = os.path.join(self.output_dir, "download_report.txt")
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(f"Download Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*80 + "\n\n")
                
                f.write(f"Total papers found: {len(papers)}\n")
                f.write(f"Successfully downloaded: {len(papers) - len(self.failed_downloads)}\n")
                f.write(f"Failed downloads: {len(self.failed_downloads)}\n\n")
                
                if self.failed_downloads:
                    f.write("Failed Downloads:\n")
                    f.write("-"*80 + "\n")
                    for fail in self.failed_downloads:
                        f.write(f"\n[{fail['index']}] {fail['title']}\n")
                        f.write(f"    Reason: {fail['reason']}\n")
                        if 'url' in fail:
                            f.write(f"    URL: {fail['url']}\n")
            
            print(f"Saved download report to: {report_file}")
    
    def run(self, keyword: str = "knowledge graph", venue: str = "AAAI", year: int = 2025):
        """Main method to run the crawler"""
        print(f"=== AAAI Knowledge Graph Papers Crawler ===")
        print(f"Searching for: '{keyword}' in {venue} {year}")
        print(f"Output directory: {self.output_dir}")
        print(f"Note: {venue} {year} proceedings might not be available yet.")
        print(f"Will also search {venue} {year-1} papers.\n")
        
        # Search DBLP
        papers = self.search_dblp(keyword=keyword, venue=venue, year=year)
        
        if not papers:
            print("\nNo papers found!")
            return
        
        print(f"\nTotal papers found: {len(papers)}")
        
        # Download papers
        print(f"\nStarting download process...")
        print("Will try multiple sources: arXiv, direct links, etc.")
        print("Note: AAAI official PDFs require institutional access.\n")
        
        success_count = 0
        for i, paper in enumerate(papers, 1):
            if self.download_paper(paper, i):
                success_count += 1
            
            print(f"\nProgress: {i}/{len(papers)} papers processed")
            print(f"Downloaded: {success_count}, Failed: {len(self.failed_downloads)}")
        
        # Save all results
        self.save_results(papers)
        
        print("\n" + "="*60)
        print(f"Download complete!")
        print(f"Successfully downloaded: {success_count}/{len(papers)} papers")
        print(f"Papers saved in: {self.output_dir}")
        
        if self.failed_downloads:
            print(f"\nFailed downloads: {len(self.failed_downloads)}")
            print("Check 'failed_downloads.json' for details.")
            print("\nCommon reasons for failures:")
            print("- Papers behind AAAI paywall (try institutional access)")
            print("- Papers not yet on arXiv")
            print("- Conference proceedings not yet published")


def main():
    """Main function to run the crawler"""
    # Configuration
    OUTPUT_DIR = "aaai_kg_papers"
    KEYWORD = "knowledge graph"
    VENUE = "AAAI"
    YEAR = 2025  # Will also search 2024
    
    # Create and run crawler
    crawler = AAIKnowledgeGraphCrawler(output_dir=OUTPUT_DIR)
    crawler.run(keyword=KEYWORD, venue=VENUE, year=YEAR)
    
    print("\n=== Alternative Access Methods ===")
    print("If many papers failed to download, consider:")
    print("1. Access through your institution's library")
    print("2. Check authors' personal websites")
    print("3. Search for papers on ResearchGate or Google Scholar")
    print("4. Wait for AAAI 2025 proceedings to be published")
    print("5. Contact paper authors directly")


if __name__ == "__main__":
    # Install required packages:
    # pip install requests beautifulsoup4 lxml
    
    main()
