# Agora3
일상용

## Supabase 연결

봇은 Supabase 프로젝트 `Multi-LLM`(ref: `ntpbzzgbltpbpmfknbjw`, ap-northeast-2)의
기존 테이블을 그대로 사용한다. 새로 만드는 테이블은 없다.

| 테이블 | 용도 |
| --- | --- |
| `operator_chat_logs` | 질문/답변 원본 적재, 직전 대화 6건을 토론 프롬프트에 주입 |
| `processed_updates` | `update_id` UNIQUE 충돌로 텔레그램 웹훅 재전송 중복 실행 차단 |
| `system_events` | 부팅 / 보고 완료 / 장애 / 권한 거부 이벤트 기록 |

### 환경변수

| 키 | 설명 |
| --- | --- |
| `SUPABASE_URL` | `https://ntpbzzgbltpbpmfknbjw.supabase.co` |
| `SUPABASE_KEY` | **service_role 키 필수** (`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_SERVICE_KEY`도 인식) |
| `TELEGRAM_TOKEN` | 텔레그램 봇 토큰 |
| `ALLOWED_USER_ID` | 허용 사용자 ID, 쉼표 구분 |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `PERPLEXITY_API_KEY` | LLM 키 |

> 위 세 테이블은 RLS가 켜져 있고 정책이 하나도 없다. 즉 anon / publishable 키로는
> 조회는 빈 배열, 기록은 42501로 전부 막힌다. 서버 전용 봇이므로 service_role 키를 쓴다.

### 상태 확인

`GET /health` 가 Supabase에 실제 쿼리를 날려 연결 상태를 반환한다.

```json
{"ok": true, "version": "v1.3.0", "supabase": {"configured": true, "reachable": true, "error": null}}
```

DB가 죽어도 봇은 죽지 않는다. 모든 DB 접근은 단일 관문(`_db`)을 거쳐 실패 시 로그만 남기고
토론/응답은 그대로 진행된다.
