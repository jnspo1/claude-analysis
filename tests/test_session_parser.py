"""Tests for session_parser.py — JSONL parsing and categorization."""

import json
from pathlib import Path

import pytest

from session_parser import (
    _is_interrupt_message,
    _extract_text_from_content,
    categorize_bash_command,
    extract_first_prompt,
    make_project_readable,
    _estimate_cost,
    count_turns,
)


class TestIsInterruptMessage:
    """Tests for _is_interrupt_message."""

    def test_exact_interrupt(self):
        assert _is_interrupt_message("[Request interrupted by user]") is True

    def test_tool_use_interrupt(self):
        assert _is_interrupt_message("[Request interrupted by user for tool use]") is True

    def test_whitespace_stripped(self):
        assert _is_interrupt_message("  [Request interrupted by user]  ") is True

    def test_normal_text(self):
        assert _is_interrupt_message("Hello, world!") is False

    def test_empty(self):
        assert _is_interrupt_message("") is False


class TestExtractTextFromContent:
    """Tests for _extract_text_from_content."""

    def test_string_content(self):
        assert _extract_text_from_content("hello") == "hello"

    def test_list_with_text_block(self):
        content = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        result = _extract_text_from_content(content)
        assert "hello" in result
        assert "world" in result

    def test_list_with_mixed_blocks(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "name": "Bash"},
        ]
        result = _extract_text_from_content(content)
        assert result == "hello"

    def test_list_with_string_items(self):
        content = ["hello", "world"]
        result = _extract_text_from_content(content)
        assert "hello" in result

    def test_empty_list(self):
        assert _extract_text_from_content([]) is None

    def test_none(self):
        assert _extract_text_from_content(None) is None

    def test_integer(self):
        assert _extract_text_from_content(42) is None


class TestCategorizeBashCommand:
    """Tests for categorize_bash_command — all categories."""

    def test_git_command(self):
        assert categorize_bash_command("git status") == "Version Control"

    def test_gh_command(self):
        assert categorize_bash_command("gh pr list") == "Version Control"

    def test_python_command(self):
        assert categorize_bash_command("python test.py") == "Running Code"

    def test_pytest_command(self):
        assert categorize_bash_command("pytest tests/") == "Running Code"

    def test_pip_install(self):
        assert categorize_bash_command("pip install flask") == "Running Code"

    def test_grep_command(self):
        assert categorize_bash_command("grep -r 'TODO' .") == "Searching & Reading"

    def test_find_command(self):
        assert categorize_bash_command("find . -name '*.py'") == "Searching & Reading"

    def test_mkdir_command(self):
        assert categorize_bash_command("mkdir -p tests/") == "File Management"

    def test_rm_command(self):
        assert categorize_bash_command("rm temp.txt") == "File Management"

    def test_curl_command(self):
        assert categorize_bash_command("curl http://localhost:8000") == "Testing & Monitoring"

    def test_systemctl_command(self):
        assert categorize_bash_command("systemctl restart nginx") == "Server & System"

    def test_echo_command(self):
        assert categorize_bash_command("echo hello") == "Server & System"

    def test_unknown_command(self):
        assert categorize_bash_command("my_custom_script.sh") == "Other"

    def test_chained_commands(self):
        # First real command is 'cd' (skipped), second is 'python'
        result = categorize_bash_command("cd /tmp && python test.py")
        assert result == "Running Code"

    def test_sudo_prefix(self):
        assert categorize_bash_command("sudo systemctl restart nginx") == "Server & System"

    def test_env_var_prefix(self):
        assert categorize_bash_command("FOO=bar python test.py") == "Running Code"

    def test_piped_commands(self):
        # First command in pipe is categorized
        assert categorize_bash_command("git log | head -5") == "Version Control"

    def test_source_venv_activate(self):
        result = categorize_bash_command("source venv/bin/activate")
        assert result == "Running Code"

    def test_dot_space_activate(self):
        result = categorize_bash_command(". venv/bin/activate")
        assert result == "Running Code"

    def test_path_prefix_command(self):
        result = categorize_bash_command("./venv/bin/python test.py")
        assert result == "Running Code"

    def test_empty_command(self):
        assert categorize_bash_command("") == "Other"

    def test_only_cd(self):
        assert categorize_bash_command("cd /tmp") == "Other"


