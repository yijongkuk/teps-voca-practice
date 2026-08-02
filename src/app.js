(() => {
  "use strict";

  const words = Array.isArray(window.TEPS_WORDS) ? window.TEPS_WORDS : [];
  const meta = window.TEPS_META || {};
  const progressKey = "teps-voca-progress-v1";
  const settingsKey = "teps-voca-settings-v1";
  const savedWordsKey = "teps-voca-saved-example-words-v1";

  const modeLabels = {
    cards: "카드 훑기",
    meaning: "뜻 가리기",
    cloze: "예문 빈칸",
    typing: "한글 뜻 → 영어",
    retry: "재시험 단어 집중",
  };

  const routineChunkCount = 10;
  // TOEFLVOCA condenses the book's 60 days into 15 chunks, so it rolls over a
  // longer cycle than the shared 10-chunk lists.
  const sourceChunkCounts = Object.assign(
    { toefl: 15 },
    meta.chunkCountsBySource && typeof meta.chunkCountsBySource === "object"
      ? meta.chunkCountsBySource
      : {},
  );
  const maxChunkCount = Math.max(
    routineChunkCount,
    ...Object.values(sourceChunkCounts).map((value) => Number(value) || 0),
  );
  const reviewWindowDays = 5;
  const autoPlayPauseMs = 450;
  const wordSpeechDelayMs = 1000;

  const defaultSettings = {
    day: 1,
    mode: "cards",
    source: "all",
    chunk: "today",
    retryStage: "all",
    order: "schedule",
    limit: "50",
    search: "",
  };

  let progress = normalizeProgress(loadJson(progressKey, {}));
  let settings = normalizeSettings({ ...defaultSettings, ...loadJson(settingsKey, {}) });
  let savedWords = normalizeSavedWords(loadJson(savedWordsKey, []));
  let sidePanelView = "queue";
  let pendingExampleSelection = null;
  let queue = [];
  let currentIndex = 0;
  let revealed = false;
  let feedback = null;
  let autoPlay = {
    active: false,
    token: 0,
    pauseTimer: null,
  };
  let speechDelayTimer = null;

  const $ = (selector) => document.querySelector(selector);

  function loadJson(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) || fallback;
    } catch {
      return fallback;
    }
  }

  function normalizeProgress(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function readStoredProgress() {
    return normalizeProgress(loadJson(progressKey, {}));
  }

  function normalizeSettings(value) {
    const next = { ...defaultSettings, ...value };
    if (next.mode === "hard") {
      next.mode = "cards";
    }
    if (!["cards", "meaning", "cloze", "typing", "retry"].includes(next.mode)) {
      next.mode = "cards";
    }
    if (next.order === "hard") {
      next.order = "schedule";
    }
    if (!["schedule", "rank", "retry"].includes(next.order)) {
      next.order = "schedule";
    }
    next.retryStage = ["all", "1", "2", "3"].includes(String(next.retryStage))
      ? String(next.retryStage)
      : "all";
    delete next.status;
    const selectedChunk = Number(next.chunk);
    if (/^\d+$/.test(String(next.chunk)) && (selectedChunk < 1 || selectedChunk > maxChunkCount)) {
      next.chunk = "today";
    }
    return next;
  }

  function normalizeSavedWords(value) {
    if (!Array.isArray(value)) {
      return [];
    }
    return value
      .filter((item) => item && typeof item === "object" && String(item.text || "").trim())
      .map((item, index) => ({
        id: String(item.id || `saved-${Date.now()}-${index}`),
        text: String(item.text || "").trim(),
        note: String(item.note || ""),
        sourceWordId: String(item.sourceWordId || ""),
        sourceWord: String(item.sourceWord || ""),
        exampleEn: String(item.exampleEn || ""),
        exampleKo: String(item.exampleKo || ""),
        createdAt: String(item.createdAt || new Date().toISOString()),
      }));
  }

  function readStoredSavedWords() {
    return normalizeSavedWords(loadJson(savedWordsKey, []));
  }

  function refreshSavedWordsFromStorage() {
    savedWords = readStoredSavedWords();
    renderQueue();
  }

  function saveProgress({ mergeRetryStages = true } = {}) {
    if (mergeRetryStages) {
      syncLatestRetryStages();
    }
    localStorage.setItem(progressKey, JSON.stringify(progress));
  }

  function saveSettings() {
    localStorage.setItem(settingsKey, JSON.stringify(settings));
  }

  function saveSavedWords() {
    localStorage.setItem(savedWordsKey, JSON.stringify(savedWords));
  }

  function todayKey() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function chunkCountForSource(source) {
    const count = Number(sourceChunkCounts[source]);
    return Number.isFinite(count) && count > 0 ? count : routineChunkCount;
  }

  function focusChunkForDay(day, chunkCount = routineChunkCount) {
    const safeDay = Math.max(1, Number(day) || 1);
    return ((safeDay - 1) % chunkCount) + 1;
  }

  function chunkOrderForDay(day, chunkCount = routineChunkCount) {
    const safeDay = Math.max(1, Number(day) || 1);
    const reviewWindowSize = Math.min(reviewWindowDays, safeDay);
    return Array.from({ length: reviewWindowSize }, (_, index) =>
      focusChunkForDay(safeDay - reviewWindowSize + index + 1, chunkCount),
    );
  }

  function routineForSource(day, source) {
    const chunkCount = chunkCountForSource(source);
    return {
      chunkCount,
      focusChunk: focusChunkForDay(day, chunkCount),
      dayOrder: chunkOrderForDay(day, chunkCount),
    };
  }

  function routinesBySource(day) {
    const routines = new Map();
    words.forEach((word) => {
      if (!routines.has(word.source)) {
        routines.set(word.source, routineForSource(day, word.source));
      }
    });
    return routines;
  }

  function getProgress(word) {
    const item = progress[word.id];
    return isProgressItem(item) ? item : {};
  }

  function ensureProgress(word) {
    if (!isProgressItem(progress[word.id])) {
      progress[word.id] = {
        seen: 0,
        correct: 0,
        wrong: 0,
        createdAt: new Date().toISOString(),
      };
    }
    return progress[word.id];
  }

  function normalizeRetryStage(value) {
    const stage = Number(value);
    return Number.isFinite(stage) ? Math.max(0, Math.floor(stage)) : 0;
  }

  function isProgressItem(value) {
    return value && typeof value === "object" && !Array.isArray(value);
  }

  function hasProgressBesidesRetryStage(item) {
    return Object.keys(item).some((key) => {
      if (["testRetryStage", "testRetryUpdatedAt", "createdAt"].includes(key)) {
        return false;
      }
      return key !== "status" || item[key] !== "New";
    });
  }

  function syncLatestRetryStages() {
    const latestProgress = readStoredProgress();
    const wordIds = new Set([...Object.keys(progress), ...Object.keys(latestProgress)]);

    wordIds.forEach((wordId) => {
      const latestItem = isProgressItem(latestProgress[wordId]) ? latestProgress[wordId] : {};
      const localItem = isProgressItem(progress[wordId])
        ? { ...progress[wordId] }
        : { ...latestItem };
      const localStage = normalizeRetryStage(localItem.testRetryStage);
      const latestStage = normalizeRetryStage(latestItem.testRetryStage);

      if (latestStage > 0) {
        localItem.testRetryStage = latestStage;
        if (latestItem.testRetryUpdatedAt) {
          localItem.testRetryUpdatedAt = latestItem.testRetryUpdatedAt;
        } else {
          delete localItem.testRetryUpdatedAt;
        }
        if (!localItem.createdAt && latestItem.createdAt) {
          localItem.createdAt = latestItem.createdAt;
        }
        progress[wordId] = localItem;
        return;
      }

      if (localStage > 0) {
        delete localItem.testRetryStage;
        delete localItem.testRetryUpdatedAt;
        if (hasProgressBesidesRetryStage(localItem)) {
          progress[wordId] = localItem;
        } else {
          delete progress[wordId];
        }
      }
    });
  }

  function refreshProgressFromStorage() {
    const currentWordId = queue[currentIndex]?.id;
    progress = readStoredProgress();
    rebuildAndRender(currentWordId);
  }

  function getRetryStage(word) {
    return normalizeRetryStage(getProgress(word).testRetryStage);
  }

  function retryStageClass(stage) {
    return `retry-stage-${Math.min(3, normalizeRetryStage(stage))}`;
  }

  function retryStagePill(stage, compact = false) {
    const safeStage = normalizeRetryStage(stage);
    if (!safeStage) {
      return "";
    }
    const label = compact ? `${safeStage}차` : `테스트 ${safeStage}차`;
    const compactClass = compact ? " queue-retry-stage" : "";
    return `<span class="retry-stage-pill ${retryStageClass(
      safeStage,
    )}${compactClass}" title="테스트에서 ${safeStage}차까지 모르는 단어로 남음">${label}</span>`;
  }

  function isRetryWord(word) {
    return getRetryStage(word) > 0;
  }

  function buildQueue() {
    const routines = routinesBySource(settings.day);
    const fallbackRoutine = routineForSource(settings.day, "");
    const routineFor = (word) => routines.get(word.source) || fallbackRoutine;
    const orderIndexFor = (word) => {
      const position = routineFor(word).dayOrder.indexOf(word.chunk);
      return position >= 0 ? position : reviewWindowDays + word.chunk;
    };
    const query = settings.search.trim().toLowerCase();

    let result = words.filter((word) => {
      const routine = routineFor(word);
      // A search is a global lookup. Applying the current study chunk first can
      // hide the requested headword and leave an unrelated example-text match.
      if (!query && settings.chunk === "today" && !routine.dayOrder.includes(word.chunk)) {
        return false;
      }
      if (!query && settings.chunk === "focus" && word.chunk !== routine.focusChunk) {
        return false;
      }
      if (!query && /^\d+$/.test(settings.chunk) && word.chunk !== Number(settings.chunk)) {
        return false;
      }
      if (settings.source !== "all" && word.source !== settings.source) {
        return false;
      }
      if (settings.mode === "retry" && !isRetryWord(word)) {
        return false;
      }
      if (settings.mode === "typing" && !word.meaning) {
        return false;
      }
      if (settings.mode === "cloze" && !String(word.clozeExample || "").includes("____")) {
        return false;
      }
      if (
        settings.retryStage !== "all" &&
        getRetryStage(word) < Number(settings.retryStage)
      ) {
        return false;
      }
      if (query) {
        const text = [
          word.word,
          word.meaning,
          word.expression,
          word.group,
          word.usageNote,
          ...(Array.isArray(word.searchTerms) ? word.searchTerms : []),
          word.exampleEn,
          word.exampleKo,
        ]
          .join(" ")
          .toLowerCase();
        if (!text.includes(query)) {
          return false;
        }
      }
      return true;
    });

    result.sort((a, b) => {
      if (query) {
        const searchRank = (word) => {
          const headword = String(word.word || "").toLowerCase();
          if (headword === query) {
            return 0;
          }
          if (headword.startsWith(query)) {
            return 1;
          }
          if (headword.includes(query)) {
            return 2;
          }
          const definition = [word.meaning, word.expression].join(" ").toLowerCase();
          return definition.includes(query) ? 3 : 4;
        };
        const rankDifference = searchRank(a) - searchRank(b);
        if (rankDifference) {
          return rankDifference;
        }
      }
      if (settings.order === "rank") {
        return sourceOrder(a) - sourceOrder(b) || a.rank - b.rank;
      }
      if (settings.order === "retry") {
        return (
          getRetryStage(b) - getRetryStage(a) ||
          sourceOrder(a) - sourceOrder(b) ||
          a.rank - b.rank
        );
      }
      return (
        orderIndexFor(a) - orderIndexFor(b) ||
        sourceOrder(a) - sourceOrder(b) ||
        a.rank - b.rank
      );
    });

    if (settings.limit !== "all") {
      result = limitQueueAroundFirstUnconfirmed(result, Number(settings.limit));
    }
    return result;
  }

  function sourceOrder(word) {
    const order = {
      frequent: 0,
      connectors: 1,
      oxford5000: 2,
      awl: 3,
      toefl: 4,
      vocab: 5,
      reading: 6,
    };
    return order[word.source] ?? 99;
  }

  function wordsForSelectedSource() {
    if (settings.source === "all") {
      return words;
    }
    return words.filter((word) => word.source === settings.source);
  }

  function isConfirmedWord(word) {
    const itemProgress = getProgress(word);
    return Boolean(
      itemProgress.viewed ||
        Number(itemProgress.seen || 0) > 0 ||
        Number(itemProgress.correct || 0) > 0 ||
        Number(itemProgress.wrong || 0) > 0 ||
        getRetryStage(word) > 0,
    );
  }

  function firstUnconfirmedItemIndex(items) {
    return items.findIndex((word) => !isConfirmedWord(word));
  }

  function limitQueueAroundFirstUnconfirmed(items, limit) {
    const safeLimit = Math.max(1, Number(limit) || items.length);
    if (items.length <= safeLimit) {
      return items;
    }

    const anchor = firstUnconfirmedItemIndex(items);
    if (anchor < 0) {
      return items.slice(0, safeLimit);
    }

    const contextCount = Math.min(5, Math.floor(safeLimit / 4));
    const start = Math.max(0, Math.min(anchor - contextCount, items.length - safeLimit));
    return items.slice(start, start + safeLimit);
  }

  function rebuildAndRender(targetId) {
    queue = buildQueue();
    if (targetId) {
      const found = queue.findIndex((word) => word.id === targetId);
      currentIndex = found >= 0 ? found : Math.min(currentIndex, Math.max(queue.length - 1, 0));
    } else {
      currentIndex = firstUnconfirmedIndex(queue);
    }
    renderDashboard();
    renderTrainer();
    renderQueue();
    syncControls();
  }

  function firstUnconfirmedIndex(items) {
    const found = firstUnconfirmedItemIndex(items);
    return found >= 0 ? found : Math.min(currentIndex, Math.max(items.length - 1, 0));
  }

  function renderDashboard() {
    const routines = routinesBySource(settings.day);
    const fallbackRoutine = routineForSource(settings.day, "");
    const dashboardWords = wordsForSelectedSource();
    const activeWords = dashboardWords.filter((word) =>
      (routines.get(word.source) || fallbackRoutine).dayOrder.includes(word.chunk),
    ).length;
    const today = todayKey();
    const seenToday = dashboardWords.filter((word) => {
      const itemProgress = getProgress(word);
      return itemProgress.lastSeen === today || itemProgress.lastViewed === today;
    }).length;
    const retryWords = dashboardWords.filter(isRetryWord).length;

    $("#totalWords").textContent = dashboardWords.length.toLocaleString("ko-KR");
    $("#activeWords").textContent = activeWords.toLocaleString("ko-KR");
    $("#seenToday").textContent = seenToday.toLocaleString("ko-KR");
    $("#retryWords").textContent = retryWords.toLocaleString("ko-KR");

    // Lists with different cycle lengths get their own strip so a 15-chunk
    // TOEFLVOCA day is never shown under the shared 10-chunk order.
    const cycles = new Map();
    dashboardWords.forEach((word) => {
      const routine = routines.get(word.source) || fallbackRoutine;
      const cycle = cycles.get(routine.chunkCount) || {
        routine,
        labels: [],
        words: [],
      };
      if (!cycle.labels.includes(word.sourceLabel)) {
        cycle.labels.push(word.sourceLabel);
      }
      cycle.words.push(word);
      cycles.set(routine.chunkCount, cycle);
    });

    const cycleList = [...cycles.values()].sort(
      (a, b) => a.routine.chunkCount - b.routine.chunkCount,
    );
    $("#chunkStrip").innerHTML = cycleList
      .map(({ routine, labels, words: cycleWords }) => {
        const chips = routine.dayOrder
          .map((chunk) => {
            const count = cycleWords.filter((word) => word.chunk === chunk).length;
            const label =
              chunk === routine.focusChunk ? "오늘 추가" : `${reviewWindowDays}일 복습`;
            return `
              <span class="chunk-chip ${chunk === routine.focusChunk ? "is-focus" : ""}">
                Chunk ${chunk}
                <small>${label} · ${count.toLocaleString("ko-KR")}개</small>
              </span>
            `;
          })
          .join("");
        const heading =
          cycleList.length > 1
            ? `<span class="chunk-cycle-label">${escapeHtml(
                labels.join(" · "),
              )} · ${routine.chunkCount}일 회전</span>`
            : "";
        return `<div class="chunk-cycle">${heading}${chips}</div>`;
      })
      .join("");

    const planText = cycleList
      .map(({ routine, labels }) => {
        const orderText = routine.dayOrder.map((chunk) => `Chunk ${chunk}`).join(" → ");
        return cycleList.length > 1 ? `${labels.join(" · ")} ${orderText}` : orderText;
      })
      .join(" / ");
    $("#planSummary").textContent = `Day ${settings.day}: ${planText}. 최근 ${reviewWindowDays}개 Chunk까지만 묶어서 반복 학습합니다.`;
  }

  function renderTrainer() {
    hideSelectionPopover();
    $("#sessionMode").textContent = modeLabels[settings.mode] || "카드 훑기";
    $("#positionText").textContent = queue.length ? `${currentIndex + 1} / ${queue.length}` : "0 / 0";

    const word = queue[currentIndex];
    if (!word) {
      $("#cardMeta").innerHTML = "";
      $("#cardBody").innerHTML = `
        <div class="empty-state">
          <h3>조건에 맞는 단어가 없습니다</h3>
          <p>청크, 테스트 반복, 검색어를 조금 넓히면 다시 목록이 만들어집니다.</p>
        </div>
      `;
      setNavigationDisabled(true);
      return;
    }

    const itemProgress = getProgress(word);
    $("#cardMeta").innerHTML = `
      <span class="badge">${escapeHtml(word.sourceLabel)}</span>
      <span class="badge">Chunk ${word.chunk}</span>
      <span class="badge">No. ${word.rank}</span>
      ${word.group ? `<span class="badge">${escapeHtml(word.group)}</span>` : ""}
      ${retryStagePill(getRetryStage(word))}
      <span class="muted">확인 ${Number(itemProgress.seen || 0)} · 정답 ${Number(
        itemProgress.correct || 0,
      )} · 오답 ${Number(itemProgress.wrong || 0)}</span>
    `;

    $("#cardBody").innerHTML = renderCardBody(word);
    bindCardEvents(word);
    setNavigationDisabled(false);
  }

  function renderCardBody(word) {
    if (settings.mode === "cloze") {
      return renderClozeMode(word);
    }
    if (settings.mode === "typing") {
      return renderTypingMode(word);
    }
    if (settings.mode === "meaning" || settings.mode === "retry") {
      return renderMeaningMode(word);
    }
    return renderCardsMode(word);
  }

  function renderCardsMode(word) {
    return `
      <div class="word-line">
        ${renderWordHeading(word)}
        <p>${renderMeaningText(word)}</p>
      </div>
      ${renderExample(word, true)}
      ${renderThesaurus(word)}
      ${renderUsageNote(word)}
      ${renderExpression(word)}
    `;
  }

  function renderMeaningMode(word) {
    return `
      <div class="word-line large">
        ${renderWordHeading(word)}
      </div>
      ${
        revealed
          ? `<div class="answer-panel"><strong>${renderMeaningText(word)}</strong></div>${renderExample(
            word,
              true,
            )}${renderThesaurus(word)}${renderUsageNote(word)}${renderExpression(word)}`
          : `<div class="hidden-panel">뜻 가림</div><button type="button" class="primary-button" id="revealBtn">뜻 보기</button>`
      }
      ${renderFeedback()}
    `;
  }

  function renderClozeMode(word) {
    const cloze = word.clozeExample || word.exampleEn || "";
    return `
      <div class="prompt-block">
        <span class="field-label">예문 빈칸</span>
        <p class="example-en">${escapeHtml(cloze)}</p>
      </div>
      <div class="answer-row">
        <input type="text" id="answerInput" placeholder="빠진 단어 입력" autocomplete="off">
        <button type="button" class="primary-button" id="checkBtn">확인</button>
      </div>
      ${
        revealed
          ? `<div class="answer-panel"><strong class="answer-word">${renderWordText(word)}</strong><span>${escapeHtml(
              word.meaning || "뜻 정보 없음",
            )}</span></div>${renderExample(word, true)}${renderThesaurus(word)}${renderUsageNote(word)}`
          : ""
      }
      ${renderFeedback()}
    `;
  }

  function renderTypingMode(word) {
    return `
      <div class="prompt-block">
        <span class="field-label">한글 뜻</span>
        <p class="meaning-prompt">${escapeHtml(word.meaning)}</p>
      </div>
      <div class="answer-row">
        <input type="text" id="answerInput" placeholder="영어 단어 또는 숙어 입력" autocomplete="off">
        <button type="button" class="primary-button" id="checkBtn">확인</button>
      </div>
      ${
        revealed
          ? `<div class="answer-panel"><strong class="answer-word">${renderWordText(word)}</strong></div>${renderExample(
            word,
              true,
            )}${renderThesaurus(word)}${renderUsageNote(word)}${renderExpression(word)}`
          : ""
      }
      ${renderFeedback()}
    `;
  }

  function renderExample(word, showKorean) {
    if (!word.exampleEn && !word.exampleKo) {
      return "";
    }
    return `
      <div class="example-box">
        ${
          word.exampleEn
            ? `<p class="example-en save-source" data-word-id="${escapeHtml(
                word.id,
              )}" title="저장할 단어나 구문을 드래그하세요">${escapeHtml(word.exampleEn)}</p>`
            : ""
        }
        ${showKorean && word.exampleKo ? `<p class="example-ko">${escapeHtml(word.exampleKo)}</p>` : ""}
        ${
          word.exampleEn
            ? `<p class="selection-hint">저장할 단어나 구문을 드래그하면 저장 버튼이 나타납니다.</p>`
            : ""
        }
      </div>
    `;
  }

  function renderThesaurus(word) {
    const senses = Array.isArray(word.senses) ? word.senses : [];
    const synonymRows = senses
      .filter((sense) => Array.isArray(sense.synonyms) && sense.synonyms.length)
      .map((sense, index) => {
        const label = [sense.pos, senses.length > 1 ? `${index + 1}` : ""]
          .filter(Boolean)
          .join(" ");
        return `
          <li>
            ${label ? `<span class="thesaurus-pos">${escapeHtml(label)}</span>` : ""}
            <span>${escapeHtml(sense.synonyms.join(", "))}</span>
          </li>
        `;
      });
    const antonyms = Array.isArray(word.antonyms) ? word.antonyms : [];
    if (!synonymRows.length && !antonyms.length) {
      return "";
    }
    return `
      <div class="thesaurus-box">
        ${
          synonymRows.length
            ? `<div class="thesaurus-group"><span>동의어</span><ul>${synonymRows.join("")}</ul></div>`
            : ""
        }
        ${
          antonyms.length
            ? `<div class="thesaurus-group"><span>반의어</span><strong>${escapeHtml(
                antonyms.join(", "),
              )}</strong></div>`
            : ""
        }
      </div>
    `;
  }

  function renderExpression(word) {
    if (!word.expression) {
      return "";
    }
    return `<div class="expression-box"><span>함께 외울 표현</span><strong>${escapeHtml(
      word.expression,
    )}</strong></div>`;
  }

  function renderUsageNote(word) {
    if (!word.usageNote) {
      return "";
    }
    return `<div class="expression-box"><span>뉘앙스·사용법</span><strong>${escapeHtml(
      word.usageNote,
    )}</strong></div>`;
  }

  function renderMeaningText(word) {
    return word.meaning ? escapeHtml(word.meaning) : "뜻 정보 없음";
  }

  function renderWordHeading(word) {
    return `<h3 class="word-heading">${renderWordText(word)}</h3>`;
  }

  function renderWordText(word) {
    return `
      <span class="word-text">${escapeHtml(word.word)}</span>
      ${
        word.pronunciation
          ? `<span class="pronunciation" aria-label="발음기호">[${escapeHtml(word.pronunciation)}]</span>`
          : ""
      }
    `;
  }

  function renderFeedback() {
    if (!feedback) {
      return "";
    }
    const className = feedback.correct ? "feedback correct" : "feedback wrong";
    const title = feedback.correct ? "정답" : "다시 확인";
    return `
      <div class="${className}">
        <strong>${title}</strong>
        <span>${escapeHtml(feedback.message)}</span>
      </div>
    `;
  }

  function bindCardEvents(word) {
    const revealButton = $("#revealBtn");
    if (revealButton) {
      revealButton.addEventListener("click", () => {
        revealed = true;
        renderTrainer();
      });
    }

    const checkButton = $("#checkBtn");
    const answerInput = $("#answerInput");
    if (checkButton && answerInput) {
      if (autoPlay.active) {
        checkButton.disabled = true;
        answerInput.disabled = true;
        return;
      }
      checkButton.addEventListener("click", () => checkAnswer(word, answerInput.value));
      answerInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          if (feedback) {
            goNext();
          } else {
            checkAnswer(word, answerInput.value);
          }
        }
      });
      answerInput.focus();
    }
  }

  function hideSelectionPopover(clearSelection = false) {
    const popover = $("#selectionSavePopover");
    popover.hidden = true;
    pendingExampleSelection = null;
    if (clearSelection) {
      window.getSelection()?.removeAllRanges();
    }
  }

  function captureExampleSelection() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      hideSelectionPopover();
      return;
    }

    const anchorElement =
      selection.anchorNode?.nodeType === Node.ELEMENT_NODE
        ? selection.anchorNode
        : selection.anchorNode?.parentElement;
    const focusElement =
      selection.focusNode?.nodeType === Node.ELEMENT_NODE
        ? selection.focusNode
        : selection.focusNode?.parentElement;
    const source = anchorElement?.closest(".example-en.save-source");
    if (!source || !source.contains(focusElement)) {
      hideSelectionPopover();
      return;
    }

    const text = selection
      .toString()
      .replace(/\s+/g, " ")
      .replace(/^[\s.,!?;:'"()[\]{}]+|[\s.,!?;:'"()[\]{}]+$/g, "")
      .trim();
    if (!text || text.length > 80) {
      hideSelectionPopover();
      return;
    }

    const sourceWord = words.find((word) => word.id === source.dataset.wordId);
    if (!sourceWord) {
      hideSelectionPopover();
      return;
    }

    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const popover = $("#selectionSavePopover");
    pendingExampleSelection = { text, sourceWord };
    popover.style.left = `${Math.max(
      8,
      Math.min(window.innerWidth - 112, rect.left + rect.width / 2 - 48),
    )}px`;
    popover.style.top = `${Math.min(window.innerHeight - 52, rect.bottom + 8)}px`;
    popover.hidden = false;
  }

  function savePendingExampleSelection() {
    if (!pendingExampleSelection) {
      return;
    }
    const { text, sourceWord } = pendingExampleSelection;
    savedWords = readStoredSavedWords();
    const duplicate = savedWords.find(
      (item) =>
        item.sourceWordId === sourceWord.id &&
        item.text.toLocaleLowerCase() === text.toLocaleLowerCase(),
    );
    if (!duplicate) {
      savedWords.unshift({
        id: `saved-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        text,
        note: "",
        sourceWordId: sourceWord.id,
        sourceWord: sourceWord.word,
        exampleEn: sourceWord.exampleEn || "",
        exampleKo: sourceWord.exampleKo || "",
        createdAt: new Date().toISOString(),
      });
      saveSavedWords();
    }
    sidePanelView = "saved";
    hideSelectionPopover(true);
    renderQueue();
  }

  function updateSavedWordNote(id, note) {
    savedWords = readStoredSavedWords();
    const item = savedWords.find((saved) => saved.id === id);
    if (!item) {
      return;
    }
    item.note = note;
    saveSavedWords();
  }

  function deleteSavedWord(id) {
    savedWords = readStoredSavedWords();
    savedWords = savedWords.filter((item) => item.id !== id);
    saveSavedWords();
    renderQueue();
  }

  function openSavedWordSource(id) {
    savedWords = readStoredSavedWords();
    const item = savedWords.find((saved) => saved.id === id);
    if (!item) {
      return;
    }
    sidePanelView = "queue";
    settings.mode = "cards";
    settings.source = "all";
    settings.retryStage = "all";
    settings.search = item.sourceWord;
    saveSettings();
    revealed = false;
    feedback = null;
    rebuildAndRender(item.sourceWordId);
  }

  function setSidePanelView(view) {
    sidePanelView = view === "saved" ? "saved" : "queue";
    if (sidePanelView === "saved") {
      savedWords = readStoredSavedWords();
    }
    hideSelectionPopover(true);
    renderQueue();
  }

  function renderSavedWords() {
    if (!savedWords.length) {
      $("#queueList").innerHTML = `
        <div class="saved-empty">
          <strong>저장한 단어가 없습니다.</strong>
          <p>영어 예문에서 단어나 구문을 드래그해 저장해 보세요.</p>
        </div>
      `;
      return;
    }

    $("#queueList").innerHTML = savedWords
      .map(
        (item) => `
          <article class="saved-word-card">
            <div class="saved-word-head">
              <strong>${escapeHtml(item.text)}</strong>
              <button type="button" class="saved-delete" data-saved-id="${escapeHtml(
                item.id,
              )}" aria-label="${escapeHtml(item.text)} 삭제">삭제</button>
            </div>
            <small>표제어: ${escapeHtml(item.sourceWord || "알 수 없음")}</small>
            <p class="saved-example">${escapeHtml(item.exampleEn)}</p>
            ${
              item.exampleKo
                ? `<p class="saved-example-ko">${escapeHtml(item.exampleKo)}</p>`
                : ""
            }
            <textarea class="saved-note" data-saved-id="${escapeHtml(
              item.id,
            )}" rows="2" placeholder="뜻이나 메모를 입력하세요">${escapeHtml(item.note)}</textarea>
            <div class="saved-word-actions">
              <button type="button" class="ghost-button saved-speak" data-saved-id="${escapeHtml(
                item.id,
              )}">듣기</button>
              <button type="button" class="ghost-button saved-source" data-saved-id="${escapeHtml(
                item.id,
              )}">원문 카드</button>
            </div>
          </article>
        `,
      )
      .join("");

    document.querySelectorAll(".saved-note").forEach((input) => {
      input.addEventListener("input", () => updateSavedWordNote(input.dataset.savedId, input.value));
    });
    document.querySelectorAll(".saved-delete").forEach((button) => {
      button.addEventListener("click", () => deleteSavedWord(button.dataset.savedId));
    });
    document.querySelectorAll(".saved-speak").forEach((button) => {
      button.addEventListener("click", () => {
        const item = savedWords.find((saved) => saved.id === button.dataset.savedId);
        speak(item?.text, wordSpeechDelayMs);
      });
    });
    document.querySelectorAll(".saved-source").forEach((button) => {
      button.addEventListener("click", () => openSavedWordSource(button.dataset.savedId));
    });
  }

  function renderQueue() {
    $("#savedWordCountBadge").textContent = savedWords.length.toLocaleString("ko-KR");
    $("#panelQueueTab").setAttribute("aria-selected", String(sidePanelView === "queue"));
    $("#panelSavedTab").setAttribute("aria-selected", String(sidePanelView === "saved"));
    $("#panelTitle").textContent = sidePanelView === "saved" ? "저장 단어" : "세션 목록";
    const panelItemCount = sidePanelView === "saved" ? savedWords.length : queue.length;
    $("#queueCount").textContent = `${panelItemCount.toLocaleString("ko-KR")}개`;
    $("#restartBtn").hidden = sidePanelView === "saved";

    if (sidePanelView === "saved") {
      renderSavedWords();
      return;
    }

    if (!queue.length) {
      $("#queueList").innerHTML = `<p class="muted queue-empty">표시할 단어가 없습니다.</p>`;
      return;
    }

    const visibleLimit = 160;
    const visibleStart =
      queue.length <= visibleLimit
        ? 0
        : Math.max(0, Math.min(currentIndex - 20, queue.length - visibleLimit));
    const visible = queue.slice(visibleStart, visibleStart + visibleLimit);
    $("#queueList").innerHTML =
      visible
        .map((word, visibleIndex) => {
          const index = visibleStart + visibleIndex;
          const retryStage = getRetryStage(word);
          const active = index === currentIndex ? "is-active" : "";
          return `
            <button type="button" class="queue-item ${active}" data-index="${index}">
              <span class="queue-index">${index + 1}</span>
              <strong>${escapeHtml(word.word)}</strong>
              <span class="queue-meta-row">
                <small>${escapeHtml(word.sourceLabel)} · C${word.chunk}</small>
                ${retryStagePill(retryStage, true)}
              </span>
            </button>
          `;
        })
        .join("") +
      (queue.length > visible.length
        ? `<p class="muted queue-more">${visibleStart + 1}-${visibleStart + visible.length}번 표시 중입니다.</p>`
        : "");

    document.querySelectorAll(".queue-item").forEach((item) => {
      item.addEventListener("click", () => {
        stopAutoPlay();
        recordViewed(queue[currentIndex]);
        currentIndex = Number(item.dataset.index);
        revealed = false;
        feedback = null;
        renderTrainer();
        renderQueue();
      });
    });
  }

  function setNavigationDisabled(disabled) {
    $("#prevBtn").disabled = disabled || autoPlay.active || currentIndex <= 0;
    $("#nextBtn").disabled = disabled || autoPlay.active || currentIndex >= queue.length - 1;
    syncPlaybackControls();
  }

  function syncControls() {
    $("#dayInput").value = settings.day;
    $("#modeSelect").value = settings.mode;
    $("#sourceSelect").value = settings.source;
    $("#chunkSelect").value = settings.chunk;
    $("#retryStageSelect").value = settings.retryStage;
    $("#orderSelect").value = settings.order;
    $("#limitSelect").value = settings.limit;
    $("#searchInput").value = settings.search;
  }

  function checkAnswer(word, rawAnswer) {
    stopAutoPlay();
    const answer = rawAnswer.trim();
    if (!answer) {
      feedback = { correct: false, message: "입력값이 비어 있습니다." };
      renderTrainer();
      return;
    }

    const targets =
      settings.mode === "cloze" ? [word.word, word.clozeAnswer].filter(Boolean) : [word.word];
    const correct = targets.some((target) => answersMatch(answer, target));
    const itemProgress = ensureProgress(word);
    itemProgress.viewed = true;
    itemProgress.lastViewed = todayKey();
    itemProgress.seen = Number(itemProgress.seen || 0) + 1;
    itemProgress.lastSeen = todayKey();
    itemProgress.updatedAt = new Date().toISOString();

    if (correct) {
      itemProgress.correct = Number(itemProgress.correct || 0) + 1;
      feedback = { correct: true, message: `${word.word} · ${word.meaning || "뜻 정보 없음"}` };
    } else {
      itemProgress.wrong = Number(itemProgress.wrong || 0) + 1;
      feedback = {
        correct: false,
        message: `정답: ${word.word} / 입력: ${answer}`,
      };
    }

    revealed = true;
    saveProgress();
    renderDashboard();
    renderTrainer();
    renderQueue();
  }

  function normalizeAnswer(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[’']/g, "")
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function answersMatch(answer, target) {
    const normalizedAnswer = normalizeAnswer(answer);
    const normalizedTarget = normalizeAnswer(target);
    if (!normalizedAnswer || !normalizedTarget) {
      return false;
    }
    return (
      normalizedAnswer === normalizedTarget ||
      normalizedAnswer.replace(/\s/g, "") === normalizedTarget.replace(/\s/g, "")
    );
  }

  function goNext() {
    stopAutoPlay();
    if (currentIndex < queue.length - 1) {
      recordViewed(queue[currentIndex]);
      currentIndex += 1;
      revealed = false;
      feedback = null;
      renderTrainer();
      renderQueue();
    }
  }

  function goPrev() {
    stopAutoPlay();
    if (currentIndex > 0) {
      recordViewed(queue[currentIndex]);
      currentIndex -= 1;
      revealed = false;
      feedback = null;
      renderTrainer();
      renderQueue();
    }
  }

  function recordViewed(word) {
    if (!word) {
      return;
    }
    const itemProgress = ensureProgress(word);
    itemProgress.viewed = true;
    itemProgress.lastViewed = todayKey();
    itemProgress.updatedAt = new Date().toISOString();
    saveProgress();
  }

  function updateSetting(key, value) {
    stopAutoPlay();
    settings[key] = value;
    if (key === "day") {
      settings.day = Math.max(1, Number(value) || 1);
    }
    saveSettings();
    currentIndex = 0;
    revealed = false;
    feedback = null;
    rebuildAndRender();
  }

  function supportsSpeech() {
    if (!("speechSynthesis" in window)) {
      alert("이 브라우저에서는 음성 합성을 사용할 수 없습니다.");
      return false;
    }
    return true;
  }

  function createEnglishUtterance(text) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.88;
    utterance.pitch = 1;
    return utterance;
  }

  function clearSpeechDelay() {
    if (speechDelayTimer) {
      window.clearTimeout(speechDelayTimer);
      speechDelayTimer = null;
    }
  }

  function speak(text, delayMs = 0) {
    stopAutoPlay();
    if (!text || !supportsSpeech()) {
      return;
    }
    window.speechSynthesis.cancel();
    if (delayMs <= 0) {
      window.speechSynthesis.speak(createEnglishUtterance(text));
      return;
    }
    speechDelayTimer = window.setTimeout(() => {
      speechDelayTimer = null;
      window.speechSynthesis.speak(createEnglishUtterance(text));
    }, delayMs);
  }

  function syncPlaybackControls() {
    const hasWord = Boolean(queue[currentIndex]);
    $("#speakWordBtn").disabled = !hasWord || autoPlay.active;
    $("#speakExampleBtn").disabled = !hasWord || autoPlay.active;
    $("#autoPlayBtn").disabled = !hasWord || autoPlay.active;
    $("#stopAutoPlayBtn").disabled = !autoPlay.active;
  }

  function clearAutoPlayPause() {
    if (autoPlay.pauseTimer) {
      window.clearTimeout(autoPlay.pauseTimer);
      autoPlay.pauseTimer = null;
    }
  }

  function stopAutoPlay() {
    const wasAutoPlayActive = autoPlay.active || Boolean(autoPlay.pauseTimer);
    if (!wasAutoPlayActive && !speechDelayTimer) {
      return;
    }
    autoPlay.active = false;
    autoPlay.token += 1;
    clearAutoPlayPause();
    clearSpeechDelay();
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    if (wasAutoPlayActive) {
      renderTrainer();
      renderQueue();
    }
  }

  function isAutoPlayCurrent(token) {
    return autoPlay.active && autoPlay.token === token;
  }

  function waitForAutoPlayPause(token, delayMs = autoPlayPauseMs) {
    return new Promise((resolve) => {
      if (!isAutoPlayCurrent(token)) {
        resolve();
        return;
      }
      autoPlay.pauseTimer = window.setTimeout(() => {
        autoPlay.pauseTimer = null;
        resolve();
      }, delayMs);
    });
  }

  function speakAutoPlayText(text, token) {
    return new Promise((resolve) => {
      if (!text || !isAutoPlayCurrent(token)) {
        resolve();
        return;
      }
      const utterance = createEnglishUtterance(text);
      utterance.onend = resolve;
      utterance.onerror = resolve;
      window.speechSynthesis.speak(utterance);
    });
  }

  function moveToAutoPlayIndex(index) {
    currentIndex = index;
    revealed = true;
    feedback = null;
    renderTrainer();
    renderQueue();
  }

  async function runAutoPlay(token) {
    while (isAutoPlayCurrent(token) && queue[currentIndex]) {
      const word = queue[currentIndex];
      recordViewed(word);
      revealed = true;
      feedback = null;
      renderDashboard();
      renderTrainer();
      renderQueue();

      await waitForAutoPlayPause(token, wordSpeechDelayMs);
      await speakAutoPlayText(word.word, token);
      await waitForAutoPlayPause(token);
      await speakAutoPlayText(word.exampleEn, token);
      await waitForAutoPlayPause(token);

      if (!isAutoPlayCurrent(token)) {
        return;
      }
      if (currentIndex >= queue.length - 1) {
        stopAutoPlay();
        return;
      }
      moveToAutoPlayIndex(currentIndex + 1);
    }
    stopAutoPlay();
  }

  function startAutoPlay() {
    if (!queue[currentIndex] || !supportsSpeech()) {
      return;
    }
    stopAutoPlay();
    autoPlay.active = true;
    autoPlay.token += 1;
    const token = autoPlay.token;
    window.speechSynthesis.cancel();
    syncPlaybackControls();
    runAutoPlay(token);
  }

  function exportProgress() {
    syncLatestRetryStages();
    savedWords = readStoredSavedWords();
    const payload = {
      version: 3,
      exportedAt: new Date().toISOString(),
      source: meta.sourceFile || "TEPS_VOCA.xlsx",
      settings,
      progress,
      savedWords,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `teps-voca-progress-${todayKey()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function importProgress(file) {
    stopAutoPlay();
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const payload = JSON.parse(String(reader.result || "{}"));
        if (!payload.progress || typeof payload.progress !== "object" || Array.isArray(payload.progress)) {
          throw new Error("No progress object");
        }
        const confirmed = confirm(
          "현재 브라우저의 진도와 저장 단어를 불러온 파일의 내용으로 교체할까요?",
        );
        if (!confirmed) {
          return;
        }
        progress = normalizeProgress(payload.progress);
        settings = normalizeSettings({ ...settings, ...(payload.settings || {}) });
        if (Array.isArray(payload.savedWords)) {
          savedWords = normalizeSavedWords(payload.savedWords);
          saveSavedWords();
        }
        saveProgress({ mergeRetryStages: false });
        saveSettings();
        currentIndex = 0;
        revealed = false;
        feedback = null;
        rebuildAndRender();
      } catch {
        alert("진도 파일을 읽지 못했습니다.");
      }
    };
    reader.readAsText(file);
  }

  function resetProgress() {
    stopAutoPlay();
    const confirmed = confirm(
      "저장된 테스트 반복 차수, 정답/오답 기록, 저장 단어를 모두 지울까요?",
    );
    if (!confirmed) {
      return;
    }
    progress = {};
    savedWords = [];
    saveProgress({ mergeRetryStages: false });
    saveSavedWords();
    sidePanelView = "queue";
    currentIndex = 0;
    revealed = false;
    feedback = null;
    rebuildAndRender();
  }

  function bindControls() {
    $("#dayDown").addEventListener("click", () => updateSetting("day", Math.max(1, settings.day - 1)));
    $("#dayUp").addEventListener("click", () => updateSetting("day", settings.day + 1));
    $("#dayInput").addEventListener("change", (event) => updateSetting("day", event.target.value));
    $("#modeSelect").addEventListener("change", (event) => updateSetting("mode", event.target.value));
    $("#sourceSelect").addEventListener("change", (event) => updateSetting("source", event.target.value));
    $("#chunkSelect").addEventListener("change", (event) => updateSetting("chunk", event.target.value));
    $("#retryStageSelect").addEventListener("change", (event) =>
      updateSetting("retryStage", event.target.value),
    );
    $("#orderSelect").addEventListener("change", (event) => updateSetting("order", event.target.value));
    $("#limitSelect").addEventListener("change", (event) => updateSetting("limit", event.target.value));
    $("#searchInput").addEventListener("input", (event) => updateSetting("search", event.target.value));
    $("#panelQueueTab").addEventListener("click", () => setSidePanelView("queue"));
    $("#panelSavedTab").addEventListener("click", () => setSidePanelView("saved"));
    $("#selectionSavePopover").addEventListener("mousedown", (event) => event.preventDefault());
    $("#selectionSavePopover").addEventListener("click", savePendingExampleSelection);
    document.addEventListener("mouseup", (event) => {
      const clickedPopover =
        event.target instanceof Element && event.target.closest("#selectionSavePopover");
      if (!clickedPopover) {
        window.setTimeout(captureExampleSelection, 0);
      }
    });

    $("#prevBtn").addEventListener("click", goPrev);
    $("#nextBtn").addEventListener("click", goNext);
    $("#restartBtn").addEventListener("click", () => {
      stopAutoPlay();
      recordViewed(queue[currentIndex]);
      currentIndex = 0;
      revealed = false;
      feedback = null;
      renderTrainer();
      renderQueue();
    });

    $("#speakWordBtn").addEventListener("click", () =>
      speak(queue[currentIndex]?.word, wordSpeechDelayMs),
    );
    $("#speakExampleBtn").addEventListener("click", () => speak(queue[currentIndex]?.exampleEn));
    $("#autoPlayBtn").addEventListener("click", startAutoPlay);
    $("#stopAutoPlayBtn").addEventListener("click", stopAutoPlay);
    $("#exportBtn").addEventListener("click", exportProgress);
    $("#importFile").addEventListener("change", (event) => importProgress(event.target.files[0]));
    $("#resetBtn").addEventListener("click", resetProgress);

    document.addEventListener("keydown", (event) => {
      if (event.target.matches("input, select, textarea")) {
        return;
      }
      if (autoPlay.active) {
        if (event.key === "Escape") {
          stopAutoPlay();
        }
        return;
      }
      if (event.key === "ArrowRight") {
        goNext();
      }
      if (event.key === "ArrowLeft") {
        goPrev();
      }
      if (event.key === " ") {
        event.preventDefault();
        revealed = true;
        renderTrainer();
      }
    });

    window.addEventListener("storage", (event) => {
      if (event.key === progressKey) {
        refreshProgressFromStorage();
      } else if (event.key === savedWordsKey) {
        refreshSavedWordsFromStorage();
      }
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) {
        savedWords = readStoredSavedWords();
        refreshProgressFromStorage();
      }
    });
  }

  bindControls();
  rebuildAndRender();
})();
