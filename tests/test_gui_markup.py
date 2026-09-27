from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_approved_interface_cleanup_is_present() -> None:
    html = (PROJECT_ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert "I understand that the selected output action" not in html
    assert "Selected matched games" not in html
    assert "ECO classification uses the bundled" not in html
    assert "Runs locally on this computer." not in html
    assert "Start at input game" not in html
    assert "Process through input game" not in html
    assert "Clean and classify" not in html
    assert "backend-version" not in html
    assert "<footer" not in html
    assert ">Start at Game<" in html
    assert ">End with Game<" in html
    assert "Check PGN errors only (does not create an output file)" in html
    assert html.index('id="validation-only"') < html.index('id="output-path"')
    assert html.index("run-controls-panel") < html.index("run-panel")
    assert 'id="count-games"' in html
    assert 'id="count-games" class="secondary" type="button"' in html
    assert 'id="source-count" class="count-badge" aria-live="polite"' in html
    assert "confirm-overwrite" not in script
    assert "needsOverwriteConfirmation" not in script
    assert 'request("/api/game-count"' in script
    assert "--suppressmatched" not in script
    assert "applyForm(savedForm, { restoreValidation: false })" in script
    assert '$("#theme-toggle-icon").textContent = isDark ? "☀" : "☾";' in script
    assert '$("#theme-toggle-label").textContent = isDark ? "Light theme" : "Dark theme";' in script
    assert "#007BFF" in styles


def test_source_file_list_is_compact_and_expandable() -> None:
    html = (PROJECT_ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert '<details id="source-list-details" class="source-list-details" hidden>' in html
    assert "<summary>Selected files</summary>" in html
    assert 'id="source-list" class="source-list"' in html
    assert 'class="remove-source"' in html

    render_sources = script.split("function renderSources()", 1)[1].split("function clearGameCount()", 1)[0]
    assert 'const listDetails = $("#source-list-details");' in render_sources
    assert "listDetails.hidden = true;" in render_sources
    assert "listDetails.hidden = false;" in render_sources
    assert "listDetails.open = false;" in render_sources
    assert 'removeButton.dataset.index = String(index);' in render_sources
    assert '$("#source-list-details").open = false;' in script

    assert ".source-list-details" in styles
    assert "max-height: 20rem;" in styles
    assert "overflow-y: auto;" in styles
    assert "scrollbar-gutter: stable;" in styles


def test_reset_and_preset_management_controls_are_present() -> None:
    html = (PROJECT_ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'id="reset-form"' in html
    assert "Reset to Defaults" in html
    assert 'id="clear-presets"' in html
    assert "Clear All Presets" in html
    assert '$("#reset-form").addEventListener("click", resetToDefaults)' in script
    assert "resetFormFields();" in script
    assert 'body: { form: collectForm() }' in script
    assert "resetInactiveRunFeedback();" in script
    assert "clearGameCount();" in script
    assert "if (state.currentRunId) return;" in script
    assert '$("#run-meta").textContent = "No run yet.";' in script
    assert '$("#command-preview").textContent = "No command run yet.";' in script
    assert 'remove.className = "danger secondary preset-delete"' in script
    assert "load.dataset.presetId = String(preset.id);" in script
    assert "remove.dataset.presetId = String(preset.id);" in script
    assert "state.presets.find((candidate) => Number(candidate.id) === presetId)" in script
    assert 'if (!window.confirm(`Delete preset “${preset.name}”?`)) return;' in script
    assert 'request(`/api/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" })' in script
    assert 'window.confirm("Delete all saved presets? This cannot be undone.")' in script
    assert 'request("/api/presets", { method: "DELETE" })' in script
    assert "async function refreshPresets()" in script
    assert "const presets = normalizePresets(data);" in script
    assert "state.presets = state.presets.filter" not in script
    assert "state.presets = [];" not in script
    assert "formEdited: false" in script
    assert "if (savedForm && !state.formEdited)" in script
    assert '$("#job-form").addEventListener("input", markFormChanged)' in script
    assert "runStarting: false" in script
    assert "state.runStarting = true;" in script
    assert "function syncResetButton()" in script
    assert "if (state.runStarting || state.currentRunId) return;" in script
    assert "presetOperation: false" in script
    assert "function beginPresetOperation()" in script
    assert "function endPresetOperation()" in script
    assert "if (state.presetOperation) return;" in script
    assert ".form-toolbar" in styles
    assert ".preset-item-actions" in styles

    delete_body = script.split("async function deletePreset", 1)[1].split("async function clearAllPresets", 1)[0]
    clear_all_body = script.split("async function clearAllPresets", 1)[1].split("async function savePreset", 1)[0]
    save_body = script.split("async function savePreset", 1)[1].split("function markPreviewStale", 1)[0]
    load_body = script.split("function loadPreset", 1)[1].split("async function deletePreset", 1)[0]
    assert delete_body.index("window.confirm") < delete_body.index("/api/presets/${encodeURIComponent(presetId)}")
    assert clear_all_body.index("window.confirm") < clear_all_body.index('request("/api/presets"')
    assert delete_body.index("beginPresetOperation") < delete_body.index("/api/presets/${encodeURIComponent(presetId)}")
    assert clear_all_body.index("beginPresetOperation") < clear_all_body.index('request("/api/presets"')
    assert save_body.index("beginPresetOperation") < save_body.index('request("/api/presets"')
    assert "beginPresetOperation" in load_body
    assert "endPresetOperation" in load_body
    assert "Could not delete preset" in delete_body
    assert "Could not clear saved presets" in clear_all_body
