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
# 1. 모델 설정 (형님 지침 준수)
# ============================================================
GEMINI_MODEL_ID = "gemini-3.1-pro-preview"
CLAUDE_MODEL_ID = "claude-sonnet-4-6"      # 형님 고정 모델
GPT_MODEL_ID    = "gpt-5.4"               # 형님 고정 모델
PPLX_MODEL_ID   = "sonar-pro"

def get_env(k):
    v = os.environ.get(k)
    if not v: return None
    return v.strip()

# 로깅 설정 강화
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Agora_v1.2")

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

# ID 리스트 처리 (공백 제거 필수)
raw_ids = get_env('ALLOWED_USER_ID')
ALLOWED_IDS = [int(x.strip()) for x in raw_ids.split(',')] if raw_ids else []

# ============================================================
# 2. 핵심 로직 (에러 핸들링 강화)
# ============================================================
async def get_pplx_fact(query: str):
    try:
        res = await pplx_client.chat.completions.create(
            model=PPLX_MODEL_ID,
            messages=[{"role": "user", "content": f"Find the latest factual data for: {query}"}]
        )
        return res.choices[0].message.content
    except Exception as e:
        logger.error(f"PPLX 에러: {e}")
        return f"팩트 체크 실패 (에러: {str(e)})"

async def conduct_debate(topic: str, fact_data: str, context: str = ""):
    """3인 군단 자유 토론 및 에이전트별 에러 체크"""
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

    base_p = f"팩트:{fact_data}\n주제:{topic}\n컨텍스트:{context}\n팩트로만 토론하라."
    ops = await asyncio.gather(
        get_opinion("Gemini", GEMINI_MODEL_ID, f"{base_p}\n시각 분석 관점."),
        get_opinion("GPT", GPT_MODEL_ID, f"{base_p}\n통계 분석 관점."),
        get_opinion("Claude", CLAUDE_MODEL_ID, f"{base_p}\n논리 분석 관점.")
    )

    synthesis_p = f"아래 토론을 요약하여 최종 결론만 보고하라.\n\nG:{ops[0]}\nT:{ops[1]}\nC:{ops[2]}"
    try:
        final = await anthropic_client.messages.create(
            model=CLAUDE_MODEL_ID, max_tokens=2500,
            messages=[{"role": "user", "content": synthesis_p}]
        )
        return final.content[0].text
    except Exception as e:
        return f"최종 합의 실패: {str(e)}\n\n[개별 의견]\nGPT: {ops[1]}\nGemini: {ops[0]}"

# ============================================================
# 3. 백그라운드 태스크 (에러 보고 기능 추가)
# ============================================================
async def safe_run_agora(query, chat_id):
    try:
        logger.info(f"작업 시작: {query}")
        fact = await get_pplx_fact(query)
        response = await conduct_debate("일상 팩트 분석", fact)
        await bot.send_message(chat_id, f"🗿 **아고라 보고**\n\n{response}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"실행 중 치명적 에러: {e}")
        await bot.send_message(chat_id, f"⚠️ **시스템 내부 에러 발생**\n{str(e)}")

# ============================================================
# 4. 웹훅 엔드포인트 (ID 검증 로그 추가)
# ============================================================
@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        if not update.message: return {"ok": True}
        
        user_id = update.message.from_user.id
        text = update.message.text or ""
        chat_id = update.effective_chat.id
        
        logger.info(f"메시지 수신: ID={user_id}, TEXT={text}")

        if user_id in ALLOWED_IDS:
            bg.add_task(safe_run_agora, text, chat_id)
        else:
            logger.warning(f"미승인 사용자 접근: {user_id}")
            # 승인되지 않은 경우 형님께 알림 (디버그용)
            await bot.send_message(chat_id, f"접근 거부됨. ID: {user_id}")
            
    except Exception as e:
        logger.error(f"웹훅 처리 중 에러: {e}")
        
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
