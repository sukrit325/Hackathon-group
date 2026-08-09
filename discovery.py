"""Discovery module: fetches technology news candidates from configured RSS feeds."""
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List
from bs4 import BeautifulSoup
from config import get_settings
import feedparser
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

FEED_URLS = [
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://www.marktechpost.com/feed/",
    "https://blog.google/technology/ai/rss/",
]

async def discover() -> List[Dict[str, Any]]:
    """Fetch candidates from high-quality tech RSS feeds."""
    candidates = []
    for url in FEED_URLS:
        try:
            # feedparser handles parsing XML/RSS smoothly
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:  # Grab top 5 latest per feed
                candidates.append({
                    "id": entry.get("id") or entry.get("link"),
                    "title": entry.get("title", "Untitled"),
                    "summary": entry.get("summary", "") or entry.get("description", ""),
                    "content": entry.get("content", [{"value": ""}])[0]["value"],
                    "source_url": entry.get("link", ""),
                    "published_at": entry.get("published", None),
                })
        except Exception as e:
            print(f"Failed to fetch feed {url}: {e}")
            
    return candidates

async def discover_candidates() -> List[dict]:
    sources = get_settings().rss_sources
    candidates = []
    cand_counter = 0

    for url in sources:
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            html = urllib.request.urlopen(req, timeout=8).read()
            root = ET.fromstring(html)

            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
            for item in items[:10]:
                title_elem = item.find('title') or item.find('{http://www.w3.org/2005/Atom}title')
                link_elem = item.find('link') or item.find('{http://www.w3.org/2005/Atom}link')

                title = title_elem.text if title_elem is not None else ""
                link = ""
                if link_elem is not None:
                    link = link_elem.text if link_elem.text else link_elem.attrib.get('href', '')

                if not title or not link:
                    continue

                content = scrape_article_text(link)
                candidates.append({
                    "id": f"cand_{cand_counter}",
                    "title": title,
                    "summary": content[:500],
                    "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sources": [link]
                })
                cand_counter += 1
        except Exception as e:
            logger.error(f"Error fetching RSS from {url}: {e}")

    return candidates

async def discover():
    dicts = await discover_candidates()
    objs = []
    for d in dicts:
        objs.append(type("C", (), {"to_dict": (lambda self, _d=d: _d)})())
    return objs

def scrape_article_text(url: str) -> str:
    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        html = urllib.request.urlopen(req, timeout=5).read()
        soup = BeautifulSoup(html, 'html.parser')
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.extract()
        paragraphs = [p.get_text().strip() for p in soup.find_all('p') if len(p.get_text().strip()) > 40]
        text_content = " ".join(paragraphs[:8])
        return text_content[:3500] if text_content else "No descriptive article text available."
    except Exception:
        return "Context extraction unavailable due to source site network or access restrictions."