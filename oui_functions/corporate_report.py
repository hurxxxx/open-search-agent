#기업 분석 보고서
from pydantic import BaseModel, Field
from typing import Callable, Awaitable, Any, Optional, TypedDict, List, Dict, Union
import json
import re

from open_webui.routers.retrieval import process_web_search, SearchForm
from open_webui.utils.middleware import chat_web_search_handler
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.misc import get_last_user_message
from open_webui.models.users import Users, UserModel

# JSON 추출 공통 함수
def extract_json_from_markdown(content: str) -> dict:
    """
    마크다운 형식의 문자열에서 JSON 객체를 추출합니다.
    
    Args:
        content (str): JSON을 포함한 마크다운 문자열
        
    Returns:
        dict: 추출된 JSON 객체, 추출 실패 시 빈 딕셔너리 반환
    """
    try:
        # ```json과 ``` 사이의 내용 추출
        json_match = re.search(r'```(?:json)?\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            # JSON 문자열을 객체로 변환
            return json.loads(json_str)
        else:
            # 일반 텍스트에서 JSON 형식 찾기 시도
            try:
                return json.loads(content)
            except:
                print("JSON 형식을 찾을 수 없습니다.")
                return {}
    except Exception as e:
        print(f"JSON 추출 중 오류 발생: {str(e)}")
        return {}


class Doc(TypedDict):
    # 문서의 실제 내용
    content: str
    # 메타데이터 예시:
    # - source: 문서 출처 URL (예: "https://en.wikipedia.org/wiki/NewJeans")
    # - title: 문서 제목 (예: "NewJeans - Wikipedia") 
    # - language: 문서 언어 코드 (예: "en")
    metadata: Dict[str, Any]

class SearchResultWithDocs(TypedDict):
    status: bool
    collection_name: None
    # filenames: 검색 결과 URL 목록
    filenames: List[str]
    docs: List[Doc]
    loaded_count: int

class SearchResultWithoutDocs(TypedDict):
    status: bool
    collection_name: str
    filenames: List[str]
    loaded_count: int

SearchResult = Union[SearchResultWithDocs, SearchResultWithoutDocs]

async def web_search(request: any, query: str) -> SearchResult:
    request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL = True
    form_data = SearchForm(query=query)
    
    try:
        result = await process_web_search(request, form_data)
        return {
            "docs": result.get("docs", []),
            "name": query,
            "type": "web_search",
            "urls": result["filenames"],
        }
    except Exception as e:
        print(f"웹 검색 중 오류 발생: {str(e)}")
        return {
            "status": False,
            "collection_name": None,
            "filenames": [],
            "loaded_count": 0
        }


class Filter:
    class Valves(BaseModel):
        status: bool = Field(default=True)


    async def emit_status(
        self,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        level: str,
        message: str,
        done: bool,
    ):
        if self.valves.status:
            await __event_emitter__(
                {
                    "type": level,
                    "data": {
                        "description": message,
                        "done": done,
                    },
                }
            )

        
    def __init__(self):
        self.valves = self.Valves()

    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __request__: Any,
        __user__: Optional[dict] = None,
        __model__: Optional[dict] = None,
    ) -> dict:
        try:

            
            user = Users.get_user_by_id(__user__["id"]) if __user__ else None

            messages = body["messages"]
            user_message = get_last_user_message(messages)

            # 사용자 질문 분석 →

            analysis_prompt = [
                {"role": "system", "content": """
                Analyze the user's corporate analysis request and return the following information in JSON format:
                {
                    "company_name": "분석 대상 기업명",
                    "industry": "기업이 속한 산업 분야",
                    "analysis_focus": "재무분석, 경쟁력 분석, 시장 점유율, 성장성, 투자 가치 등 분석 초점",
                    "keywords": ["핵심", "키워드", "목록"],
                    "preferred_format": "보고서, 요약, 목록, 단계별 설명 등",
                    "complexity": "간단/중간/복잡 - 질문의 복잡성 수준",
                    "needs_search": true/false - 웹 검색이 필요한지 여부,
                    "needs_financial_data": true/false - 재무 데이터가 필요한지 여부,
                    "preliminary_search_keywords": ["키워드1", "키워드2", "..."] // 사전 웹 검색을 위한 키워드
                }
                
                Return an empty object ({}) in the following cases:
                1. If a specific company name cannot be identified in the user's question
                2. If the question is not related to corporate analysis or corporate reporting
                3. If it's a general conversation or greeting
                4. If insufficient information is provided for corporate analysis
                5. If the question is about a topic other than corporate analysis
                """
                },
                {"role": "user", "content": f"Please analyze the following corporate analysis request: {user_message}"}
            ]

            analysis_payload = {
                    "model": "o3-mini",
                    "messages": analysis_prompt,
                    "stream": False,
                }

            analysis_response = await generate_chat_completion(
                request=__request__,
                form_data=analysis_payload,
                user=user,
            )
            # analysis_response에서 content 추출
            content = analysis_response.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            # 공통 함수를 사용하여 JSON 객체 추출
            analysis_obj = extract_json_from_markdown(content)
            
            # 빈 객체인 경우 함수 종료
            if not analysis_obj or len(analysis_obj) == 0:
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message="기업 분석을 위한 충분한 정보가 없습니다. 일반 대화 모드로 전환합니다.",
                    done=True,
                )
                return body
            

            websearch_keywords = analysis_obj.get("preliminary_search_keywords", [])

            # 웹 검색 결과를 저장할 리스트
            search_results = []
            
            # 각 키워드에 대한 웹 검색 수행 및 결과 저장
            for keyword in websearch_keywords:
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"키워드 '{keyword}'에 대한 웹 검색 중...",
                    done=False,
                )
                web_search_result = await web_search(__request__, keyword)
                search_results.append(web_search_result)
                
            # 검색 결과 취합
            combined_docs = []
            combined_urls = []
            
            for result in search_results:
                if "docs" in result:
                    combined_docs.extend(result.get("docs", []))
                if "urls" in result:
                    combined_urls.extend(result.get("urls", []))
                    
            # 중복 URL 제거
            combined_urls = list(dict.fromkeys(combined_urls))
            
                   
            # 검색 결과 검증 및 요약 단계 추가
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="검색 결과 검증 및 요약 중...",
                done=False,
            )
            
            # 검색 결과 내용 추출
            search_content = ""
            for doc in combined_docs[:5]:  # 처음 5개 문서만 사용 (너무 길어지지 않도록)
                search_content += doc.get("content", "") + "\n\n"
            
            # 검색 결과 검증 및 요약 프롬프트
            validation_prompt = [
                {"role": "system", "content": """
                You are an expert in validating and summarizing search results for corporate analysis reports.
                Analyze the user's corporate analysis request and web search results to return the following in JSON format:
                
                {
                    "content": "Organized text that can be used for corporate analysis reports, excluding unnecessary text from search results. Please exclude advertisements, duplicate content, irrelevant content, and include only useful information such as company information, financial data, market information, competitor information, etc.",
                }
                
                Return an empty object ({}) in the following cases:
                1. If a specific company cannot be identified from the search results
                2. If the search results are not related to corporate analysis
                3. If the search results are too general or insufficient to write a corporate report
                4. If the search results are about topics other than companies (e.g., general products, services, individuals, etc.)
                5. If it's not an existing company
                6. If there are typos in the company name
                """
                },
                {"role": "user", "content": f"""
                User's corporate analysis request: {user_message}
                                                                
                Sample search result content:
                {search_content[:5000] if len(search_content) > 5000 else search_content}
                
                Based on the above information, please verify if the search results are suitable for writing a corporate analysis report and summarize the key content for use in the Plan.
                """}
            ]
            
            # 검증 및 요약 요청
            validation_payload = {
                "model": "o3-mini",
                "messages": validation_prompt,
                "stream": False,
            }
            
            validation_response = await generate_chat_completion(
                request=__request__,
                form_data=validation_payload,
                user=user,
            )
            
            # 검증 응답에서 content 추출
            validation_content = validation_response.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            # JSON 객체 추출
            validation_obj = extract_json_from_markdown(validation_content)
            
            # 검증 결과가 유효하지 않은 경우 함수 종료
            if not validation_obj or len(validation_obj) == 0:
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message="기업 분석을 위한 충분한 정보가 없습니다. 일반 대화 모드로 전환합니다.",
                    done=True,
                )
                return body
            
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="검색 결과 검증 및 요약 완료",
                done=True,
            )
            
            # 계획 생성을 위한 프롬프트 작성
            plan_prompt = [
                {"role": "system", "content": """
                You are an expert in developing corporate analysis plans. Based on the user's corporate analysis request and initial web search results,
                please create a detailed corporate analysis plan in JSON format:
                
                {
                    "analysis_plan": {
                        "company_name": "분석 대상 기업명",
                        "industry": "기업이 속한 산업 분야",
                        "main_question": "사용자의 주요 질문",
                        "analysis_sections": ["기업 개요", "산업 분석", "재무 분석", "경쟁사 분석", "SWOT 분석", "미래 전망", "투자 의견"],
                        "research_steps": [
                            {
                                "step": 1,
                                "description": "단계 설명 (예: 기업 기본 정보 수집)",
                                "search_queries": ["검색어 1", "검색어 2", ...],
                                "expected_outcomes": "이 단계에서 기대되는 결과"
                            },
                            ...
                        ],
                        "required_financial_data": ["Revenue", "Operating Profit", "Net Profit", "Debt Ratio", "ROE", ...],
                        "required_market_data": ["Market Size", "Market Share", "Competitor Status", ...],
                        "information_gaps": ["Currently missing information 1", "Currently missing information 2", ...],
                        "estimated_completion_steps": 5
                    }
                }
                """
                },
                {"role": "user", "content": f"""
                Corporate analysis request: {user_message}
                
                Initial analysis results: {json.dumps(analysis_obj, ensure_ascii=False)}
                
                Initial web search keywords: {websearch_keywords}

                Initial web search summary: {json.dumps(validation_obj, ensure_ascii=False)}
                
                Based on the above information, please create a detailed corporate analysis plan in JSON format.
                """}
            ]
            
            # 계획 생성 요청
            plan_payload = {
                "model": "o3-mini",
                "messages": plan_prompt,
                "stream": False,
            }
            
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="연구 계획 생성 중...",
                done=False,
            )
            
            plan_response = await generate_chat_completion(
                request=__request__,
                form_data=plan_payload,
                user=user,
            )
            
            # 계획 응답에서 content 추출
            plan_content = plan_response.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            # JSON 객체 추출
            research_plan = extract_json_from_markdown(plan_content)
            
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="기업 분석 계획 생성 완료",
                done=True,
            )
            
            print("############################################ 기업 분석 계획 ##############################################")
            print(research_plan)
            print("################################################ 기업 분석 계획 끝 #########################################")

            # 분석 계획 스탭 별 상세 검색 및 개별 보고서 생성
            step_reports = []  # 각 스탭별 보고서를 저장할 리스트
            
            for step in research_plan.get("analysis_plan", {}).get("research_steps", []):
                step_number = step.get("step", "N/A")
                step_description = step.get("description", "")
                step_search_queries = step.get("search_queries", [])
                step_expected_outcomes = step.get("expected_outcomes", "")
                
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"기업 분석 계획 스탭 {step_number}에 대한 상세 검색 및 보고서 작성 시작...",
                    done=False,
                )
                
                # 각 스탭의 검색 결과 취합
                step_combined_docs = []
                step_combined_urls = []
                for query in step_search_queries:
                    await self.emit_status(
                        __event_emitter__,
                        level="status",
                        message=f"스탭 {step_number}: 키워드 '{query}' 웹 검색 중...",
                        done=False,
                    )
                    search_result = await web_search(__request__, query)
                    if search_result:
                        if "docs" in search_result:
                            step_combined_docs.extend(search_result.get("docs", []))
                        if "urls" in search_result:
                            step_combined_urls.extend(search_result.get("urls", []))
                
                # 중복 URL 제거
                step_combined_urls = list(dict.fromkeys(step_combined_urls))
                
                # 검색 결과의 요약 텍스트 생성 (docs의 content를 간단히 결합)
                combined_search_text = ""
                for doc in step_combined_docs:
                    combined_search_text += doc.get("content", "") + "\n"
                if step_combined_urls:
                    combined_search_text += "\n관련 URL: " + ", ".join(step_combined_urls)
                
                # 스탭별 보고서 생성을 위한 프롬프트 구성
                step_prompt = [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert in writing corporate analysis reports. Based on the information below, please write a detailed "
                            "report for this analysis step. The report should be objective and detailed, based on facts, "
                            "and up to 3000 words if necessary. Financial data, market data, competitor information, etc. should include "
                            "accurate figures and sources as much as possible."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"""
Company Name: {research_plan.get("analysis_plan", {}).get("company_name", "Not specified")}
Industry: {research_plan.get("analysis_plan", {}).get("industry", "Not specified")}
Analysis Step: {step_number}
Step Description: {step_description}
Search Keywords: {step_search_queries}
Expected Outcomes: {step_expected_outcomes}

[Search Results Summary]
{combined_search_text}
                        """
                    }
                ]
                
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"기업 분석 계획 스탭 {step_number}에 대한 보고서 작성 중...",
                    done=False,
                )
                
                # LLM을 통해 스탭별 보고서 생성 요청
                step_report_response = await generate_chat_completion(
                    request=__request__,
                    form_data={
                        "model": "o3-mini",
                        "messages": step_prompt,
                        "stream": False,
                    },
                    user=user,
                )
                
                step_report_content = step_report_response.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # 개별 스탭 보고서 저장
                step_reports.append({
                    "step": step_number,
                    "report": step_report_content,
                })
                
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"기업 분석 계획 스탭 {step_number} 보고서 작성 완료",
                    done=True,
                )
            
            
            # 모든 스탭의 개별 보고서가 생성된 후 최종 종합 보고서 요청 프롬프트 생성
            combined_step_reports_text = ""
            for step_report in step_reports:
                combined_step_reports_text += f"분석 단계 {step_report['step']} 보고서:\n{step_report['report']}\n\n"
            
            final_report_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are an expert in writing comprehensive corporate analysis reports. Below are reports for each analysis step. "
                        "Based on these, please write a final comprehensive corporate analysis report. The report should follow this structure:\n\n"
                        "1. Executive Summary: Briefly summarize key analysis results and investment opinions\n"
                        "2. Company Overview: Company history, business areas, main products/services, management, etc.\n"
                        "3. Industry Analysis: Current status, trends, growth potential, regulatory environment, etc. of the industry\n"
                        "4. Financial Analysis: Analysis of key financial indicators such as sales, profits, growth rate, profitability, debt ratio, etc.\n"
                        "5. Competitor Analysis: Comparison with major competitors, market share, competitive advantages, etc.\n"
                        "6. SWOT Analysis: Analysis of strengths, weaknesses, opportunities, and threats\n"
                        "7. Future Outlook: Company growth strategy, new businesses, risk factors, etc.\n"
                        "8. Investment Opinion: Investment recommendation, target price, investment risks, etc.\n\n"
                        "The report should be objective and detailed, based on facts, and all figures and claims should include sources when possible. "
                        "Up to 4000 words are allowed if necessary.\n\n"
                        "**IMPORTANT**: You MUST write the final report in the SAME LANGUAGE as the user's original request. "
                        "If the user's request is in Korean, write the entire report in Korean. "
                        "If the user's request is in English, write the entire report in English. "
                        "Match the language of the user's original input exactly."
                    )
                },
                {
                    "role": "user",
                    "content": f"""
User's corporate analysis request: {user_message}

Corporate Analysis Plan Overview: {json.dumps(research_plan, ensure_ascii=False, indent=2)}

Reports for each analysis step:
{combined_step_reports_text}

Based on the above information, please write a comprehensive and detailed final corporate analysis report in response to the user's request.

**IMPORTANT**: Your final report MUST be written in the SAME LANGUAGE as my original request above. Match the language I used in my request.
"""
                }
            ]
          
            # 최종 보고서 요청 프롬프트를 body에 저장하여 후속 처리하도록 함
            body["messages"] = final_report_prompt
            
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="최종 기업 분석 보고서 요청 프롬프트 생성 완료",
                done=True,
            )
            
                    
       
        except Exception as e:
            print(f"오류 발생: {str(e)}")
            print(f"오류 상세 정보:")
            print(f"오류 유형: {type(e).__name__}")
            print(f"오류 발생 위치: {e.__traceback__.tb_frame.f_code.co_filename}:{e.__traceback__.tb_lineno}")
            print(f"오류 상세 메시지: {str(e)}")
            
            # 스택 트레이스 출력
            import traceback
            print("스택 트레이스:")
            print(''.join(traceback.format_tb(e.__traceback__)))
            
        return body

