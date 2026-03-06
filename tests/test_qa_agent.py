"""
Unit tests for qa_agent.py — no browser / no network required.

Run with:
    python3 -m pytest tests/ -v
"""

import importlib
import os
import sys

import pytest

# Ensure repo root is on sys.path so qa_agent is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# 1. StateGraph fingerprinting
# ---------------------------------------------------------------------------

class TestStateGraphFingerprint:
    def _sg(self):
        from qa_agent import StateGraph
        return StateGraph()

    def test_query_string_stripped(self):
        """Two URLs differing only in query string → same fingerprint."""
        sg = self._sg()
        fp1 = sg.fingerprint("https://example.com/page?foo=1", "<h1>Hello</h1>")
        fp2 = sg.fingerprint("https://example.com/page?bar=2", "<h1>Hello</h1>")
        assert fp1 == fp2

    def test_fragment_stripped(self):
        """Two URLs differing only in fragment → same fingerprint."""
        sg = self._sg()
        fp1 = sg.fingerprint("https://example.com/page#section1", "<p>text</p>")
        fp2 = sg.fingerprint("https://example.com/page#section2", "<p>text</p>")
        assert fp1 == fp2

    def test_different_dom_different_fingerprint(self):
        """Same URL but different DOM → different fingerprint."""
        sg = self._sg()
        fp1 = sg.fingerprint("https://example.com/page", "<h1>Dashboard</h1>")
        fp2 = sg.fingerprint("https://example.com/page", "<h1>Profile</h1>")
        assert fp1 != fp2

    def test_trailing_slash_stripped(self):
        """Trailing slash is normalised away."""
        sg = self._sg()
        fp1 = sg.fingerprint("https://example.com/page/", "<div>A</div>")
        fp2 = sg.fingerprint("https://example.com/page",  "<div>A</div>")
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# 2. Jaccard deduplication in capture_bug
# ---------------------------------------------------------------------------

class TestJaccardDedup:
    def _agent(self):
        from qa_agent import QAAgent
        agent = QAAgent.__new__(QAAgent)
        agent.bugs = []
        return agent

    class _FakePage:
        url = "https://example.com/test"
        def screenshot(self, path):
            pass  # no-op

    def test_near_duplicate_merged(self):
        """A second bug whose issue text is >50% Jaccard similarity is not added."""
        agent = self._agent()
        page  = self._FakePage()
        agent.capture_bug(page, "Login page has no error message shown", "steps", "P0")
        agent.capture_bug(page, "Login page has no error message visible", "steps", "P0")
        assert len(agent.bugs) == 1

    def test_distinct_bugs_kept(self):
        """Two clearly different bugs are both recorded."""
        agent = self._agent()
        page  = self._FakePage()
        agent.capture_bug(page, "Login page has no error message", "steps", "P0")
        agent.capture_bug(page, "Export PDF button missing on dashboard", "steps", "P1")
        assert len(agent.bugs) == 2

    def test_exact_duplicate_merged(self):
        """Exact same issue string is never recorded twice."""
        agent = self._agent()
        page  = self._FakePage()
        for _ in range(3):
            agent.capture_bug(page, "Wrong credentials no error", "steps", "P0")
        assert len(agent.bugs) == 1


# ---------------------------------------------------------------------------
# 3. Config env override
# ---------------------------------------------------------------------------

class TestConfigEnvOverride:
    def test_default_max_bfs_states(self):
        """Without env override, MAX_BFS_STATES defaults to 60."""
        import qa_agent
        importlib.reload(qa_agent)
        assert qa_agent.Config.MAX_BFS_STATES == 60

    def test_env_override_max_bfs_states(self, monkeypatch):
        """QA_MAX_BFS_STATES=5 → Config.MAX_BFS_STATES == 5 after reload."""
        monkeypatch.setenv("QA_MAX_BFS_STATES", "5")
        import qa_agent
        importlib.reload(qa_agent)
        assert qa_agent.Config.MAX_BFS_STATES == 5
        # Restore: reload without env var so other tests see the default
        monkeypatch.delenv("QA_MAX_BFS_STATES", raising=False)
        importlib.reload(qa_agent)

    def test_env_override_max_nav_items(self, monkeypatch):
        """QA_MAX_NAV_ITEMS=4 → Config.MAX_NAV_ITEMS == 4 after reload."""
        monkeypatch.setenv("QA_MAX_NAV_ITEMS", "4")
        import qa_agent
        importlib.reload(qa_agent)
        assert qa_agent.Config.MAX_NAV_ITEMS == 4
        monkeypatch.delenv("QA_MAX_NAV_ITEMS", raising=False)
        importlib.reload(qa_agent)


# ---------------------------------------------------------------------------
# 4. YAML schema validator
# ---------------------------------------------------------------------------

class TestYAMLValidator:
    def _validator(self):
        from qa_agent import QAAgent
        agent = QAAgent.__new__(QAAgent)
        return agent

    def test_valid_config_no_warnings(self):
        """A well-formed YAML config produces zero warnings."""
        agent = self._validator()
        config = {
            "tests": [
                {
                    "name": "login flow",
                    "steps": [
                        {"click": "button:has-text('Sign in')"},
                        {"expect_url": "/dashboard"},
                    ],
                }
            ]
        }
        assert agent._validate_yaml_config(config) == []

    def test_missing_tests_key_warns(self):
        """Config without 'tests' key → exactly one warning."""
        agent = self._validator()
        warnings = agent._validate_yaml_config({"base_url": "https://x.com"})
        assert len(warnings) == 1
        assert "tests" in warnings[0].lower()

    def test_unknown_action_warns(self):
        """An unrecognised action in a step → warning containing the action name."""
        agent = self._validator()
        config = {
            "tests": [{
                "name": "bad action test",
                "steps": [{"bogus": "some_value"}],
            }]
        }
        warnings = agent._validate_yaml_config(config)
        assert any("bogus" in w for w in warnings)

    def test_non_dict_root_warns(self):
        """Non-dict YAML root → warning."""
        agent = self._validator()
        warnings = agent._validate_yaml_config(["not", "a", "dict"])
        assert len(warnings) >= 1

    def test_step_with_multiple_keys_warns(self):
        """Step dict with more than one key → warning."""
        agent = self._validator()
        config = {
            "tests": [{
                "name": "multi-key step",
                "steps": [{"click": "btn", "wait": 2}],
            }]
        }
        warnings = agent._validate_yaml_config(config)
        assert any("exactly one" in w for w in warnings)
