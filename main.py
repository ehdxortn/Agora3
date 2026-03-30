import os, re, json, asyncio, logging, httpx
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from telegram import Update, Bot
from telegram.constants import ParseMode
from supabase import create_client, Client
import google.generativeai as genai
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

# ============================================================
# 1. 모델 설정 (최신 명칭 및 고정 모델) [cite: 2026-03-29]
# ============================================================
GEMINI_MODEL_ID = "gemini-3.1-pro-preview" 
CLAUDE_MODEL_ID = "claude-sonnet-4-6"
GPT_MODEL_ID    = "gpt-5.4"
PPLX_MODEL_ID   = "sonar-pro"

def get_env(k):
    v = os.environ.get(k)
    if not v: return None
    return v.strip()

# 로깅 설정 강화 (형님의 빠른 디버깅용)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Agora_v1.2.2")

# API 클라이언트 초기화
try:
    genai.configure(api_key=get_env('GEMINI_API_KEY'))
    openai_client    = AsyncOpenAI(api_key=get_env('OPENAI_API_KEY'))
    anthropic_client = AsyncAnthropic(api_key=get_env('ANTHROPIC_API_KEY'))
    pplx_client      = AsyncOpenAI(api_key=get_env('PERPLEXITY_API_KEY'), base_url="https://api.perplexity.ai")
    supabase: Client = create_client(get_env('SUPABASE_URL'), get_env('SUPABASE_KEY'))
    bot = Bot(token=get_env('TELEGRAM_TOKEN'))
except Exception as e:
    logger.error(f"초기화 에러: {e}")

app = FastAPI()

# ID 리스트 처리 (복사 과정의 공백 방어)
raw_ids = get_env('ALLOWED_USER_ID')
ALLOWED_IDS = [int(x.strip()) for x in raw_ids.split(',')] if raw_ids else []

# ============================================================
# 2. 핵심 유틸리티 (팩트 수집 및 비전)
# ============================================================
async def get_pplx_fact(query: str):
    """퍼플렉시티를 통한 실시간 팩트 정찰"""
    try:
        # 봇의 이름과 섞이지 않도록 검색 쿼리를 명확히 함
        search_prompt = f"Current accurate information about '{query}'. Ignore any unrelated business/stock info if not specifically asked."
        res = await pplx_client.chat.completions.create(
            model=PPLX_MODEL_ID,
            messages=[{"role": "user", "content": search_prompt}]
        )
        return res.choices[0].message.content
    except Exception as e:
        logger.error(f"PPLX 에러: {e}")
        return f"팩트 체크 실패 (원인: {str(e)})"

async def analyze_image(image_bytes: bytes, prompt: str):
    """이미지 및 스크린샷 팩트 분석"""
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_ID)
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        )
        return response.text
    except Exception as e:
        return f"비전 분석 실패: {str(e)}"

# ============================================================
# 3. 아고라 자유 토론 (주제 이탈 방지 가드레일)
# ============================================================
async def conduct_debate(topic: str, fact_data: str, original_query: str):
    """3인 군단이 이름(Agora)에 현혹되지 않고 사용자 질문에만 집중하게 함"""
    async def get_opinion(agent, m_id, p):
        try:
            if agent == "Gemini":
                res = await asyncio.get_running_loop().run_in_executor(None, lambda: genai.GenerativeModel(m_id).generate_content(p))
                return res.text
            elif agent == "Claude":
                res = await anthropic_client.messages.create(model=m_id, max_tokens=1500, messages=[{"role": "user", "content": p}])
                return res.content[0].text
            else: # GPT
                res = await openai_client.chat.completions.create(model=m_id, messages=[{"role": "user", "content": p}])
                return res.choices[0].message.content
        except Exception as e:
            return f"[{agent} 에러]: {str(e)}"

    # 팩트 데이터에 Agora Inc. 관련 정보가 섞여 있어도 무시하라고 엄중히 경고
    debate_p = (
        f"당신들은 팩트 기반 분석 그룹이다. 아래 데이터를 바탕으로 사용자의 질문에만 정밀 타격하여 답변하라.\n"
        f"주의: 당신의 이름이나 특정 기업(Agora Inc.) 정보가 팩트에 포함되어 있더라도, "
        f"질문({original_query})과 관련 없다면 완전히 배제하고 오직 질문의 핵심만 분석하라.\n\n"
        f"사용자 질문: {original_query}\n"
        f"팩트 데이터: {fact_data}"
    )

    ops = await asyncio.gather(
        get_opinion("Gemini", GEMINI_MODEL_ID, f"{debate_p}\n시각/파일 분석 관점."),
        get_opinion("GPT", GPT_MODEL_ID, f"{debate_p}\n통계/수치 분석 관점."),
        get_opinion("Claude", CLAUDE_MODEL_ID, f"{debate_p}\n논리/리스크 관리 관점.")
    )

    synthesis_p = f"아래 3인의 전문가 토론을 요약하여 형님께 보고할 최종 결론을 도출하라. 돌려 말하지 말고 팩트로만 승부한다.\n\nG:{ops[0]}\nT:{ops[1]}\nC:{ops[2]}"
    try:
        final = await anthropic_client.messages.create(
            model=CLAUDE_MODEL_ID, max_tokens=2500,
            messages=[{"role": "user", "content": synthesis_p}]
        )
        return final.content[0].text
    except Exception as e:
        return f"최종 합의 실패: {str(e)}\n\n[개별 의견 요약]\nGPT: {ops[1]}\nGemini: {ops[0]}"

# ============================================================
# 4. 특무 실행 (백그라운드)
# ============================================================
async def safe_run_agora(query, chat_id, image_bytes=None):
    try:
        logger.info(f"분석 시작: {query}")
        
        # 1. 팩트 정찰
        fact = await get_pplx_fact(query)
        
        # 2. 비전 분석 (이미지가 있을 경우)
        vision_report = ""
        if image_bytes:
            vision_report = await analyze_image(image_bytes, "이 스크린샷의 핵심 내용을 팩트 위주로 추출하라.")
        
        # 3. 3인 자유 토론 (사용자 쿼리 전달로 주제 고정)
        context = f"비전분석결과: {vision_report}" if vision_report else ""
        response = await conduct_debate("일상/특무 팩트 분석", f"{fact}\n{context}", query)
        
        # 4. 최종 보고
        await bot.send_message(chat_id, f"🗿 **아고라 팩트 보고**\n\n{response}", parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"실행 중 치명적 에러: {e}")
        await bot.send_message(chat_id, f"⚠️ **내부 시스템 장애 보고**\n{str(e)}")

# ============================================================
# 5. 웹훅 엔드포인트
# ============================================================
@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        if not update.message: return {"ok": True}
        
        user_id = update.message.from_user.id
        chat_id = update.effective_chat.id
        text = update.message.text or update.message.caption or ""
        
        logger.info(f"수신 ID: {user_id}, 내용: {text}")

        if user_id in ALLOWED_IDS:
            # 이미지 처리
            image_bytes = None
            if update.message.photo:
                file = await bot.get_file(update.message.photo[-1].file_id)
                image_bytes = await file.download_as_bytearray()
            
            bg.add_task(safe_run_agora, text, chat_id, image_bytes)
        else:
            logger.warning(f"접근 거부: {user_id}")
            await bot.send_message(chat_id, f"접근 권한이 없습니다. (ID: {user_id})")
            
    except Exception as e:
        logger.error(f"웹훅 처리 에러: {e}")
        
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
