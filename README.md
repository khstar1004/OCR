# KSMRO OCR 프로젝트

KSMRO 웹사이트의 상품 정보를 크롤링하고 비법정단위를 검출하는 도구입니다.

## 프로젝트 구조

```
src/
├── crawler/                  # 웹 크롤링 관련 코드
│   └── ksmro_crawler.py      # KSMRO 웹사이트 크롤러
├── data/                     # 데이터 저장 디렉토리
│   ├── cache/                # 이미지 캐시 디렉토리
│   └── output/               # 결과 저장 디렉토리
├── logs/                     # 로그 파일 디렉토리
├── ocr/                      # OCR 처리 관련 코드
│   └── processor.py          # OCR 텍스트 및 이미지 처리기
├── tests/                    # 테스트 코드
│   └── test_crawl_ocr.py     # 크롤링 및 OCR 테스트
├── utils/                    # 유틸리티 코드
│   ├── config.py             # 설정 파일
│   ├── logger.py             # 로깅 유틸리티
│   ├── memory_manager.py     # 메모리 관리 유틸리티
│   └── report_generator.py   # 결과 보고서 생성기
└── main.py                   # 메인 실행 파일
```

## 사용 방법

### 기본 사용법

```bash
python src/main.py [옵션]
```

### 주요 옵션

- 입력 소스 옵션 (다음 중 하나 필수):
  - `--scan-all`: 모든 카테고리 스캔
  - `--url URL`: 단일 상품 URL 처리
  - `--url-file PATH`: 상품 URL 목록 파일 처리
  - `--category URL`: 카테고리 URL 처리
  - `--search KEYWORD`: 검색어로 상품 찾기
  - `--id-patterns PATTERNS`: 상품 ID 패턴 (쉼표로 구분)
  - `--id-range START-END`: ID 범위 (예: 10000-20000)
  - `--id-file PATH`: ID 목록 파일
  - `--id-pattern-hint HINT`: ID 패턴 힌트 (예: 102XXXXX)

- 일반 옵션:
  - `--output PATH`: 결과 Excel 파일 경로 (기본값: ksmro_report.xlsx)
  - `--threads N`: 병렬 처리 스레드 수 (기본값: 4)
  - `--no-cache`: 이미지 캐시 사용하지 않음
  - `--max-pages N`: 카테고리/검색 결과에서 크롤링할 최대 페이지 수 (기본값: 5)
  - `--export-ids`: 발견된 상품 ID 저장
  - `--detailed-log`: 상세 로그 출력
  - `--resume PATH`: 이전 세션에서 재개 (JSON 파일 경로)
  - `--save-state PATH`: 현재 세션 상태 저장 (JSON 파일 경로)

### 사용 예제

1. 단일 상품 URL 처리:
```bash
python src/main.py --url "https://ksmro.com/product/12345"
```

2. ID 패턴으로 검색:
```bash
python src/main.py --id-patterns "1234567,1234568,1234569" --threads 8
```

3. ID 범위 처리:
```bash
python src/main.py --id-range "10000-11000" --output "range_results.xlsx"
```

4. 이전 세션 이어서 처리:
```bash
'python src/main.py --scan-all' --save-state "session.json" --resume "session.json"
```

## 주요 기능

- **웹 크롤링**: Selenium과 Requests를 활용한 동적/정적 페이지 크롤링
- **OCR 처리**: Tesseract + EasyOCR 조합으로 이미지 텍스트 추출
- **단위 검출**: 인치, 피트, 온스 등 7가지 비법정 단위 자동 식별
- **보고서 생성**: 엑셀 형식의 상세 분석 보고서 출력
- **메모리 관리**: 대용량 데이터 처리에 최적화된 메모리 관리 시스템
- **세션 관리**: 중단된 크롤링 작업을 이어서 진행할 수 있는 기능

## 설치 방법

### 1. 필수 요구사항

- Python 3.7 이상
- Chrome 브라우저 (v100 이상)
- Tesseract OCR 5.0+ (한국어 언어팩 필수)

### 2. 패키지 설치

```bash
# 필요한 패키지 설치
pip install -r requirements.txt
```

### 3. Tesseract 설치

#### Windows
1. [공식 설치파일](https://github.com/UB-Mannheim/tesseract/wiki) 다운로드
2. 설치 시 한국어 언어팩 선택
3. 환경변수에 Tesseract 경로 추가 (예: C:\Program Files\Tesseract-OCR)

#### macOS
```bash
brew install tesseract tesseract-lang
```

#### Linux
```bash
sudo apt install tesseract-ocr tesseract-ocr-kor
```

## 디렉토리 설명

- **crawler/**: 웹 페이지 크롤링 기능을 담당하는 모듈
- **ocr/**: 이미지와 텍스트에서 비법정단위를 검출하는 OCR 모듈
- **utils/**: 설정, 로깅, 메모리 관리 등 유틸리티 함수
  - config.py: 프로그램 설정 클래스
  - logger.py: 로그 기록 설정 및 유틸리티
  - memory_manager.py: 메모리 사용량 관리 및 최적화
  - report_generator.py: 검출 결과 보고서 생성
- **data/**: 데이터 저장소 (캐시 및 결과)
- **logs/**: 로그 파일 저장 디렉토리
- **tests/**: 단위 테스트 및 통합 테스트 코드
- **main.py**: 프로그램 메인 진입점

## 문제 해결

**Q: ChromeDriver 버전 오류 발생 시**  
A: 현재 Chrome 버전과 일치하는 드라이버 설치
   [ChromeDriver 다운로드 페이지](https://chromedriver.chromium.org/) 방문

**Q: 한글 OCR 인식률 저하 시**  
A: Tesseract 한국어 데이터 재설치
```bash
sudo apt install tesseract-ocr-kor  # Ubuntu/Debian
brew reinstall tesseract-lang       # macOS
```

**Q: 메모리 사용량이 너무 높을 때**  
A: 배치 처리 크기 조정
```bash
python src/main.py --scan-all --threads 2  # 스레드 수 줄이기
```

## 라이센스

MIT License. 자세한 내용은 LICENSE 파일 참조.

## 문의

- 이슈 트래커: https://github.com/your-repo/ksmro-unit-detector/issues
- 이메일: jamesen1004@gmail.com
