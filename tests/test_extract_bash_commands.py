"""Tests for extract_bash_commands.py — heredoc cleaning and command extraction."""

import pytest

from extract_bash_commands import clean_heredoc


class TestCleanHeredoc:
    """Tests for clean_heredoc utility."""

    def test_git_commit_heredoc_simplified(self):
        """Heredoc in git commit is collapsed to placeholder."""
        cmd = (
            "git add -A && git commit -m \"$(cat <<'EOF'\n"
            "Add new feature\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            "EOF\n"
            ")\" && git push"
        )
        result = clean_heredoc(cmd)
        assert "<<'EOF'...[heredoc]...EOF" in result
        assert "Add new feature" not in result
        assert "git push" in result

    def test_heredoc_without_quotes(self):
        """Heredoc delimiter without quotes also works."""
        cmd = "cat <<MARKER\nsome content\nMARKER"
        result = clean_heredoc(cmd)
        assert "<<'MARKER'...[heredoc]...MARKER" in result
        assert "some content" not in result

    def test_python_heredoc(self):
        """Python heredoc block (no space before delimiter) is collapsed."""
        cmd = "python3 <<'EOF'\nprint('hello')\nEOF"
        result = clean_heredoc(cmd)
        assert "<<'EOF'...[heredoc]...EOF" in result
        assert "print('hello')" not in result

    def test_heredoc_with_space_not_matched(self):
        """Heredoc with space before delimiter is NOT matched (regex limitation)."""
        cmd = "python3 << 'EOF'\nprint('hello')\nEOF"
        result = clean_heredoc(cmd)
        # Space between << and delimiter means regex doesn't match
        assert "<<'EOF'...[heredoc]...EOF" not in result

    def test_no_heredoc_unchanged(self):
        """Commands without heredocs pass through unchanged (except newline collapsing)."""
        cmd = "git status"
        result = clean_heredoc(cmd)
        assert result == "git status"

    def test_newlines_collapsed(self):
        """Multiline commands have newlines collapsed to spaces."""
        cmd = "echo hello\necho world"
        result = clean_heredoc(cmd)
        assert "\n" not in result
        assert "echo hello" in result
        assert "echo world" in result

    def test_empty_string(self):
        """Empty string returns empty."""
        assert clean_heredoc("") == ""

    def test_multiple_heredocs(self):
        """Multiple heredoc blocks in one command are both collapsed."""
        cmd = (
            "cat <<'A'\nfirst block\nA\n"
            "cat <<'B'\nsecond block\nB"
        )
        result = clean_heredoc(cmd)
        assert "first block" not in result
        assert "second block" not in result
        assert "<<'A'...[heredoc]...A" in result
        assert "<<'B'...[heredoc]...B" in result
