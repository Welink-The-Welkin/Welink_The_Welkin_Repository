# 本文件由 codex 辅助生成（外围模块）
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]


def test_frontend_has_role_intro_route_and_ending_metadata_rendering():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "角色与玩法" in html
    assert "renderRoleIntro" in script
    assert "ending.title" in script
    assert "ending.summary" in script


def test_frontend_has_free_chat_route_and_api_contract():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "#/chat" in script
    assert "renderChat" in script
    assert "/api/chat/sessions" in script
    assert "messages" in script
    assert "data-form=\"chat\"" in script
    assert "wanderer-chat-history" in script


def test_frontend_exposes_mode_loading_and_error_states_for_chat():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "data-chat-error" in script
    assert "pending = message.pending" in script
    assert "data-chat-error" in script
    assert "chat-history" in script
    assert ".chat-layout" in styles


def test_frontend_uses_chinese_labels_and_does_not_expose_internal_ids():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "CONVERSATIONS" not in script
    assert "FREE ROLEPLAY" not in script
    assert "${escapeHtml(state.scene_id)}" not in script
    assert "id.slice(0, 8)" not in script
    assert "emotionLabels" not in script
    assert "${escapeHtml(ending.ending_id)}" not in script


def test_frontend_does_not_render_latest_history_item_twice():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "history.slice(0, -1)" in script


def test_frontend_supports_named_player_and_replaces_character_display_name():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "player_name" in script
    assert "data-player-name" in script
    assert "「浮浪倾客」" in script
    assert "流浪者" not in script
    assert "旅人</div>" not in script
    assert 'href="#home"' in html


def test_frontend_guides_story_before_and_after_the_journey_and_removes_replay_picker():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "前情概要" in script
    assert "endingEpilogue" in script
    assert "选择预录路径" not in script
    assert "replay-picker" not in script


def test_frontend_chat_history_can_be_deleted_and_navigation_resets_hash():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "delete-chat" in script
    assert "title=\"新建对话\">新建</button>" in script
    assert "对话 ${appState.chatHistory.length - index}" not in script
    assert 'href="#home"' in html
    assert html.count('class="home-shortcut top-home-shortcut"') == 1
    assert "<a class=\"back-link\"" not in script


def test_role_intro_uses_the_requested_description_and_personalized_journey_copy():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "身份成谜的浮浪人，心随形至的修验者，如清风一般，活在世间，行在人间。" in script
    assert "旅行者的身份" not in script


def test_frontend_has_extensible_story_directory_and_forces_replay_mode():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "storyCatalog" in script
    assert "renderStoryDirectory" in script
    assert "#/stories" in script
    assert 'mode: "offline"' in script
    assert "data-action=\"select-story\"" in script
    assert "demo_direct_path" in script


def test_story_directory_selection_and_explicit_routes_work_with_saved_progress():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'route === "#/stories"' in script
    assert 'route === "#/game"' in script
    assert "function selectStory(replayId)" in script
    assert 'button.dataset.action === "select-story"' in script
    assert "data-replay-id" in script
    assert "async function startSession(replayId" in script


def test_resume_prompt_is_reached_after_restore_and_decline_keeps_saved_session():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "async function restoreSession()" in script
    assert "appState.session.state?.is_finished" in script
    assert 'button.dataset.action === "resume-journey"' in script
    assert 'button.dataset.action === "dismiss-resume"' in script
    assert "localStorage.removeItem(\"wanderer-session\")" in script
    assert "继续上一段旅途" in script


def test_story_mode_badges_and_mode_switch_are_removed_from_product_ui():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    game_markup = script.split("function renderGame()", 1)[1].split("function renderEnding(", 1)[0]

    assert 'class="mode-pill"' not in game_markup
    assert "固定回放" not in game_markup
    assert "实时接口" not in game_markup
    assert 'id="mode-toggle"' not in html


def test_frontend_removes_mode_selector_and_mode_badges_from_product_ui():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="mode-toggle"' not in html
    assert "实时接口" not in html + script
    assert "固定回放" not in html + script
    assert 'class="mode-pill' not in script
    assert "chat-mode-note" not in script


def test_free_chat_uses_backend_configured_mode_without_sending_a_ui_mode():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    start_chat = script.split("async function startChatSession()", 1)[1].split("async function restoreChatSession", 1)[0]

    assert 'body: JSON.stringify({ player_name: appState.playerName || "同行者" })' in start_chat
    assert 'mode: appState.mode' not in start_chat


