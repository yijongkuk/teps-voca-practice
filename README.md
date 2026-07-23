# 단어 반복 연습장

TEPS 어휘빈출 단어장 `src/TEPS_Voca(통합).xlsx`(`어휘단어장(통합)` 시트), Oxford 5000 추가 목록, AWL570을 바탕으로 만든 웹용 단어 반복 학습장입니다.

## 기능

- 10일 5청크 롤링 루틴 학습
- Day별 최근 5개 청크 반복 순서
- Easy / Familiar / Hard / Critical 상태 체크
- 기본 세션을 열 때 첫 미확인 단어 위치로 이동
- 카드 훑기, 뜻 가리기, 예문 빈칸, 한글 뜻 -> 영어 타이핑
- CMUdict 기반 발음기호 표시
- Hard 단어 압축 복습
- TEPS 어휘빈출 / Oxford 5000 / AWL570 단어장별 필터와 독립 청크
- 표제어, 뜻, 예문, AWL 관련 어형 통합 검색
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

각 단어장을 원본 순서대로 10개 청크에 독립적으로 균등 분배합니다. 하루치 단어는 이후 4일간 더 복습 대상에 포함되어 총 5일에 걸쳐 반복됩니다.

난이도 체크를 했거나 카드에서 `다음`, `이전`, 세션 목록 이동으로 지나간 단어는 본 단어로 저장됩니다. 같은 조건으로 다시 열면 목록은 유지하되 첫 미확인 단어 위치에서 시작합니다.

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
