from typing import List, Dict, Any, Optional
import logging
from app.services.llm_service import LLMService
from app.services.search_service import SearchService
from app.models.schemas import AgentResponse, AgentSearchStep
from app.core.config import settings

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(self):
        self.llm_service = LLMService()
        self.search_service = SearchService()
        self.max_search_iterations = 3  # Limit the number of search iterations

    async def process_prompt(self, prompt: str, search_provider_override: Optional[str] = None) -> AgentResponse:
        """
        Process a user prompt through the search agent workflow
        """
        try:
            # Step 1: Decompose the prompt into search queries
            search_queries = self.llm_service.decompose_prompt(prompt)

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
                logger.info(f"Using overridden search provider: {search_provider_override}")

            for query in search_queries:
                # Perform search with the appropriate search service
                results = await search_service.search(query)

                # Evaluate if results are sufficient
                evaluation = self.llm_service.evaluate_search_results(prompt, results)

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
                    break

            # Step 3: If we don't have sufficient results after initial queries,
            # try additional queries suggested by the LLM
            iteration = 0
            while iteration < self.max_search_iterations:
                # Check if any step was sufficient
                if any(step.sufficient for step in search_steps):
                    break

                # Get the last evaluation
                last_evaluation = self.llm_service.evaluate_search_results(
                    prompt,
                    [result for step in all_search_results for result in step.get("results", [])]
                )

                # If the evaluation says we have sufficient results, break
                if last_evaluation.get("sufficient", False):
                    break

                # Get additional queries
                additional_queries = last_evaluation.get("additional_queries", [])
                if not additional_queries:
                    break

                # Perform additional searches
                for query in additional_queries[:2]:  # Limit to 2 additional queries per iteration
                    # Use the same search service as before (with override if specified)
                    results = await search_service.search(query)

                    evaluation = self.llm_service.evaluate_search_results(prompt, results)

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
                        break

                iteration += 1

            # Step 4: Generate the final report
            final_report = self.llm_service.generate_report(prompt, all_search_results)

            # Collect all sources
            sources = []
            for step in all_search_results:
                for result in step.get("results", []):
                    if result not in sources:
                        sources.append(result)

            # Create the response
            response = AgentResponse(
                original_prompt=prompt,
                search_steps=[step.model_dump() for step in search_steps],
                final_report=final_report,
                sources=sources
            )

            return response
        except Exception as e:
            logger.error(f"Error in process_prompt: {str(e)}")
            # Return a basic response in case of error
            return AgentResponse(
                original_prompt=prompt,
                search_steps=[],
                final_report=f"Error processing prompt: {str(e)}",
                sources=[]
            )
