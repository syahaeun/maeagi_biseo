# 테스트 종류와 화면 증거

모든 테스트와 보조 스크립트는 **Python 3.12** 가상환경에서 실행합니다. 먼저 `.\.venv\Scripts\python.exe --version`으로 3.12인지 확인합니다. 가상환경 실행에 실패하면 Python 3.12 환경을 복구하며, Python 3.10 등 다른 버전으로 대체 실행하지 않습니다.

모든 검사에 같은 의미의 “실제 테스트”라는 이름을 붙이지 않고 아래처럼 구분합니다.

| 실행 옵션 | 대상 | 입력·데이터 | 화면 기록 |
| --- | --- | --- | --- |
| `unit` | 이동 계산, 이미지 로딩, 문구·설정, 말풍선 | 로컬 함수·픽셀 검사 | 이미지·말풍선 렌더링 결과 |
| `api` | Gemini 모델 조회, 응답, 후속 대화·말풍선 연결 | `.env`의 실제 키와 실제 Google 응답 | 로그; UI 조작 검사로 취급하지 않음 |
| `native` | Windows 창 이동·최소화·종료와 메애기 착지 | 실제 HWND/DWM API | 실행 로그 |
| `ui` | 설정 → 모델 조회 → 연결 테스트 → 저장 → 채팅 → 후속 대화 | 표시된 Windows 창의 Qt 마우스·키 입력, 실제 Gemini API | 단계별 화면 PNG와 수행 기록 |
| `meso` / `sol-erda` | 자동 탐지·캡처 CLI·설정창 | 참조 이미지와 모의 결과 | 탐지·크롭 이미지, JSON, Qt 렌더링 |
| `ocr` | 메소 금액·조각 수량, 단위 환산, OCR 설정창 표시 | 제공된 참조 이미지·1.5배 확대본에 실제 Windows OCR/RapidOCR 실행; 설정창은 모의 결과 | `ocr/` 입력·전처리 이미지·정답 비교 JSON, `meso/`·`sol_erda/` Qt 렌더링 |
| `capture` | 직접 영역 지정, 창 기준 좌표, 로컬 OCR 전용 판독, 이전 설정 호환 | 실제 로컬 OCR, Qt 선택 드래그, 비로컬 요청 차단 | `manual/` OCR 이미지·JSON, 설정창·영역 선택 Qt 렌더링; 이미지 API 호출 없음 검증 |

UI 테스트는 `send()`나 `test_connection()`을 직접 호출하지 않습니다. 버튼과 입력창에 마우스·키 입력을 전달합니다.
첫 메시지는 Enter로, 후속 메시지는 전송 버튼으로 보내 두 입력 경로를 함께 검증합니다.
API 테스트의 내부 메서드 호출과 단위 검사를 사람의 클릭 검사로 보고하지 않습니다.
추가 데스크톱 검증은 Windows Computer Use의 시스템 입력과 Windows 화면 캡처로 수행하며 `Test/desktop_review/`에 별도로 기록합니다.

## 실행

프로젝트 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m tools.run_tests --suite unit
.\.venv\Scripts\python.exe -m tools.run_tests --suite api
.\.venv\Scripts\python.exe -m tools.run_tests --suite native
.\.venv\Scripts\python.exe -m tools.run_tests --suite ui
.\.venv\Scripts\python.exe -m tools.run_tests --suite all
```

`all`은 단계를 서로 다른 프로세스로 실행합니다. 단위 검사에서 사용하는 offscreen 설정이 실제 화면 검사를 방해하지 않도록 했습니다.
`ui`와 `native`는 Windows 데스크톱이 필요합니다. 실행 중에는 해당 창을 직접 조작하지 마세요.
API·UI 검사는 실제 호출량을 사용합니다. `.env`의 Gemini 키를 읽으며, 키가 없으면 건너뜀으로 기록합니다.
건너뛴 단계는 전체 성공으로 처리하지 않습니다. 실패 시 로그와 이미지를 유지합니다.

## 저장 구조

```text
Test/
  latest_run.txt
  runs/20261111_230302_403967/
    summary.json
    ui.log
    ui/
      evidence.json
      settings.ini
      01_start.png
      02_settings.png
      03_connection_success.png
      04_typed_1.png
      05_reply_1.png
      06_bubble_1.png
      04_typed_2.png
      05_reply_2.png
      06_bubble_2.png
  desktop_review/
    Windows 시스템 입력 검증 화면과 evidence.json
