from typing import List, Dict, Any, Optional, AsyncGenerator
import logging
import traceback
import asyncio
from app.services.llm_service import LLMService
from app.services.search_service import SearchService
from app.models.schemas import AgentResponse, AgentSearchStep, StreamingSearchResponse
from app.core.config import settings

# 로깅 레벨 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class AgentService:
    def __init__(self):
        self.llm_service = LLMService()
        self.search_service = SearchService()
        self.max_search_iterations = 3  # Limit the number of search iterations

    async def process_prompt_stream(self, prompt: str, search_provider_override: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process a user prompt through the search agent workflow with streaming response
        Yields events as they occur for real-time updates
        """
        try:
            logger.info(f"Processing prompt with streaming: {prompt}")
            if search_provider_override:
                logger.info(f"Using search provider override: {search_provider_override}")

            # Yield initial event
            yield {
                "event": "status",
                "data": {"message": "Decomposing prompt into search queries..."}
            }

            # Step 1: Decompose the prompt into search queries
            search_queries = self.llm_service.decompose_prompt(prompt)
            logger.info(f"Decomposed into {len(search_queries)} search queries: {search_queries}")

            # Yield decomposed queries event
            yield {
                "event": "decomposed_queries",
                "data": {"queries": search_queries}
            }

            # Step 2: Perform searches and evaluate results
            search_steps = []
            all_search_results = []

            # Create a temporary search service with the overridden provider if specified
            search_service = self.search_service
            if search_provider_override:
                # Create a new search service with the overridden provider
                temp_search_service = SearchService()
                temp_search_service.search_provider = search_provider_override
                search_service = temp_search_service
                logger.info(f"Created search service with provider: {search_provider_override}")

            for i, query in enumerate(search_queries):
                # Yield search query event
                yield {
                    "event": "search_query",
                    "data": {
                        "query": query,
                        "index": i,
                        "total": len(search_queries)
                    }
                }

                logger.info(f"Executing search query {i+1}/{len(search_queries)}: {query}")

                # Perform search with the appropriate search service
                results = await search_service.search(query)
                logger.info(f"Search returned {len(results)} results for query: {query}")

                # Yield search results event
                yield {
                    "event": "search_results",
                    "data": {
                        "query": query,
                        "count": len(results),
                        "results": results[:3]  # Send preview of first 3 results
                    }
                }

                # Log the first result as a sample (if available)
                if results:
                    first_result = results[0]
                    logger.debug(f"Sample result - Title: {first_result.get('title', 'N/A')[:30]}..., Link: {first_result.get('link', 'N/A')[:30]}...")

                    # Yield summarization start event
                    yield {
                        "event": "status",
                        "data": {"message": f"Summarizing {len(results)} results for query: {query}"}
                    }

                    # Summarize each search result to extract relevant information
                    summarized_results = []
                    for j, result in enumerate(results):
                        # Yield progress event
                        if j % 2 == 0:  # Only send every other update to reduce traffic
                            yield {
                                "event": "summarize_progress",
                                "data": {
                                    "current": j + 1,
                                    "total": len(results),
                                    "query": query
                                }
                            }

                        # Use the LLM service to summarize each result
                        summarized_result = self.llm_service.summarize_search_result(prompt, query, result)
                        summarized_results.append(summarized_result)

                    # Replace the original results with summarized ones
                    results = summarized_results
                    logger.info(f"Summarized {len(results)} results for query: {query}")

                    # Yield summarization complete event
                    yield {
                        "event": "summarize_complete",
                        "data": {
                            "query": query,
                            "count": len(results)
                        }
                    }
                else:
                    logger.warning(f"No results found for query: {query}")

                    # Yield no results event
                    yield {
                        "event": "no_results",
                        "data": {"query": query}
                    }

                # Evaluate if results are sufficient
                yield {
                    "event": "status",
                    "data": {"message": f"Evaluating search results for query: {query}"}
                }

                evaluation = self.llm_service.evaluate_search_results(prompt, results)
                logger.info(f"Evaluation for query '{query}': Sufficient={evaluation.get('sufficient', False)}")

                # Record this search step
                step = AgentSearchStep(
                    query=query,
                    results=results,
                    sufficient=evaluation.get("sufficient", False),
                    reasoning=evaluation.get("reasoning", "")
                )
                search_steps.append(step)
                all_search_results.append({
                    "query": query,
                    "results": results
                })

                # Yield evaluation event
                yield {
                    "event": "evaluation",
                    "data": {
                        "query": query,
                        "sufficient": evaluation.get("sufficient", False),
                        "reasoning": evaluation.get("reasoning", "")[:200]  # Truncate reasoning for the event
                    }
                }

                # If we have sufficient results, we can stop searching
                if evaluation.get("sufficient", False):
                    logger.info(f"Found sufficient results with query: {query}")
                    yield {
                        "event": "status",
                        "data": {"message": f"Found sufficient results with query: {query}"}
                    }
                    break

            # Step 3: If we don't have sufficient results after initial queries,
            # try additional queries suggested by the LLM
            iteration = 0
            while iteration < self.max_search_iterations:
                # Check if any step was sufficient
                if any(step.sufficient for step in search_steps):
                    logger.info("At least one search step was sufficient, stopping iterations")
                    yield {
                        "event": "status",
                        "data": {"message": "At least one search step was sufficient, stopping iterations"}
                    }
                    break

                # Get the last evaluation
                all_results_flat = [result for step in all_search_results for result in step.get("results", [])]
                logger.info(f"Evaluating all {len(all_results_flat)} results collected so far")

                yield {
                    "event": "status",
                    "data": {"message": f"Evaluating all {len(all_results_flat)} results collected so far"}
                }

                last_evaluation = self.llm_service.evaluate_search_results(
                    prompt,
                    all_results_flat
                )

                # If the evaluation says we have sufficient results, break
                if last_evaluation.get("sufficient", False):
                    logger.info("Combined results are sufficient, stopping iterations")
                    yield {
                        "event": "status",
                        "data": {"message": "Combined results are sufficient, stopping iterations"}
                    }
                    break

                # Get additional queries
                additional_queries = last_evaluation.get("additional_queries", [])
                if not additional_queries:
                    logger.info("No additional queries suggested, stopping iterations")
                    yield {
                        "event": "status",
                        "data": {"message": "No additional queries suggested, stopping iterations"}
                    }
                    break

                logger.info(f"Iteration {iteration+1}: LLM suggested {len(additional_queries)} additional queries")
                yield {
                    "event": "additional_queries",
                    "data": {
                        "iteration": iteration + 1,
                        "queries": additional_queries
                    }
                }

                # Perform additional searches
                for j, query in enumerate(additional_queries):
                    logger.info(f"Executing additional query {j+1}: {query}")
                    yield {
                        "event": "search_query",
                        "data": {
                            "query": query,
                            "index": j,
                            "total": len(additional_queries),
                            "additional": True
                        }
                    }

                    # Use the same search service as before (with override if specified)
                    results = await search_service.search(query)
                    logger.info(f"Additional search returned {len(results)} results for query: {query}")

                    yield {
                        "event": "search_results",
                        "data": {
                            "query": query,
                            "count": len(results),
                            "results": results[:3],  # Send preview of first 3 results
                            "additional": True
                        }
                    }

                    # Summarize each search result to extract relevant information
                    if results:
                        yield {
                            "event": "status",
                            "data": {"message": f"Summarizing {len(results)} results for additional query: {query}"}
                        }

                        summarized_results = []
                        for k, result in enumerate(results):
                            # Yield progress event
                            if k % 2 == 0:  # Only send every other update to reduce traffic
                                yield {
                                    "event": "summarize_progress",
                                    "data": {
                                        "current": k + 1,
                                        "total": len(results),
                                        "query": query,
                                        "additional": True
                                    }
                                }

                            # Use the LLM service to summarize each result
                            summarized_result = self.llm_service.summarize_search_result(prompt, query, result)
                            summarized_results.append(summarized_result)

                        # Replace the original results with summarized ones
                        results = summarized_results
                        logger.info(f"Summarized {len(results)} results for additional query: {query}")

                        yield {
                            "event": "summarize_complete",
                            "data": {
                                "query": query,
                                "count": len(results),
                                "additional": True
                            }
                        }

                    evaluation = self.llm_service.evaluate_search_results(prompt, results)
                    logger.info(f"Evaluation for additional query '{query}': Sufficient={evaluation.get('sufficient', False)}")

                    step = AgentSearchStep(
                        query=query,
                        results=results,
                        sufficient=evaluation.get("sufficient", False),
                        reasoning=evaluation.get("reasoning", "")
                    )
                    search_steps.append(step)
                    all_search_results.append({
                        "query": query,
                        "results": results
                    })

                    yield {
                        "event": "evaluation",
                        "data": {
                            "query": query,
                            "sufficient": evaluation.get("sufficient", False),
                            "reasoning": evaluation.get("reasoning", "")[:200],  # Truncate reasoning for the event
                            "additional": True
                        }
                    }

                    if evaluation.get("sufficient", False):
                        logger.info(f"Found sufficient results with additional query: {query}")
                        yield {
                            "event": "status",
                            "data": {"message": f"Found sufficient results with additional query: {query}"}
                        }
                        break

                iteration += 1

            # Step 4: Generate the final report
            logger.info(f"Generating final report based on {len(all_search_results)} search steps")
            yield {
                "event": "status",
                "data": {"message": f"Generating final report based on {len(all_search_results)} search steps"}
            }

            # Check if we have any results at all
            total_results = sum(len(step.get("results", [])) for step in all_search_results)
            logger.info(f"Total search results collected: {total_results}")

            if total_results == 0:
                logger.warning("No search results found for any query")
                final_report = "No search results were found for your queries. Please try different search terms or a different search provider."
                yield {
                    "event": "report",
                    "data": {"content": final_report}
                }
            else:
                try:
                    # Use streaming report generation
                    async for chunk in self.llm_service.generate_report_stream(prompt, all_search_results):
                        yield {
                            "event": "report_chunk",
                            "data": {"content": chunk}
                        }

                except Exception as report_error:
                    error_trace = traceback.format_exc()
                    logger.error(f"Error generating report: {str(report_error)}")
                    logger.error(f"Traceback: {error_trace}")

                    # 오류 유형에 따른 상세 메시지
                    if "maximum context length" in str(report_error).lower():
                        logger.error(f"Context length exceeded. Total results: {total_results}")
                        error_message = "Error: The search results are too large to process. Please try a more specific query or use fewer search terms."
                    else:
                        error_message = f"Error generating report: {str(report_error)}"

                    yield {
                        "event": "error",
                        "data": {"message": error_message}
                    }

            # Collect all sources
            sources = []
            for step in all_search_results:
                for result in step.get("results", []):
                    if result not in sources:
                        sources.append(result)

            logger.info(f"Collected {len(sources)} unique sources")
            yield {
                "event": "sources",
                "data": {"sources": sources}
            }

        except Exception as e:
            logger.error(f"Error in process_prompt_stream: {str(e)}", exc_info=True)
            yield {
                "event": "error",
                "data": {"message": f"Error processing prompt: {str(e)}"}
            }

    async def process_prompt(self, prompt: str, search_provider_override: Optional[str] = None) -> AgentResponse:
        """
        Process a user prompt through the search agent workflow
        """
        try:
            logger.info(f"Processing prompt: {prompt}")
            if search_provider_override:
                logger.info(f"Using search provider override: {search_provider_override}")

            # Step 1: Decompose the prompt into search queries
            search_queries = self.llm_service.decompose_prompt(prompt)
            logger.info(f"Decomposed into {len(search_queries)} search queries: {search_queries}")

            # Step 2: Perform searches and evaluate results
            search_steps = []
            all_search_results = []

            # Create a temporary search service with the overridden provider if specified
            search_service = self.search_service
            if search_provider_override:
                # Create a new search service with the overridden provider
                temp_search_service = SearchService()
                temp_search_service.search_provider = search_provider_override
                search_service = temp_search_service
                logger.info(f"Created search service with provider: {search_provider_override}")

            for i, query in enumerate(search_queries):
                logger.info(f"Executing search query {i+1}/{len(search_queries)}: {query}")

                # Perform search with the appropriate search service
                results = await search_service.search(query)
                logger.info(f"Search returned {len(results)} results for query: {query}")

                # Log the first result as a sample (if available)
                if results:
                    first_result = results[0]
                    logger.debug(f"Sample result - Title: {first_result.get('title', 'N/A')[:30]}..., Link: {first_result.get('link', 'N/A')[:30]}...")

                    # Summarize each search result to extract relevant information
                    summarized_results = []
                    for result in results:
                        # Use the LLM service to summarize each result
                        summarized_result = self.llm_service.summarize_search_result(prompt, query, result)
                        summarized_results.append(summarized_result)

                    # Replace the original results with summarized ones
                    results = summarized_results
                    logger.info(f"Summarized {len(results)} results for query: {query}")
                else:
                    logger.warning(f"No results found for query: {query}")

                # Evaluate if results are sufficient
                evaluation = self.llm_service.evaluate_search_results(prompt, results)
                logger.info(f"Evaluation for query '{query}': Sufficient={evaluation.get('sufficient', False)}")

                # Record this search step
                step = AgentSearchStep(
                    query=query,
                    results=results,
                    sufficient=evaluation.get("sufficient", False),
                    reasoning=evaluation.get("reasoning", "")
                )
                search_steps.append(step)
                all_search_results.append({
                    "query": query,
                    "results": results
                })

                # If we have sufficient results, we can stop searching
                if evaluation.get("sufficient", False):
                    logger.info(f"Found sufficient results with query: {query}")
                    break

            # Step 3: If we don't have sufficient results after initial queries,
            # try additional queries suggested by the LLM
            iteration = 0
            while iteration < self.max_search_iterations:
                # Check if any step was sufficient
                if any(step.sufficient for step in search_steps):
                    logger.info("At least one search step was sufficient, stopping iterations")
                    break

                # Get the last evaluation
                all_results_flat = [result for step in all_search_results for result in step.get("results", [])]
                logger.info(f"Evaluating all {len(all_results_flat)} results collected so far")

                last_evaluation = self.llm_service.evaluate_search_results(
                    prompt,
                    all_results_flat
                )

                # If the evaluation says we have sufficient results, break
                if last_evaluation.get("sufficient", False):
                    logger.info("Combined results are sufficient, stopping iterations")
                    break

                # Get additional queries
                additional_queries = last_evaluation.get("additional_queries", [])
                if not additional_queries:
                    logger.info("No additional queries suggested, stopping iterations")
                    break

                logger.info(f"Iteration {iteration+1}: LLM suggested {len(additional_queries)} additional queries")

                # Perform additional searches
                for j, query in enumerate(additional_queries):  # No limit on additional queries
                    logger.info(f"Executing additional query {j+1}: {query}")

                    # Use the same search service as before (with override if specified)
                    results = await search_service.search(query)
                    logger.info(f"Additional search returned {len(results)} results for query: {query}")

                    # Summarize each search result to extract relevant information
                    if results:
                        summarized_results = []
                        for result in results:
                            # Use the LLM service to summarize each result
                            summarized_result = self.llm_service.summarize_search_result(prompt, query, result)
                            summarized_results.append(summarized_result)

                        # Replace the original results with summarized ones
                        results = summarized_results
                        logger.info(f"Summarized {len(results)} results for additional query: {query}")

                    evaluation = self.llm_service.evaluate_search_results(prompt, results)
                    logger.info(f"Evaluation for additional query '{query}': Sufficient={evaluation.get('sufficient', False)}")

                    step = AgentSearchStep(
                        query=query,
                        results=results,
                        sufficient=evaluation.get("sufficient", False),
                        reasoning=evaluation.get("reasoning", "")
                    )
                    search_steps.append(step)
                    all_search_results.append({
                        "query": query,
                        "results": results
                    })

                    if evaluation.get("sufficient", False):
                        logger.info(f"Found sufficient results with additional query: {query}")
                        break

                iteration += 1

            # Step 4: Generate the final report
            logger.info(f"Generating final report based on {len(all_search_results)} search steps")

            # Check if we have any results at all
            total_results = sum(len(step.get("results", [])) for step in all_search_results)
            logger.info(f"Total search results collected: {total_results}")

            if total_results == 0:
                logger.warning("No search results found for any query")
                final_report = "No search results were found for your queries. Please try different search terms or a different search provider."
            else:
                try:
                    final_report = self.llm_service.generate_report(prompt, all_search_results)
                    # 보고서가 비어 있는지 확인
                    if not final_report or final_report.strip() == "":
                        logger.warning("Generated report is empty")
                        final_report = "Error: The report generation failed. The search results may be too large to process."
                except Exception as report_error:
                    error_trace = traceback.format_exc()
                    logger.error(f"Error generating report: {str(report_error)}")
                    logger.error(f"Traceback: {error_trace}")

                    # 오류 유형에 따른 상세 메시지
                    if "maximum context length" in str(report_error).lower():
                        logger.error(f"Context length exceeded. Total results: {total_results}")
                        final_report = "Error: The search results are too large to process. Please try a more specific query or use fewer search terms."
                    else:
                        final_report = f"Error generating report: {str(report_error)}"

            # Collect all sources
            sources = []
            for step in all_search_results:
                for result in step.get("results", []):
                    if result not in sources:
                        sources.append(result)

            logger.info(f"Collected {len(sources)} unique sources")

            # Create the response
            response = AgentResponse(
                original_prompt=prompt,
                search_steps=[step.model_dump() for step in search_steps],
                final_report=final_report,
                sources=sources
            )

            return response
        except Exception as e:
            logger.error(f"Error in process_prompt: {str(e)}", exc_info=True)
            # Return a basic response in case of error
            return AgentResponse(
                original_prompt=prompt,
                search_steps=[],
                final_report=f"Error processing prompt: {str(e)}",
                sources=[]
            )
