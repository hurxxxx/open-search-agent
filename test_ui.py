#!/usr/bin/env python3
"""
UI 테스트 스크립트 - 스트리밍 검색 기능 테스트
"""

import asyncio
import time
from playwright.async_api import async_playwright

async def test_streaming_search():
    """스트리밍 검색 기능을 테스트합니다."""
    async with async_playwright() as p:
        # 브라우저 시작
        browser = await p.chromium.launch(headless=False)  # headless=False로 설정하여 브라우저 창을 볼 수 있게 함
        context = await browser.new_context()
        page = await context.new_page()

        # 웹 페이지 로드
        print("웹 페이지 로드 중...")
        await page.goto("http://localhost:8080")
        await page.wait_for_load_state("networkidle")

        # 검색어 입력
        print("검색어 입력 중...")
        await page.fill("#prompt", "인공지능의 역사와 발전 과정")

        # 검색 버튼 클릭
        print("검색 버튼 클릭...")
        await page.click("#search-button")

        # 스트리밍 응답 확인
        print("스트리밍 응답 확인 중...")

        # 상태 메시지 확인
        status_visible = False
        for _ in range(10):  # 10초 동안 확인
            if await page.query_selector(".status-message") is not None:
                status_visible = True
                status_text = await page.text_content(".status-message")
                print(f"상태 메시지 확인: {status_text}")
                break
            await asyncio.sleep(1)

        if not status_visible:
            print("❌ 상태 메시지가 표시되지 않았습니다.")
        else:
            print("✅ 상태 메시지가 표시되었습니다.")

        # 검색 쿼리 분해 확인
        decomposed_visible = False
        for _ in range(20):  # 20초 동안 확인
            if await page.query_selector(".decomposed-queries") is not None:
                decomposed_visible = True
                print("✅ 검색 쿼리 분해가 표시되었습니다.")
                break
            await asyncio.sleep(1)

        if not decomposed_visible:
            print("❌ 검색 쿼리 분해가 표시되지 않았습니다.")

        # 보고서 생성 확인
        report_content = ""
        for _ in range(120):  # 120초 동안 확인
            report_element = await page.query_selector("#report")
            if report_element:
                content = await report_element.text_content()
                if content and "Generating report..." not in content and len(content) > 50:
                    report_content = content
                    print("✅ 보고서가 생성되었습니다.")
                    print(f"보고서 내용 일부: {content[:100]}...")
                    break
            print(f"보고서 대기 중... ({_+1}/120초)")
            await asyncio.sleep(1)

        if not report_content:
            print("❌ 보고서가 생성되지 않았습니다.")

        # 검색 단계 확인
        steps_visible = False
        for _ in range(10):  # 10초 동안 확인
            if await page.query_selector(".step") is not None:
                steps_visible = True
                steps_count = len(await page.query_selector_all(".step"))
                print(f"✅ 검색 단계가 표시되었습니다. (총 {steps_count}개)")
                break
            await asyncio.sleep(1)

        if not steps_visible:
            print("❌ 검색 단계가 표시되지 않았습니다.")

        # 소스 확인
        sources_visible = False
        for _ in range(30):  # 30초 동안 확인
            if await page.query_selector("#sources-list li") is not None:
                sources_visible = True
                sources_count = len(await page.query_selector_all("#sources-list li"))
                print(f"✅ 소스가 표시되었습니다. (총 {sources_count}개)")
                break
            print(f"소스 대기 중... ({_+1}/30초)")
            await asyncio.sleep(1)

        if not sources_visible:
            print("❌ 소스가 표시되지 않았습니다.")

        # 스크린샷 저장
        await page.screenshot(path="search_result.png")
        print("스크린샷이 search_result.png로 저장되었습니다.")

        # 테스트 결과 요약
        print("\n테스트 결과 요약:")
        print(f"상태 메시지 표시: {'✅' if status_visible else '❌'}")
        print(f"검색 쿼리 분해 표시: {'✅' if decomposed_visible else '❌'}")
        print(f"보고서 생성: {'✅' if report_content else '❌'}")
        print(f"검색 단계 표시: {'✅' if steps_visible else '❌'}")
        print(f"소스 표시: {'✅' if sources_visible else '❌'}")

        # 브라우저 종료 전 잠시 대기
        await asyncio.sleep(3)

        # 브라우저 종료
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_streaming_search())
