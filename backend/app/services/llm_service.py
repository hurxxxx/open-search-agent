from typing import List, Dict, Any
import json
import logging
from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4"  # Default model

    def decompose_prompt(self, prompt: str) -> List[str]:
        """
        Decompose a user prompt into multiple search queries
        """
        try:
            messages = [
                {"role": "system", "content": "You are an AI assistant that helps decompose complex questions into simpler search queries. Your task is to analyze the user's prompt and generate a list of search queries that would help gather information to answer the prompt comprehensively."},
                {"role": "user", "content": f"Please decompose the following prompt into 3-5 search queries that would help gather information to answer it: '{prompt}'"}
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )
            
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
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            
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

    def generate_report(self, prompt: str, all_search_results: List[Dict[str, Any]]) -> str:
        """
        Generate a comprehensive report based on the search results
        """
        try:
            # Format all search results for the LLM
            formatted_results = ""
            for i, step in enumerate(all_search_results):
                formatted_results += f"Search Query {i+1}: {step.get('query', 'N/A')}\n"
                for j, result in enumerate(step.get('results', [])):
                    formatted_results += f"  Result {j+1}:\n"
                    formatted_results += f"  Title: {result.get('title', 'N/A')}\n"
                    formatted_results += f"  Link: {result.get('link', 'N/A')}\n"
                    formatted_results += f"  Snippet: {result.get('snippet', 'N/A')}\n\n"
            
            messages = [
                {"role": "system", "content": "You are an AI assistant that generates comprehensive reports based on search results. Your task is to synthesize the information from multiple search results to provide a detailed answer to the user's original prompt. Include citations to the sources in your report."},
                {"role": "user", "content": f"Original prompt: {prompt}\n\nSearch results:\n{formatted_results}\n\nPlease generate a comprehensive report that answers the original prompt based on these search results. Include citations to the sources."}
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=2000
            )
            
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error in generate_report: {str(e)}")
            return f"Error generating report: {str(e)}"