```

`summary.json`에는 실행한 테스트 수·종료 코드·성공/실패/건너뜀·소요 시간이 있습니다.
`ui/evidence.json`에는 실제 수행한 단계, 응답 길이, 모델 이름과 스크린샷 경로가 있습니다.
실제 테스트에 사용한 API 키는 로그나 설정 파일에 쓰지 않으며 화면에서는 마스킹합니다.
테스트 설정은 `Test`의 별도 INI 파일에 저장하므로 사용자의 원래 설정을 덮어쓰지 않습니다.

## 캡처 방식 확인

UI 테스트는 먼저 네이티브 창 캡처를 사용합니다. 투명한 도구 창 등에서 Windows 캡처가 검은색을 반환하면
표시 중인 Qt 위젯 렌더링으로 저장하고 `capture_method`에 그 사실을 명시합니다.
이 대체 캡처를 Windows 화면 캡처라고 표시하지 않습니다. Windows Computer Use 검증의 캡처는 별도 보관합니다.

스크린샷은 성공 단계를 확인한 다음에 저장하며, 실패한 단계도 `failure_*.png`와 오류 기록을 남깁니다.
이미지 파일이 존재한다는 것만으로 테스트 성공을 판단하지 않습니다.

## 수동 화면 점검용 앱

```powershell
.\.venv\Scripts\python.exe -m tools.review_app
```

실제 앱 UI를 `메애기 UI 검증`이라는 제목으로 열고, 테스트 설정 파일과 실제 `.env`를 사용합니다.
일반 앱은 `.\.venv\Scripts\python.exe main.py` 또는 `.\.venv\Scripts\python.exe -m maeagi_biseo`로 실행합니다.

## Gemini CLI 진단

### 연결·후속 대화 검사

기본 실행은 `.env` 또는 환경 변수의 실제 키로 Google API를 호출해 첫 답변과 후속 대화를 확인합니다.

```powershell
.\.venv\Scripts\python.exe -m tools.gemini_test
```

설정창의 실제 모델 조회·응답과 채팅창의 실제 후속 대화·말풍선 연결은 다음 명령으로 검사합니다.

```powershell
.\.venv\Scripts\python.exe -m tools.run_tests --suite api
```

이 검사는 실제 Gemini를 호출합니다. 키가 없으면 검사하지 못한 항목을 명시적으로 건너뛰며, 고정 응답으로 대체하지 않습니다.
### 모델 목록과 모델 지정

모델 목록만 조회하려면 다음 명령을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m tools.gemini_test --list-models
```

목록에서 모델 ID를 골라 첫 답변과 후속 대화를 확인합니다. 이 명령은 답변을 두 번 생성하므로 API 사용량이 발생합니다.

```powershell
.\.venv\Scripts\python.exe -m tools.gemini_test --model "조회한_모델_ID"
```

모델을 생략하면 `GEMINI_MODEL`을 사용합니다. 이 항목도 없으면 실제 목록에 `gemini-flash-latest`가 있을 때 우선 선택하고,
없으면 미리보기보다 정식 버전, 오래된 버전보다 새 Flash 버전을 우선 선택합니다.
이미지·음성 전용으로 알려진 이름은 기본 목록에서 제외하지만 모델 ID를 직접 입력할 수 있습니다.
모델 이용 가능 여부와 한도는 계정·프로젝트에 따라 다릅니다. 오류가 나면 결과의 HTTP 상태와 서버 안내를 확인하세요.
목록에 있더라도 계정에서 생성을 허용하지 않는 모델이 있을 수 있습니다. 오류 시 모델 목록과 서버 안내를 확인하세요.

## 화면 캡처 진단

기본 설치에 캡처·로컬 OCR 의존성이 포함됩니다. 프로젝트 루트에서 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m tools.run_tests --suite capture
```

### 보유 메소 UI 캡처 확인

다음은 개발용 자동 탐지 CLI입니다. 일반 설정창의 자동 탐지·영역 보정 사용법은 [README](../README.md)를 참고하세요.
`Images/Capture/Meso.png`의 동전과 오른쪽 테두리를 함께 찾아 금액을 포함한 전체 UI를 잘라냅니다.
`Images/Capture/Meso2.png`처럼 가로 비율이 다른 UI도 별도 레이아웃으로 자동 탐지하며 OCR 영역도 함께 보정합니다.
`result.json`의 `layout`에 선택된 기준 이미지가 기록됩니다.
숫자 영역은 탐지 기준에서 제외하며, 버전 2에서는 Windows 내장 한국어 OCR로 금액을 읽습니다.
LLM에 전송하지 않습니다.
메이플 창 안에서 메소 UI를 열어 두세요. 다른 앱이 메이플 창을 가려도 창 자체를 캡처합니다. 최소화는 지원하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m tools.meso_capture
.\.venv\Scripts\python.exe -m tools.meso_capture --image "game.png"
.\.venv\Scripts\python.exe -m tools.run_tests --suite meso
```

캡처 결과는 `Test/meso/실행시각/`에 원본·좌표·탐지 점수·크롭·확대본으로 저장합니다.
전용 테스트는 위치·배율·금액 변경, 미탐지, 동전만 있을 때 오탐 여부, CLI 파일 저장과
설정창 성공·실패·오류 표시를 검증합니다. 로그와 확인용 이미지는 `Test/runs/실행시각/`에 저장합니다.
설정창 테스트 이미지는 모의 결과를 사용한 Qt 렌더링이며 실제 게임 캡처 증거와 구분됩니다.

