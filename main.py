import os, re, json, asyncio, logging, httpx
import pandas as pd
import talib
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from telegram import Update, Bot
from telegram.constants import ParseMode
from supabase import create_client, Client
import google.generativeai as genai
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

# ============================================================
# 1. 고정 모델 및 환경 설정 (2026-03-30 최적화)
# ============================================================
GEMINI_MODEL_ID = "gemini-3.1-pro-preview" # 비전 및 분석
CLAUDE_MODEL_ID = "claude-sonnet-4-6"      # 논리 및 최종 정제
GPT_MODEL_ID    = "gpt-5.4"               # 창의적 가교 및 퀀트
PPLX_MODEL_ID   = "sonar-reasoning"       # 실시간 팩트 가드레일

def get_env(k):
    v = os.environ.get(k)
    if not v: raise ValueError(f"ENV {k} 누락!")
    return v.strip()

# API 클라이언트 초기화
genai.configure(api_key=get_env('GEMINI_API_KEY'))
openai_client    = AsyncOpenAI(api_key=get_env('OPENAI_API_KEY'))
anthropic_client = AsyncAnthropic(api_key=get_env('ANTHROPIC_API_KEY'))
pplx_client      = AsyncOpenAI(api_key=get_env('PERPLEXITY_API_KEY'), base_url="https://api.perplexity.ai")
supabase: Client = create_client(get_env('SUPABASE_URL'), get_env('SUPABASE_KEY'))
bot = Bot(token=get_env('TELEGRAM_TOKEN'))
app = FastAPI()

ALLOWED_IDS = [int(x.strip()) for x in get_env('ALLOWED_USER_ID').split(',')]
TAVILY_KEY  = get_env('TAVILY_KEY')
FINNHUB_KEY = get_env('FINNHUB_KEY')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Agora_Sovereign_v33")

# ============================================================
# 2. 핵심 유틸리티 (비전 처리 및 팩트 게이트)
# ============================================================
async def get_pplx_fact(query: str):
    """퍼플렉시티를 통한 최신 팩트 수집 (할루시네이션 방어)"""
    try:
        res = await pplx_client.chat.completions.create(
            model=PPLX_MODEL_ID,
            messages=[{"role": "user", "content": f"Find the latest factual data for: {query}"}]
        )
        return res.choices[0].message.content
    except: return "실시간 데이터 수집 지연"

async def analyze_image(image_bytes: bytes, prompt: str):
    """Gemini 비전 기능을 통한 스크린샷 분석"""
    model = genai.GenerativeModel(GEMINI_MODEL_ID)
    response = await asyncio.get_running_loop().run_in_executor(
        None, lambda: model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
    )
    return response.text

def extract_json(text):
    """JSON 데이터 정밀 추출 파서"""
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match: return json.loads(match.group())
    except: pass
    return {"report": text}

# ============================================================
# 3. 아고라 자유 토론 프로토콜 (MAD)
# ============================================================
async def conduct_debate(topic: str, fact_data: str, context: str = ""):
    """3인 군단의 계급장 뗀 자유 토론"""
    # 1단계: 각자 팩트 기반 초안 작성
    async def get_opinion(agent, m_id, p):
        if agent == "Gemini":
            res = await asyncio.get_running_loop().run_in_executor(None, lambda: genai.GenerativeModel(m_id).generate_content(p))
            return res.text
        elif agent == "Claude":
            res = await anthropic_client.messages.create(model=m_id, max_tokens=1500, messages=[{"role": "user", "content": p}])
            return res.content[0].text
        else:
            res = await openai_client.chat.completions.create(model=m_id, messages=[{"role": "user", "content": p}])
            return res.choices[0].message.content

    base_p = f"팩트:{fact_data}\n주제:{topic}\n컨텍스트:{context}\n돌려 말하지 말고 팩트로만 승부하라."
    ops = await asyncio.gather(
        get_opinion("Gemini", GEMINI_MODEL_ID, f"{base_p}\n시각/파일 관점에서 분석하라."),
        get_opinion("GPT", GPT_MODEL_ID, f"{base_p}\n퀀트/통계 관점에서 분석하라."),
        get_opinion("Claude", CLAUDE_MODEL_ID, f"{base_p}\n논리/리스크 관점에서 분석하라.")
    )

    # 2단계: 상호 비판 및 합의 (Claude가 최종 정제)
    synthesis_p = f"아래 3명의 토론 내용을 바탕으로 형님께 보고할 최종 결론을 도출하라. 거짓이나 포장은 배제한다.\n\nG:{ops[0]}\nT:{ops[1]}\nC:{ops[2]}"
    final = await anthropic_client.messages.create(
        model=CLAUDE_MODEL_ID, max_tokens=2500,
        messages=[{"role": "user", "content": synthesis_p}]
    )
    return final.content[0].text

# ============================================================
# 4. 수동 정밀 타격 모드 (MTF & Scenario)
# ============================================================
async def run_command_sovereign(query, chat_id, image_data=None):
    """v33.1 커맨드 소버린: 수동 정밀 타격"""
    await bot.send_message(chat_id, "🎯 **커맨드 소버린 가동: 정밀 타격 준비...**")
    
    # 1. 팩트 및 시각 데이터 수집
    fact = await get_pplx_fact(query)
    vision_report = ""
    if image_data:
        vision_report = await analyze_image(image_data, "차트의 주요 추세선과 패턴을 기술적으로 분석하라.")
    
    # 2. MTF 심층 토론 및 시나리오 생성
    report = await conduct_debate(
        topic=f"MTF(1D, 4H, 15M) 통합 분석 및 대응 시나리오",
        fact_data=fact,
        context=f"사용자질문:{query}\n비전분석:{vision_report}"
    )
    
    await bot.send_message(chat_id, f"🔱 **[정밀 타격 보고서]**\n\n{report}", parse_mode=ParseMode.MARKDOWN)

# ============================================================
# 5. 아고라 일상/특무 모드 (사주, 스포츠, 로또)
# ============================================================
async def run_agora_friend(query, chat_id, file_data=None):
    """아고라 v1.1: 팩트 중심 일상 친구"""
    # 팩트 우선 수급
    fact = await get_pplx_fact(query)
    
    # 자유 토론 및 결론 도출 (포장 없음)
    response = await conduct_debate(
        topic="일상/스포츠/사주/로또 팩트 분석",
        fact_data=fact,
        context=f"질문:{query}\n파일데이터:{file_data if file_data else '없음'}"
    )
    
    await bot.send_message(chat_id, f"🗿 **아고라 팩트 보고**\n\n{response}")

# ============================================================
# 6. Webhook 통합
# ============================================================
@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    data = await request.json()
    update = Update.de_json(data, bot)
    if not update.message: return {"ok": True}
    
    text = update.message.text or update.message.caption or ""
    chat_id = update.effective_chat.id
    
    if update.message.from_user.id in ALLOWED_IDS:
        # 1. 이미지 처리 준비
        image_bytes = None
        if update.message.photo:
            file = await bot.get_file(update.message.photo[-1].file_id)
            image_bytes = await file.download_as_bytearray()

        # 2. 의도 분류 및 실행 (수동 트리거)
        if any(kw in text.upper() for kw in ['분석', '타격', '명령', 'BTC', '매수', '매도']):
            bg.add_task(run_command_sovereign, text, chat_id, image_bytes)
        elif "/빌드업" in text:
            # 코드 빌드업 모드 별도 실행 가능
            bg.add_task(conduct_debate, "코드 빌드업 및 최적화", "사용자 제공 소스코드", text)
        else:
            bg.add_task(run_agora_friend, text, chat_id)
            
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