def test_story_ending_hides_emotion_and_requested_identity_copy_everywhere():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    game_markup = script.split("function renderGame()", 1)[1].split("function renderEnding(", 1)[0]
    ending_markup = script.split("function renderEnding(", 1)[1].split("async function startSession(", 1)[0]

    assert 'class="emotion"' not in game_markup
    assert "emotionLabel(response" not in ending_markup
    assert "須弥 · 無所属" not in script
    assert "角色 IP 归米哈游所有" not in html + script + readme
    assert "同人创作 · 非商业技术演示" not in html + script + readme
    assert "同人创作，非商业技术演示" not in html + script + readme


def test_story_directory_and_resume_dialog_keep_the_existing_visual_palette():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert ".story-directory" in styles
    assert ".story-row" in styles
    assert ".resume-overlay" in styles
    assert "var(--gold)" in styles
    assert "var(--line)" in styles


def test_free_chat_long_user_messages_use_left_aligned_intrinsic_bubbles():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    message_block = styles.split(".chat-message {", 1)[1].split(".chat-message.user", 1)[0]
    user_block = styles.split(".chat-message.user", 1)[1].split(".chat-message.pending", 1)[0]
    paragraph_block = styles.split(".chat-message p", 1)[1].split(".chat-message time", 1)[0]

    assert "width:fit-content" in message_block
    assert "min-width:0" in message_block
    assert "text-align:left" in user_block
    assert "overflow-wrap:anywhere" in paragraph_block
    assert "word-break:break-word" in paragraph_block


def test_frontend_resumes_saved_journey_and_always_has_home_navigation():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'aria-label="首页"' in html
    assert "resume-dialog" in script
    assert "resume-journey" in script
    assert "dismiss-resume" in script
    assert "is_finished" in script


def test_home_action_keeps_saved_story_when_declining_resume():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function dismissResumePrompt()" in script
    dismiss_logic = script.split("function dismissResumePrompt()", 1)[1].split("function renderStoryDirectory()", 1)[0]
    assert "appState.resumePromptDismissed = true" in dismiss_logic
    assert "localStorage.removeItem(\"wanderer-session\")" not in dismiss_logic


def test_frontend_removes_story_emotions_identity_and_disclaimer_modules():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "角色 IP 归米哈游所有" not in html + script
    assert "同人创作 · 非商业技术演示" not in html + script
    assert "同人创作，非商业技术演示" not in script
    assert "須弥 · 無所属" not in script
    game_markup = script.split("function renderGame()", 1)[1].split("function renderEnding(", 1)[0]
    assert 'class="emotion"' not in game_markup
    assert 'class="mode-pill"' not in game_markup


def test_frontend_behavior_regressions_run_in_javascript_runtime():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is optional for the Python-only application runtime")

    result = subprocess.run(
        [node, "--test", str(ROOT / "tests" / "frontend_behavior.test.cjs")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_game_scene_narration_changes_with_the_current_scene():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "sceneDescriptions" in script
    assert "sceneDescriptions[state.scene_id]" in script


def test_implement_spec_matches_native_frontend_tree():
    spec = (ROOT / "docs" / "IMPLEMENT_SPEC.md").read_text(encoding="utf-8")

    assert "│  ├─ app.js" in spec
    assert "│  ├─ index.html" in spec
    assert "│  └─ styles.css" in spec
    assert "frontend/src/" not in spec
    assert "package.json" not in spec
    assert "test_frontend.py" in spec
    assert "browser_flow.py" not in spec
    assert "玩家可在开始前输入并保存自定义姓名" in spec

def test_story_journey_no_longer_offers_free_text_input():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    game_markup = script.split("function renderGame()", 1)[1].split("function renderEnding(", 1)[0]

    assert 'data-form="turn"' not in script
    assert "player-message" not in script
    assert "输入你的回应" not in script
    assert 'data-action="option"' in game_markup
    assert "submitTurn({ player_message" not in script


def test_free_chat_reply_supports_copy_and_regenerate_shortcuts():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'data-action="copy-reply"' in script
    assert 'data-action="regenerate-reply"' in script
    assert "navigator.clipboard" in script
    assert "async function copyReply(index)" in script
    assert "async function regenerateReply()" in script
    assert "/regenerate" in script
    assert ".chat-actions" in styles
    assert ".chat-action" in styles


def test_free_chat_reply_actions_reuse_existing_design_tokens():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    actions_block = styles.split(".chat-actions", 1)[1].split(".chat-empty", 1)[0]

    assert "var(--wind)" in actions_block
    assert "var(--line)" in actions_block
    assert "#52645d" in actions_block
    assert "border-radius:2px" in actions_block
