# TEPS 단어 반복 연습장

빈출 단어장 `src/TEPS_Voca(통합).xlsx`(`어휘단어장(통합)` 시트)를 바탕으로 만든 웹용 TEPS 단어 반복 학습장입니다.

## 기능

- 10일 5청크 롤링 루틴 학습
- Day별 최근 5개 청크 반복 순서
- Easy / Familiar / Hard / Critical 상태 체크
- 기본 세션을 열 때 첫 미확인 단어 위치로 이동
- 카드 훑기, 뜻 가리기, 예문 빈칸, 한글 뜻 -> 영어 타이핑
- CMUdict 기반 발음기호 표시
- Hard 단어 압축 복습
- 브라우저 TTS 기반 단어/예문 듣기
- 브라우저 localStorage 진도 저장
- 진도 JSON 내보내기/불러오기

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

빈출 단어 1,535개를 원본 순위 순서대로 10개 청크(하루치 약 150개)에 균등하게 나눕니다. 하루치 단어는 이후 4일간 더 복습 대상에 포함되어 총 5일에 걸쳐 반복됩니다.

난이도 체크를 했거나 카드에서 `다음`, `이전`, 세션 목록 이동으로 지나간 단어는 본 단어로 저장됩니다. 같은 조건으로 다시 열면 목록은 유지하되 첫 미확인 단어 위치에서 시작합니다.

## 데이터 다시 생성

엑셀 원본 `src/TEPS_Voca(통합).xlsx`를 수정한 뒤 아래 명령으로 웹 데이터 파일을 다시 만들 수 있습니다.

```powershell
python src\generate_words_data.py
```

생성 결과는 `src/words-data.js`에 저장됩니다.

발음기호 데이터는 CMU Pronouncing Dictionary를 IPA로 변환한 `src/pronunciations.json`을 사용합니다. 발음 사전을 새로 받은 뒤 아래처럼 다시 만들 수 있습니다.

```powershell
python src\generate_pronunciations.py C:\tmp\cmudict.dict
python src\generate_words_data.py
```
