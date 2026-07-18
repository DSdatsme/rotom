"""Print the top 10 Hacker News story titles, one per line."""

import json
import urllib.request


def get(url: str):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


ids = get("https://hacker-news.firebaseio.com/v0/topstories.json")[:10]
for i in ids:
    item = get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json") or {}
    print(f"- {item.get('title', '?')} ({item.get('url', '')})")
