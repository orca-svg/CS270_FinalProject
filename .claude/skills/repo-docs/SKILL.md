---
name: repo-docs
description: >
  CS270 FinalProject GitHub 저장소의 문서를 관리하는 오케스트레이터.
  README 업데이트, 기술 스펙 작성, 현재 동작 방식 서술, 팀원 공유용 문서 생성 요청 시 반드시 이 스킬을 사용하라.
  "README 고쳐줘", "스펙 문서 만들어줘", "이게 어떻게 동작해?", "팀원한테 설명할 자료 만들어줘",
  "프로토콜 문서화해줘", "아키텍처 설명해줘", "설치 방법 정리해줘",
  "한국어로 번역해줘", "한국어 버전 만들어줘", "docs 한국어 지원", "README.ko 만들어줘",
  "다시 실행", "업데이트해줘", "최신화해줘" 등의 요청이 트리거다.
  단순 코드 질문(버그 수정, 기능 추가)은 이 스킬 없이 직접 응답한다.
---

# CS270 Repo Docs Orchestrator

CS270 FinalProject 저장소의 문서를 팀원이 활용할 수 있는 상태로 유지한다.
README, 기술 스펙, 동작 방식 문서를 에이전트 팀이 병렬로 작성·업데이트한다.

## 실행 모드

**팬아웃 → 팬인** (에이전트 팀)
- `readme-agent`와 `spec-agent`가 병렬로 각자 담당 문서를 작성
- 오케스트레이터가 결과를 통합하고 커밋 여부를 확인

---

## Phase 0: 컨텍스트 확인

작업 시작 전 현재 상태를 파악한다.

1. `_workspace/` 디렉토리 존재 여부 확인
   - **존재 + 부분 수정 요청** → 해당 에이전트만 재호출 (Phase 2로 바로 진입)
   - **존재 + 새 요청** → `_workspace/`를 `_workspace_prev/`로 이동 후 새 실행
   - **미존재** → 초기 실행, `mkdir _workspace`
2. `docs/` 디렉토리 존재 여부 확인 — 없으면 Phase 2에서 생성
3. 사용자 요청을 분류:
   - **README만** → readme-agent만 실행
   - **스펙/동작/아키텍처/프로토콜** → spec-agent만 실행
   - **전체 / 팀 공유 준비** → 두 에이전트 모두 실행
   - **한국어 지원 / 번역** → 두 에이전트 모두 실행 (언어=한국어 지시)
4. 언어 범위 결정:
   - "한국어만" → `README.ko.md` + `docs/ko/` 만 생성
   - "영어만" → `README.md` + `docs/` 만 생성
   - 미지정 또는 "둘 다" → 두 언어 모두 생성

---

## Phase 1: 에이전트 팀 구성 및 병렬 실행

Phase 0 분류 결과에 따라 에이전트를 호출한다.

### 전체 실행 시 (두 에이전트 모두)

두 에이전트를 **동시에** 백그라운드로 실행한다.

**readme-agent 지시 (Agent 도구, model: opus, run_in_background: true):**
```
CS270_FinalProject 저장소의 README.md를 업데이트하라.

담당 섹션: Repository Structure, Hardware 포트 맵, Setup, Usage, Motion Constants 표
소스: gesture_bt/ 하위 Python 파일 직접 읽기

완료 후 _workspace/readme_changes.md에 변경 요약 저장.
```

**spec-agent 지시 (Agent 도구, model: opus, run_in_background: true):**
```
CS270_FinalProject 저장소의 기술 스펙 문서를 생성하라.

생성 대상:
- docs/ARCHITECTURE.md : 시스템 아키텍처 + Mermaid 데이터 흐름도
- docs/PROTOCOL.md : BLE 패킷 포맷, rdy 핸드쉐이크, 타임아웃 정책
- docs/STATE_MACHINES.md : C모터 상태 머신, fire latch, 데드락 복구

소스: gesture_bt/ 하위 Python 파일 직접 읽기
완료 후 _workspace/spec_draft.md에 Architecture Notes 요약 저장.
```