### 솔 에르다 UI 캡처 확인

다음은 개발용 자동 탐지·스크린샷 CLI입니다. 기본 의존성 설치 후 사용할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m tools.sol_erda_capture
# 저장한 게임 스크린샷으로 오프라인 확인
.\.venv\Scripts\python.exe -m tools.sol_erda_capture --image "game.png"
.\.venv\Scripts\python.exe -m unittest tests.unit.test_sol_erda_capture -v
# 로그, 결과 JSON, 탐지 이미지, 설정창 미리보기를 Test/runs/ 아래에 저장
.\.venv\Scripts\python.exe -m tools.run_tests --suite sol-erda
```

실행 후 3초 안에 메이플 창 안에서 솔 에르다 UI를 열어 두세요. 메이플 창은 최소화하지 않으면 다른 창 뒤에 있어도 됩니다.
룬타이머처럼 DPI를 보정한 실제 화면 좌표와 Windows Graphics Capture를 사용하며, 메이플 클라이언트 안에서
`Images/Capture/Sol Erda.png`의 두 아이콘을 함께 찾아 전체 UI를 잘라냅니다. 수량 영역은 매칭에서 제외합니다.
원본 대비 0.75~2배 크기를 탐색하며, 탐지 기준은 `--threshold 0.80`으로 조절할 수 있습니다.

`Test/sol_erda/실행시각/`에 원본 `source.png`, 탐지 좌표와 점수 `result.json`을 저장합니다.
탐지 성공 시 빨간 테두리 `detected.png`, 로컬 OCR용 크롭 `sol_erda.png`, 확인용 확대본
`sol_erda_4x.png`도 저장합니다. 실패 시 잘못된 크롭을 저장하지 않고 종료 코드 2를 반환합니다.
버전 2에서는 로컬 RapidOCR로 오른쪽 조각 수량을 읽습니다. 왼쪽 에르다 진행도는 읽지 않습니다.
LLM에는 전송하지 않습니다. 게임 UI 크기·테마·가림에 따라
실제 탐지 정확도는 저장된 결과로 확인해야 합니다.

### 내부 OCR 검증

```powershell
.\.venv\Scripts\python.exe -m tools.run_tests --suite ocr
```

`Test/runs/실행시각/ocr/`에는 실제 OCR의 입력·전처리 이미지·원문·판독값·기대값을 저장합니다.
설정창 이미지는 모의 결과 표시 테스트이며, 실제 로컬 OCR 테스트와 구분됩니다.
일반 캡처 폴더의 `result.json`에도 `version: 2`와 `ocr` 결과가 추가됩니다.
캡처 CLI의 종료 코드 0은 UI 탐지 성공이며, OCR 성공은 `ocr.status == "ok"`로 확인합니다.

OCR 정확도는 테스트 입력 범위에 한정됩니다. 다른 금액·수량·게임 배율은 새 스크린샷으로 확인하세요.
Windows 한국어 OCR 언어가 없으면 메소는 판독 불가를 표시합니다.
`역`을 `억`으로 읽은 경우 숫자 뒤 단위 위치에 한해서 보정하고 원문을 함께 저장합니다.
내부 OCR 방식은 외부 API를 호출하지 않으며, RapidOCR는 설치 패키지에 포함된 로컬 모델을 사용합니다.

## 재획 기록 검증

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_farming tests.unit.test_tool_chat tests.unit.test_farming_ui -v
.\.venv\Scripts\python.exe -m unittest tests.integration.test_farming_tools_live -v
```

실제 Gemini 도구 호출 검사는 별도 테스트 DB를 사용하며 게임 캡처나 실제 재획 기록을 변경하지 않습니다. API 사용량은 발생합니다.

## 백그라운드 창 캡처 검증

```powershell
.\.venv\Scripts\python.exe -m tools.run_tests --suite native
```

서로 다른 색의 실제 Windows 창을 겹쳐 놓고, 뒤쪽 창의 픽셀이 캡처되는지와 캡처 전후 포커스가 유지되는지 확인합니다. 단위 검사는 캡처 시간 초과·창 종료·프레임 변환 실패 시 세션 종료를 확인합니다. 재획 판독 준비 중 메애기·대화창·대화 타이머가 유지되는지도 검사합니다.

실제 게임에서의 판독은 메이플 창을 최소화하지 않고 메소·솔 에르다 UI를 열어 둔 뒤 캡처 CLI로 확인합니다. 결과 JSON의 capture_method는 windows_graphics_capture입니다. 화면 캡처 실패를 데스크톱 캡처로 대체하지 않습니다.
