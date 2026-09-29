import requests


class WebSearcher:
    """DuckDuckGo Instant Answer search (no API key needed)."""

    API_URL = "https://api.duckduckgo.com/"

    def search(self, query, num_results=5):
        try:
            response = requests.get(self.API_URL, params={
                'q': query,
                'format': 'json',
                'no_redirect': 1,
                'no_html': 1
            }, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            return f"Search error: {e}"

        lines = []
        if data.get('AbstractText'):
            lines.append(f"📌 {data['AbstractText']}")
        if data.get('Answer'):
            lines.append(f"📌 {data['Answer']}")

        # RelatedTopics mixes plain results with groups that hold their own 'Topics'
        topics = []
        for item in data.get('RelatedTopics', []):
            topics.extend(item.get('Topics', [item]))
        lines.extend(f"- {t['Text']}" for t in topics if t.get('Text'))

        lines = lines[:num_results + 2]
        if not lines:
            return "No results found"
        return f"🔍 Search results for '{query}':\n" + "\n".join(lines)