두 에이전트 완료 후 readme-agent가 `_workspace/spec_draft.md`를 반영하여 README의 Architecture Notes 섹션을 최종 갱신한다.

### README만 업데이트
readme-agent만 foreground로 실행.

### 스펙/동작 문서만
spec-agent만 foreground로 실행. 생성 대상을 요청에 맞게 지정.

---

## Phase 2: 산출물 검증

두 에이전트 완료 후:

1. `_workspace/readme_changes.md` 내용 확인 — 어떤 섹션이 바뀌었는지 요약
2. `docs/` 하위 파일 목록 확인 — 의도한 파일이 모두 생성되었는지
3. README.md의 코드 블록 커맨드가 실제로 실행 가능한지 spot-check (파일 존재 여부, 파라미터명 일치)

---

## Phase 3: 사용자 보고 및 커밋 제안

작업 완료 보고 포맷:

```
**Repo Docs 업데이트 완료**
- README.md: [변경된 섹션 목록]
- 새 문서: [생성된 docs/ 파일 목록]
- 주요 변경: [핵심 내용 2–3줄]

커밋하고 GitHub에 push할까요?
```

사용자가 커밋을 승인하면:
```bash
git -C <repo_path> add README.md docs/ _workspace/
git -C <repo_path> commit -m "docs: update README and technical specs"
git -C <repo_path> push origin main
```

---

### 한국어 전용 실행 시

**readme-agent 지시 (Agent 도구, model: opus):**
```
CS270_FinalProject 저장소의 README.ko.md를 한국어로 작성하라.
README.md를 원본으로 읽고, 동일한 구조와 내용으로 한국어 번역본을 생성한다.
- 파일 상단에 [English README](README.md) 링크 포함
- 기술 용어(BLE, argparse, GATT 등)는 영어 유지
- 코드 블록·커맨드·상수는 번역하지 않음
- 버전·날짜 표시 금지
출력: README.ko.md 생성 (Write 도구)
```

**spec-agent 지시 (Agent 도구, model: opus):**
```
CS270_FinalProject 저장소의 docs/ko/ 디렉토리에 한국어 스펙 문서 3개를 생성하라.
docs/ 하위 영문 파일을 원본으로 읽고, 동일한 구조·내용·Mermaid 다이어그램으로 한국어 번역본을 생성한다.
- docs/ko/ARCHITECTURE.md
- docs/ko/PROTOCOL.md
- docs/ko/STATE_MACHINES.md
규칙:
- Mermaid 다이어그램 레이블은 영어 유지 (렌더링 안정성)
- 기술 용어·상수·코드 블록은 번역하지 않음
- 각 파일 상단에 [English version](../파일명.md) 링크 포함
출력: docs/ko/ 하위 3개 파일 생성 (Write 도구)
```

## 에러 핸들링

| 상황 | 처리 |
|------|------|
| 에이전트가 코드 파일을 읽지 못함 | 해당 섹션 `<!-- TODO -->` 마킹 후 계속 |
| docs/ 파일 생성 실패 | 오케스트레이터가 직접 빈 파일 생성 후 에이전트 재호출 |
| 두 에이전트 결과가 Architecture Notes에서 충돌 | spec-agent 버전을 우선 적용, 출처 병기 |

---

## 테스트 시나리오

**정상 흐름:**
1. "팀원한테 공유할 수 있게 repo 문서 정리해줘" → 두 에이전트 병렬 실행 → README + docs/ 생성 → push

**부분 재실행:**
1. 이전 실행 후 "프로토콜 부분만 다시 써줘" → `_workspace/` 존재 확인 → spec-agent만 PROTOCOL.md 업데이트

**에러 흐름:**
1. spec-agent가 C모터 상태 전이 조건을 파악 못 함 → `⚠️` 마킹 후 나머지 진행, 보고서에 명시
