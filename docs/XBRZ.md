# xBRZ 연동

편집창의 **도트 계단 줄이기 → xBRZ · 도트 보정**을 선택합니다.
미리보기와 저장은 동일한 xBRZ 처리 코드를 사용합니다. **원본 비교**를 체크하면
보정 전 이미지를 볼 수 있습니다. 기존 Scale2x와 사용 안 함도 유지됩니다.

- 2배·4배: 해당 배율의 xBRZ 결과를 직접 저장합니다.
- 확대 사용 안 함: xBRZ 2배 처리 후 원래 해상도로 Lanczos 축소합니다.
- 화면 표시 크기, 프레임 시간과 발 위치는 유지됩니다.
- 저장한 결과에 다시 적용하면 효과가 누적되므로 원본에서 비교하세요.

## 구현과 재현

[@kayahr/xbrz](https://github.com/kayahr/xbrz) 1.1.2의 실제 xBRZ WASM 포트를
Python `wasmtime`으로 실행합니다. JavaScript나 별도 C++ 컴파일러 없이 로컬에서
처리하며 런타임 네트워크 요청은 없습니다. 5-bit LUT를 사용합니다.

- upstream commit: `bab2980d2e7db4f292cbc48c459a7398fa4ea643`
- WASM SHA-256: `8bd19c2446e4e2a694cd9f12034e5d3e7bd08117d28befdc9dbea2e28aa65093`
- 원본 소스와 빌드 설정: `third_party/xbrz/`
- 라이선스: GPL-3.0-only, 원문 `licenses/xbrz/LICENSE.md`
- Python 어댑터: `maeagi_biseo/core/xbrz.py`

Python 3.12 가상환경에서 `python -m tools.vendor_xbrz`를 실행하면 고정 버전의
npm 배포물을 SHA-512로 검증한 뒤 WASM과 해당 커밋 소스·기준 이미지를 가져옵니다.
평소 실행과 빌드에는 다운로드가 필요하지 않습니다.

배포 시 xBRZ의 GPL-3.0 조건에 따라 고지와 대응 소스 제공 의무를 준수해야 합니다.
PyInstaller 설정에 WASM, Wasmtime 네이티브 런타임, 라이선스 및 대응 소스를 포함합니다.

검증: Python 3.12에서 `python -m unittest tests.unit.test_upscale -v`.
공식 투명 이미지의 2배·4배 기준 결과와 RGBA 픽셀을 비교하며 저장과 미리보기의
일치, 프레임 정보 유지, 크기 제한도 검사합니다.
