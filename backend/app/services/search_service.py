from typing import List, Dict, Any, Optional
import httpx
import logging
import json
import urllib.parse
from app.core.config import settings
from app.models.schemas import SearchResult

logger = logging.getLogger(__name__)

class SearchService:
    def __init__(self):
        self.search_provider = settings.SEARCH_PROVIDER

        # Google Search settings
        self.google_api_key = settings.GOOGLE_SEARCH_API_KEY
        self.google_search_engine_id = settings.GOOGLE_SEARCH_ENGINE_ID
        self.google_search_url = "https://www.googleapis.com/customsearch/v1"

        # SearXNG settings
        self.searxng_url = settings.SEARXNG_URL

        # Tavily settings
        self.tavily_api_key = settings.TAVILY_API_KEY
        self.tavily_search_url = "https://api.tavily.com/search"

        # Serper settings
        self.serper_api_key = settings.SERPER_API_KEY
        self.serper_search_url = "https://serper.dev/search"

        # Brave Search settings
        self.brave_api_key = settings.BRAVE_API_KEY
        self.brave_search_url = "https://api.search.brave.com/res/v1/web/search"

        # DuckDuckGo settings (no API key needed)
        self.duckduckgo_search_url = "https://api.duckduckgo.com"

    async def search_google(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Perform a search using Google Custom Search API
        """
        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_search_engine_id,
                "q": query,
                "num": min(num_results, 10)  # Google API allows max 10 results per request
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(self.google_search_url, params=params)
                response.raise_for_status()
                data = response.json()

                results = []
                if "items" in data:
                    for item in data["items"]:
                        result = SearchResult(
                            title=item.get("title", ""),
                            link=item.get("link", ""),
                            snippet=item.get("snippet", "")
                        )
                        results.append(result)

                return results
        except Exception as e:
            logger.error(f"Error in search_google: {str(e)}")
            # Return empty results in case of error
            return []

    async def search_duckduckgo(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Perform a search using DuckDuckGo API
        """
        try:
            params = {
                "q": query,
                "format": "json",
                "no_html": "1",
                "no_redirect": "1",
                "t": "AiWebSearchAgent"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(self.duckduckgo_search_url, params=params)
                response.raise_for_status()
                data = response.json()

                results = []

                # Add the abstract result if available
                if data.get("AbstractText") and data.get("AbstractURL"):
                    result = SearchResult(
                        title=data.get("Heading", ""),
                        link=data.get("AbstractURL", ""),
                        snippet=data.get("AbstractText", "")
                    )
                    results.append(result)

                # Add related topics
                for topic in data.get("RelatedTopics", [])[:num_results]:
                    if "Text" in topic and "FirstURL" in topic:
                        result = SearchResult(
                            title=topic.get("Text", "").split(" - ")[0] if " - " in topic.get("Text", "") else topic.get("Text", ""),
                            link=topic.get("FirstURL", ""),
                            snippet=topic.get("Text", "")
                        )
                        results.append(result)

                # If we still don't have enough results, try to use the Infobox
                if len(results) < num_results and data.get("Infobox") and data.get("Infobox", {}).get("content"):
                    for content in data.get("Infobox", {}).get("content", [])[:num_results - len(results)]:
                        if content.get("data_type") == "link" and content.get("value") and content.get("label"):
                            result = SearchResult(
                                title=content.get("label", ""),
                                link=content.get("value", ""),
                                snippet=content.get("label", "")
                            )
                            results.append(result)

                return results[:num_results]
        except Exception as e:
            logger.error(f"Error in search_duckduckgo: {str(e)}")
            # If the API fails, try the HTML scraping fallback
            return await self._search_duckduckgo_html_fallback(query, num_results)

    async def _search_duckduckgo_html_fallback(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Fallback method for DuckDuckGo search using HTML scraping approach
        """
        try:
            # Use the HTML endpoint
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                html_content = response.text

                # Very basic HTML parsing to extract results
                results = []
                result_blocks = html_content.split('<div class="result__body')

                for block in result_blocks[1:num_results+1]:  # Skip the first split which is before the first result
                    try:
                        # Extract title
                        title_start = block.find('<a class="result__a" href="')
                        title_end = block.find('</a>', title_start)
                        title = block[block.find('>', title_start) + 1:title_end].strip()

                        # Extract link
                        link_start = block.find('href="', title_start) + 6
                        link_end = block.find('"', link_start)
                        link = block[link_start:link_end].strip()

                        # Extract snippet
                        snippet_start = block.find('<a class="result__snippet"')
                        snippet_end = block.find('</a>', snippet_start)
                        snippet = block[block.find('>', snippet_start) + 1:snippet_end].strip()

                        if title and link:
                            result = SearchResult(
                                title=title,
                                link=link,
                                snippet=snippet
                            )
                            results.append(result)
                    except Exception as parsing_error:
                        logger.error(f"Error parsing HTML result: {str(parsing_error)}")
                        continue

                return results
        except Exception as e:
            logger.error(f"Error in _search_duckduckgo_html_fallback: {str(e)}")
            return []

    async def search_searxng(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Perform a search using SearXNG instance
        """
        try:
            params = {
                "q": query,
                "format": "json",
                "categories": "general",
                "language": "en-US",
                "count": num_results
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.searxng_url}/search", params=params)
                response.raise_for_status()
                data = response.json()

                results = []
                for result in data.get("results", [])[:num_results]:
                    search_result = SearchResult(
                        title=result.get("title", ""),
                        link=result.get("url", ""),
                        snippet=result.get("content", "")
                    )
                    results.append(search_result)

                return results
        except Exception as e:
            logger.error(f"Error in search_searxng: {str(e)}")
            return []

    async def search_tavily(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Perform a search using Tavily API
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": self.tavily_api_key
            }

            payload = {
                "query": query,
                "max_results": num_results,
                "search_depth": "basic"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.tavily_search_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for result in data.get("results", [])[:num_results]:
                    search_result = SearchResult(
                        title=result.get("title", ""),
                        link=result.get("url", ""),
                        snippet=result.get("content", "")
                    )
                    results.append(search_result)

                return results
        except Exception as e:
            logger.error(f"Error in search_tavily: {str(e)}")
            return []

    async def search_serper(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Perform a search using Serper API
        """
        try:
            headers = {
                "X-API-KEY": self.serper_api_key,
                "Content-Type": "application/json"
            }

            payload = {
                "q": query,
                "num": num_results
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.serper_search_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for result in data.get("organic", [])[:num_results]:
                    search_result = SearchResult(
                        title=result.get("title", ""),
                        link=result.get("link", ""),
                        snippet=result.get("snippet", "")
                    )
                    results.append(search_result)

                return results
        except Exception as e:
            logger.error(f"Error in search_serper: {str(e)}")
            return []

    async def search_brave(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Perform a search using Brave Search API
        """
        try:
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.brave_api_key
            }

            params = {
                "q": query,
                "count": min(num_results, 20)  # Brave API limit
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.brave_search_url,
                    headers=headers,
                    params=params
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for result in data.get("web", {}).get("results", [])[:num_results]:
                    search_result = SearchResult(
                        title=result.get("title", ""),
                        link=result.get("url", ""),
                        snippet=result.get("description", "")
                    )
                    results.append(search_result)

                return results
        except Exception as e:
            logger.error(f"Error in search_brave: {str(e)}")
            return []

    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Perform a search using the configured search provider
        """
        results: List[SearchResult] = []

        # Select the appropriate search provider based on configuration
        if self.search_provider == "google":
            results = await self.search_google(query, num_results)
        elif self.search_provider == "duckduckgo":
            results = await self.search_duckduckgo(query, num_results)
        elif self.search_provider == "searxng":
            results = await self.search_searxng(query, num_results)
        elif self.search_provider == "tavily":
            results = await self.search_tavily(query, num_results)
        elif self.search_provider == "serper":
            results = await self.search_serper(query, num_results)
        elif self.search_provider == "brave":
            results = await self.search_brave(query, num_results)
        else:
            # Default to DuckDuckGo if provider is not recognized
            logger.warning(f"Unrecognized search provider: {self.search_provider}. Using DuckDuckGo as fallback.")
            results = await self.search_duckduckgo(query, num_results)

        # If the selected provider returned no results, try DuckDuckGo as a fallback
        if not results and self.search_provider != "duckduckgo":
            logger.info(f"No results from {self.search_provider}, trying DuckDuckGo as fallback")
            results = await self.search_duckduckgo(query, num_results)

        # Convert to dict for easier handling
        return [result.model_dump() for result in results]
