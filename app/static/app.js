(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const TERMINAL_RUN_STATUSES = new Set([
    "completed",
    "complete",
    "succeeded",
    "success",
    "failed",
    "error",
    "cancelled",
    "canceled",
    "cancelled_by_user",
  ]);
  const THEME_SETTING_KEY = "ui_theme";
  const THEME_STORAGE_KEY = "pgn-extractor-gui.theme";

  const state = {
    sources: [],
    gameCount: null,
    countingGames: false,
    presets: [],
    latestPreview: null,
    currentRunId: null,
    runStarting: false,
    pollTimer: null,
    pollFailures: 0,
    noticeTimer: null,
    themeChangedByUser: false,
    formEdited: false,
    presetOperation: false,
  };

  class ApiError extends Error {
    constructor(message, status = 0, payload = null) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
    }
  }

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    bindEvents();
    applyTheme(readStoredTheme() || preferredTheme());
    syncResetButton();
    syncPresetControls();
    syncOutputModeControls();
    renderSources();
    renderPresets();

    const [health, settings, presets] = await Promise.allSettled([
      request("/api/health"),
      request("/api/settings"),
      request("/api/presets"),
    ]);

    if (health.status !== "fulfilled") {
      showNotice(
        "The local backend could not be reached. Start the app again, then refresh this window.",
        "error",
      );
    }

    if (settings.status === "fulfilled") {
      const savedTheme = extractSavedTheme(settings.value);
      if (savedTheme && !state.themeChangedByUser) applyTheme(savedTheme);
      const savedForm = extractSavedForm(settings.value);
      if (savedForm && !state.formEdited) {
        applyForm(savedForm, { restoreValidation: false });
        showNotice("Restored locally saved settings.", "success", 2800);
      }
    }

    if (presets.status === "fulfilled") {
      state.presets = normalizePresets(presets.value);
      renderPresets();
    } else if (health.status === "fulfilled") {
      showNotice("The app is ready, but saved presets could not be loaded.", "error");
    }

    const binary = health.status === "fulfilled" && health.value && health.value.binary;
    if (binary && !binary.compatible) {
      showNotice(
        binary.message || "A compatible pgn-extract v26-06 (or newer) executable is required before a run can start.",
        "error",
      );
    }
  }

  function bindEvents() {
    $("#add-source").addEventListener("click", () => {
      addSourceInput();
    });

    $("#source-path").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addSourceInput();
      }
    });

    $("#browse-sources").addEventListener("click", chooseSourceFiles);
    $("#count-games").addEventListener("click", countSelectedGames);
    $("#browse-output").addEventListener("click", chooseOutputFile);
    $("#browse-split-output").addEventListener("click", chooseSplitOutputDirectory);
    $("#theme-toggle").addEventListener("click", toggleTheme);
    $("#reset-form").addEventListener("click", resetToDefaults);

    $("#split-games").addEventListener("input", syncOutputModeControls);
    $("#validation-only").addEventListener("change", syncOutputModeControls);

    $("#source-list").addEventListener("click", (event) => {
      const button = event.target.closest(".remove-source");
      if (!button) return;
      const index = Number(button.dataset.index);
      if (!Number.isInteger(index) || index < 0 || index >= state.sources.length) return;
      state.sources.splice(index, 1);
      clearGameCount();
      renderSources();
      markFormChanged();
    });

    $("#append-output").addEventListener("change", (event) => {
      if (event.target.checked) $("#overwrite-output").checked = false;
      markFormChanged();
    });

    $("#overwrite-output").addEventListener("change", (event) => {
      if (event.target.checked) $("#append-output").checked = false;
      markFormChanged();
    });

    document.querySelectorAll("[data-disclosure]").forEach((button) => {
      button.addEventListener("click", () => toggleDisclosure(button));
    });

    $("#job-form").addEventListener("submit", (event) => {
      event.preventDefault();
      runCommand();
    });

    $("#cancel-run").addEventListener("click", cancelCurrentRun);
    $("#save-preset").addEventListener("click", savePreset);
    $("#clear-presets").addEventListener("click", clearAllPresets);
    $("#preset-name").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        savePreset();
      }
    });

    $("#preset-list").addEventListener("click", (event) => {
      if (state.presetOperation) return;
      const button = event.target.closest(".preset-load, .preset-delete");
      if (!button) return;
      const presetId = Number(button.dataset.presetId);
      if (!Number.isInteger(presetId) || presetId < 1) return;
      const preset = state.presets.find((candidate) => Number(candidate.id) === presetId);
      if (!preset) return;
      if (button.classList.contains("preset-delete")) {
        deletePreset(preset, button);
        return;
      }
      loadPreset(preset);
    });

    $("#job-form").addEventListener("input", markFormChanged);
    $("#job-form").addEventListener("change", markFormChanged);
    window.addEventListener("beforeunload", stopPolling);
  }

  async function resetToDefaults() {
    if (state.runStarting || state.currentRunId) return;

    resetFormFields();
    clearGameCount();
    renderSources();
    markFormChanged();
    resetInactiveRunFeedback();
    $("#preset-name").value = "";

    try {
      await request("/api/settings", {
        method: "POST",
        body: { form: collectForm() },
      });
      showNotice("Reset form to defaults.", "success", 3200);
    } catch (error) {
      showNotice(
        `Reset form to defaults, but could not save the defaults: ${messageFromError(error)}`,
        "error",
      );
    }
  }

  function syncOutputModeControls() {
    const validationOnly = $("#validation-only").checked;
    const splitting = !validationOnly && valueOf("#split-games") !== "";
    const singleOutputDisabled = validationOnly || splitting;

    ["#output-path", "#browse-output", "#append-output", "#overwrite-output"].forEach((selector) => {
      $(selector).disabled = singleOutputDisabled;
    });
    ["#split-output-dir", "#browse-split-output"].forEach((selector) => {
      $(selector).disabled = validationOnly || !splitting;
    });
    $("#split-games").disabled = validationOnly;
  }

  function syncResetButton() {
    $("#reset-form").disabled = state.runStarting || Boolean(state.currentRunId);
  }

  function resetInactiveRunFeedback() {
    if (state.currentRunId) return;

    setRunStatus("idle");
    $("#run-meta").textContent = "No run yet.";
    $("#run-outputs").replaceChildren();
    $("#run-outputs").classList.add("hidden");
    $("#command-preview").textContent = "No command run yet.";
    $("#run-stdout").textContent = "No run output yet.";
    $("#run-stderr").textContent = "No errors yet.";
    renderMessageList("#command-errors", []);
    renderMessageList("#command-warnings", []);
  }

  function markFormChanged(event) {
    if (event && event.target && event.target.id === "preset-name") return;
    state.formEdited = true;
    markPreviewStale();
  }

  function normalizeTheme(value) {
    return value === "dark" || value === "light" ? value : null;
  }

  function preferredTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function readStoredTheme() {
    try {
      return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
    } catch {
      return null;
    }
  }

  function extractSavedTheme(payload) {
    if (!payload || typeof payload !== "object") return null;
    const settings = payload.settings;
    const value =
      (settings && typeof settings === "object" ? settings[THEME_SETTING_KEY] : null) ??
      payload[THEME_SETTING_KEY];
    return normalizeTheme(value);
  }

  function applyTheme(theme) {
    const selected = normalizeTheme(theme) || preferredTheme();
    document.documentElement.dataset.theme = selected;

    const isDark = selected === "dark";
    const toggle = $("#theme-toggle");
    toggle.setAttribute("aria-pressed", String(isDark));
    toggle.setAttribute("aria-label", `Switch to ${isDark ? "light" : "dark"} theme`);
    $("#theme-toggle-icon").textContent = isDark ? "☀" : "☾";
    $("#theme-toggle-label").textContent = isDark ? "Light theme" : "Dark theme";
  }

  function toggleTheme() {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    state.themeChangedByUser = true;
    applyTheme(next);
    persistTheme(next);
  }

  function persistTheme(theme) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // The SQLite setting below remains available when browser storage is unavailable.
    }

    request("/api/settings", {
      method: "POST",
      body: { settings: { [THEME_SETTING_KEY]: theme } },
    }).catch((error) => {
      console.warn("Could not save the selected theme:", error);
    });
  }

  async function request(path, options = {}) {
    const { method = "GET", body } = options;
    const requestOptions = {
      method,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    };

    if (body !== undefined) {
      requestOptions.headers["Content-Type"] = "application/json";
      requestOptions.body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(path, requestOptions);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Network request failed";
      throw new ApiError(`Could not reach the local backend: ${message}`);
    }

    const raw = await response.text();
    let payload = null;
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        payload = raw;
      }
    }

    if (!response.ok) {
      throw new ApiError(describeApiProblem(payload, response.status), response.status, payload);
    }

    return payload;
  }

  function describeApiProblem(payload, status) {
    if (payload && typeof payload === "object") {
      const detail = payload.detail ?? payload.error ?? payload.message ?? payload.errors;
      const description = messageText(detail);
      if (description) return description;
    }
    if (typeof payload === "string" && payload.trim()) return payload.trim();
    return `The local backend returned HTTP ${status}.`;
  }

  function messageText(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) {
      return value.map(messageText).filter(Boolean).join("; ");
    }
    if (typeof value === "object") {
      if (value.msg) return String(value.msg);
      if (value.message) return String(value.message);
      if (value.detail) return messageText(value.detail);
      try {
        return JSON.stringify(value);
      } catch {
        return "Unexpected response from the local backend.";
      }
    }
    return "";
  }

  function showNotice(message, kind = "success", timeout = 0) {
    const notice = $("#app-notice");
    window.clearTimeout(state.noticeTimer);
    notice.textContent = message;
    notice.className = `notice ${kind}`;
    if (timeout > 0) {
      state.noticeTimer = window.setTimeout(() => {
        notice.className = "notice hidden";
        notice.textContent = "";
      }, timeout);
    }
  }

  function clearNotice() {
    window.clearTimeout(state.noticeTimer);
    const notice = $("#app-notice");
    notice.className = "notice hidden";
    notice.textContent = "";
  }

  function toggleDisclosure(button) {
    const target = document.getElementById(button.dataset.disclosure);
    if (!target) return;
    const collapsed = !target.hidden;
    target.hidden = collapsed;
    target.classList.toggle("is-collapsed", collapsed);
    button.setAttribute("aria-expanded", String(!collapsed));
    button.textContent = collapsed ? "Show" : "Hide";
  }

  function addSourceInput() {
    const input = $("#source-path");
    if (!input.value.trim()) {
      showNotice("Enter a PGN file path first.", "error", 3200);
      input.focus();
      return;
    }
    const paths = input.value.split(/\r?\n/);
    const added = addSources(paths);
    if (added) {
      input.value = "";
      input.focus();
    }
  }

  function addSources(paths) {
    const existing = new Set(state.sources.map((path) => comparablePath(path)));
    let added = 0;
    let duplicates = 0;
    const flatPaths = Array.isArray(paths) ? paths : [paths];

    flatPaths.forEach((value) => {
      String(value || "")
        .split(/\r?\n/)
        .map((path) => path.trim())
        .filter(Boolean)
        .forEach((path) => {
          const key = comparablePath(path);
          if (existing.has(key)) {
            duplicates += 1;
            return;
          }
          existing.add(key);
          state.sources.push(path);
          added += 1;
        });
    });

    if (added) {
      clearGameCount();
      renderSources();
      markFormChanged();
    }
    if (!added && duplicates) showNotice("That source file is already in the list.", "error", 3200);
    return added;
  }

  function comparablePath(path) {
    return String(path).replaceAll("/", "\\").toLocaleLowerCase();
  }

  function renderSources() {
    const list = $("#source-list");
    const listDetails = $("#source-list-details");
    const count = state.sources.length;
    const countText = `${count} ${count === 1 ? "file" : "files"}`;
    const gameCountText = state.gameCount === null
      ? ""
      : ` · ${state.gameCount} ${state.gameCount === 1 ? "game" : "games"}`;
    $("#source-count").textContent = `${countText}${gameCountText}`;
    $("#count-games").disabled = count === 0 || state.countingGames;
    list.replaceChildren();

    if (!count) {
      listDetails.hidden = true;
      listDetails.open = false;
      const empty = document.createElement("li");
      empty.className = "empty-state";
      empty.textContent = "No input files selected yet.";
      list.append(empty);
      return;
    }

    listDetails.hidden = false;

    const template = $("#source-item-template");
    state.sources.forEach((path, index) => {
      const fragment = template.content.cloneNode(true);
      const item = fragment.querySelector(".source-item");
      const pathNode = fragment.querySelector(".source-item-path");
      const removeButton = fragment.querySelector(".remove-source");
      pathNode.textContent = path;
      pathNode.title = path;
      item.title = path;
      removeButton.dataset.index = String(index);
      removeButton.setAttribute("aria-label", `Remove ${path}`);
      list.append(fragment);
    });
  }

  function clearGameCount() {
    state.gameCount = null;
  }

  function sourceSignature(paths = state.sources) {
    return paths.map(comparablePath).join("\u0000");
  }

  async function countSelectedGames() {
    if (!state.sources.length || state.countingGames) return;

    const sources = [...state.sources];
    const signature = sourceSignature(sources);
    state.countingGames = true;
    setButtonBusy("#count-games", true, "Counting…");
    try {
      const result = await request("/api/game-count", {
        method: "POST",
        body: { input_files: sources },
      });
      const gameCount = Number(result && result.game_count);
      if (!Number.isInteger(gameCount) || gameCount < 0) {
        throw new ApiError("The local backend returned an invalid game count.");
      }
      if (signature === sourceSignature()) {
        state.gameCount = gameCount;
      }
    } catch (error) {
      showNotice(`Could not count games: ${messageFromError(error)}`, "error");
    } finally {
      state.countingGames = false;
      setButtonBusy("#count-games", false, "Count games");
      renderSources();
    }
  }

  function getDesktopApi() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  async function chooseSourceFiles() {
    const desktop = getDesktopApi();
    if (!desktop || typeof desktop.pickFiles !== "function") {
      $("#source-path").focus();
      showNotice("The file picker is unavailable here. Paste a PGN path into the source field.", "error");
      return;
    }

    try {
      const selected = await desktop.pickFiles({
        multiple: true,
        extensions: ["pgn"],
      });
      const paths = pathsFromPicker(selected);
      if (paths.length) addSources(paths);
    } catch (error) {
      showNotice(`Could not open the file picker: ${messageFromError(error)}`, "error");
    }
  }

  async function chooseOutputFile() {
    const desktop = getDesktopApi();
    if (!desktop || typeof desktop.pickSaveFile !== "function") {
      if (desktop && typeof desktop.pickDirectory === "function") {
        await chooseOutputDirectory(desktop);
        return;
      }
      $("#output-path").focus();
      showNotice("The save dialog is unavailable here. Enter an output file path manually.", "error");
      return;
    }

    try {
      const selected = await desktop.pickSaveFile({
        suggestedName: "extracted.pgn",
        extensions: ["pgn"],
      });
      const paths = pathsFromPicker(selected);
      if (paths.length) {
        $("#output-path").value = paths[0];
        markFormChanged();
      }
    } catch (error) {
      showNotice(`Could not open the save dialog: ${messageFromError(error)}`, "error");
    }
  }

  async function chooseOutputDirectory(desktop) {
    try {
      const selected = await desktop.pickDirectory();
      const paths = pathsFromPicker(selected);
      if (!paths.length) return;
      const folder = paths[0].replace(/[\\/]+$/, "");
      $("#output-path").value = `${folder}\\extracted.pgn`;
      markFormChanged();
      showNotice("Selected a folder and used the default file name extracted.pgn. You can edit the name.", "success", 4600);
    } catch (error) {
      $("#output-path").focus();
      showNotice(`Could not choose an output folder: ${messageFromError(error)}`, "error");
    }
  }

  async function chooseSplitOutputDirectory() {
    const desktop = getDesktopApi();
    if (!desktop || typeof desktop.pickDirectory !== "function") {
      $("#split-output-dir").focus();
      showNotice("The folder picker is unavailable here. Enter a split-output folder manually.", "error");
      return;
    }

    try {
      const selected = await desktop.pickDirectory();
      const paths = pathsFromPicker(selected);
      if (paths.length) {
        $("#split-output-dir").value = paths[0];
        markFormChanged();
      }
    } catch (error) {
      showNotice(`Could not choose a split-output folder: ${messageFromError(error)}`, "error");
    }
  }

  function pathsFromPicker(result) {
    if (result === null || result === undefined || result === false) return [];
    if (typeof result === "string") return result.trim() ? [result] : [];
    if (Array.isArray(result)) return result.flatMap(pathsFromPicker);
    if (typeof result === "object") {
      const candidates = result.paths || result.files || result.path || result.file || result.value;
      return pathsFromPicker(candidates);
    }
    return [];
  }

  function messageFromError(error) {
    if (error instanceof Error) return error.message;
    return String(error || "Unknown error");
  }

  function collectForm() {
    const filters = {
      player: valueOf("#filter-player"),
      event: valueOf("#filter-event"),
      site: valueOf("#filter-site"),
      date: valueOf("#filter-date"),
      date_from: valueOf("#filter-date-from"),
      date_to: valueOf("#filter-date-to"),
      round: valueOf("#filter-round"),
      white: valueOf("#filter-white"),
      black: valueOf("#filter-black"),
      result: valueOf("#filter-result"),
      eco: valueOf("#filter-eco"),
      minimum_elo: numberValue("#filter-minimum-elo"),
      maximum_elo: numberValue("#filter-maximum-elo"),
      selected_games: valueOf("#filter-selected-games"),
      first_game: numberValue("#filter-first-game"),
      last_game: numberValue("#filter-last-game"),
      min_plies: numberValue("#filter-min-plies"),
      max_plies: numberValue("#filter-max-plies"),
      checkmate: $("#filter-checkmate").checked,
      stalemate: $("#filter-stalemate").checked,
      repetition: $("#filter-repetition").checked,
      setup_position: $("#filter-setup").checked,
    };

    const formatting = {
      output_format: "pgn",
      variations: valueOf("#variation-mode") || "keep",
      line_width: numberValue("#line-width"),
      include_tags: $("#include-tags").checked,
      remove_duplicates: $("#remove-duplicates").checked,
      remove_comments: $("#remove-comments").checked,
      remove_nags: $("#remove-nags").checked,
      include_fen_comments: $("#include-fen-comments").checked,
      classify_eco: $("#classify-eco").checked,
    };

    const inputFiles = [...state.sources];
    const validationOnly = $("#validation-only").checked;
    const splitGames = validationOnly ? null : numberValue("#split-games");
    const splitting = splitGames !== null;

    return {
      input_files: inputFiles,
      sources: inputFiles,
      output_path: validationOnly || splitting ? null : valueOf("#output-path") || null,
      append_output: !validationOnly && !splitting && $("#append-output").checked,
      overwrite_output: !validationOnly && !splitting && $("#overwrite-output").checked,
      split_games: splitGames,
      split_output_dir: splitting ? valueOf("#split-output-dir") || null : null,
      validation_only: validationOnly,
      game_filters: filters,
      filters,
      formatting,
      advanced_tokens: [],
      literal_tokens: [],
    };
  }

  function valueOf(selector) {
    return $(selector).value.trim();
  }

  function numberValue(selector) {
    const value = valueOf(selector);
    if (value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function validateForm(form) {
    const errors = [];
    const warnings = [];
    const filters = form.game_filters || {};

    if (!form.input_files.length) errors.push("Add at least one PGN source file before running.");
    if (filters.first_game !== null && filters.first_game !== undefined && filters.first_game < 1) {
      errors.push("First game must be at least 1.");
    }
    if (filters.last_game !== null && filters.last_game !== undefined && filters.last_game < 1) {
      errors.push("Last game must be at least 1.");
    }
    if (filters.min_plies !== null && filters.min_plies !== undefined && filters.min_plies < 0) {
      errors.push("Minimum plies cannot be negative.");
    }
    if (filters.max_plies !== null && filters.max_plies !== undefined && filters.max_plies < 0) {
      errors.push("Maximum plies cannot be negative.");
    }
    if (
      filters.first_game !== null &&
      filters.first_game !== undefined &&
      !Number.isInteger(filters.first_game)
    ) {
      errors.push("First game must be a whole number.");
    }
    if (
      filters.last_game !== null &&
      filters.last_game !== undefined &&
      !Number.isInteger(filters.last_game)
    ) {
      errors.push("Last game must be a whole number.");
    }
    if (
      filters.min_plies !== null &&
      filters.min_plies !== undefined &&
      !Number.isInteger(filters.min_plies)
    ) {
      errors.push("Minimum plies must be a whole number.");
    }
    if (
      filters.max_plies !== null &&
      filters.max_plies !== undefined &&
      !Number.isInteger(filters.max_plies)
    ) {
      errors.push("Maximum plies must be a whole number.");
    }
    if (
      filters.first_game !== null &&
      filters.last_game !== null &&
      filters.first_game !== undefined &&
      filters.last_game !== undefined &&
      filters.first_game > filters.last_game
    ) {
      errors.push("The first game cannot be greater than the last game.");
    }
    if (filters.min_plies !== null && filters.max_plies !== null && filters.min_plies > filters.max_plies) {
      errors.push("Minimum plies cannot be greater than maximum plies.");
    }
    if (filters.minimum_elo !== null && filters.minimum_elo !== undefined) {
      if (!Number.isInteger(filters.minimum_elo) || filters.minimum_elo < 0) {
        errors.push("Minimum Elo must be a whole number of at least 0.");
      }
    }
    if (filters.maximum_elo !== null && filters.maximum_elo !== undefined) {
      if (!Number.isInteger(filters.maximum_elo) || filters.maximum_elo < 0) {
        errors.push("Maximum Elo must be a whole number of at least 0.");
      }
    }
    if (
      filters.minimum_elo !== null &&
      filters.maximum_elo !== null &&
      filters.minimum_elo > filters.maximum_elo
    ) {
      errors.push("Minimum Elo cannot be greater than maximum Elo.");
    }
    const dateFields = [filters.date, filters.date_from, filters.date_to].filter(Boolean);
    if (dateFields.some((date) => !/^\d{4}(?:\.\d{2}(?:\.\d{2})?)?$/.test(date))) {
      errors.push("Date filters must use YYYY, YYYY.MM, or YYYY.MM.DD.");
    }
    if (filters.date && (filters.date_from || filters.date_to)) {
      errors.push("Use either Date / year or a Date from/through range, not both.");
    }
    const selectedGamesError = validateSelectedGames(filters.selected_games);
    if (selectedGamesError) errors.push(selectedGamesError);
    if (form.formatting.line_width !== null && form.formatting.line_width !== undefined) {
      if (!Number.isInteger(form.formatting.line_width) || form.formatting.line_width < 20) {
        errors.push("Line width must be a whole number of at least 20.");
      }
    }
    if (form.split_games !== null && form.split_games !== undefined) {
      if (!Number.isInteger(form.split_games) || form.split_games < 1) {
        errors.push("Games per output file must be a whole number of at least 1.");
      }
      if (!form.split_output_dir) errors.push("Choose a split-output folder when splitting games.");
    }
    if (!form.output_path && (form.append_output || form.overwrite_output)) {
      warnings.push("Append/overwrite is selected, but no output file is set. Results will remain in the run log.");
    }
    return { errors, warnings };
  }

  function validateSelectedGames(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    let previousEnd = 0;
    for (const rawRange of text.split(",")) {
      const range = rawRange.trim();
      if (!range) return "Selected games must be a comma-separated list of game numbers or ranges.";
      const bounds = range.split(":");
      if (bounds.length > 2 || bounds.some((bound) => !/^\d+$/.test(bound))) {
        return "Selected game ranges use numbers and one colon, for example 1:10,15,89:94.";
      }
      const start = Number(bounds[0]);
      const end = Number(bounds[bounds.length - 1]);
      if (start < 1 || end < 1 || start > end) {
        return "Each selected game range must use positive ascending numbers.";
      }
      if (start <= previousEnd) {
        return "Selected game ranges must be strictly ascending and cannot overlap.";
      }
      previousEnd = end;
    }
    return "";
  }

  async function previewCommand() {
    clearNotice();
    const form = collectForm();
    const validation = validateForm(form);
    if (validation.errors.length) {
      renderPreview(null, validation.errors, validation.warnings);
      return null;
    }

    try {
      const preview = await request("/api/command/preview", {
        method: "POST",
        body: { form },
      });
      state.latestPreview = preview || {};
      renderPreview(preview, [], validation.warnings);
      return preview || {};
    } catch (error) {
      state.latestPreview = null;
      renderPreview(null, [messageFromError(error)], validation.warnings);
      return null;
    }
  }

  function renderPreview(preview, localErrors = [], localWarnings = []) {
    const errors = [...localErrors, ...normalizeMessages(preview && preview.errors)];
    const warnings = [...localWarnings, ...normalizeMessages(preview && preview.warnings)];
    const previewElement = $("#command-preview");

    if (preview) {
      const command = preview.display || commandDisplay(preview.argv);
      previewElement.textContent = command || "The backend did not return a command preview.";
    } else if (errors.length) {
      previewElement.textContent = "Resolve the listed issue(s), then run again.";
    } else {
      previewElement.textContent = "The command will appear here when a run starts.";
    }

    renderMessageList("#command-errors", errors);
    renderMessageList("#command-warnings", warnings);
  }

  function commandDisplay(argv) {
    if (!Array.isArray(argv)) return "";
    return argv.map((argument) => quoteArgument(argument)).join(" ");
  }

  function quoteArgument(argument) {
    const value = String(argument ?? "");
    if (!value || /[\s"^&|<>]/.test(value)) return `"${value.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
    return value;
  }

  function normalizeMessages(value) {
    if (value === null || value === undefined || value === false) return [];
    const values = Array.isArray(value) ? value : [value];
    return values.map(messageText).filter(Boolean);
  }

  function renderMessageList(selector, messages) {
    const element = $(selector);
    element.replaceChildren();
    if (!messages.length) {
      element.classList.add("hidden");
      return;
    }
    const list = document.createElement("ul");
    messages.forEach((message) => {
      const item = document.createElement("li");
      item.textContent = message;
      list.append(item);
    });
    element.append(list);
    element.classList.remove("hidden");
  }

  function setButtonBusy(selector, busy, idleText) {
    const button = $(selector);
    if (busy) {
      button.dataset.idleText = button.textContent;
      button.disabled = true;
      button.textContent = idleText;
      return;
    }
    button.disabled = false;
    button.textContent = button.dataset.idleText || idleText;
  }

  async function runCommand() {
    if (state.currentRunId || state.runStarting) {
      showNotice("A run is already active. Cancel it or wait for it to finish.", "error");
      return;
    }

    state.runStarting = true;
    syncResetButton();
    const runButton = $("#run-command");
    runButton.disabled = true;
    runButton.textContent = "Checking…";
    try {
      const preview = await previewCommand();
      if (!preview) return;
      const previewErrors = normalizeMessages(preview.errors);
      if (previewErrors.length) return;

      runButton.textContent = "Starting…";
      const run = await request("/api/runs", {
        method: "POST",
        body: { form: collectForm() },
      });
      const id = run && (run.id || run.run_id);
      if (!id) {
        throw new ApiError(run && run.error ? String(run.error) : "The backend did not return a run ID.");
      }

      state.currentRunId = String(id);
      state.pollFailures = 0;
      setRunStatus((run && run.status) || "running");
      runButton.textContent = "Run active";
      $("#cancel-run").disabled = false;
      $("#run-meta").textContent = `Run ${id} started. Waiting for pgn-extract…`;
      $("#run-stdout").textContent = "Waiting for output…";
      $("#run-stderr").textContent = "No errors reported yet.";
      $("#run-outputs").replaceChildren();
      $("#run-outputs").classList.add("hidden");
      startPolling(state.currentRunId);
    } catch (error) {
      setRunStatus("failed");
      $("#run-meta").textContent = `Could not start the run: ${messageFromError(error)}`;
      showNotice(`Could not start pgn-extract: ${messageFromError(error)}`, "error");
    } finally {
      state.runStarting = false;
      syncResetButton();
      if (!state.currentRunId) {
        runButton.disabled = false;
        runButton.textContent = "Run pgn-extract";
      }
    }
  }

  function startPolling(id) {
    stopPolling();
    const poll = async () => {
      if (!state.currentRunId || state.currentRunId !== id) return;
      try {
        const job = await request(`/api/runs/${encodeURIComponent(id)}`);
        state.pollFailures = 0;
        renderRun(job || { id });
        const status = normalizeStatus(job && job.status);
        if (isTerminalStatus(status)) {
          finishRun();
          return;
        }
        state.pollTimer = window.setTimeout(poll, 850);
      } catch (error) {
        state.pollFailures += 1;
        $("#run-meta").textContent = `Run ${id} is still active, but its status could not be read: ${messageFromError(error)}`;
        if (state.pollFailures >= 4) {
          setRunStatus("failed");
          showNotice("Stopped polling the run after repeated backend errors. The process may still be active.", "error");
          finishRun();
          return;
        }
        state.pollTimer = window.setTimeout(poll, 1500);
      }
    };
    poll();
  }

  function stopPolling() {
    if (state.pollTimer !== null) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function finishRun() {
    stopPolling();
    state.currentRunId = null;
    syncResetButton();
    $("#cancel-run").disabled = true;
    $("#run-command").disabled = false;
    $("#run-command").textContent = "Run pgn-extract";
  }

  function renderRun(job) {
    const status = normalizeStatus(job.status || "running");
    setRunStatus(status);
    const details = [];
    if (job.id || job.run_id) details.push(`Run ${job.id || job.run_id}`);
    if (job.started_at) details.push(`started ${formatTimestamp(job.started_at)}`);
    if (job.finished_at) details.push(`finished ${formatTimestamp(job.finished_at)}`);
    if (job.returncode !== null && job.returncode !== undefined) details.push(`exit code ${job.returncode}`);
    if (!details.length) details.push("Waiting for run details…");
    $("#run-meta").textContent = details.join(" · ");

    if (Object.hasOwn(job, "stdout")) {
      $("#run-stdout").textContent = job.stdout || "(No standard output.)";
    }
    if (Object.hasOwn(job, "stderr")) {
      $("#run-stderr").textContent = job.stderr || "(No standard error.)";
    }

    if (job.display_command) {
      $("#command-preview").textContent = job.display_command;
    }
    if (job.warnings) {
      renderMessageList("#command-warnings", normalizeMessages(job.warnings));
    }
    if (job.error) {
      renderMessageList("#command-errors", [messageText(job.error)]);
    }
    renderOutputs(job.outputs);
  }

  function renderOutputs(outputs) {
    const container = $("#run-outputs");
    const values = Array.isArray(outputs) ? outputs : outputs ? [outputs] : [];
    container.replaceChildren();
    if (!values.length) {
      container.classList.add("hidden");
      return;
    }

    values.forEach((output) => {
      const path = typeof output === "string" ? output : output.path || output.file || output.name || messageText(output);
      if (!path) return;
      const item = document.createElement("div");
      item.className = "run-output-link";
      item.title = path;
      item.textContent = path;
      container.append(item);
    });
    container.classList.toggle("hidden", !container.childElementCount);
  }

  function normalizeStatus(status) {
    return String(status || "idle").trim().toLocaleLowerCase().replaceAll(" ", "_");
  }

  function isTerminalStatus(status) {
    return TERMINAL_RUN_STATUSES.has(status);
  }

  function setRunStatus(status) {
    const element = $("#run-status");
    const normalized = normalizeStatus(status);
    element.className = `run-status ${statusClass(normalized)}`;
    element.textContent = displayStatus(normalized);
  }

  function statusClass(status) {
    if (["completed", "complete", "succeeded", "success"].includes(status)) return "completed";
    if (["failed", "error"].includes(status)) return "failed";
    if (["cancelled", "canceled", "cancelled_by_user"].includes(status)) return "cancelled";
    if (["running", "queued", "starting", "cancelling"].includes(status)) return "running";
    return "idle";
  }

  function displayStatus(status) {
    if (!status) return "Idle";
    return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function formatTimestamp(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }).format(date);
  }

  async function cancelCurrentRun() {
    const id = state.currentRunId;
    if (!id) return;
    $("#cancel-run").disabled = true;
    $("#cancel-run").textContent = "Cancelling…";
    try {
      const run = await request(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      setRunStatus((run && run.status) || "cancelling");
      $("#run-meta").textContent = `Cancellation requested for run ${id}.`;
    } catch (error) {
      $("#cancel-run").disabled = false;
      showNotice(`Could not cancel the run: ${messageFromError(error)}`, "error");
    } finally {
      $("#cancel-run").textContent = "Cancel run";
    }
  }

  function extractSavedForm(settings) {
    if (!settings || typeof settings !== "object") return null;
    const candidates = [settings.form, settings.last_form, settings.lastForm, settings.default_form, settings.defaultForm];
    return candidates.find((candidate) => candidate && typeof candidate === "object") || null;
  }

  function applyForm(saved, { restoreValidation = true } = {}) {
    const form = saved.form && typeof saved.form === "object" ? saved.form : saved;
    resetFormFields();
    const sources = form.input_files || form.sources || form.inputPaths || form.input_paths || [];
    state.sources = uniquePaths(Array.isArray(sources) ? sources : [sources]);
    clearGameCount();
    renderSources();

    setValueIfPresent("#output-path", form.output_path ?? form.outputPath);
    setCheckboxIfPresent("#append-output", form.append_output ?? form.appendOutput);
    setCheckboxIfPresent("#overwrite-output", form.overwrite_output ?? form.overwriteOutput);
    setValueIfPresent("#split-games", form.split_games ?? form.splitGames ?? form.games_per_file);
    setValueIfPresent("#split-output-dir", form.split_output_dir ?? form.splitOutputDir);
    if (restoreValidation) {
      setCheckboxIfPresent("#validation-only", form.validation_only ?? form.validationOnly);
    }

    const filters = form.game_filters || form.filters || {};
    setValueIfPresent("#filter-player", filters.player ?? form.player);
    setValueIfPresent("#filter-event", filters.event ?? form.event);
    setValueIfPresent("#filter-site", filters.site ?? form.site);
    setValueIfPresent("#filter-date", filters.date ?? form.date);
    setValueIfPresent("#filter-date-from", filters.date_from ?? filters.dateFrom ?? form.date_from);
    setValueIfPresent("#filter-date-to", filters.date_to ?? filters.dateTo ?? form.date_to);
    setValueIfPresent("#filter-round", filters.round ?? form.round);
    setValueIfPresent("#filter-white", filters.white ?? form.white);
    setValueIfPresent("#filter-black", filters.black ?? form.black);
    setSelectIfPresent("#filter-result", filters.result ?? form.result);
    setValueIfPresent("#filter-eco", filters.eco ?? form.eco);
    setValueIfPresent("#filter-minimum-elo", filters.minimum_elo ?? filters.min_elo ?? form.minimum_elo);
    setValueIfPresent("#filter-maximum-elo", filters.maximum_elo ?? filters.max_elo ?? form.maximum_elo);
    setValueIfPresent("#filter-selected-games", filters.selected_games ?? filters.selectedGames ?? form.selected_games);
    setValueIfPresent("#filter-first-game", filters.first_game ?? filters.firstGame ?? form.first_game);
    setValueIfPresent("#filter-last-game", filters.last_game ?? filters.lastGame ?? form.last_game);
    setValueIfPresent("#filter-min-plies", filters.min_plies ?? filters.minPlies ?? form.min_plies);
    setValueIfPresent("#filter-max-plies", filters.max_plies ?? filters.maxPlies ?? form.max_plies);
    setCheckboxIfPresent("#filter-checkmate", filters.checkmate ?? form.checkmate);
    setCheckboxIfPresent("#filter-stalemate", filters.stalemate ?? form.stalemate);
    setCheckboxIfPresent("#filter-repetition", filters.repetition ?? form.repetition);
    setCheckboxIfPresent("#filter-setup", filters.setup_position ?? filters.setupPosition ?? form.setup_position);

    const formatting = form.formatting || form.output_formatting || {};
    const variation = formatting.variations ?? formatting.variation_mode ?? form.variations;
    if (typeof variation === "boolean") {
      $("#variation-mode").value = variation ? "keep" : "remove";
    } else if (variation !== null && variation !== undefined) {
      setSelectIfPresent("#variation-mode", variation);
    } else if (typeof formatting.keep_variations === "boolean") {
      $("#variation-mode").value = formatting.keep_variations ? "keep" : "remove";
    } else {
      setSelectIfPresent("#variation-mode", formatting.keep_variations);
    }
    setValueIfPresent("#line-width", formatting.line_width ?? formatting.lineWidth ?? form.line_width);
    setCheckboxIfPresent("#include-tags", formatting.include_tags ?? formatting.tags ?? form.include_tags);
    setCheckboxIfPresent("#remove-duplicates", formatting.remove_duplicates ?? form.remove_duplicates);
    applyRemovalSetting(
      "#remove-comments",
      formatting.remove_comments ?? form.remove_comments,
      formatting.include_comments ?? formatting.keep_comments ?? formatting.comments ?? form.include_comments,
    );
    applyRemovalSetting(
      "#remove-nags",
      formatting.remove_nags ?? form.remove_nags,
      formatting.include_nags ?? formatting.keep_nags ?? formatting.nags ?? form.include_nags,
    );
    setCheckboxIfPresent("#include-fen-comments", formatting.include_fen_comments ?? formatting.fen_comments ?? form.include_fen_comments);
    setCheckboxIfPresent("#classify-eco", formatting.classify_eco ?? formatting.eco ?? form.classify_eco);
    syncOutputModeControls();
  }

  function resetFormFields() {
    state.sources = [];
    $("#source-list-details").open = false;
    $("#source-path").value = "";
    [
      "#output-path",
      "#split-games",
      "#split-output-dir",
      "#filter-player",
      "#filter-event",
      "#filter-site",
      "#filter-date",
      "#filter-date-from",
      "#filter-date-to",
      "#filter-round",
      "#filter-white",
      "#filter-black",
      "#filter-eco",
      "#filter-minimum-elo",
      "#filter-maximum-elo",
      "#filter-selected-games",
      "#filter-first-game",
      "#filter-last-game",
      "#filter-min-plies",
      "#filter-max-plies",
      "#line-width",
    ].forEach((selector) => {
      $(selector).value = "";
    });
    $("#filter-result").value = "";
    $("#variation-mode").value = "keep";
    [
      "#append-output",
      "#overwrite-output",
      "#validation-only",
      "#filter-checkmate",
      "#filter-stalemate",
      "#filter-repetition",
      "#filter-setup",
      "#remove-duplicates",
      "#remove-comments",
      "#remove-nags",
      "#include-fen-comments",
      "#classify-eco",
    ].forEach((selector) => {
      $(selector).checked = false;
    });
    ["#include-tags"].forEach((selector) => {
      $(selector).checked = true;
    });
    syncOutputModeControls();
  }

  function uniquePaths(paths) {
    const seen = new Set();
    return paths
      .map((path) => String(path || "").trim())
      .filter(Boolean)
      .filter((path) => {
        const key = comparablePath(path);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }

  function setValueIfPresent(selector, value) {
    if (value === null || value === undefined) return;
    $(selector).value = String(value);
  }

  function setSelectIfPresent(selector, value) {
    if (value === null || value === undefined) return;
    const select = $(selector);
    const candidate = String(value);
    if ([...select.options].some((option) => option.value === candidate)) select.value = candidate;
  }

  function checkboxValue(value) {
    return value === true || value === 1 || value === "1" || value === "true" || value === "True" || value === "on";
  }

  function setCheckboxIfPresent(selector, value) {
    if (value === null || value === undefined) return;
    $(selector).checked = checkboxValue(value);
  }

  function applyRemovalSetting(selector, removalValue, legacyKeepValue) {
    if (removalValue !== null && removalValue !== undefined) {
      setCheckboxIfPresent(selector, removalValue);
    } else if (legacyKeepValue !== null && legacyKeepValue !== undefined) {
      $(selector).checked = !checkboxValue(legacyKeepValue);
    }
  }

  function normalizePresets(data) {
    if (Array.isArray(data)) return data.map(normalizePreset).filter(Boolean);
    if (!data || typeof data !== "object") return [];
    const collection = data.presets || data.items || data.results;
    if (Array.isArray(collection)) return collection.map(normalizePreset).filter(Boolean);
    if (collection && typeof collection === "object") {
      return Object.entries(collection)
        .map(([name, form]) => normalizePreset({ name, form }))
        .filter(Boolean);
    }
    return [];
  }

  function normalizePreset(preset) {
    if (!preset) return null;
    if (typeof preset === "string") return { name: preset, form: null };
    if (typeof preset !== "object") return null;
    return {
      ...preset,
      name: String(preset.name || preset.title || preset.id || "Unnamed preset"),
      form: preset.form || preset.configuration || preset.data || preset.options || null,
    };
  }

  function syncPresetControls() {
    const busy = state.presetOperation;
    $("#preset-name").disabled = busy;
    $("#save-preset").disabled = busy;
    $("#clear-presets").disabled = busy || state.presets.length === 0;
    document.querySelectorAll(".preset-load, .preset-delete").forEach((button) => {
      button.disabled = busy;
    });
  }

  function beginPresetOperation() {
    if (state.presetOperation) return false;
    state.presetOperation = true;
    syncPresetControls();
    return true;
  }

  function endPresetOperation() {
    state.presetOperation = false;
    syncPresetControls();
  }

  function renderPresets() {
    const container = $("#preset-list");
    container.replaceChildren();
    if (!state.presets.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No saved presets.";
      container.append(empty);
      syncPresetControls();
      return;
    }

    state.presets.forEach((preset) => {
      const item = document.createElement("div");
      item.className = "preset-item";
      const name = document.createElement("span");
      name.className = "preset-name";
      name.textContent = preset.name;
      name.title = preset.name;
      const load = document.createElement("button");
      load.className = "secondary preset-load";
      load.type = "button";
      load.dataset.presetId = String(preset.id);
      load.textContent = "Load";
      load.setAttribute("aria-label", `Load preset ${preset.name}`);
      const actions = document.createElement("div");
      actions.className = "preset-item-actions";
      const remove = document.createElement("button");
      remove.className = "danger secondary preset-delete";
      remove.type = "button";
      remove.dataset.presetId = String(preset.id);
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", `Delete preset ${preset.name}`);
      actions.append(load, remove);
      item.append(name, actions);
      container.append(item);
    });
    syncPresetControls();
  }

  async function refreshPresets() {
    const data = await request("/api/presets");
    const presets = normalizePresets(data);
    state.presets = presets;
    renderPresets();
  }

  function loadPreset(preset) {
    if (!beginPresetOperation()) return;
    try {
      const form = preset.form || preset.configuration || preset.data || preset.options;
      if (!form || typeof form !== "object") {
        showNotice("That preset does not contain usable form settings.", "error");
        return;
      }
      applyForm(form);
      markFormChanged();
      showNotice(`Loaded preset “${preset.name || "Unnamed preset"}”.`, "success", 3000);
    } finally {
      endPresetOperation();
    }
  }

  async function deletePreset(preset, button) {
    const presetId = Number(preset && preset.id);
    if (!Number.isInteger(presetId) || presetId < 1) {
      showNotice("That preset cannot be deleted because it has no valid saved ID.", "error");
      return;
    }
    if (!window.confirm(`Delete preset “${preset.name}”?`)) return;
    if (!beginPresetOperation()) return;

    const idleText = button.textContent;
    button.disabled = true;
    button.textContent = "Deleting…";
    try {
      await request(`/api/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" });
      try {
        await refreshPresets();
      } catch (error) {
        showNotice(
          `Deleted preset “${preset.name}”, but could not refresh the preset list: ${messageFromError(error)}`,
          "error",
        );
        return;
      }
      showNotice(`Deleted preset “${preset.name}”.`, "success", 3200);
    } catch (error) {
      showNotice(`Could not delete preset “${preset.name}”: ${messageFromError(error)}`, "error");
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = idleText;
      }
      endPresetOperation();
    }
  }

  async function clearAllPresets() {
    if (!state.presets.length) return;
    if (!window.confirm("Delete all saved presets? This cannot be undone.")) return;
    if (!beginPresetOperation()) return;

    const button = $("#clear-presets");
    const idleText = button.textContent;
    button.disabled = true;
    button.textContent = "Clearing…";
    try {
      await request("/api/presets", { method: "DELETE" });
      try {
        await refreshPresets();
      } catch (error) {
        showNotice(
          `Cleared saved presets, but could not refresh the preset list: ${messageFromError(error)}`,
          "error",
        );
        return;
      }
      showNotice("Cleared all saved presets.", "success", 3200);
    } catch (error) {
      showNotice(`Could not clear saved presets: ${messageFromError(error)}`, "error");
    } finally {
      if (button.isConnected) {
        button.textContent = idleText;
      }
      endPresetOperation();
    }
  }

  async function savePreset() {
    const input = $("#preset-name");
    const name = input.value.trim();
    if (!name) {
      input.focus();
      showNotice("Enter a name before saving a preset.", "error");
      return;
    }
    if (!beginPresetOperation()) return;

    setButtonBusy("#save-preset", true, "Saving…");
    try {
      await request("/api/presets", { method: "POST", body: { name, form: collectForm() } });
      input.value = "";
      await refreshPresets();
      showNotice(`Saved preset “${name}”.`, "success", 3200);
    } catch (error) {
      showNotice(`Could not save the preset: ${messageFromError(error)}`, "error");
    } finally {
      setButtonBusy("#save-preset", false, "Save");
      endPresetOperation();
    }
  }

  function markPreviewStale() {
    state.latestPreview = null;
  }
})();
