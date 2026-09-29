import re

import requests

# Wikimedia asks API users to identify themselves
USER_AGENT = "PersonalAIAssistant/1.0 (local chatbot; https://github.com/ryanc3352/Iambadatcb-bot)"


class WebSearcher:
    """Web search without API keys.

    Uses the `ddgs` library for real web results (it rotates between search engines),
    plus DuckDuckGo's instant answers, and Wikipedia when nothing else is found.
    Each source fails quietly, so one being down never breaks the chat.
    """

    INSTANT_ANSWER_URL = "https://api.duckduckgo.com/"
    WIKIPEDIA_URL = "https://en.wikipedia.org/w/api.php"

    def search(self, query, num_results=5):
        """Search the web and return the results as text for the model."""
        lines = self._instant_answer(query)
        results = self._web_results(query, num_results) or self._wikipedia(query, num_results)
        lines += [f"- {r['title']}: {r['body']} ({r['url']})" for r in results]
        if not lines:
            return "No results found"
        return f"🔍 Search results for '{query}':\n" + "\n".join(lines)

    def _instant_answer(self, query):
        """DuckDuckGo's short answer box (Wikipedia-style abstracts, conversions...)."""
        try:
            response = requests.get(self.INSTANT_ANSWER_URL, params={
                'q': query, 'format': 'json', 'no_redirect': 1, 'no_html': 1
            }, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"Instant answer error: {e}")
            return []
        return [f"📌 {data[key]}" for key in ('Answer', 'AbstractText') if data.get(key)]

    def _web_results(self, query, num_results):
        """Real web results via the ddgs library (optional dependency)."""
        try:
            from ddgs import DDGS
        except ImportError:
            return []
        try:
            hits = DDGS(timeout=10).text(query, max_results=num_results) or []
        except Exception as e:  # the library raises its own error types for blocks/timeouts
            print(f"Web search error: {e}")
            return []
        return [{'title': h.get('title', ''), 'body': (h.get('body') or '')[:300], 'url': h.get('href', '')}
                for h in hits[:num_results] if h.get('title') or h.get('body')]

    def _wikipedia(self, query, num_results):
        """Wikipedia article matches, used when web search finds nothing."""
        try:
            response = requests.get(self.WIKIPEDIA_URL, params={
                'action': 'query', 'list': 'search', 'srsearch': query,
                'format': 'json', 'srlimit': min(num_results, 3)
            }, headers={'User-Agent': USER_AGENT}, timeout=10)
            response.raise_for_status()
            hits = response.json().get('query', {}).get('search', [])
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"Wikipedia search error: {e}")
            return []
        return [{'title': h['title'],
                 'body': re.sub(r"<[^>]+>", "", h.get('snippet', '')),
                 'url': f"https://en.wikipedia.org/wiki/{h['title'].replace(' ', '_')}"}
                for h in hits]
