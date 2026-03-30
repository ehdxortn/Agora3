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
# 1. 고정 모델 설정 (장프로 형님 지정 리스트)
# ============================================================
GEMINI_MODEL_ID = "gemini-3.1-pro-preview" 
CLAUDE_MODEL_ID = "claude-sonnet-4-6"
GPT_MODEL_ID    = "gpt-5.4"
PPLX_MODEL_ID   = "sonar-pro"

def get_env(k):
    v = os.environ.get(k)
    if not v: return None
    return v.strip()

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Agora_v1.2.3")

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

# ID 리스트 처리
raw_ids = get_env('ALLOWED_USER_ID')
ALLOWED_IDS = [int(x.strip()) for x in raw_ids.split(',')] if raw_ids else []

# ============================================================
# 2. 핵심 유틸리티
# ============================================================
async def get_pplx_fact(query: str):
    """퍼플렉시티 실시간 팩트 정찰"""
    try:
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
    """비전 분석 (Gemini 3.1 Pro 활용)"""
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_ID)
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        )
        return response.text
    except Exception as e:
        return f"비전 분석 실패: {str(e)}"

# ============================================================
# 3. 아고라 자유 토론 (가드레일 강화)
# ============================================================
async def conduct_debate(topic: str, fact_data: str, original_query: str):
    """3인 군단 자유 토론 프로토콜"""
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

    debate_p = (
        f"당신들은 팩트 기반 분석 전문가다. 아래 데이터를 바탕으로 사용자의 질문에만 정밀 타격하여 답변하라.\n"
        f"주의: 기업(Agora Inc.) 정보가 팩트에 포함되어 있더라도 질문({original_query})과 관련 없다면 무시하라.\n\n"
        f"사용자 질문: {original_query}\n"
        f"팩트 데이터: {fact_data}"
    )

    ops = await asyncio.gather(
        get_opinion("Gemini", GEMINI_MODEL_ID, f"{debate_p}\n시각/파일 분석 관점."),
        get_opinion("GPT", GPT_MODEL_ID, f"{debate_p}\n통계/수치 분석 관점."),
        get_opinion("Claude", CLAUDE_MODEL_ID, f"{debate_p}\n논리/리스크 관리 관점.")
    )

    synthesis_p = f"아래 3인의 전문가 토론을 요약하여 최종 결론만 보고하라. 돌려 말하지 말고 팩트로만 승부한다.\n\nG:{ops[0]}\nT:{ops[1]}\nC:{ops[2]}"
    try:
        final = await anthropic_client.messages.create(
            model=CLAUDE_MODEL_ID, max_tokens=2500,
            messages=[{"role": "user", "content": synthesis_p}]
        )
        return final.content[0].text
    except Exception as e:
        return f"최종 합의 실패: {str(e)}"

# ============================================================
# 4. 특무 실행 및 웹훅
# ============================================================
async def safe_run_agora(query, chat_id, image_bytes=None):
    try:
        fact = await get_pplx_fact(query)
        vision_report = await analyze_image(image_bytes, "팩트 추출") if image_bytes else ""
        response = await conduct_debate("팩트 분석", f"{fact}\n{vision_report}", query)
        await bot.send_message(chat_id, f"🗿 **아고라 보고**\n\n{response}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await bot.send_message(chat_id, f"⚠️ **시스템 장애 보고**\n{str(e)}")

@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        if not update.message: return {"ok": True}
        
        user_id = update.message.from_user.id
        chat_id = update.effective_chat.id
        text = update.message.text or update.message.caption or ""
        
        if user_id in ALLOWED_IDS:
            image_bytes = None
            if update.message.photo:
                file = await bot.get_file(update.message.photo[-1].file_id)
                image_bytes = await file.download_as_bytearray()
            bg.add_task(safe_run_agora, text, chat_id, image_bytes)
        else:
            await bot.send_message(chat_id, f"접근 권한이 없습니다. (ID: {user_id})")
    except Exception as e:
        logger.error(f"웹훅 에러: {e}")
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
