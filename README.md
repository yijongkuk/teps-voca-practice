# 단어 반복 연습장

TEPS 어휘빈출 단어장 `src/TEPS_Voca(통합).xlsx`, TEPS 접속사 단어장 `src/TEPS_Reading_9-10_Connectors.xlsx`, Oxford 5000 추가 목록, AWL570, Hackers TOEFL Vocabulary 스캔본에서 뽑아낸 TOEFLVOCA를 바탕으로 만든 웹용 단어 반복 학습장입니다.

## 기능

- 10일 5청크 롤링 루틴 학습
- Day별 최근 5개 청크 반복 순서
- 테스트에서 모르는 단어로 남은 최고 차수(1차, 2차, 3차) 기록
- 기본 세션을 열 때 첫 미확인 단어 위치로 이동
- 카드 훑기, 뜻 가리기, 예문 빈칸, 한글 뜻 -> 영어 타이핑
- 100/150/200개를 한 번에 확인하는 별도 단어 테스트 페이지
- 테스트 표의 뜻·예문 개별 공개 및 열 전체 공개, 단어별 `안다` 체크
- 이미 출제한 단어를 제외한 `새 단어만` 출제 또는 `포함해서 랜덤` 출제 선택
- 일반 학습장과 테스트의 영어 예문에서 단어나 구문을 드래그해 저장
- 최초 테스트 묶음을 유지한 채 체크하지 않은 단어만 반복하는 끝장 복습
- CMUdict 기반 발음기호 표시와 독립 스피커 버튼 음성 재생
- 테스트 반복 단어 집중 복습과 차수 높은 순 정렬
- TEPS 어휘빈출 / TEPS 접속사 / Oxford 5000 / AWL570 / TOEFLVOCA 단어장별 필터와 독립 청크
- TOEFLVOCA 카드의 뜻별 동의어와 반의어 표시
- 표제어, 뜻, 예문, AWL 관련 어형 통합 검색
- 브라우저 TTS 기반 단어/예문 듣기
- 브라우저 localStorage 진도 저장
- 테스트 목록과 `안다` 체크 결과를 별도 localStorage 세션으로 저장
- 진도 JSON 내보내기/불러오기

## 단어 테스트

학습장 오른쪽 위의 `단어 테스트`에서 단어장, 학습 기록 범위, 이미 출제한 단어
처리 방식, 출제 개수를 고른 뒤 새 테스트를 만들 수 있습니다. `이미 출제한 단어`를
`새 단어만`으로 두면 지금까지 테스트에 나온 단어는 제외하고 아직 출제하지 않은
단어만 뽑아 계속 새로운 단어를 학습할 수 있고, `포함해서 랜덤`으로 두면 기존 단어까지
모두 포함해 무작위로 뽑습니다. 단어를 먼저 보고 뜻·예문 셀을 눌러 정답을 확인하고,
아는 단어만 체크하면 됩니다. 현재 단어 순서, 공개한 답, 체크 결과는 새로고침해도
유지됩니다. `모르는 단어만 반복`을 누르면 새 단어 묶음으로 넘어가지 않고 현재
테스트에서 체크하지 않은 단어만 남습니다. 처음 뽑은 단어를 모두 알게 될 때까지
그날 같은 테스트 안에서 반복할 수 있습니다. 테스트 표의 단어 오른쪽에는 등록된
발음기호가 표시되고, 단어 오른쪽의 스피커 버튼을 누르면 영어 음성을 들을 수
있습니다. 반복 버튼을 누를 때 남은 단어에는 1차, 2차, 3차 기록이 누적되며 일반
단어장에도 최고 차수가 계속 표시됩니다. 공개한 영어 예문에서 단어나 구문을
드래그하면 일반 단어장의 `저장 단어` 목록에 함께 저장됩니다.

## 학습 루틴