class TestExtractFirstPrompt:
    """Tests for extract_first_prompt."""

    def test_extracts_from_sample(self, sample_jsonl):
        prompt = extract_first_prompt(sample_jsonl)
        assert prompt is not None
        assert "hello world" in prompt.lower()

    def test_empty_file(self, empty_jsonl):
        assert extract_first_prompt(empty_jsonl) is None

    def test_skips_system_messages(self, tmp_path):
        jsonl = tmp_path / "system.jsonl"
        lines = [
            json.dumps({"type": "message", "message": {
                "role": "user",
                "content": "<local-command>init</local-command>"
            }}),
            json.dumps({"type": "message", "message": {
                "role": "user",
                "content": "Build me a web server"
            }}),
        ]
        jsonl.write_text("\n".join(lines) + "\n")
        prompt = extract_first_prompt(jsonl)
        assert prompt == "Build me a web server"


class TestMakeProjectReadable:
    """Tests for make_project_readable."""

    def test_strips_home_pi_python(self):
        assert make_project_readable("-home-pi-python-admin-panel") == "admin-panel"

    def test_strips_home_pi(self):
        assert make_project_readable("-home-pi-myproject") == "myproject"

    def test_home_misc(self):
        assert make_project_readable("-home-pi") == "home (misc)"

    def test_tp_prefix(self):
        # "-home-pi-TP-" strips to "", falls through to `"" or raw`
        assert make_project_readable("-home-pi-TP-") == "-home-pi-TP-"

    def test_passthrough(self):
        assert make_project_readable("already-clean") == "already-clean"

    def test_empty(self):
        assert make_project_readable("") == ""


class TestEstimateCost:
    """Tests for _estimate_cost."""

    def test_sonnet_pricing(self):
        cost = _estimate_cost(1_000_000, 100_000, 0, "claude-sonnet-4")
        # 1M input * $3/M + 100K output * $15/M = $3 + $1.5 = $4.5
        assert cost == pytest.approx(4.5, rel=0.01)

    def test_opus_pricing(self):
        cost = _estimate_cost(1_000_000, 100_000, 0, "claude-opus-4")
        # 1M input * $15/M + 100K output * $75/M = $15 + $7.5 = $22.5
        assert cost == pytest.approx(22.5, rel=0.01)

    def test_haiku_pricing(self):
        cost = _estimate_cost(1_000_000, 100_000, 0, "claude-haiku-4")
        # 1M input * $0.80/M + 100K output * $4/M = $0.80 + $0.40 = $1.20
        assert cost == pytest.approx(1.2, rel=0.01)

    def test_cache_read_discount(self):
        # Cache reads at 10% of input rate (sonnet: $0.30/M)
        cost = _estimate_cost(0, 0, 1_000_000, "claude-sonnet-4")
        assert cost == pytest.approx(0.3, rel=0.01)

    def test_cache_creation_premium(self):
        # Cache creation at 125% of input rate (sonnet: $3.75/M)
        cost = _estimate_cost(0, 0, 0, "claude-sonnet-4", cache_creation_tokens=1_000_000)
        assert cost == pytest.approx(3.75, rel=0.01)

    def test_no_model_defaults_to_sonnet(self):
        cost = _estimate_cost(1_000_000, 0, 0, None)
        assert cost == pytest.approx(3.0, rel=0.01)

    def test_zero_tokens(self):
        assert _estimate_cost(0, 0, 0, "claude-sonnet-4") == 0.0


class TestCountTurns:
    """Tests for count_turns."""

    def test_sample_jsonl(self, sample_jsonl):
        # The sample has 1 user message
        count = count_turns(sample_jsonl)
        assert count == 1

    def test_empty_file(self, empty_jsonl):
        assert count_turns(empty_jsonl) == 0
