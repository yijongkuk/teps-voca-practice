# TEPS 단어 반복 연습장

엑셀 단어장 `src/TEPS_VOCA.xlsx`를 바탕으로 만든 웹용 TEPS 단어 반복 학습장입니다.

## 기능

- 5청크 압축 회전 학습
- Day별 자동 청크 순서
- Easy / Familiar / Hard / Critical 상태 체크
- 카드 훑기, 뜻 가리기, 예문 빈칸, 한글 뜻 -> 영어 타이핑
- Hard 단어 압축 복습
- 브라우저 TTS 기반 단어/예문 듣기
- 브라우저 localStorage 진도 저장
- 진도 JSON 내보내기/불러오기

## 학습 회전

- Day 1: Chunk 1
- Day 2: Chunk 1 -> 2
- Day 3: Chunk 1 -> 2 -> 3
- Day 4: Chunk 1 -> 2 -> 3 -> 4
- Day 5: Chunk 1 -> 2 -> 3 -> 4 -> 5
- Day 6 이후: Chunk 2 -> 3 -> 4 -> 5 -> 1처럼 5청크를 계속 회전

## 데이터 다시 생성

엑셀 원본을 수정한 뒤 아래 명령으로 웹 데이터 파일을 다시 만들 수 있습니다.

```powershell
python src\generate_words_data.py
```

생성 결과는 `src/words-data.js`에 저장됩니다.