- Day 1: Chunk 1
- Day 2: Chunk 1 + Chunk 2
- Day 3: Chunk 1 + Chunk 2 + Chunk 3
- Day 4: Chunk 1 + Chunk 2 + Chunk 3 + Chunk 4
- Day 5: Chunk 1 + Chunk 2 + Chunk 3 + Chunk 4 + Chunk 5
- Day 6: Chunk 2 + Chunk 3 + Chunk 4 + Chunk 5 + Chunk 6
- Day 7: Chunk 3 + Chunk 4 + Chunk 5 + Chunk 6 + Chunk 7
- Day 8: Chunk 4 + Chunk 5 + Chunk 6 + Chunk 7 + Chunk 8
- Day 9: Chunk 5 + Chunk 6 + Chunk 7 + Chunk 8 + Chunk 9
- Day 10: Chunk 6 + Chunk 7 + Chunk 8 + Chunk 9 + Chunk 10
- 이후 같은 방식으로 최근 5개 Chunk만 묶어 반복 (Day 11부터는 Chunk 1로 다시 순환)

각 단어장을 원본 순서대로 10개 청크에 독립적으로 균등 분배합니다. 하루치 단어는 이후 4일간 더 복습 대상에 포함되어 총 5일에 걸쳐 반복됩니다.

TOEFLVOCA만 예외로 15개 청크를 씁니다. 원본 책이 60일 구성이라 4일치를 한 청크로 묶어 15일 완성으로 회전합니다. 즉 Chunk 1은 책의 DAY 01-04, Chunk 15는 DAY 57-60입니다. 회전 주기가 다른 단어장은 대시보드에서 각각 별도 줄로 표시됩니다.

정답·오답을 확인했거나 카드에서 `다음`, `이전`, 세션 목록 이동으로 지나간 단어는 본 단어로 저장됩니다. 같은 조건으로 다시 열면 목록은 유지하되 첫 미확인 단어 위치에서 시작합니다.

## 데이터 다시 생성

의존성을 설치하고 아래 명령으로 웹 데이터 파일을 다시 만들 수 있습니다.

```powershell
python -m pip install -r requirements.txt
python src\generate_words_data.py
```

생성 결과는 `src/words-data.js`에 저장됩니다.

발음기호 데이터는 CMU Pronouncing Dictionary를 IPA로 변환한 `src/pronunciations.json`을 사용합니다. 발음 사전을 새로 받은 뒤 아래처럼 다시 만들 수 있습니다.

```powershell
python src\generate_pronunciations.py C:\tmp\cmudict.dict
python src\generate_words_data.py
```

## Oxford 5000 / AWL570 원본 갱신

Oxford가 제공하는 PDF는 Oxford 3000에 더해지는 2,000개 항목입니다. 뜻별로 중복된 `counter`, `grave`, `strip`을 철자 기준으로 합쳐 앱에는 1,997개 고유 표제어가 들어갑니다. AWL은 10개 서브리스트의 570개 표제어와 관련 어형을 함께 저장합니다.

```powershell
python src\generate_external_word_lists.py
python src\generate_external_word_details.py
python src\generate_words_data.py
```

- Oxford source: https://www.oxfordlearnersdictionaries.com/external/pdf/wordlists/oxford-3000-5000/American_Oxford_5000.pdf
- AWL source: https://www.eapfoundation.com/vocab/academic/awllists/

## TOEFLVOCA 원본 갱신

`src/03 TOEFLVOCA.pdf`는 OCR 텍스트 레이어가 붙은 스캔본이라 글자가 깨진 곳이 많습니다.
`src/generate_toefl_word_list.py`는 글자 대신 지면 배치를 읽어 표제어(왼쪽 열에서 가장 큰
글씨), 발음기호, 반의어, 품사별 동의어, 예문을 분리하고, 깨진 철자는 책 색인 페이지와 예문에서
만든 어휘 목록으로 복구합니다. PDF는 용량이 커서 저장소에 넣지 않으므로 `src/` 아래에 직접
두고 실행하세요. 결과는 `src/toefl_word_list.json`에 저장되고 `_meta`에 복구 통계와 끝내 복구하지
못한 항목이 남습니다.

```powershell
python src\generate_toefl_word_list.py
python src\generate_external_word_details.py
python src\generate_words_data.py
python src\generate_example_translations.py --only-suspect
```

- 원본: Hackers TOEFL Vocabulary (60일 구성, 약 2,300 표제어)
- `--cmudict <경로>`로 CMUdict를 넘기면 철자 복구용 사전이 넓어집니다.
