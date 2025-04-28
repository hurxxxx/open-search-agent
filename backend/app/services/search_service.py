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
        self.serper_search_url = "https://google.serper.dev/search"

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
        Perform a search using DuckDuckGo
        """
        # For Korean queries, directly use the HTML fallback method which works better
        if any('\u3131' <= c <= '\u318F' or '\uAC00' <= c <= '\uD7A3' or '\u1100' <= c <= '\u11FF' for c in query):
            logger.info(f"Korean query detected: {query}. Using HTML scraping directly.")
            return await self._search_duckduckgo_html_fallback(query, num_results)

        # For non-Korean queries, try the API first
        try:
            logger.info(f"Performing DuckDuckGo API search for query: {query}")

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

                # Log the raw response for debugging (truncated)
                logger.debug(f"DuckDuckGo raw response preview: {str(data)[:500]}...")

                results = []

                # Add the abstract result if available
                if data.get("AbstractText") and data.get("AbstractURL"):
                    logger.info(f"Found abstract result for query: {query}")
                    result = SearchResult(
                        title=data.get("Heading", ""),
                        link=data.get("AbstractURL", ""),
                        snippet=data.get("AbstractText", "")
                    )
                    results.append(result)

                # Add related topics
                related_topics = data.get("RelatedTopics", [])
                logger.info(f"Found {len(related_topics)} related topics for query: {query}")

                for topic in related_topics[:num_results]:
                    if "Text" in topic and "FirstURL" in topic:
                        result = SearchResult(
                            title=topic.get("Text", "").split(" - ")[0] if " - " in topic.get("Text", "") else topic.get("Text", ""),
                            link=topic.get("FirstURL", ""),
                            snippet=topic.get("Text", "")
                        )
                        results.append(result)

                # If we still don't have enough results, try to use the Infobox
                if len(results) < num_results and data.get("Infobox") and data.get("Infobox", {}).get("content"):
                    infobox_content = data.get("Infobox", {}).get("content", [])
                    logger.info(f"Using Infobox with {len(infobox_content)} items for query: {query}")

                    for content in infobox_content[:num_results - len(results)]:
                        if content.get("data_type") == "link" and content.get("value") and content.get("label"):
                            result = SearchResult(
                                title=content.get("label", ""),
                                link=content.get("value", ""),
                                snippet=content.get("label", "")
                            )
                            results.append(result)

                logger.info(f"DuckDuckGo API search returned {len(results)} results for query: {query}")

                # If no results were found, try the HTML fallback
                if not results:
                    logger.warning(f"No results found in DuckDuckGo API for query: {query}")
                    logger.info(f"Trying HTML scraping for query: {query}")
                    return await self._search_duckduckgo_html_fallback(query, num_results)

                return results[:num_results]
        except Exception as e:
            logger.error(f"Error in search_duckduckgo: {str(e)}")
            # If the API fails, try the HTML scraping fallback
            logger.info(f"Falling back to HTML scraping for query: {query}")
            return await self._search_duckduckgo_html_fallback(query, num_results)

    async def _search_duckduckgo_html_fallback(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Fallback method for DuckDuckGo search using HTML scraping approach
        """
        try:
            logger.info(f"Using DuckDuckGo HTML fallback for query: {query}")

            # Use the HTML endpoint with Korean language preference for Korean queries
            encoded_query = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}&kl=kr-kr"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                html_content = response.text

                logger.debug(f"Received HTML response of length: {len(html_content)} characters")

                # Very basic HTML parsing to extract results
                results = []

                # Try to find result blocks
                result_blocks = html_content.split('<div class="result__body')

                logger.info(f"Found {len(result_blocks)-1} potential result blocks in HTML response")

                for i, block in enumerate(result_blocks[1:num_results+1]):  # Skip the first split which is before the first result
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
                        if snippet_start == -1:  # Try alternative snippet location
                            snippet_start = block.find('<div class="result__snippet"')

                        if snippet_start != -1:
                            snippet_end = block.find('</a>' if '<a class="result__snippet"' in block else '</div>', snippet_start)
                            snippet = block[block.find('>', snippet_start) + 1:snippet_end].strip()
                        else:
                            snippet = "No description available"

                        if title and link:
                            result = SearchResult(
                                title=title,
                                link=link,
                                snippet=snippet
                            )
                            results.append(result)
                            logger.debug(f"Extracted result {i+1}: Title: {title[:30]}...")
                        else:
                            logger.warning(f"Could not extract title or link from result block {i+1}")
                    except Exception as parsing_error:
                        logger.error(f"Error parsing HTML result block {i+1}: {str(parsing_error)}")
                        continue

                # If we couldn't find results with the standard approach, try an alternative parsing method
                if not results:
                    logger.info("Trying alternative HTML parsing method")

                    # Look for results in a different format
                    try:
                        # Try to find results in the format used by DuckDuckGo's newer HTML
                        result_blocks = html_content.split('<div class="result results_links results_links_deep web-result">')

                        logger.info(f"Alternative parsing found {len(result_blocks)-1} potential result blocks")

                        for i, block in enumerate(result_blocks[1:num_results+1]):
                            try:
                                # Extract title and link
                                title_section = block.split('<h2 class="result__title">')[1].split('</h2>')[0]
                                title_start = title_section.find('<a')
                                title_end = title_section.find('</a>')

                                title = title_section[title_section.find('>', title_start) + 1:title_end].strip()

                                link_start = title_section.find('href="') + 6
                                link_end = title_section.find('"', link_start)
                                link = title_section[link_start:link_end].strip()

                                # Extract snippet
                                snippet = ""
                                if '<div class="result__snippet">' in block:
                                    snippet_section = block.split('<div class="result__snippet">')[1].split('</div>')[0]
                                    snippet = snippet_section.strip()

                                if title and link:
                                    result = SearchResult(
                                        title=title,
                                        link=link,
                                        snippet=snippet
                                    )
                                    results.append(result)
                                    logger.debug(f"Alternative parsing - Extracted result {i+1}: Title: {title[:30]}...")
                            except Exception as alt_parsing_error:
                                logger.error(f"Error in alternative parsing for block {i+1}: {str(alt_parsing_error)}")
                                continue
                    except Exception as alt_method_error:
                        logger.error(f"Error in alternative parsing method: {str(alt_method_error)}")

                logger.info(f"DuckDuckGo HTML fallback returned {len(results)} results for query: {query}")

                if not results:
                    # If still no results, try a direct web search as a last resort
                    logger.warning(f"No results found in DuckDuckGo HTML fallback for query: {query}")

                    # Try a direct web search using a different URL format
                    try:
                        logger.info("Trying direct web search as last resort")
                        direct_url = f"https://duckduckgo.com/?q={encoded_query}&kl=kr-kr&ia=web"

                        async with httpx.AsyncClient() as direct_client:
                            direct_response = await direct_client.get(direct_url, headers=headers)
                            direct_response.raise_for_status()

                            # Create a minimal result with the search URL
                            results.append(SearchResult(
                                title=f"DuckDuckGo search results for: {query}",
                                link=direct_url,
                                snippet=f"Click to view web search results for '{query}' on DuckDuckGo."
                            ))
                            logger.info("Added direct search link as a fallback result")
                    except Exception as direct_search_error:
                        logger.error(f"Error in direct web search fallback: {str(direct_search_error)}")

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
