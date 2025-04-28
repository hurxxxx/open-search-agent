from typing import List, Dict, Any, Optional, AsyncGenerator
import json
import logging
import traceback
import asyncio
from openai import OpenAI, AsyncOpenAI

from app.core.config import settings

# 로깅 레벨 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class LLMService:
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL  # Get model from settings

    def decompose_prompt(self, prompt: str) -> List[str]:
        """
        Decompose a user prompt into multiple search queries
        """
        try:
            messages = [
                {"role": "system", "content": "You are an AI assistant that helps decompose complex questions into simpler search queries. Your task is to analyze the user's prompt and generate a list of search queries that would help gather information to answer the prompt comprehensively."},
                {"role": "user", "content": f"Please decompose the following prompt into 3-5 search queries that would help gather information to answer it: '{prompt}'"}
            ]

            # Set base parameters
            params = {
                "model": self.model,
                "messages": messages
            }
            
            response = self.client.chat.completions.create(**params)

            # Extract the search queries from the response
            content = response.choices[0].message.content

            # Try to parse as JSON if the response is formatted that way
            try:
                # Check if the content contains a JSON array
                if "[" in content and "]" in content:
                    json_str = content[content.find("["):content.rfind("]")+1]
                    queries = json.loads(json_str)
                    return queries
            except json.JSONDecodeError:
                pass

            # Fallback: extract queries line by line
            lines = content.strip().split("\n")
            queries = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith(("Here", "#", "Search", "Query", "-", "1.", "2.", "3.", "4.", "5.")):
                    queries.append(line)
                elif line.startswith(("-", "1.", "2.", "3.", "4.", "5.")):
                    query = line.split(" ", 1)[1] if " " in line else line
                    queries.append(query.strip())

            # If we still don't have queries, use the whole response
            if not queries:
                queries = [content.strip()]

            return queries
        except Exception as e:
            logger.error(f"Error in decompose_prompt: {str(e)}")
            return [prompt]  # Fallback to the original prompt

    def evaluate_search_results(self, prompt: str, search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate if the search results are sufficient to answer the prompt
        """
        try:
            # Format search results for the LLM
            formatted_results = ""
            for i, result in enumerate(search_results):
                formatted_results += f"Result {i+1}:\n"
                formatted_results += f"Title: {result.get('title', 'N/A')}\n"
                formatted_results += f"Link: {result.get('link', 'N/A')}\n"
                formatted_results += f"Snippet: {result.get('snippet', 'N/A')}\n\n"

            messages = [
                {"role": "system", "content": "You are an AI assistant that evaluates search results to determine if they provide sufficient information to answer a user's question. If the information is insufficient, you should suggest additional search queries."},
                {"role": "user", "content": f"Original prompt: {prompt}\n\nSearch results:\n{formatted_results}\n\nAre these search results sufficient to answer the original prompt? If not, what additional search queries would you suggest? Respond in JSON format with the following structure: {{\"sufficient\": boolean, \"reasoning\": \"your reasoning\", \"additional_queries\": [\"query1\", \"query2\"]}}"}
            ]

            # Set base parameters
            params = {
                "model": self.model,
                "messages": messages
            }

            response = self.client.chat.completions.create(**params)

            content = response.choices[0].message.content

            # Try to extract JSON from the response
            try:
                # Find JSON-like content in the response
                start_idx = content.find("{")
                end_idx = content.rfind("}")

                if start_idx != -1 and end_idx != -1:
                    json_str = content[start_idx:end_idx+1]
                    evaluation = json.loads(json_str)
                    return evaluation
            except json.JSONDecodeError:
                pass

            # Fallback: parse the response manually
            sufficient = "sufficient" in content.lower() and "yes" in content.lower()
            reasoning = content

            return {
                "sufficient": sufficient,
                "reasoning": reasoning,
                "additional_queries": []
            }
        except Exception as e:
            logger.error(f"Error in evaluate_search_results: {str(e)}")
            return {
                "sufficient": False,
                "reasoning": f"Error evaluating results: {str(e)}",
                "additional_queries": []
            }

    def summarize_search_result(self, prompt: str, query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Summarize a single search result to extract only the relevant information
        Uses a smaller model (o4-mini) to reduce costs
        """
        try:
            # Extract result information
            title = result.get('title', 'N/A')
            link = result.get('link', 'N/A')
            snippet = result.get('snippet', 'N/A')

            # Create system prompt for summarization
            system_prompt = """
            You are an AI assistant that extracts and summarizes only the relevant information from search results.
            Your task is to analyze a search result and extract only the information that is directly relevant to the original query.
            Focus on key facts, dates, events, and developments that answer the query.
            Be concise but preserve all important information.
            Do not add any information that is not in the original snippet.
            """

            # Create user prompt with the search result
            user_prompt = f"""
            Original prompt: {prompt}
            Search query: {query}

            Search result:
            Title: {title}
            Link: {link}
            Snippet: {snippet}

            Please extract and summarize only the information that is directly relevant to the original prompt.
            Focus on key facts, dates, events, and developments.
            Be concise but preserve all important information.
            Your summary should be no more than 3-4 sentences.
            """

            # Call the LLM to summarize the result
            # Use OPENAI_MODEL_LOW for cost efficiency
            params = {
                "model": settings.OPENAI_MODEL_LOW,  # Use a smaller model for summarization
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            }

            # Make the API call
            response = self.client.chat.completions.create(**params)

            # Extract the summary from the response
            summary = response.choices[0].message.content.strip()

            # Create a new result with the summary
            summarized_result = {
                'title': title,
                'link': link,
                'original_snippet': snippet,
                'summary': summary,
                'snippet': summary  # Add the summary as snippet to maintain compatibility with the model
            }

            logger.info(f"Summarized result: {title[:30]}...")
            return summarized_result

        except Exception as e:
            logger.error(f"Error summarizing search result: {e}")
            # Return the original result if summarization fails
            return result

    def generate_report(self, prompt: str, all_search_results: List[Dict[str, Any]]) -> str:
        """
        Generate a user-friendly presentation of search results using summarized content
        """
        try:
            # Check if we have any search results
            if not all_search_results:
                logger.warning("No search results provided to generate_report")
                return "No search results were found for your query. Please try a different search term or search provider."

            # Log the search results for debugging
            logger.info(f"Generating report for prompt: {prompt}")
            logger.info(f"Number of search result steps: {len(all_search_results)}")

            # Format all search results for the LLM
            formatted_results = ""
            total_results = 0

            for i, step in enumerate(all_search_results):
                query = step.get('query', 'N/A')
                results = step.get('results', [])

                logger.info(f"Search Query {i+1}: {query} - Number of results: {len(results)}")

                formatted_results += f"Search Query {i+1}: {query}\n"

                if not results:
                    formatted_results += "  No results found for this query.\n\n"
                    continue

                total_results += len(results)

                for j, result in enumerate(results):
                    formatted_results += f"  Result {j+1}:\n"

                    # Use the summary if available, otherwise use the original snippet
                    title = result.get('title', 'N/A')
                    link = result.get('link', 'N/A')

                    # Check if this result has been summarized
                    if 'summary' in result:
                        content = result.get('summary', 'N/A')
                        formatted_results += f"  Title: {title}\n"
                        formatted_results += f"  Link: {link}\n"
                        formatted_results += f"  Summary: {content}\n\n"
                    else:
                        # If not summarized, use the original snippet
                        snippet = result.get('snippet', 'N/A')
                        formatted_results += f"  Title: {title}\n"
                        formatted_results += f"  Link: {link}\n"
                        formatted_results += f"  Snippet: {snippet}\n\n"

            # If we have no actual results across all queries
            if total_results == 0:
                logger.warning("No actual search results found in any query")
                return "Search was performed but no results were found. Please try different search terms or a different search provider."

            # Log the formatted results for debugging (truncated to avoid excessive logging)
            logger.info(f"Formatted results preview (first 500 chars): {formatted_results[:500]}...")

            messages = [
                {"role": "system", "content": "You are an AI assistant that organizes search results in a user-friendly format. Your task is to create a comprehensive report that answers the original prompt based on the search results provided. The search results have already been summarized to extract the most relevant information. Organize the information in a logical structure with clear headings and sections. Combine related information from different sources. Include proper citations to the sources. Do not add any significant information that is not in the search results."},
                {"role": "user", "content": f"Original prompt: {prompt}\n\nSearch results:\n{formatted_results}\n\nPlease create a comprehensive report that answers the original prompt based on these search results. Organize the information in a logical structure with clear headings and sections. Combine related information from different sources. Include proper citations to the sources."}
            ]

            # Set base parameters
            params = {
                "model": self.model,
                "messages": messages
            }

            # Add model-specific parameters
            if self.model.startswith("o4-"):
                # o4 models don't support temperature parameter
                pass
            else:
                params["temperature"] = 0.3  # Lower temperature for more deterministic output

            response = self.client.chat.completions.create(**params)

            report_content = response.choices[0].message.content

            # Log a preview of the generated report
            logger.info(f"Generated report preview (first 500 chars): {report_content[:500]}...")

            return report_content
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"Error in generate_report: {str(e)}")
            logger.error(f"Traceback: {error_trace}")

            # 오류 유형에 따른 상세 로깅
            if "maximum context length" in str(e).lower():
                logger.error(f"Context length exceeded. Formatted results length: {len(formatted_results)}")
                logger.error(f"Total tokens in messages: approximately {len(str(messages)) / 4} tokens")
                return f"Error generating report: The search results are too large to process. Please try a more specific query or use fewer search terms."

            return f"Error generating report: {str(e)}"

    async def generate_report_stream(self, prompt: str, all_search_results: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        """
        Generate a comprehensive report based on search results with streaming response
        Yields chunks of the report as they are generated
        """
        try:
            logger.info(f"Generating streaming report for prompt: {prompt}")
            logger.info(f"Number of search result steps: {len(all_search_results)}")

            # Format the search results for the LLM
            formatted_results = ""
            for i, step in enumerate(all_search_results):
                query = step.get("query", "Unknown query")
                results = step.get("results", [])

                formatted_results += f"\n\nSEARCH QUERY {i+1}: {query}\n"
                formatted_results += f"Number of results: {len(results)}\n\n"

                for j, result in enumerate(results):
                    title = result.get("title", "No title")
                    link = result.get("link", "No link")
                    snippet = result.get("snippet", "No content")

                    formatted_results += f"Result {j+1}:\n"
                    formatted_results += f"Title: {title}\n"
                    formatted_results += f"URL: {link}\n"
                    formatted_results += f"Content: {snippet}\n\n"

            logger.info(f"Formatted {len(all_search_results)} search steps with a total of {sum(len(step.get('results', [])) for step in all_search_results)} results")

            # Create the messages for the LLM
            messages = [
                {
                    "role": "system",
                    "content": """You are a helpful research assistant that generates comprehensive reports based on search results.
                    Your task is to analyze the search results and create a well-structured, informative report that addresses the user's query.
                    Include relevant information from the search results and cite your sources.
                    Format your report with clear sections, bullet points where appropriate, and a conclusion.
                    Do not include any personal opinions or information not found in the search results."""
                },
                {
                    "role": "user",
                    "content": f"""Please generate a comprehensive report based on the following search query and results:

USER QUERY: {prompt}

SEARCH RESULTS:
{formatted_results}

Create a well-structured report that addresses the query comprehensively. Include all relevant information from the search results.
Format the report with clear sections, headings, and bullet points where appropriate.
Cite sources by referring to the titles or URLs of the search results.
End with a conclusion that summarizes the key findings."""
                }
            ]

            # Set base parameters
            params = {
                "model": self.model,
                "messages": messages,
                "stream": True  # Enable streaming
            }

            # Add model-specific parameters
            if self.model.startswith("o4-"):
                # o4 models don't support temperature parameter
                pass
            else:
                params["temperature"] = 0.3  # Lower temperature for more deterministic output

            # Create a streaming completion
            stream = await self.async_client.chat.completions.create(**params)

            # Process the stream
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield content

        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"Error in generate_report_stream: {str(e)}")
            logger.error(f"Traceback: {error_trace}")

            # 오류 유형에 따른 상세 로깅
            if "maximum context length" in str(e).lower():
                logger.error(f"Context length exceeded. Formatted results length: {len(formatted_results)}")
                logger.error(f"Total tokens in messages: approximately {len(str(messages)) / 4} tokens")
                yield f"Error generating report: The search results are too large to process. Please try a more specific query or use fewer search terms."
            else:
                yield f"Error generating report: {str(e)}"
