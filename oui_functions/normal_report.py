#범용 보고서
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
                Analyze the user's question and return the following information in JSON format:
                {
                    "topic": "The main topic of the question",
                    "intent": "Information search, explanation request, comparative analysis, fact checking, etc.",
                    "keywords": ["key", "words", "list"],
                    "preferred_format": "Report, summary, list, step-by-step explanation, etc.",
                    "complexity": "Simple/Medium/Complex - level of question complexity",
                    "needs_search": true/false - whether web search is needed,
                    "needs_expertise": true/false - whether specialized knowledge is required,
                    "preliminary_search_keywords": ["keyword1", "keyword2", "..."]  // Preliminary search keywords for pre-web research
                }
                """
                },
                {"role": "user", "content": f"Please analyze the following question: {user_message}"}
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
            
            # 취합된 검색 결과
            combined_search_result = {
                "docs": combined_docs,
                "urls": combined_urls,
                "keywords": websearch_keywords,
                "type": "combined_web_search"
            }
            
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="웹 검색 결과 취합 완료",
                done=True,
            )
            
            # 계획 생성을 위한 프롬프트 작성
            plan_prompt = [
                {"role": "system", "content": """
                당신은 연구 계획을 수립하는 전문가입니다. 사용자의 질문과 초기 웹 검색 결과를 바탕으로 
                상세한 연구 계획을 JSON 형식으로 작성해주세요:
                
                {
                    "research_plan": {
                        "main_question": "사용자의 주요 질문",
                        "sub_questions": ["세부 질문 1", "세부 질문 2", ...],
                        "research_steps": [
                            {
                                "step": 1,
                                "description": "단계 설명",
                                "search_queries": ["검색어 1", "검색어 2", ...],
                                "expected_outcomes": "이 단계에서 기대되는 결과"
                            },
                            ...
                        ],
                        "information_gaps": ["현재 부족한 정보 1", "현재 부족한 정보 2", ...],
                        "additional_resources_needed": ["추가 필요 자료 1", "추가 필요 자료 2", ...],
                        "estimated_completion_steps": 5
                    }
                }
                
             
                """
                },
                {"role": "user", "content": f"""
                사용자 질문: {user_message}
                
                초기 분석 결과: {json.dumps(analysis_obj, ensure_ascii=False)}
                
                초기 웹 검색 키워드: {websearch_keywords}

                초기 웹 검색 결과: {json.dumps(combined_search_result, ensure_ascii=False)}
                
                검색된 URL 수: {len(combined_urls)}
                검색된 문서 수: {len(combined_docs)}
                
                위 정보를 바탕으로 상세한 연구 계획을 JSON 형식으로 작성해주세요.
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
                message="연구 계획 생성 완료",
                done=True,
            )
            
            print("############################################ 연구 계획 ##############################################")
            print(research_plan)
            print("################################################ 연구 계획 끝 #########################################")

            # 연구 계획 스탭 별 상세 검색 및 개별 보고서 생성
            step_reports = []  # 각 스탭별 보고서를 저장할 리스트
            
            for step in research_plan.get("research_steps", []):
                step_number = step.get("step", "N/A")
                step_description = step.get("description", "")
                step_search_queries = step.get("search_queries", [])
                step_expected_outcomes = step.get("expected_outcomes", "")
                
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"연구 계획 스탭 {step_number}에 대한 상세 검색 및 보고서 작성 시작...",
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
                            "당신은 조사 보고서를 작성하는 전문가입니다. 아래의 정보를 바탕으로 해당 연구 단계에 대한 "
                            "상세 보고서를 작성해주세요. 보고서는 최대한 자세하게 작성되어야 하며, 필요시 3000단어까지 허용됩니다."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"""
연구 단계: {step_number}
단계 설명: {step_description}
검색 키워드: {step_search_queries}
예상 결과: {step_expected_outcomes}

[검색 결과 요약]
{combined_search_text}
                        """
                    }
                ]
                
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"연구 계획 스탭 {step_number}에 대한 보고서 작성 중...",
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
                    message=f"연구 계획 스탭 {step_number} 보고서 작성 완료",
                    done=True,
                )
            
            
            # 모든 스탭의 개별 보고서가 생성된 후 최종 종합 보고서 요청 프롬프트 생성
            combined_step_reports_text = ""
            for step_report in step_reports:
                combined_step_reports_text += f"연구 단계 {step_report['step']} 보고서:\n{step_report['report']}\n\n"
            
            final_report_prompt = [
                {
                    "role": "system",
                    "content": (
                        "당신은 종합 보고서를 작성하는 전문가입니다. 아래에 각 연구 단계에 대한 보고서가 있습니다. "
                        "이를 바탕으로 최종 종합 보고서를 작성해주세요. 보고서는 최대한 자세하게 작성되어야 하며, "
                        "필요시 3000단어까지 허용됩니다."
                    )
                },
                {
                    "role": "user",
                    "content": f"""
사용자의 최초 질문: {user_message}

연구 계획 개요: {json.dumps(research_plan, ensure_ascii=False, indent=2)}

각 연구 단계별 보고서:
{combined_step_reports_text}

위 정보를 바탕으로 사용자의 최초 질문에 대한 종합적이고 상세한 최종 보고서를 작성해주세요.
"""
                }
            ]
            print("############################################ final_report_prompt start ##############################################")
            print(final_report_prompt)
            print("################################################ final_report_prompt end #########################################")
            # 최종 보고서 요청 프롬프트를 body에 저장하여 후속 처리하도록 함
            body["messages"] = final_report_prompt
            
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="최종 보고서 요청 프롬프트 생성 완료",
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

