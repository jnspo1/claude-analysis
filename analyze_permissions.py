#!/usr/bin/env python3
"""
Analyze historical tool calls against proposed permission rules.
Shows how many would be allowed/asked/denied and provides details on ask/deny cases.

UPDATED: 2026-02-12
- Fixed pattern matching to use fnmatch (glob-style) instead of regex
- Treats | as literal character (not regex alternation)
- Updated to use revised permission rules from PERMISSION_MATCHING_ANALYSIS.md
"""

from __future__ import annotations

import csv
import fnmatch
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


class PermissionAnalyzer:
    def __init__(self, rules: Dict):
        self.rules = rules
        self.stats = {
            'allow': 0,
            'ask': 0,
            'deny': 0,
            'total': 0
        }
        self.ask_cases = []
        self.deny_cases = []

    def parse_rule_pattern(self, rule: str) -> tuple[str, str]:
        """
        Parse a rule like 'Bash(git *)' or 'Read(**/.env)' into (tool, pattern).
        """
        match = re.match(r'^(\w+)\((.*)\)$', rule)
        if match:
            return match.group(1), match.group(2)
        return None, None

    def normalize_path(self, path: str) -> str:
        """Normalize path for matching - handle // prefix meaning absolute /"""
        if path.startswith('//'):
            return '/' + path[2:]
        return path

    def match_glob_pattern(self, pattern: str, value: str) -> bool:
        """
        Match a glob pattern against a value using fnmatch.
        Handles ** for multi-level directories.
        """
        if not value:
            return False

        # Normalize pattern (// -> /)
        pattern = self.normalize_path(pattern)
        value = self.normalize_path(value)

        # Handle ** by trying multiple match strategies
        if '**' in pattern:
            # Replace ** with * for fnmatch (fnmatch doesn't support **)
            # But we need to handle it specially for path matching

            # Split pattern into parts
            parts = pattern.split('**')

            # If pattern is just **/something, match if value ends with something
            if len(parts) == 2 and not parts[0]:
                suffix_pattern = parts[1].lstrip('/')
                # Try matching the suffix against the value or its basename
                if fnmatch.fnmatch(value, '*' + suffix_pattern):
                    return True
                # Also try matching just the filename
                basename = value.split('/')[-1]
                if fnmatch.fnmatch(basename, suffix_pattern.lstrip('/')):
                    return True

            # If pattern is something/**, match if value starts with something
            elif len(parts) == 2 and not parts[1]:
                prefix_pattern = parts[0].rstrip('/')
                if value.startswith(prefix_pattern + '/') or value == prefix_pattern:
                    return True

            # For patterns like **/something/**, convert to simple wildcards
            simple_pattern = pattern.replace('**/', '*/').replace('/**', '/*')
            if fnmatch.fnmatch(value, simple_pattern):
                return True
        else:
            # No **, use direct fnmatch
            if fnmatch.fnmatch(value, pattern):
                return True

        return False

    def match_bash_pattern(self, pattern: str, command: str) -> bool:
        """
        Match a bash command pattern against a command using glob matching.
        Uses fnmatch for proper wildcard handling (NOT regex).
        Treats | as a literal character.
        """
        if not command:
            return False

        # Normalize whitespace in command (but preserve structure)
        command = ' '.join(command.split())
        pattern = ' '.join(pattern.split())

        # Use fnmatch for glob-style matching
        # This treats * as wildcard and | as literal character
        if fnmatch.fnmatch(command, pattern):
            return True

        return False

    def check_rule_match(self, tool_name: str, value: str, rules: list[str]) -> str | None:
        """
        Check if a tool call matches any rule in the list.
        Returns the matched rule or None.
        """
        for rule in rules:
            rule_tool, rule_pattern = self.parse_rule_pattern(rule)

            if not rule_tool or rule_tool != tool_name:
                continue

            # For Bash, match command pattern
            if tool_name == 'Bash':
                if self.match_bash_pattern(rule_pattern, value):
                    return rule

            # For file operations, match path pattern
            elif tool_name in ['Read', 'Edit', 'Write']:
                if self.match_glob_pattern(rule_pattern, value):
                    return rule

        return None

    def categorize_call(self, tool_name: str, value: str) -> tuple[str, str | None]:
        """
        Categorize a tool call as 'allow', 'ask', or 'deny'.
        Returns (category, matched_rule).
        """
        # Check deny first (highest priority)
        matched = self.check_rule_match(tool_name, value, self.rules.get('deny', []))
        if matched:
            return 'deny', matched

        # Check ask
        matched = self.check_rule_match(tool_name, value, self.rules.get('ask', []))
        if matched:
            return 'ask', matched

        # Check allow
        matched = self.check_rule_match(tool_name, value, self.rules.get('allow', []))
        if matched:
            return 'allow', matched

        # Default to ask if no rule matches
        return 'ask', None

    def analyze_tool_call(self, row: Dict) -> Dict:
        """Analyze a single tool call from CSV row."""
        tool_name = row['tool_name']

        # Extract the relevant value based on tool type
        if tool_name == 'Bash':
            value = row['bash_command']
        elif tool_name == 'Read':
            value = row['read_file_path']
        elif tool_name == 'Edit':
            value = row['edit_file_path']
        elif tool_name == 'Write':
            value = row['write_file_path']
        else:
            # Other tools - for now, allow them
            return {
                'category': 'allow',
                'matched_rule': None,
                'tool_name': tool_name,
                'value': '',
                'timestamp': row['timestamp'],
                'project': row['project']
            }

        if not value:
            # Empty value - allow it
            return {
                'category': 'allow',
                'matched_rule': None,
                'tool_name': tool_name,
                'value': '',
                'timestamp': row['timestamp'],
                'project': row['project']
            }

        category, matched_rule = self.categorize_call(tool_name, value)

        return {
            'category': category,
            'matched_rule': matched_rule,
            'tool_name': tool_name,
            'value': value,
            'timestamp': row['timestamp'],
            'project': row['project']
        }

    def analyze_csv(self, csv_path: str):
        """Analyze all tool calls from CSV."""
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)

            for row in reader:
                result = self.analyze_tool_call(row)

                self.stats['total'] += 1
                self.stats[result['category']] += 1

                if result['category'] == 'ask':
                    self.ask_cases.append(result)
                elif result['category'] == 'deny':
                    self.deny_cases.append(result)

    def generate_report(self) -> str:
        """Generate a comprehensive report."""
        lines = []
        lines.append("=" * 80)
        lines.append("PERMISSION ANALYSIS REPORT")
        lines.append("=" * 80)
        lines.append("")
        self._report_summary(lines)
        self._report_deny_cases(lines)
        self._report_ask_cases(lines)
        self._report_tool_breakdown(lines)
        return '\n'.join(lines)

    def _report_summary(self, lines: list) -> None:
        """Append summary statistics section to report lines."""
        lines.append("SUMMARY STATISTICS")
        lines.append("-" * 80)
        lines.append(f"Total tool calls analyzed: {self.stats['total']:,}")
        lines.append("")
        total = self.stats['total']
        lines.append(f"  ALLOW: {self.stats['allow']:,} ({self.stats['allow']/total*100:.1f}%)")
        lines.append(f"  ASK:   {self.stats['ask']:,} ({self.stats['ask']/total*100:.1f}%)")
        lines.append(f"  DENY:  {self.stats['deny']:,} ({self.stats['deny']/total*100:.1f}%)")
        lines.append("")

    def _report_deny_cases(self, lines: list) -> None:
        """Append deny cases section to report lines."""
        lines.append("=" * 80)
        lines.append(f"DENY CASES ({len(self.deny_cases)} total)")
        lines.append("=" * 80)

        if not self.deny_cases:
            lines.append("")
            lines.append("✓ No tool calls would have been denied!")
            lines.append("")
            return

        by_rule = defaultdict(list)
        for case in self.deny_cases:
            rule = case['matched_rule'] or 'No rule matched (default deny)'
            by_rule[rule].append(case)

        for rule, cases in sorted(by_rule.items(), key=lambda x: len(x[1]), reverse=True):
            lines.append("")
            lines.append(f"Rule: {rule}")
            lines.append(f"Count: {len(cases)}")
            lines.append("-" * 80)
            for i, case in enumerate(cases[:10]):
                lines.append(f"  {i+1}. [{case['tool_name']}] {case['value']}")
                lines.append(f"     Project: {case['project']}")
                lines.append(f"     Time: {case['timestamp']}")
            if len(cases) > 10:
                lines.append(f"  ... and {len(cases) - 10} more")

    def _report_ask_cases(self, lines: list) -> None:
        """Append ask cases section to report lines."""
        lines.append("")
        lines.append("=" * 80)
        lines.append(f"ASK CASES ({len(self.ask_cases)} total)")
        lines.append("=" * 80)

        if not self.ask_cases:
            lines.append("")
            lines.append("✓ No tool calls would require asking!")
            lines.append("")
            return

        by_tool_rule = defaultdict(lambda: defaultdict(list))
        for case in self.ask_cases:
            tool = case['tool_name']
            rule = case['matched_rule'] or 'No rule matched (default ask)'
            by_tool_rule[tool][rule].append(case)

        for tool in sorted(by_tool_rule.keys()):
            lines.append("")
            lines.append(f"Tool: {tool}")
            lines.append("=" * 80)
            for rule, cases in sorted(by_tool_rule[tool].items(), key=lambda x: len(x[1]), reverse=True):
                lines.append("")
                lines.append(f"  Rule: {rule}")
                lines.append(f"  Count: {len(cases)}")
                lines.append("  " + "-" * 76)
                value_counts = Counter(case['value'] for case in cases)
                for value, count in value_counts.most_common(20):
                    lines.append(f"    {count:4d}x  {value}")
                if len(value_counts) > 20:
                    lines.append(f"    ... and {len(value_counts) - 20} more unique values")

    def _report_tool_breakdown(self, lines: list) -> None:
        """Append per-tool breakdown section to report lines."""
        lines.append("")
        lines.append("=" * 80)
        lines.append("BREAKDOWN BY TOOL TYPE")
        lines.append("=" * 80)

        tool_stats = defaultdict(lambda: {'allow': 0, 'ask': 0, 'deny': 0})

        all_cases = []
        with open('tool_events.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = self.analyze_tool_call(row)
                all_cases.append(result)

        for case in all_cases:
            tool_stats[case['tool_name']][case['category']] += 1

        lines.append("")
        lines.append(f"{'Tool':<20} {'Allow':>10} {'Ask':>10} {'Deny':>10} {'Total':>10}")
        lines.append("-" * 80)

        for tool in sorted(tool_stats.keys()):
            stats = tool_stats[tool]
            total = stats['allow'] + stats['ask'] + stats['deny']
            lines.append(
                f"{tool:<20} {stats['allow']:>10,} {stats['ask']:>10,} "
                f"{stats['deny']:>10,} {total:>10,}"
            )


def main():
    # Define the LATEST permission rules (updated 2026-02-12 v3)
    rules = {
        "deny": [
            # ------------------------------------------------------------
            # 1) NEVER READ/WRITE: SSH keys and related material anywhere
            # ------------------------------------------------------------
            "Read(**/.ssh/**)",
            "Read(**/id_rsa*)",
            "Read(**/authorized_keys)",
            "Read(**/known_hosts)",
            "Edit(**/.ssh/**)",
            "Write(**/.ssh/**)",

            # ------------------------------------------------------------
            # 2) HARD DENY: catastrophic disk / wipe / format operations
            # ------------------------------------------------------------
            "Bash(dd *)",
            "Bash(mkfs*)",
            "Bash(wipefs *)",
            "Bash(parted *)",
            "Bash(fdisk *)",
            "Bash(sgdisk *)",
            "Bash(shred *)",

            # ------------------------------------------------------------
            # 3) HARD DENY: destructive deletes of system roots/trees
            # ------------------------------------------------------------
            "Bash(rm -rf /)",
            "Bash(rm -rf /*)",
            "Bash(sudo rm -rf /)",
            "Bash(sudo rm -rf /*)",
            "Bash(rm -rf /etc*)",
            "Bash(rm -rf /usr*)",
            "Bash(rm -rf /var*)",
            "Bash(rm -rf /boot*)",
            "Bash(rm -rf /sys*)",
            "Bash(rm -rf /proc*)",

            # ------------------------------------------------------------
            # 4) HARD DENY: avoid locking yourself out remotely
            # (block systemctl actions on access-path/network services)
            # ------------------------------------------------------------
            "Bash(sudo systemctl * ssh*)",
            "Bash(sudo systemctl * sshd*)",
            "Bash(sudo systemctl * tailscale*)",
            "Bash(sudo systemctl * tailscaled*)",
            "Bash(sudo systemctl * cloudflared*)",
            "Bash(sudo systemctl * networking*)",
            "Bash(sudo systemctl * NetworkManager*)",
            "Bash(sudo systemctl * systemd-networkd*)",
            "Bash(sudo systemctl * wpa_supplicant*)",
        ],

        "ask": [
            # ------------------------------------------------------------
            # Pipe-to-shell handling (wildcard-safe):
            # Ask on any curl/wget that includes a pipe, except the explicit
            # allow-listed trusted addresses below.
            # ------------------------------------------------------------
            "Bash(curl *|*)",
            "Bash(wget *|*)",

            # ------------------------------------------------------------
            # Env files: YOU REQUESTED read to be ASK (not deny).
            # Keep edits/writes as ASK too.
            # This will include .env, .env.local, .env.production, etc.
            # ------------------------------------------------------------
            "Read(**/.env)",
            "Read(**/.env.*)",
            "Edit(**/.env)",
            "Edit(**/.env.*)",
            "Write(**/.env)",
            "Write(**/.env.*)",

            # ------------------------------------------------------------
            # System paths: ask for edits/writes (read is allowed)
            # ------------------------------------------------------------
            "Edit(//etc/**)",
            "Write(//etc/**)",
            "Edit(//usr/**)",
            "Write(//usr/**)",
            "Edit(//var/**)",
            "Write(//var/**)",
            "Edit(//boot/**)",
            "Write(//boot/**)",
            "Edit(//lib/**)",
            "Write(//lib/**)",
            "Edit(//bin/**)",
            "Write(//bin/**)",
            "Edit(//sbin/**)",
            "Write(//sbin/**)",
            "Edit(//proc/**)",
            "Write(//proc/**)",
            "Edit(//sys/**)",
            "Write(//sys/**)",
            "Edit(//dev/**)",
            "Write(//dev/**)",

            # Permission/ownership changes
            "Bash(chmod *)",
            "Bash(chown *)",
            "Bash(sudo chmod *)",
            "Bash(sudo chown *)",

            # System package changes
            "Bash(sudo apt *)",
            "Bash(sudo apt-get *)",
            "Bash(sudo dpkg *)",
        ],

        "allow": [
            # ------------------------------------------------------------
            # Read: liberal everywhere (except deny-listed patterns)
            # ------------------------------------------------------------
            "Read(//**)",

            # ------------------------------------------------------------
            # Write/Edit: liberal within /home/pi
            # ------------------------------------------------------------
            "Edit(//home/pi/**)",
            "Write(//home/pi/**)",

            # Temp file workflows
            "Read(//tmp/**)",
            "Edit(//tmp/**)",
            "Write(//tmp/**)",

            # ------------------------------------------------------------
            # git: fully autonomous (including push)
            # ------------------------------------------------------------
            "Bash(git *)",

            # ------------------------------------------------------------
            # Service management autonomy (except deny-listed services)
            # ------------------------------------------------------------
            "Bash(sudo systemctl *)",
            "Bash(sudo journalctl *)",
            "Bash(sudo nginx *)",

            # ------------------------------------------------------------
            # curl allowed only to local + tailnet IP for health checks
            # (non-piped versions)
            # ------------------------------------------------------------
            "Bash(curl *127.0.0.1*)",
            "Bash(curl *localhost*)",
            "Bash(curl *100.99.27.84*)",

            # ------------------------------------------------------------
            # curl allowed WITH pipes to trusted addresses (eliminate prompts
            # for curl | jq on local/tailnet)
            # ------------------------------------------------------------
            "Bash(curl *127.0.0.1*|*)",
            "Bash(curl *localhost*|*)",
            "Bash(curl *100.99.27.84*|*)",

            # ------------------------------------------------------------
            # Common dev commands (include bare versions)
            # ------------------------------------------------------------
            "Bash(ls)",
            "Bash(ls *)",
            "Bash(pwd)",
            "Bash(hostname)",
            "Bash(find *)",
            "Bash(grep *)",
            "Bash(cat *)",
            "Bash(head *)",
            "Bash(tail *)",
            "Bash(wc *)",
            "Bash(ps *)",
            "Bash(ss *)",
            "Bash(which *)",

            # Extra "safe utilities" to reduce default ASK noise
            "Bash(mkdir *)",
            "Bash(uname *)",
            "Bash(df *)",
            "Bash(du *)",
            "Bash(tree *)",
            "Bash(file *)",
            "Bash(ip *)",
            "Bash(whoami)",
            "Bash(id)",
            "Bash(date *)",
            "Bash(uptime)",

            # Python tooling
            "Bash(python *)",
            "Bash(python3 *)",
            "Bash(pip *)",
            "Bash(pip3 *)",
            "Bash(./venv/bin/python *)",
            "Bash(source *)",

            # rm: allow scoped deletes under /home/pi (non-sudo)
            "Bash(rm * /home/pi/*)",
        ]
    }

    # Create analyzer
    analyzer = PermissionAnalyzer(rules)

    # Analyze the CSV
    print("Analyzing tool calls from tool_events.csv...")
    analyzer.analyze_csv('tool_events.csv')

    # Generate report
    report = analyzer.generate_report()

    # Write to file
    output_file = 'permission_analysis_report.txt'
    with open(output_file, 'w') as f:
        f.write(report)

    print(f"\n✓ Analysis complete! Report written to: {output_file}")
    print(f"\nQuick summary:")
    print(f"  Total: {analyzer.stats['total']:,}")
    print(f"  Allow: {analyzer.stats['allow']:,} ({analyzer.stats['allow']/analyzer.stats['total']*100:.1f}%)")
    print(f"  Ask:   {analyzer.stats['ask']:,} ({analyzer.stats['ask']/analyzer.stats['total']*100:.1f}%)")
    print(f"  Deny:  {analyzer.stats['deny']:,} ({analyzer.stats['deny']/analyzer.stats['total']*100:.1f}%)")


if __name__ == '__main__':
    main()
