"""Discovery: fetch candidates from RSS feeds."""

import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def discover_candidates() -> List[dict]:
    """Fetch candidates from Hacker News RSS feed."""
    url = "https://news.ycombinator.com/rss"
    candidates = []
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read()
        root = ET.fromstring(html)
        
        for idx, item in enumerate(root.findall('.//item')[:20]):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            
            if not title or not link:
                continue
            
            # Scrape content
            content = scrape_article_text(link)
            
            candidates.append({
                "id": f"cand_{idx}",
                "title": title,
                "summary": content[:500],
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sources": [link]
            })
            
    except Exception as e:
        logger.error(f"Error fetching RSS: {e}")
        
    return candidates


def scrape_article_text(url: str) -> str:
    """Scrape article text from URL."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read()
        soup = BeautifulSoup(html, 'html.parser')
        
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.extract()
            
        paragraphs = [p.get_text().strip() for p in soup.find_all('p') if len(p.get_text().strip()) > 40]
        text_content = " ".join(paragraphs[:8])
        return text_content[:3500] if text_content else "No descriptive article text available."
    except Exception:
        return "Context extraction unavailable due to source site network or access restrictions."