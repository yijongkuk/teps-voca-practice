(() => {
  "use strict";

  const words = Array.isArray(window.TEPS_WORDS) ? window.TEPS_WORDS : [];
  const wordById = new Map(words.map((word) => [String(word.id), word]));
  const progressKey = "teps-voca-progress-v1";
  const settingsKey = "teps-voca-settings-v1";
  const testSessionKey = "teps-voca-test-session-v1";
  const savedWordsKey = "teps-voca-saved-example-words-v1";
  const testedWordsKey = "teps-voca-tested-words-v1";
  const validSources = new Set(["all", "frequent", "connectors", "oxford5000", "awl"]);
  const validScopes = new Set(["all", "studied"]);
  const validNovelty = new Set(["new", "all"]);
  const validCounts = new Set([100, 150, 200]);
  const sourceLabels = {
    all: "전체 단어장",
    frequent: "TEPS 어휘빈출",
    connectors: "TEPS 접속사",
    oxford5000: "Oxford 5000",
    awl: "AWL570",
  };

  const $ = (selector) => document.querySelector(selector);

  function loadJson(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return value ?? fallback;
    } catch {
      return fallback;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
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

  function normalizeTestedIds(value) {
    const set = new Set();
    if (Array.isArray(value)) {
      value.forEach((id) => {
        const key = String(id);
        if (wordById.has(key)) {
          set.add(key);
        }
      });
    }
    return set;
  }

  function normalizeIdList(value, allowedIds) {
    if (!Array.isArray(value)) {
      return [];
    }
    return [...new Set(value.map(String))].filter((id) => allowedIds.has(id));
  }

  function normalizeSession(value) {
    if (!value || typeof value !== "object" || !Array.isArray(value.wordIds)) {
      return null;
    }

    const wordIds = [...new Set(value.wordIds.map(String))].filter((id) => wordById.has(id));
    const allowedIds = new Set(wordIds);
    const requestedCount = Number(value.requestedCount);
    const legacyRound = Math.max(1, Math.floor(Number(value.round) || 1));
    const repeatCount = Math.max(
      0,
      Math.floor(Number(value.repeatCount) || legacyRound - 1),
    );
    const retryStagesRecordedThrough =
      Number(value.version) >= 4
        ? Math.max(
            0,
            Math.min(
              repeatCount,
              Math.floor(Number(value.retryStagesRecordedThrough) || 0),
            ),
          )
        : 0;
    const initialCount = Math.max(
      wordIds.length,
      Math.floor(Number(value.initialCount) || wordIds.length),
    );

    return {
      version: 4,
      source: validSources.has(value.source) ? value.source : "all",
      scope: validScopes.has(value.scope) ? value.scope : "all",
      novelty: validNovelty.has(value.novelty) ? value.novelty : "all",
      requestedCount: validCounts.has(requestedCount) ? requestedCount : 100,
      poolSize: Math.max(wordIds.length, Number(value.poolSize) || 0),
      repeatCount,
      retryStagesRecordedThrough,
      initialCount,
      wordIds,
      knownIds: normalizeIdList(value.knownIds, allowedIds),
      meaningDefaultVisible: Boolean(value.meaningDefaultVisible),
      meaningExceptions: normalizeIdList(value.meaningExceptions, allowedIds),
      exampleDefaultVisible: Boolean(value.exampleDefaultVisible),
      exampleExceptions: normalizeIdList(value.exampleExceptions, allowedIds),
      createdAt: String(value.createdAt || new Date().toISOString()),
    };
  }

  let progress = loadJson(progressKey, {});
  const studySettings = loadJson(settingsKey, {});
  let session = normalizeSession(loadJson(testSessionKey, null));
  let testedWordIds = normalizeTestedIds(loadJson(testedWordsKey, []));
  let sessionStorageAvailable = true;
  let progressStorageAvailable = true;
  let activeSpeechButton = null;
  let speechToken = 0;
  let pendingExampleSelection = null;
  let selectionCaptureTimer = null;
  let selectionResultTimer = null;
  let selectionResultVisible = false;
  let selectionPopoverInteracting = false;

  function speechIsSupported() {
    return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  }

  function clearSpeechHighlight() {
    activeSpeechButton?.classList.remove("is-speaking");
    activeSpeechButton = null;
  }

  function stopSpeech() {
    speechToken += 1;
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    clearSpeechHighlight();
  }

  function speakWord(button) {
    const wordId = String(button.dataset.wordId || "");
    const word = wordById.get(wordId);
    if (!word?.word) {
      return;
    }
    if (!speechIsSupported()) {
      window.alert("이 브라우저에서는 단어 음성 재생을 사용할 수 없습니다.");
      return;
    }

    stopSpeech();
    const token = speechToken;
    const utterance = new SpeechSynthesisUtterance(word.word);
    utterance.lang = "en-US";
    utterance.rate = 0.88;
    utterance.pitch = 1;
    activeSpeechButton = button;
    button.classList.add("is-speaking");

    const finishSpeech = () => {
      if (token === speechToken && activeSpeechButton === button) {
        clearSpeechHighlight();
      }
    };
    utterance.onend = finishSpeech;
    utterance.onerror = finishSpeech;
    window.speechSynthesis.speak(utterance);
  }

  function selectionNodeElement(node) {
    return node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
  }

  function selectedExampleSource(selection = window.getSelection()) {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return null;
    }
    const anchorElement = selectionNodeElement(selection.anchorNode);
    const focusElement = selectionNodeElement(selection.focusNode);
    const source = anchorElement?.closest(".test-example-save-source");
    return source && source.contains(focusElement) ? source : null;
  }

  function normalizedSelectionText(selection) {
    return selection
      .toString()
      .replace(/\s+/g, " ")
      .replace(/^[\s.,!?;:'"()[\]{}]+|[\s.,!?;:'"()[\]{}]+$/g, "")
      .trim();
  }

  function announceSelectionStatus(message) {
    const status = $("#testSelectionStatus");
    status.textContent = "";
    window.requestAnimationFrame(() => {
      status.textContent = message;
    });
  }

  function hideSelectionPopover(clearSelection = false) {
    window.clearTimeout(selectionCaptureTimer);
    window.clearTimeout(selectionResultTimer);
    selectionCaptureTimer = null;
    selectionResultTimer = null;
    selectionResultVisible = false;
    selectionPopoverInteracting = false;
    pendingExampleSelection = null;

    const popover = $("#selectionSavePopover");
    popover.hidden = true;
    popover.textContent = "선택 저장";
    popover.setAttribute("aria-label", "선택한 예문 표현 저장");
    popover.removeAttribute("aria-disabled");
    popover.classList.remove("is-saved", "is-duplicate", "is-error");
    if (clearSelection) {
      window.getSelection()?.removeAllRanges();
    }
  }

  function scheduleSelectionCapture(delay = 0) {
    if (selectionResultVisible || selectionPopoverInteracting) {
      return;
    }
    window.clearTimeout(selectionCaptureTimer);
    selectionCaptureTimer = window.setTimeout(captureExampleSelection, delay);
  }

  function captureExampleSelection() {
    selectionCaptureTimer = null;
    const selection = window.getSelection();
    const source = selectedExampleSource(selection);
    if (!source) {
      hideSelectionPopover();
      return;
    }

    const text = normalizedSelectionText(selection);
    if (!text || text.length > 80) {
      hideSelectionPopover();
      return;
    }

    const sourceWord = wordById.get(String(source.dataset.wordId || ""));
    if (!sourceWord) {
      hideSelectionPopover();
      return;
    }

    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const popover = $("#selectionSavePopover");
    const popoverWidth = 104;
    const belowSelection = rect.bottom + 8;
    const top =
      belowSelection + 46 <= window.innerHeight
        ? belowSelection
        : Math.max(8, rect.top - 46);

    pendingExampleSelection = { text, sourceWord };
    selectionResultVisible = false;
    window.clearTimeout(selectionResultTimer);
    popover.textContent = "선택 저장";
    popover.setAttribute("aria-label", `${text} 저장`);
    popover.removeAttribute("aria-disabled");
    popover.classList.remove("is-saved", "is-duplicate", "is-error");
    popover.style.left = `${Math.max(
      8,
      Math.min(window.innerWidth - popoverWidth - 8, rect.left + rect.width / 2 - popoverWidth / 2),
    )}px`;
    popover.style.top = `${top}px`;
    popover.hidden = false;
    announceSelectionStatus("선택 저장 버튼이 나타났습니다.");
  }

  function showSelectionSaveResult(message, className) {
    const popover = $("#selectionSavePopover");
    selectionResultVisible = true;
    pendingExampleSelection = null;
    window.clearTimeout(selectionCaptureTimer);
    window.clearTimeout(selectionResultTimer);
    selectionCaptureTimer = null;
    popover.textContent = message;
    popover.setAttribute("aria-label", message);
    popover.setAttribute("aria-disabled", "true");
    popover.classList.remove("is-saved", "is-duplicate", "is-error");
    popover.classList.add(className);
    popover.hidden = false;
    window.getSelection()?.removeAllRanges();
    announceSelectionStatus(message);
    selectionResultTimer = window.setTimeout(() => hideSelectionPopover(), 1200);
  }

  function savePendingExampleSelection() {
    if (!pendingExampleSelection) {
      return;
    }
    const { text, sourceWord } = pendingExampleSelection;
    const savedWords = readStoredSavedWords();
    const duplicate = savedWords.some(
      (item) =>
        item.sourceWordId === String(sourceWord.id) &&
        item.text.toLocaleLowerCase() === text.toLocaleLowerCase(),
    );

    if (duplicate) {
      showSelectionSaveResult("이미 저장됨", "is-duplicate");
      return;
    }

    savedWords.unshift({
      id: `saved-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      text,
      note: "",
      sourceWordId: String(sourceWord.id),
      sourceWord: sourceWord.word,
      exampleEn: sourceWord.exampleEn || "",
      exampleKo: sourceWord.exampleKo || "",
      createdAt: new Date().toISOString(),
    });
    try {
      localStorage.setItem(savedWordsKey, JSON.stringify(savedWords));
      showSelectionSaveResult("저장 완료", "is-saved");
    } catch {
      showSelectionSaveResult("저장 실패", "is-error");
    }
  }

  function hasSelectedExampleInside(element) {
    const source = selectedExampleSource();
    return Boolean(source && element.contains(source));
  }

  function saveSession() {
    try {
      localStorage.setItem(testSessionKey, JSON.stringify(session));
      sessionStorageAvailable = true;
      return true;
    } catch {
      sessionStorageAvailable = false;
      return false;
    }
  }

  function normalizeRetryStage(value) {
    const stage = Number(value);
    return Number.isFinite(stage) ? Math.max(0, Math.floor(stage)) : 0;
  }

  function getRetryStage(word) {
    return normalizeRetryStage(progress[word.id]?.testRetryStage);
  }

  function retryStageClass(stage) {
    return `retry-stage-${Math.min(3, normalizeRetryStage(stage))}`;
  }

  function saveRetryStages(wordIds, stage) {
    const safeStage = normalizeRetryStage(stage);
    if (!safeStage || !wordIds.length) {
      return true;
    }

    const latestValue = loadJson(progressKey, {});
    const latest =
      latestValue && typeof latestValue === "object" && !Array.isArray(latestValue)
        ? latestValue
        : {};
    const updatedAt = new Date().toISOString();
    let changed = false;

    wordIds.forEach((wordId) => {
      const current =
        latest[wordId] && typeof latest[wordId] === "object" ? latest[wordId] : {};
      if (normalizeRetryStage(current.testRetryStage) >= safeStage) {
        return;
      }
      latest[wordId] = {
        ...current,
        testRetryStage: safeStage,
        testRetryUpdatedAt: updatedAt,
        createdAt: String(current.createdAt || updatedAt),
      };
      changed = true;
    });

    progress = latest;
    if (!changed) {
      return true;
    }
    try {
      localStorage.setItem(progressKey, JSON.stringify(progress));
      progressStorageAvailable = true;
      return true;
    } catch {
      progressStorageAvailable = false;
      return false;
    }
  }

  function hasStudyRecord(word) {
    const item = progress[word.id];
    if (!item || typeof item !== "object") {
      return false;
    }
    return Boolean(
      item.viewed ||
        item.lastViewed ||
        item.lastSeen ||
        Number(item.seen || 0) > 0 ||
        normalizeRetryStage(item.testRetryStage) > 0 ||
        (item.status && item.status !== "New"),
    );
  }

  function hasTestRecord(word) {
    return testedWordIds.has(String(word.id)) || getRetryStage(word) > 0;
  }

  function markWordsTested(wordIds) {
    if (!wordIds.length) {
      return;
    }
    const stored = normalizeTestedIds(loadJson(testedWordsKey, []));
    let changed = false;
    wordIds.forEach((id) => {
      const key = String(id);
      if (wordById.has(key) && !stored.has(key)) {
        stored.add(key);
        changed = true;
      }
    });
    testedWordIds = stored;
    if (!changed) {
      return;
    }
    try {
      localStorage.setItem(testedWordsKey, JSON.stringify([...stored]));
    } catch {
      // 출제 기록 저장은 실패해도 테스트 진행에는 영향을 주지 않습니다.
    }
  }

  function getCandidates(source, scope, novelty = "all") {
    return words.filter((word) => {
      if (source !== "all" && word.source !== source) {
        return false;
      }
      if (scope === "studied" && !hasStudyRecord(word)) {
        return false;
      }
      if (novelty === "new" && hasTestRecord(word)) {
        return false;
      }
      return true;
    });
  }

  function shuffled(items) {
    const result = [...items];
    for (let index = result.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
    }
    return result;
  }

  function selectedWords() {
    return session.wordIds.map((id) => wordById.get(id)).filter(Boolean);
  }

  function sessionCounts(currentWords = selectedWords()) {
    const activeIds = new Set(currentWords.map((word) => String(word.id)));
    const knownCount = session.knownIds.filter((id) => activeIds.has(id)).length;
    const total = currentWords.length;
    const unknownCount = Math.max(0, total - knownCount);
    const masteredCount = Math.max(
      0,
      Math.min(session.initialCount, session.initialCount - total + knownCount),
    );
    return { total, knownCount, unknownCount, masteredCount };
  }

  function createTestSession() {
    const currentCounts = session ? sessionCounts() : null;
    if (
      currentCounts?.masteredCount > 0 &&
      !window.confirm(
        `현재 반복 테스트에서 익힌 ${currentCounts.masteredCount.toLocaleString(
          "ko-KR",
        )}개 기록이 사라집니다. 새 테스트를 만들까요?`,
      )
    ) {
      return;
    }

    stopSpeech();
    const source = validSources.has($("#testSourceSelect").value)
      ? $("#testSourceSelect").value
      : "all";
    const scope = validScopes.has($("#testScopeSelect").value)
      ? $("#testScopeSelect").value
      : "all";
    const novelty = validNovelty.has($("#testNoveltySelect").value)
      ? $("#testNoveltySelect").value
      : "new";
    const requestedCount = Number($("#testCountSelect").value);
    const safeCount = validCounts.has(requestedCount) ? requestedCount : 100;
    const candidates = getCandidates(source, scope, novelty);
    const selected = shuffled(candidates).slice(0, safeCount);

    session = {
      version: 4,
      source,
      scope,
      novelty,
      requestedCount: safeCount,
      poolSize: candidates.length,
      repeatCount: 0,
      retryStagesRecordedThrough: 0,
      initialCount: selected.length,
      wordIds: selected.map((word) => String(word.id)),
      knownIds: [],
      meaningDefaultVisible: false,
      meaningExceptions: [],
      exampleDefaultVisible: false,
      exampleExceptions: [],
      createdAt: new Date().toISOString(),
    };
    saveSession();
    markWordsTested(session.wordIds);
    renderAll();
  }

  function sessionSet(key) {
    return new Set(session[key]);
  }

  function isCellVisible(field, wordId) {
    const defaultKey = `${field}DefaultVisible`;
    const exceptionsKey = `${field}Exceptions`;
    return session[defaultKey] !== sessionSet(exceptionsKey).has(wordId);
  }

  function answerContent(word, field) {
    if (field === "meaning") {
      return word.meaning
        ? `<span class="test-answer-primary">${escapeHtml(word.meaning)}</span>`
        : `<span class="test-answer-empty">등록된 뜻 없음</span>`;
    }
    if (!word.exampleEn) {
      return `<span class="test-answer-empty">등록된 예문 없음</span>`;
    }
    return `
      <span
        class="test-answer-primary test-example-save-source save-source"
        data-word-id="${escapeHtml(word.id)}"
        lang="en"
        title="저장할 단어나 구문을 드래그하세요"
      >${escapeHtml(word.exampleEn)}</span>
      ${
        word.exampleKo
          ? `<span class="test-answer-secondary">${escapeHtml(word.exampleKo)}</span>`
          : `<span class="test-answer-secondary">등록된 예문 해석 없음</span>`
      }
    `;
  }

  function cellContent(word, field, visible) {
    if (visible) {
      return answerContent(word, field);
    }
    const label = field === "meaning" ? "뜻" : "예문";
    return `<span class="test-hidden-prompt">클릭해서 ${label} 보기</span>`;
  }

  function renderRows() {
    hideSelectionPopover(true);
    const currentWords = selectedWords();
    const knownIds = sessionSet("knownIds");

    if (!currentWords.length) {
      $("#testRows").innerHTML = `
        <tr>
          <td class="test-table-empty" colspan="4">
            선택한 조건에 출제할 단어가 없습니다.
            <strong>출제 범위</strong>나 <strong>이미 출제한 단어</strong> 설정을 바꿔보세요.
          </td>
        </tr>
      `;
      return;
    }

    $("#testRows").innerHTML = currentWords
      .map((word, index) => {
        const wordId = String(word.id);
        const isKnown = knownIds.has(wordId);
        const meaningVisible = isCellVisible("meaning", wordId);
        const exampleVisible = isCellVisible("example", wordId);
        const retryStage = getRetryStage(word);
        return `
          <tr data-word-id="${escapeHtml(wordId)}" class="${isKnown ? "is-known" : ""}">
            <td class="test-known-cell">
              <input
                type="checkbox"
                class="test-known-checkbox"
                data-word-id="${escapeHtml(wordId)}"
                aria-label="${escapeHtml(word.word)} 안다"
                ${isKnown ? "checked" : ""}
              >
            </td>
            <th scope="row" class="test-word-cell">
              <div class="test-word-line">
                <div class="test-word-details">
                  <span class="test-word-text" lang="en">${escapeHtml(word.word)}</span>
                  ${
                    word.pronunciation
                      ? `<span class="test-word-pronunciation" aria-hidden="true">[${escapeHtml(
                          word.pronunciation,
                        )}]</span>`
                      : ""
                  }
                  ${
                    retryStage
                      ? `<span class="retry-stage-pill ${retryStageClass(
                          retryStage,
                        )} test-retry-stage" title="테스트에서 ${retryStage}차까지 모르는 단어로 남음" aria-hidden="true">${retryStage}차</span>`
                      : ""
                  }
                </div>
                <button
                  type="button"
                  class="test-word-speak"
                  data-word-id="${escapeHtml(wordId)}"
                  aria-label="${escapeHtml(word.word)} 발음 듣기"
                  title="발음 듣기"
                >
                  <span class="test-word-audio-icon" aria-hidden="true">🔊</span>
                </button>
              </div>
              <small>${index + 1}. ${escapeHtml(word.sourceLabel)} · Chunk ${word.chunk}</small>
            </th>
            <td class="test-answer-cell">
              <button
                type="button"
                class="test-cell-toggle ${meaningVisible ? "is-revealed" : ""}"
                data-word-id="${escapeHtml(wordId)}"
                data-field="meaning"
                aria-pressed="${meaningVisible}"
                aria-label="${escapeHtml(word.word)} 뜻 표시"
              >
                ${cellContent(word, "meaning", meaningVisible)}
              </button>
            </td>
            <td class="test-answer-cell">
              <button
                type="button"
                class="test-cell-toggle ${exampleVisible ? "is-revealed" : ""}"
                data-word-id="${escapeHtml(wordId)}"
                data-field="example"
                aria-pressed="${exampleVisible}"
                aria-label="${escapeHtml(word.word)} 예문 표시"
              >
                ${cellContent(word, "example", exampleVisible)}
              </button>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  function renderNotice(currentWords = selectedWords(), counts = sessionCounts(currentWords)) {
    const { total, unknownCount, masteredCount } = counts;
    const scopeLabel = session.scope === "studied" ? "학습 기록 있는 단어" : "전체 단어";
    const isNewOnly = session.novelty === "new";
    const rangeLabel = `${sourceLabels[session.source]} · ${scopeLabel}`;
    let notice;
    if (!total) {
      notice = `${rangeLabel}에서 출제할 단어를 찾지 못했습니다.`;
      if (isNewOnly) {
        notice +=
          " 새로 출제할 단어가 없다면 '이미 출제한 단어'를 '포함해서 랜덤'으로 바꿔보세요.";
      }
    } else if (unknownCount === 0) {
      notice = `오늘 테스트 완료 · 처음 출제한 ${session.initialCount.toLocaleString(
        "ko-KR",
      )}개 단어를 모두 알게 됐습니다!`;
    } else if (session.repeatCount > 0) {
      notice = `같은 테스트 반복 ${session.repeatCount.toLocaleString(
        "ko-KR",
      )}번 · 처음 ${session.initialCount.toLocaleString(
        "ko-KR",
      )}개 중 ${masteredCount.toLocaleString("ko-KR")}개를 외웠고 ${unknownCount.toLocaleString(
        "ko-KR",
      )}개가 남았습니다.`;
    } else if (total < session.requestedCount) {
      const poolLabel = isNewOnly ? "아직 출제하지 않은 단어" : rangeLabel;
      notice = `${poolLabel}가 ${session.poolSize.toLocaleString(
        "ko-KR",
      )}개뿐이라 전부 출제했습니다.`;
    } else {
      const pickLabel = isNewOnly ? "아직 출제하지 않은 단어 중 무작위로" : "무작위로";
      notice = `${rangeLabel}에서 ${pickLabel} ${total.toLocaleString(
        "ko-KR",
      )}개를 출제했습니다.`;
    }
    if (!sessionStorageAvailable || !progressStorageAvailable) {
      notice += " 브라우저 저장이 차단되어 현재 화면에서만 유지됩니다.";
    }
    $("#testNotice").textContent = notice;
  }

  function renderSummary() {
    const currentWords = selectedWords();
    const counts = sessionCounts(currentWords);
    const { total, knownCount, unknownCount } = counts;
    const percent = total ? (knownCount / total) * 100 : 0;
    const retryButton = $("#retryUnknownBtn");

    $("#testTotal").textContent = total.toLocaleString("ko-KR");
    $("#knownCount").textContent = knownCount.toLocaleString("ko-KR");
    $("#unknownCount").textContent = unknownCount.toLocaleString("ko-KR");
    $("#knownProgress").style.width = `${percent}%`;
    $("#resetKnownBtn").disabled = knownCount === 0;
    $("#testTableTitle").textContent =
      session.repeatCount > 0
        ? `현재 테스트 · 같은 묶음 반복 ${session.repeatCount.toLocaleString("ko-KR")}번`
        : "현재 테스트";
    $(".test-summary").classList.toggle("is-complete", total > 0 && unknownCount === 0);

    if (!total) {
      retryButton.disabled = true;
      retryButton.textContent = "모르는 단어만 반복";
    } else if (unknownCount === 0) {
      retryButton.disabled = true;
      retryButton.textContent = "오늘 테스트 단어를 모두 외웠어요";
    } else {
      retryButton.disabled = false;
      retryButton.textContent = `모르는 단어 ${unknownCount.toLocaleString(
        "ko-KR",
      )}개만 반복`;
    }

    renderNotice(currentWords, counts);
  }

  function columnIsFullyVisible(field) {
    const currentWords = selectedWords();
    return (
      currentWords.length > 0 &&
      currentWords.every((word) => isCellVisible(field, String(word.id)))
    );
  }

  function renderColumnButtons() {
    const currentWords = selectedWords();
    [
      ["meaning", $("#toggleAllMeanings"), "뜻"],
      ["example", $("#toggleAllExamples"), "예문"],
    ].forEach(([field, button, label]) => {
      const fullyVisible = columnIsFullyVisible(field);
      button.disabled = currentWords.length === 0;
      button.setAttribute("aria-pressed", String(fullyVisible));
      button.textContent = fullyVisible ? `${label} 전체 가리기` : `${label} 전체 보기`;
    });
  }

  function renderAll() {
    renderRows();
    renderSummary();
    renderColumnButtons();
  }

  function updateCellButton(button, word, field) {
    const visible = isCellVisible(field, String(word.id));
    button.classList.toggle("is-revealed", visible);
    button.setAttribute("aria-pressed", String(visible));
    button.setAttribute("aria-label", `${word.word} ${field === "meaning" ? "뜻" : "예문"} 표시`);
    button.innerHTML = cellContent(word, field, visible);
  }

  function toggleCell(button) {
    const wordId = String(button.dataset.wordId || "");
    const field = button.dataset.field;
    if (!wordById.has(wordId) || !["meaning", "example"].includes(field)) {
      return;
    }

    hideSelectionPopover(true);
    const defaultKey = `${field}DefaultVisible`;
    const exceptionsKey = `${field}Exceptions`;
    const exceptions = sessionSet(exceptionsKey);
    const nextVisible = !isCellVisible(field, wordId);

    if (nextVisible === session[defaultKey]) {
      exceptions.delete(wordId);
    } else {
      exceptions.add(wordId);
    }
    session[exceptionsKey] = [...exceptions];
    saveSession();
    updateCellButton(button, wordById.get(wordId), field);
    renderColumnButtons();
    renderNotice();
  }

  function toggleColumn(field) {
    hideSelectionPopover(true);
    const shouldShowAll = !columnIsFullyVisible(field);
    session[`${field}DefaultVisible`] = shouldShowAll;
    session[`${field}Exceptions`] = [];
    saveSession();

    document.querySelectorAll(`.test-cell-toggle[data-field="${field}"]`).forEach((button) => {
      const word = wordById.get(String(button.dataset.wordId || ""));
      if (word) {
        updateCellButton(button, word, field);
      }
    });
    renderColumnButtons();
    renderNotice();
  }

  function updateKnown(checkbox) {
    const wordId = String(checkbox.dataset.wordId || "");
    if (!wordById.has(wordId)) {
      return;
    }
    const knownIds = sessionSet("knownIds");
    if (checkbox.checked) {
      knownIds.add(wordId);
    } else {
      knownIds.delete(wordId);
    }
    session.knownIds = [...knownIds];
    saveSession();
    checkbox.closest("tr")?.classList.toggle("is-known", checkbox.checked);
    renderSummary();
  }

  function repeatUnknownWords() {
    const knownIds = sessionSet("knownIds");
    const unknownIds = session.wordIds.filter((id) => !knownIds.has(id));
    if (!unknownIds.length) {
      return;
    }

    stopSpeech();
    const nextRetryStage = session.repeatCount + 1;
    const retryStagesSaved = saveRetryStages(unknownIds, nextRetryStage);
    session.wordIds = shuffled(unknownIds);
    session.knownIds = [];
    session.meaningDefaultVisible = false;
    session.meaningExceptions = [];
    session.exampleDefaultVisible = false;
    session.exampleExceptions = [];
    session.repeatCount = nextRetryStage;
    if (retryStagesSaved) {
      session.retryStagesRecordedThrough = nextRetryStage;
    }
    session.updatedAt = new Date().toISOString();
    saveSession();
    renderAll();

    const tableScroll = $(".test-table-scroll");
    tableScroll.scrollTop = 0;
    tableScroll.scrollLeft = 0;
  }

  function resetKnown() {
    if (!session.knownIds.length) {
      return;
    }
    if (
      !window.confirm(
        `'안다'로 체크한 ${session.knownIds.length.toLocaleString(
          "ko-KR",
        )}개 결과를 모두 해제할까요?`,
      )
    ) {
      return;
    }

    session.knownIds = [];
    saveSession();
    document.querySelectorAll(".test-known-checkbox").forEach((checkbox) => {
      checkbox.checked = false;
      checkbox.closest("tr")?.classList.remove("is-known");
    });
    renderSummary();
  }

  function syncControls() {
    $("#testSourceSelect").value = session.source;
    $("#testScopeSelect").value = session.scope;
    $("#testNoveltySelect").value = session.novelty;
    $("#testCountSelect").value = String(session.requestedCount);
  }

  function setInitialControls() {
    const preferredSource = validSources.has(studySettings.source) ? studySettings.source : "all";
    const hasStudiedWords = getCandidates(preferredSource, "studied").length > 0;
    $("#testSourceSelect").value = preferredSource;
    $("#testScopeSelect").value = hasStudiedWords ? "studied" : "all";
    $("#testNoveltySelect").value = "new";
    $("#testCountSelect").value = "100";
  }

  function bindControls() {
    $("#newTestBtn").addEventListener("click", createTestSession);
    $("#retryUnknownBtn").addEventListener("click", repeatUnknownWords);
    $("#resetKnownBtn").addEventListener("click", resetKnown);
    $("#toggleAllMeanings").addEventListener("click", () => toggleColumn("meaning"));
    $("#toggleAllExamples").addEventListener("click", () => toggleColumn("example"));
    $("#testRows").addEventListener("click", (event) => {
      const speechButton = event.target.closest(".test-word-speak");
      if (speechButton) {
        speakWord(speechButton);
        return;
      }
      const button = event.target.closest(".test-cell-toggle");
      if (button) {
        if (
          button.dataset.field === "example" &&
          button.classList.contains("is-revealed") &&
          hasSelectedExampleInside(button)
        ) {
          event.preventDefault();
          captureExampleSelection();
          return;
        }
        toggleCell(button);
      }
    });
    $("#testRows").addEventListener("change", (event) => {
      if (event.target.matches(".test-known-checkbox")) {
        updateKnown(event.target);
      }
    });

    const selectionPopover = $("#selectionSavePopover");
    selectionPopover.addEventListener("mousedown", (event) => event.preventDefault());
    selectionPopover.addEventListener("pointerdown", () => {
      if (selectionResultVisible) {
        return;
      }
      selectionPopoverInteracting = true;
      window.clearTimeout(selectionCaptureTimer);
    });
    selectionPopover.addEventListener("pointerup", () => {
      savePendingExampleSelection();
      selectionPopoverInteracting = false;
    });
    selectionPopover.addEventListener("pointercancel", () => {
      selectionPopoverInteracting = false;
    });
    selectionPopover.addEventListener("click", savePendingExampleSelection);
    document.addEventListener("pointerup", () => {
      selectionPopoverInteracting = false;
    });
    document.addEventListener("pointercancel", () => {
      selectionPopoverInteracting = false;
    });
    document.addEventListener("mouseup", (event) => {
      const clickedPopover =
        event.target instanceof Element && event.target.closest("#selectionSavePopover");
      if (!clickedPopover) {
        scheduleSelectionCapture();
      }
    });
    document.addEventListener(
      "touchend",
      (event) => {
        const touchedPopover =
          event.target instanceof Element && event.target.closest("#selectionSavePopover");
        if (!touchedPopover) {
          scheduleSelectionCapture(80);
        }
      },
      { passive: true },
    );
    document.addEventListener("selectionchange", () => scheduleSelectionCapture(140));
    $(".test-table-scroll").addEventListener(
      "scroll",
      () => hideSelectionPopover(),
      { passive: true },
    );
    window.addEventListener("resize", () => hideSelectionPopover());
  }

  bindControls();
  if (session) {
    if (session.repeatCount > session.retryStagesRecordedThrough) {
      const retryStagesSaved = saveRetryStages(session.wordIds, session.repeatCount);
      if (retryStagesSaved) {
        session.retryStagesRecordedThrough = session.repeatCount;
        saveSession();
      }
    }
    syncControls();
    renderAll();
  } else {
    setInitialControls();
    createTestSession();
  }
})();
