(() => {
  "use strict";

  const words = Array.isArray(window.TEPS_WORDS) ? window.TEPS_WORDS : [];
  const meta = window.TEPS_META || {};
  const progressKey = "teps-voca-progress-v1";
  const settingsKey = "teps-voca-settings-v1";

  const statusConfig = {
    New: { label: "미학습", className: "status-new", weight: 3 },
    Easy: { label: "Easy", className: "status-easy", weight: 5 },
    Familiar: { label: "Familiar", className: "status-familiar", weight: 4 },
    Hard: { label: "Hard", className: "status-hard", weight: 1 },
    Critical: { label: "Critical", className: "status-critical", weight: 0 },
  };

  const modeLabels = {
    cards: "카드 훑기",
    meaning: "뜻 가리기",
    cloze: "예문 빈칸",
    typing: "한글 뜻 → 영어",
    hard: "Hard 압축",
  };

  const defaultSettings = {
    day: 1,
    mode: "cards",
    source: "all",
    chunk: "today",
    status: "all",
    order: "schedule",
    limit: "50",
    search: "",
  };

  let progress = loadJson(progressKey, {});
  let settings = { ...defaultSettings, ...loadJson(settingsKey, {}) };
  let queue = [];
  let currentIndex = 0;
  let revealed = false;
  let feedback = null;

  const $ = (selector) => document.querySelector(selector);

  function loadJson(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) || fallback;
    } catch {
      return fallback;
    }
  }

  function saveProgress() {
    localStorage.setItem(progressKey, JSON.stringify(progress));
  }

  function saveSettings() {
    localStorage.setItem(settingsKey, JSON.stringify(settings));
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

  function focusChunkForDay(day) {
    const safeDay = Math.max(1, Number(day) || 1);
    if (safeDay <= 5) {
      return safeDay;
    }
    return ((safeDay - 5) % 5) + 1;
  }

  function chunkOrderForDay(day) {
    const safeDay = Math.max(1, Number(day) || 1);
    if (safeDay <= 5) {
      return Array.from({ length: safeDay }, (_, index) => index + 1);
    }
    const start = focusChunkForDay(safeDay);
    return Array.from({ length: 5 }, (_, index) => ((start - 1 + index) % 5) + 1);
  }

  function getProgress(word) {
    return progress[word.id] || {};
  }

  function ensureProgress(word) {
    if (!progress[word.id]) {
      progress[word.id] = {
        status: "New",
        seen: 0,
        correct: 0,
        wrong: 0,
        createdAt: new Date().toISOString(),
      };
    }
    return progress[word.id];
  }

  function getStatus(word) {
    return getProgress(word).status || "New";
  }

  function statusPill(status) {
    const config = statusConfig[status] || statusConfig.New;
    return `<span class="status-pill ${config.className}">${config.label}</span>`;
  }

  function isHardWord(word) {
    const itemProgress = getProgress(word);
    const status = getStatus(word);
    return status === "Hard" || status === "Critical" || Number(itemProgress.wrong || 0) > 0;
  }

  function buildQueue() {
    const dayOrder = chunkOrderForDay(settings.day);
    const dayOrderIndex = new Map(dayOrder.map((chunk, index) => [chunk, index]));
    const focusChunk = focusChunkForDay(settings.day);
    const query = settings.search.trim().toLowerCase();

    let result = words.filter((word) => {
      if (settings.chunk === "today" && !dayOrder.includes(word.chunk)) {
        return false;
      }
      if (settings.chunk === "focus" && word.chunk !== focusChunk) {
        return false;
      }
      if (/^[1-5]$/.test(settings.chunk) && word.chunk !== Number(settings.chunk)) {
        return false;
      }
      if (settings.source !== "all" && word.source !== settings.source) {
        return false;
      }
      if (settings.mode === "hard" && !isHardWord(word)) {
        return false;
      }
      if (settings.status !== "all" && getStatus(word) !== settings.status) {
        return false;
      }
      if (query) {
        const text = [
          word.word,
          word.meaning,
          word.exampleEn,
          word.exampleKo,
          word.expression,
          word.group,
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
      if (settings.order === "rank") {
        return sourceOrder(a) - sourceOrder(b) || a.rank - b.rank;
      }
      if (settings.order === "hard") {
        return (
          statusWeight(a) - statusWeight(b) ||
          Number(getProgress(b).wrong || 0) - Number(getProgress(a).wrong || 0) ||
          sourceOrder(a) - sourceOrder(b) ||
          a.rank - b.rank
        );
      }
      return (
        (dayOrderIndex.get(a.chunk) ?? a.chunk + 10) -
          (dayOrderIndex.get(b.chunk) ?? b.chunk + 10) ||
        sourceOrder(a) - sourceOrder(b) ||
        a.rank - b.rank
      );
    });

    if (settings.limit !== "all") {
      result = result.slice(0, Number(settings.limit));
    }
    return result;
  }

  function sourceOrder(word) {
    return word.source === "vocab" ? 0 : 1;
  }

  function statusWeight(word) {
    return (statusConfig[getStatus(word)] || statusConfig.New).weight;
  }

  function rebuildAndRender(targetId) {
    queue = buildQueue();
    if (targetId) {
      const found = queue.findIndex((word) => word.id === targetId);
      currentIndex = found >= 0 ? found : Math.min(currentIndex, Math.max(queue.length - 1, 0));
    } else {
      currentIndex = Math.min(currentIndex, Math.max(queue.length - 1, 0));
    }
    renderDashboard();
    renderTrainer();
    renderQueue();
    syncControls();
  }

  function renderDashboard() {
    const dayOrder = chunkOrderForDay(settings.day);
    const focusChunk = focusChunkForDay(settings.day);
    const activeWords = words.filter((word) => dayOrder.includes(word.chunk)).length;
    const seenToday = words.filter((word) => getProgress(word).lastSeen === todayKey()).length;
    const hardWords = words.filter((word) => ["Hard", "Critical"].includes(getStatus(word))).length;

    $("#totalWords").textContent = meta.total || words.length;
    $("#activeWords").textContent = activeWords.toLocaleString("ko-KR");
    $("#seenToday").textContent = seenToday.toLocaleString("ko-KR");
    $("#hardWords").textContent = hardWords.toLocaleString("ko-KR");

    $("#chunkStrip").innerHTML = dayOrder
      .map((chunk, index) => {
        const count = words.filter((word) => word.chunk === chunk).length;
        const label = chunk === focusChunk ? "오늘 우선" : index === 0 ? "첫 회전" : "복습";
        return `
          <span class="chunk-chip ${chunk === focusChunk ? "is-focus" : ""}">
            Chunk ${chunk}
            <small>${label} · ${count.toLocaleString("ko-KR")}개</small>
          </span>
        `;
      })
      .join("");

    const firstChunk = dayOrder[0];
    const orderText = dayOrder.map((chunk) => `Chunk ${chunk}`).join(" → ");
    $("#planSummary").textContent =
      settings.day <= 5
        ? `Day ${settings.day}: ${orderText}. 새 청크를 더하면서 누적 노출을 늘립니다.`
        : `Day ${settings.day}: ${orderText}. Chunk ${firstChunk}부터 다시 앞에 세워 5개 청크를 계속 회전합니다.`;
  }

  function renderTrainer() {
    $("#sessionMode").textContent = modeLabels[settings.mode] || "카드 훑기";
    $("#positionText").textContent = queue.length ? `${currentIndex + 1} / ${queue.length}` : "0 / 0";

    const word = queue[currentIndex];
    if (!word) {
      $("#cardMeta").innerHTML = "";
      $("#cardBody").innerHTML = `
        <div class="empty-state">
          <h3>조건에 맞는 단어가 없습니다</h3>
          <p>청크, 상태, 검색어를 조금 넓히면 다시 목록이 만들어집니다.</p>
        </div>
      `;
      setNavigationDisabled(true);
      setStatusButtonState();
      return;
    }

    const itemProgress = getProgress(word);
    $("#cardMeta").innerHTML = `
      <span class="badge">${escapeHtml(word.sourceLabel)}</span>
      <span class="badge">Chunk ${word.chunk}</span>
      <span class="badge">No. ${word.rank}</span>
      ${word.group ? `<span class="badge">${escapeHtml(word.group)}</span>` : ""}
      ${statusPill(getStatus(word))}
      <span class="muted">확인 ${Number(itemProgress.seen || 0)} · 정답 ${Number(
        itemProgress.correct || 0,
      )} · 오답 ${Number(itemProgress.wrong || 0)}</span>
    `;

    $("#cardBody").innerHTML = renderCardBody(word);
    bindCardEvents(word);
    setNavigationDisabled(false);
    setStatusButtonState(word);
  }

  function renderCardBody(word) {
    if (settings.mode === "cloze") {
      return renderClozeMode(word);
    }
    if (settings.mode === "typing") {
      return renderTypingMode(word);
    }
    if (settings.mode === "meaning" || settings.mode === "hard") {
      return renderMeaningMode(word);
    }
    return renderCardsMode(word);
  }

  function renderCardsMode(word) {
    return `
      <div class="word-line">
        <h3>${escapeHtml(word.word)}</h3>
        <p>${escapeHtml(word.meaning)}</p>
      </div>
      ${renderExample(word, true)}
      ${renderExpression(word)}
    `;
  }

  function renderMeaningMode(word) {
    return `
      <div class="word-line large">
        <h3>${escapeHtml(word.word)}</h3>
      </div>
      ${
        revealed
          ? `<div class="answer-panel"><strong>${escapeHtml(word.meaning)}</strong></div>${renderExample(
              word,
              true,
            )}${renderExpression(word)}`
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
          ? `<div class="answer-panel"><strong>${escapeHtml(word.word)}</strong><span>${escapeHtml(
              word.meaning,
            )}</span></div>${renderExample(word, true)}`
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
          ? `<div class="answer-panel"><strong>${escapeHtml(word.word)}</strong></div>${renderExample(
              word,
              true,
            )}${renderExpression(word)}`
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
        ${word.exampleEn ? `<p class="example-en">${escapeHtml(word.exampleEn)}</p>` : ""}
        ${showKorean && word.exampleKo ? `<p class="example-ko">${escapeHtml(word.exampleKo)}</p>` : ""}
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

  function renderQueue() {
    $("#queueCount").textContent = `${queue.length.toLocaleString("ko-KR")}개`;
    if (!queue.length) {
      $("#queueList").innerHTML = `<p class="muted queue-empty">표시할 단어가 없습니다.</p>`;
      return;
    }

    const visible = queue.slice(0, 160);
    $("#queueList").innerHTML =
      visible
        .map((word, index) => {
          const status = getStatus(word);
          const active = index === currentIndex ? "is-active" : "";
          return `
            <button type="button" class="queue-item ${active}" data-index="${index}">
              <span>${index + 1}</span>
              <strong>${escapeHtml(word.word)}</strong>
              <small>${escapeHtml(word.sourceLabel)} · C${word.chunk} · ${
                statusConfig[status].label
              }</small>
            </button>
          `;
        })
        .join("") +
      (queue.length > visible.length
        ? `<p class="muted queue-more">앞 ${visible.length}개만 표시 중입니다.</p>`
        : "");

    document.querySelectorAll(".queue-item").forEach((item) => {
      item.addEventListener("click", () => {
        currentIndex = Number(item.dataset.index);
        revealed = false;
        feedback = null;
        renderTrainer();
        renderQueue();
      });
    });
  }

  function setNavigationDisabled(disabled) {
    $("#prevBtn").disabled = disabled || currentIndex <= 0;
    $("#nextBtn").disabled = disabled || currentIndex >= queue.length - 1;
    $("#speakWordBtn").disabled = disabled;
    $("#speakExampleBtn").disabled = disabled;
  }

  function setStatusButtonState(word) {
    document.querySelectorAll(".status-buttons button").forEach((button) => {
      button.disabled = !word;
      button.classList.toggle("is-active", Boolean(word) && button.dataset.status === getStatus(word));
    });
  }

  function syncControls() {
    $("#dayInput").value = settings.day;
    $("#modeSelect").value = settings.mode;
    $("#sourceSelect").value = settings.source;
    $("#chunkSelect").value = settings.chunk;
    $("#statusSelect").value = settings.status;
    $("#orderSelect").value = settings.order;
    $("#limitSelect").value = settings.limit;
    $("#searchInput").value = settings.search;
  }

  function markStatus(status) {
    const word = queue[currentIndex];
    if (!word) {
      return;
    }
    const itemProgress = ensureProgress(word);
    itemProgress.status = status;
    itemProgress.seen = Number(itemProgress.seen || 0) + 1;
    itemProgress.lastSeen = todayKey();
    itemProgress.updatedAt = new Date().toISOString();
    saveProgress();

    const nextId = queue[currentIndex + 1]?.id;
    revealed = false;
    feedback = null;
    rebuildAndRender(nextId);
  }

  function checkAnswer(word, rawAnswer) {
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
    itemProgress.seen = Number(itemProgress.seen || 0) + 1;
    itemProgress.lastSeen = todayKey();
    itemProgress.updatedAt = new Date().toISOString();

    if (correct) {
      itemProgress.correct = Number(itemProgress.correct || 0) + 1;
      if (!itemProgress.status || itemProgress.status === "New" || itemProgress.status === "Hard") {
        itemProgress.status = "Familiar";
      }
      feedback = { correct: true, message: `${word.word} · ${word.meaning}` };
    } else {
      itemProgress.wrong = Number(itemProgress.wrong || 0) + 1;
      itemProgress.status = itemProgress.wrong >= 3 ? "Critical" : "Hard";
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
    if (currentIndex < queue.length - 1) {
      currentIndex += 1;
      revealed = false;
      feedback = null;
      renderTrainer();
      renderQueue();
    }
  }

  function goPrev() {
    if (currentIndex > 0) {
      currentIndex -= 1;
      revealed = false;
      feedback = null;
      renderTrainer();
      renderQueue();
    }
  }

  function updateSetting(key, value) {
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

  function speak(text) {
    if (!text) {
      return;
    }
    if (!("speechSynthesis" in window)) {
      alert("이 브라우저에서는 음성 합성을 사용할 수 없습니다.");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.88;
    utterance.pitch = 1;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  function exportProgress() {
    const payload = {
      version: 1,
      exportedAt: new Date().toISOString(),
      source: meta.sourceFile || "TEPS_VOCA.xlsx",
      settings,
      progress,
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
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const payload = JSON.parse(String(reader.result || "{}"));
        if (!payload.progress || typeof payload.progress !== "object") {
          throw new Error("No progress object");
        }
        const confirmed = confirm("현재 브라우저의 진도를 불러온 파일로 교체할까요?");
        if (!confirmed) {
          return;
        }
        progress = payload.progress;
        settings = { ...settings, ...(payload.settings || {}) };
        saveProgress();
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
    const confirmed = confirm("저장된 상태, 정답/오답 기록을 모두 지울까요?");
    if (!confirmed) {
      return;
    }
    progress = {};
    saveProgress();
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
    $("#statusSelect").addEventListener("change", (event) => updateSetting("status", event.target.value));
    $("#orderSelect").addEventListener("change", (event) => updateSetting("order", event.target.value));
    $("#limitSelect").addEventListener("change", (event) => updateSetting("limit", event.target.value));
    $("#searchInput").addEventListener("input", (event) => updateSetting("search", event.target.value));

    $("#prevBtn").addEventListener("click", goPrev);
    $("#nextBtn").addEventListener("click", goNext);
    $("#restartBtn").addEventListener("click", () => {
      currentIndex = 0;
      revealed = false;
      feedback = null;
      renderTrainer();
      renderQueue();
    });

    $("#speakWordBtn").addEventListener("click", () => speak(queue[currentIndex]?.word));
    $("#speakExampleBtn").addEventListener("click", () => speak(queue[currentIndex]?.exampleEn));
    $("#exportBtn").addEventListener("click", exportProgress);
    $("#importFile").addEventListener("change", (event) => importProgress(event.target.files[0]));
    $("#resetBtn").addEventListener("click", resetProgress);

    document.querySelectorAll(".status-buttons button").forEach((button) => {
      button.addEventListener("click", () => markStatus(button.dataset.status));
    });

    document.addEventListener("keydown", (event) => {
      if (event.target.matches("input, select, textarea")) {
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
      if (["1", "2", "3", "4"].includes(event.key)) {
        const statuses = ["Easy", "Familiar", "Hard", "Critical"];
        markStatus(statuses[Number(event.key) - 1]);
      }
    });
  }

  bindControls();
  rebuildAndRender();
})();
