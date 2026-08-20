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
APP_VERSION     = "v1.3.0"
GEMINI_MODEL_ID = "gemini-3.1-pro-preview" 
CLAUDE_MODEL_ID = "claude-sonnet-4-6"
GPT_MODEL_ID    = "gpt-5.4"
PPLX_MODEL_ID   = "sonar-pro"

# Supabase 테이블 (기존 스키마 그대로 사용)
TBL_CHAT_LOG = "operator_chat_logs"    # chat_id, role, content, created_at
TBL_UPDATES  = "processed_updates"     # update_id UNIQUE -> 웹훅 중복 차단
TBL_EVENTS   = "system_events"         # event, job, app_version, duration_ms, detail

def get_env(*keys):
    """여러 후보 키 중 먼저 잡히는 환경변수를 반환"""
    for k in keys:
        v = os.environ.get(k)
        if v and v.strip():
            return v.strip()
    return None

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(f"Agora_{APP_VERSION}")

# ============================================================
# 2. 클라이언트 초기화 (개별 격리 - 하나 죽어도 나머지는 산다)
# ============================================================
def _init(name, factory):
    try:
        return factory()
    except Exception as e:
        logger.error(f"[INIT] {name} 초기화 실패: {e}")
        return None

def _init_supabase() -> Client:
    url = get_env('SUPABASE_URL')
    key = get_env('SUPABASE_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수 누락")
    client = create_client(url, key)
    logger.info(f"[INIT] Supabase 연결 준비 완료: {url}")
    return client

_init("Gemini", lambda: genai.configure(api_key=get_env('GEMINI_API_KEY')))
openai_client    = _init("OpenAI",     lambda: AsyncOpenAI(api_key=get_env('OPENAI_API_KEY')))
anthropic_client = _init("Anthropic",  lambda: AsyncAnthropic(api_key=get_env('ANTHROPIC_API_KEY')))
pplx_client      = _init("Perplexity", lambda: AsyncOpenAI(api_key=get_env('PERPLEXITY_API_KEY'), base_url="https://api.perplexity.ai"))
supabase         = _init("Supabase",   _init_supabase)
bot              = _init("Telegram",   lambda: Bot(token=get_env('TELEGRAM_TOKEN')))

app = FastAPI()

# ID 리스트 처리
raw_ids = get_env('ALLOWED_USER_ID')
ALLOWED_IDS = [int(x.strip()) for x in raw_ids.split(',')] if raw_ids else []

# ============================================================
# 3. Supabase 기억 저장소 (동기 SDK -> 스레드로 밀어 이벤트 루프 보호)
# ============================================================
async def _db(fn, what):
    """모든 DB 접근의 단일 관문. 실패해도 봇 본체는 절대 죽지 않는다."""
    if supabase is None:
        logger.warning(f"[DB] 미연결 상태라 스킵: {what}")
        return None
    try:
        return await asyncio.to_thread(fn)
    except Exception as e:
        logger.error(f"[DB] {what} 실패: {e}")
        return None

async def is_duplicate_update(update_id) -> bool:
    """텔레그램 재전송 방어. update_id UNIQUE 충돌이면 이미 처리한 건이다."""
    if supabase is None or update_id is None:
        return False
    try:
        await asyncio.to_thread(
            lambda: supabase.table(TBL_UPDATES).insert({"update_id": update_id}).execute()
        )
        return False
    except Exception as e:
        msg = str(e).lower()
        if "23505" in msg or "duplicate key" in msg or "already exists" in msg:
            logger.info(f"[DB] 중복 업데이트 무시: {update_id}")
            return True
        logger.error(f"[DB] 업데이트 기록 실패: {e}")
        return False

async def log_chat(chat_id: int, role: str, content: str):
    """대화 원본을 operator_chat_logs에 적재"""
    if not content:
        return
    await _db(
        lambda: supabase.table(TBL_CHAT_LOG).insert({
            "chat_id": chat_id, "role": role, "content": content[:8000]
        }).execute(),
        "대화 로그 저장"
    )

async def fetch_recent_context(chat_id: int, limit: int = 6) -> str:
    """직전 대화를 끌어와 토론 프롬프트에 주입 (봇의 기억)"""
    res = await _db(
        lambda: supabase.table(TBL_CHAT_LOG)
            .select("role,content,created_at")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute(),
        "대화 이력 조회"
    )
    if not res or not getattr(res, "data", None):
        return ""
    lines = []
    for row in reversed(res.data):
        speaker = "형님" if row.get("role") == "user" else "아고라"
        lines.append(f"{speaker}: {(row.get('content') or '')[:500]}")
    return "\n".join(lines)

async def log_event(event: str, job: str = None, detail: dict = None, duration_ms: int = None):
    """운영 이벤트/장애를 system_events에 기록"""
    await _db(
        lambda: supabase.table(TBL_EVENTS).insert({
            "event": event, "job": job, "app_version": APP_VERSION,
            "duration_ms": duration_ms, "detail": detail
        }).execute(),
        "시스템 이벤트 기록"
    )

# ============================================================
# 4. 핵심 유틸리티
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
# 5. 아고라 자유 토론 (가드레일 강화)
# ============================================================
async def conduct_debate(topic: str, fact_data: str, original_query: str, history: str = ""):
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

    history_block = f"이전 대화 기록:\n{history}\n\n" if history else ""
    debate_p = (
        f"당신들은 팩트 기반 분석 전문가다. 아래 데이터를 바탕으로 사용자의 질문에만 정밀 타격하여 답변하라.\n"
        f"주의: 기업(Agora Inc.) 정보가 팩트에 포함되어 있더라도 질문({original_query})과 관련 없다면 무시하라.\n\n"
        f"{history_block}"
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
# 6. 특무 실행 및 웹훅
# ============================================================
async def safe_run_agora(query, chat_id, image_bytes=None):
    started = datetime.utcnow()
    try:
        await log_chat(chat_id, "user", query)
        history = await fetch_recent_context(chat_id)

        fact = await get_pplx_fact(query)
        vision_report = await analyze_image(image_bytes, "팩트 추출") if image_bytes else ""
        response = await conduct_debate("팩트 분석", f"{fact}\n{vision_report}", query, history)

        await bot.send_message(chat_id, f"🗿 **아고라 보고**\n\n{response}", parse_mode=ParseMode.MARKDOWN)
        await log_chat(chat_id, "assistant", response)
        await log_event(
            "agora_report", job="telegram_debate",
            detail={"chat_id": chat_id, "has_image": bool(image_bytes), "query_len": len(query or "")},
            duration_ms=int((datetime.utcnow() - started).total_seconds() * 1000)
        )
    except Exception as e:
        logger.error(f"특무 실행 에러: {e}")
        await log_event("agora_failure", job="telegram_debate", detail={"chat_id": chat_id, "error": str(e)})
        try:
            await bot.send_message(chat_id, f"⚠️ **시스템 장애 보고**\n{str(e)}")
        except Exception as send_err:
            logger.error(f"장애 보고 전송 실패: {send_err}")

@app.get("/health")
async def health():
    """Cloud Run 헬스체크 + Supabase 연결 실측"""
    db = {"configured": supabase is not None, "reachable": False, "error": None}
    if supabase is not None:
        try:
            await asyncio.to_thread(
                lambda: supabase.table(TBL_EVENTS).select("id").limit(1).execute()
            )
            db["reachable"] = True
        except Exception as e:
            db["error"] = str(e)
    return {"ok": True, "version": APP_VERSION, "supabase": db}

@app.on_event("startup")
async def on_startup():
    await log_event("boot", job="agora_web", detail={"allowed_ids": len(ALLOWED_IDS)})

@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        if not update.message: return {"ok": True}

        if await is_duplicate_update(update.update_id):
            return {"ok": True, "duplicate": True}

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
            await log_event("access_denied", job="telegram_webhook", detail={"user_id": user_id})
            await bot.send_message(chat_id, f"접근 권한이 없습니다. (ID: {user_id})")
    except Exception as e:
        logger.error(f"웹훅 에러: {e}")
        await log_event("webhook_failure", job="telegram_webhook", detail={"error": str(e)})
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
