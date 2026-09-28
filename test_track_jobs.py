#!/usr/bin/env python3
"""
Unit tests for high-risk logic in track_jobs.py
Tests: quality score calculation, role filtering, salary parsing,
profile loading, work-mode and region filtering
"""

import dataclasses
import re
from collections import Counter
from pathlib import Path

import pytest
from track_jobs import (
    DEFAULT_PROFILE,
    SOURCE_ATTRIBUTION,
    SOURCE_FETCHERS,
    _score_badge,
    build_job_embed,
    calculate_job_quality_components,
    calculate_job_quality_score,
    collect_matches,
    detect_work_mode,
    extract_key_signals,
    get_webhook_url,
    html_to_text,
    is_eor_supported,
    is_target_role,
    load_profile,
    matches_region,
    matches_work_mode,
    parse_salary_info,
)
import check_boards
import track_jobs

PROFILES_DIR = Path(__file__).parent / "profiles"


# =============================================================================
# QUALITY SCORE TESTS
# =============================================================================
class TestQualityScore:
    """Test job quality score calculation"""

    def test_perfect_score_all_factors(self):
        """Near-perfect score with all positive factors"""
        title = "Staff React TypeScript Engineer"
        content = "React, TypeScript, Next.js, GraphQL, PostgreSQL"
        score = calculate_job_quality_score(title, content, "VERIFIED")
        # Tech: 31 (React+TS+Next+GraphQL=28, PostgreSQL=3)
        # Level: 30 (Staff)
        # Salary: 20 (VERIFIED)
        # Role: 12 (React in title)
        # Total: 93
        assert score == 93, f"Expected 93, got {score}"

    def test_tech_stack_only(self):
        """Score with tech stack but no level/salary"""
        title = "React Engineer"
        content = "React, TypeScript, GraphQL"
        score = calculate_job_quality_score(title, content, "UNLISTED")
        # Tech: 21 (React + TS + GraphQL = 3 techs * 7) = 21
        # Role: 15 (React in title but no specific role word) = 0
        # Actually: React in title but "react" keyword counts toward role focus
        # Let's check: title has "react", so role_emphases won't trigger
        # But "react" in title_lower will trigger the elif for 12 points
        # Tech: React(7) + TypeScript(7) + GraphQL(7) = 21
        # Level: 0 (no staff/principal/lead)
        # Salary: 5 (UNLISTED)
        # Role: 12 (react in title_lower)
        # Total: 21 + 0 + 5 + 12 = 38
        assert 30 <= score <= 45, f"Expected ~38, got {score}"

    def test_level_match_only(self):
        """Score with Staff level but generic tech"""
        title = "Staff Software Engineer"
        content = "General software engineering"
        score = calculate_job_quality_score(title, content, "UNLISTED")
        # Tech: 0 (no premium/good techs)
        # Level: 30 (staff)
        # Salary: 5 (unlisted)
        # Role: 12 (react in title? No. typescript? No. fullstack/front-end? No)
        # So role gets 0
        # But wait - "staff software engineer" - this won't match frontstack/front end keywords
        # So role = 0
        # Total: 0 + 30 + 5 + 0 = 35
        assert 30 <= score <= 40, f"Expected ~35, got {score}"

    def test_verified_salary_boost(self):
        """Verified salary adds 20 points"""
        title1 = "React Engineer"
        content = "React, TypeScript"
        
        score_verified = calculate_job_quality_score(title1, content, "VERIFIED")
        score_unlisted = calculate_job_quality_score(title1, content, "UNLISTED")
        
        diff = score_verified - score_unlisted
        assert diff == 15, f"Verified should be +15 more (20 vs 5), got diff={diff}"

    def test_fullstack_title_bonus(self):
        """Fullstack in title adds 15 role points"""
        title_fullstack = "Full Stack Engineer"
        title_generic = "Engineer"
        content = "React"
        
        score_fs = calculate_job_quality_score(title_fullstack, content, "UNLISTED")
        score_gen = calculate_job_quality_score(title_generic, content, "UNLISTED")
        
        diff = score_fs - score_gen
        assert diff == 15, f"Fullstack title should add 15 points, got diff={diff}"

    def test_signals_past_2000_chars_are_scored(self):
        """Scoring window must match the one extract_key_signals uses.

        A truncated window let a card list signals it had scored as zero.
        """
        content = ("Pinterest is an equal opportunity employer. " * 80) + (
            " We work in TypeScript, GraphQL, Python and Node.js."
        )
        assert len(content) > 2000

        score = calculate_job_quality_score(
            "Staff Software Engineer", content, "VERIFIED"
        )
        # Signals: TypeScript(7) + GraphQL(7) + Python(3) + Node.js(3) = 20
        # Level: 30 (staff) | Salary: 20 (VERIFIED) | Role: 0
        assert score == 70, f"Expected 70, got {score}"

    def test_score_agrees_with_listed_signals(self):
        """If the card lists signals, they must contribute points."""
        content = ("Lorem ipsum boilerplate. " * 120) + " Built with React."
        assert len(content) > 2000

        assert "React" in extract_key_signals(content)
        assert calculate_job_quality_score("Engineer", content, "UNLISTED") > 5


# =============================================================================
# ROLE FILTERING TESTS
# =============================================================================
class TestRoleFiltering:
    """Test is_target_role filtering logic"""

    def test_specific_role_keywords_pass(self):
        """Titles with specific keywords pass"""
        assert is_target_role("Frontend Engineer", "some content") == True
        assert is_target_role("Full Stack React Developer", "") == True
        assert is_target_role("React TypeScript Engineer", "") == True
        assert is_target_role("Product Engineer", "") == True
        assert is_target_role("UI Engineer", "") == True

    def test_excluded_roles_rejected(self):
        """Excluded role types are rejected"""
        assert is_target_role("Platform Engineer", "") == False
        assert is_target_role("DevOps Engineer", "") == False
        assert is_target_role("Site Reliability Engineer", "") == False
        assert is_target_role("Data Engineer", "") == False
        assert is_target_role("Machine Learning Engineer", "") == False

    def test_generic_software_engineer_requires_description(self):
        """Generic 'Software Engineer' needs description keywords"""
        # Without description keywords → reject
        assert is_target_role("Software Engineer", "Python backend development") == False
        assert is_target_role("Software Engineer", "System administration") == False
        
        # With description keywords → accept
        assert is_target_role("Software Engineer", "React and TypeScript") == True
        assert is_target_role("Software Engineer", "Frontend with GraphQL") == True
        assert is_target_role("Software Engineer", "Full stack development") == True
        assert is_target_role("Software Engineer", "Next.js framework") == True

    def test_vue_in_title_passes(self):
        """Vue.js in title passes (not in REQUIRE_IN_DESCRIPTION)"""
        assert is_target_role("Vue.js Engineer", "") == True
        assert is_target_role("Vue Developer", "") == False  # "vue" keyword not in INCLUDE

    def test_case_insensitive_matching(self):
        """Role matching is case-insensitive"""
        assert is_target_role("REACT ENGINEER", "") == True
        assert is_target_role("React Engineer", "") == True
        assert is_target_role("react engineer", "") == True


# =============================================================================
# SALARY PARSING TESTS
# =============================================================================
class TestSalaryParsing:
    """Test salary extraction and validation"""

    def test_structured_usd_salary_valid(self):
        """Structured ATS salary payload validation"""
        meets, text, status = parse_salary_info(
            "",
            comp_data={
                "targetCompensationMin": 150000,
                "targetCompensationMax": 200000,
                "currency": "USD"
            }
        )
        assert meets == True
        assert status == "VERIFIED"
        assert "150,000" in text

    def test_structured_usd_salary_below_threshold(self):
        """Structured salary below minimum threshold"""
        meets, text, status = parse_salary_info(
            "",
            comp_data={
                "targetCompensationMin": 120000,
                "targetCompensationMax": 150000,
                "currency": "USD"
            }
        )
        assert meets == False
        assert status == "BELOW_THRESHOLD"

    def test_structured_cad_salary_valid(self):
        """CAD salary meeting Canadian threshold"""
        meets, text, status = parse_salary_info(
            "",
            comp_data={
                "targetCompensationMin": 210000,
                "targetCompensationMax": 250000,
                "currency": "CAD"
            }
        )
        assert meets == True
        assert status == "VERIFIED"

    def test_structured_eur_salary_valid(self):
        """EUR salary meeting European threshold"""
        meets, text, status = parse_salary_info(
            "",
            comp_data={
                "targetCompensationMin": 140000,
                "targetCompensationMax": 180000,
                "currency": "EUR"
            }
        )
        assert meets == True
        assert status == "VERIFIED"

    def test_regex_salary_extraction(self):
        """Regex fallback for salary in description text"""
        text = "We offer competitive salary between $150,000 - $180,000 annually"
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert meets == True
        assert status == "VERIFIED"
        assert "150" in display or "150,000" in display

    def test_regex_salary_k_format(self):
        """Handle salary in 'k' format (e.g., 150k)"""
        text = "Salary range: $150k - $200k"
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert meets == True
        assert status == "VERIFIED"

    def test_regex_cad_salary(self):
        """Regex extraction of CAD salary"""
        # Pattern expects currency symbol/code OR amount, not "CAD $" both
        text = "$200,000 - $250,000 CAD"
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert meets == True
        assert status == "VERIFIED"

    def test_regex_eur_salary(self):
        """Regex extraction of EUR salary"""
        text = "€140,000 to €180,000"
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert meets == True
        assert status == "VERIFIED"

    def test_regex_salary_below_threshold(self):
        """Regex salary below minimum"""
        text = "Salary: $100,000 - $120,000"
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert meets == False
        assert status == "BELOW_THRESHOLD"

    def test_no_salary_info(self):
        """No salary information → marked as UNLISTED"""
        text = "Join our team for an exciting opportunity..."
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert meets == True  # We don't reject unlisted, just flag them
        assert status == "UNLISTED"
        assert "Unlisted" in display

    def test_em_dash_separated_range(self):
        """Greenhouse pay widget uses an em dash, not a hyphen"""
        text = "$177,185 — $364,795 USD"
        meets, display, status = parse_salary_info(text, comp_data=None)
        assert status == "VERIFIED"
        assert meets == True

    def test_em_dash_range_without_spaces(self):
        """The widget emits no whitespace around the dash"""
        meets, display, status = parse_salary_info(
            "$177,185—$364,795 USD", comp_data=None
        )
        assert status == "VERIFIED"

    def test_en_dash_range_still_parses(self):
        """Widening the separator must not drop the existing en dash"""
        meets, display, status = parse_salary_info(
            "$150,000 – $180,000", comp_data=None
        )
        assert status == "VERIFIED"


# =============================================================================
# HTML FLATTENING TESTS
# =============================================================================
class TestHtmlToText:
    """Greenhouse serves entity-escaped HTML; scoring needs plain text"""

    def test_strips_escaped_markup(self):
        raw = "&lt;p&gt;&lt;strong&gt;About us:&lt;/strong&gt;&lt;/p&gt;"
        assert html_to_text(raw) == "About us:"

    def test_resolves_doubly_escaped_entity(self):
        """Entities inside the markup arrive escaped twice (&amp;mdash;)"""
        raw = (
            "&lt;span&gt;$177,185&lt;/span&gt;"
            "&lt;span&gt;&amp;mdash;&lt;/span&gt;"
            "&lt;span&gt;$364,795 USD&lt;/span&gt;"
        )
        assert html_to_text(raw) == "$177,185 — $364,795 USD"

    def test_tags_become_spaces_not_nothing(self):
        """Deleting tags would fuse adjacent list items into one token"""
        raw = "&lt;li&gt;React&lt;/li&gt;&lt;li&gt;GraphQL&lt;/li&gt;"
        assert html_to_text(raw) == "React GraphQL"

    def test_empty_input(self):
        assert html_to_text("") == ""

    def test_plain_text_passes_through(self):
        assert html_to_text("Staff Engineer, remote") == "Staff Engineer, remote"

    def test_greenhouse_normalizer_flattens_content(self):
        """End-to-end: escaped payload -> parseable salary"""
        job = track_jobs._normalize_greenhouse(
            {
                "id": 1,
                "title": "Staff Frontend Engineer",
                "location": {"name": "Remote, CA, US"},
                "content": (
                    "&lt;div class=&quot;pay-range&quot;&gt;"
                    "&lt;span&gt;$177,185&lt;/span&gt;"
                    "&lt;span&gt;&amp;mdash;&lt;/span&gt;"
                    "&lt;span&gt;$364,795 USD&lt;/span&gt;&lt;/div&gt;"
                ),
                "absolute_url": "https://example.com/1",
            },
            "pinterest",
        )
        assert "&lt;" not in job["content"]
        _, _, status = parse_salary_info(job["content"], job["comp_data"])
        assert status == "VERIFIED"


# =============================================================================
# PROFILE LOADING TESTS
# =============================================================================
class TestProfileLoading:
    """Test SearchProfile construction from YAML"""

    def test_no_path_returns_defaults(self):
        """Omitting --profile yields the built-in defaults"""
        assert load_profile(None) is DEFAULT_PROFILE

    def test_engineering_yaml_matches_defaults(self):
        """profiles/engineering.yml must not drift from the built-in defaults"""
        loaded = load_profile(str(PROFILES_DIR / "engineering.yml"))
        assert loaded == DEFAULT_PROFILE

    def test_product_owner_yaml_loads(self):
        """The product-owner profile parses and overrides what it declares"""
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert p.name == "product-owner"
        assert p.min_salary == {"CAD": 125000, "USD": 100000}
        assert p.require_eor is False
        assert p.work_modes == ["remote", "hybrid"]

    def test_omitted_fields_inherit_defaults(self, tmp_path):
        """A profile only declares what differs; the rest is inherited"""
        f = tmp_path / "minimal.yml"
        f.write_text("require_eor: false\n")
        p = load_profile(str(f))

        assert p.require_eor is False
        assert p.name == "minimal"  # derived from the file stem
        assert p.boards == DEFAULT_PROFILE.boards
        assert p.min_salary == DEFAULT_PROFILE.min_salary

    def test_explicit_name_overrides_stem(self, tmp_path):
        f = tmp_path / "whatever.yml"
        f.write_text("name: custom-name\n")
        assert load_profile(str(f)).name == "custom-name"

    def test_unknown_key_rejected(self, tmp_path):
        """Typos fail loudly rather than being silently ignored"""
        f = tmp_path / "typo.yml"
        f.write_text("min_salery:\n  USD: 100000\n")
        with pytest.raises(ValueError, match="Unknown profile keys"):
            load_profile(str(f))

    def test_invalid_name_rejected(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text("name: Product Owner!\n")
        with pytest.raises(ValueError, match="must match"):
            load_profile(str(f))

    def test_invalid_work_mode_rejected(self, tmp_path):
        f = tmp_path / "modes.yml"
        f.write_text("work_modes:\n  - remote\n  - telepathic\n")
        with pytest.raises(ValueError, match="Invalid work_modes"):
            load_profile(str(f))

    def test_empty_file_is_defaults_with_stem_name(self, tmp_path):
        f = tmp_path / "blank.yml"
        f.write_text("")
        p = load_profile(str(f))
        assert p.name == "blank"
        assert p.min_salary == DEFAULT_PROFILE.min_salary


class TestWebhookResolution:
    """Test per-profile Discord webhook lookup"""

    def test_explicit_webhook_env_wins(self, monkeypatch, tmp_path):
        f = tmp_path / "p.yml"
        f.write_text("name: custom\nwebhook_env: MY_HOOK\n")
        monkeypatch.setenv("MY_HOOK", "https://example.invalid/explicit")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/generic")
        assert get_webhook_url(load_profile(str(f))) == "https://example.invalid/explicit"

    def test_per_profile_env_preferred_over_generic(self, monkeypatch, tmp_path):
        f = tmp_path / "product-owner.yml"
        f.write_text("{}\n")
        monkeypatch.setenv("DISCORD_WEBHOOK_PRODUCT_OWNER", "https://example.invalid/po")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/generic")
        assert get_webhook_url(load_profile(str(f))) == "https://example.invalid/po"

    def test_falls_back_to_generic_webhook(self, monkeypatch, tmp_path):
        f = tmp_path / "product-owner.yml"
        f.write_text("{}\n")
        monkeypatch.delenv("DISCORD_WEBHOOK_PRODUCT_OWNER", raising=False)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/generic")
        assert get_webhook_url(load_profile(str(f))) == "https://example.invalid/generic"

    def test_missing_webhook_returns_none(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_ENGINEERING", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert get_webhook_url(DEFAULT_PROFILE) is None


# =============================================================================
# WORK MODE & REGION TESTS
# =============================================================================
class TestWorkModeDetection:
    """Test detect_work_mode classification"""

    def test_explicit_workplace_type(self):
        assert detect_work_mode("", "remote", "") == "remote"
        assert detect_work_mode("", "hybrid", "") == "hybrid"
        assert detect_work_mode("", "onsite", "") == "onsite"

    def test_remote_from_location(self):
        assert detect_work_mode("Remote - Canada", "", "") == "remote"
        assert detect_work_mode("Work from anywhere", "", "") == "remote"

    def test_remote_from_description_head(self):
        assert detect_work_mode("", "", "This is a fully remote role.") == "remote"

    def test_remote_signal_late_in_description_ignored(self):
        """Only the first 500 chars are scanned, to avoid footer boilerplate"""
        padding = "x" * 600
        assert detect_work_mode("", "", padding + " remote") == "unknown"

    def test_hybrid_location_beats_remote_workplace_type(self):
        """An explicit hybrid location wins over a 'remote' ATS tag"""
        assert detect_work_mode("Hybrid - Toronto", "remote", "") == "hybrid"

    def test_onsite_location_beats_remote_description(self):
        assert detect_work_mode("Onsite - NYC", "", "remote friendly team") == "onsite"

    def test_no_signal_is_unknown(self):
        assert detect_work_mode("New York, NY", "", "Join our team") == "unknown"


class TestWorkModeFiltering:
    """Test matches_work_mode against profile.work_modes"""

    def test_default_profile_accepts_only_remote(self):
        assert matches_work_mode("Remote", "", "") is True
        assert matches_work_mode("Hybrid - Toronto", "", "") is False
        assert matches_work_mode("New York, NY", "", "") is False  # unknown

    def test_product_owner_accepts_remote_and_hybrid(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert matches_work_mode("Remote - Canada", "", "", p) is True
        assert matches_work_mode("Hybrid - Toronto", "", "", p) is True
        assert matches_work_mode("Onsite - Toronto", "", "", p) is False
        assert matches_work_mode("Toronto, ON", "", "", p) is False  # unknown

    def test_empty_work_modes_disables_filter(self, tmp_path):
        f = tmp_path / "anymode.yml"
        f.write_text("work_modes: []\n")
        p = load_profile(str(f))
        assert matches_work_mode("Onsite - NYC", "", "", p) is True

    def test_unknown_can_be_opted_into(self, tmp_path):
        f = tmp_path / "loose.yml"
        f.write_text("work_modes:\n  - remote\n  - unknown\n")
        p = load_profile(str(f))
        assert matches_work_mode("New York, NY", "", "", p) is True
        assert matches_work_mode("Hybrid - NYC", "", "", p) is False


class TestRegionFiltering:
    """Test matches_region against profile.regions"""

    def test_empty_regions_accepts_anywhere(self):
        assert matches_region("Berlin, Germany", "", DEFAULT_PROFILE) is True

    def test_product_owner_region_matching(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert matches_region("Toronto, ON", "", p) is True
        assert matches_region("Remote - Canada", "", p) is True
        assert matches_region("Austin, TX", "", p) is False

    def test_region_found_in_description_head(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert matches_region("Remote", "Open to candidates in Ontario.", p) is True


# =============================================================================
# EOR TESTS
# =============================================================================
class TestEorDetection:
    """Test is_eor_supported. The signal list is deliberately narrow: only
    explicit EOR terminology and named vendors, matched on word boundaries."""

    def test_explicit_eor_language_detected(self):
        assert is_eor_supported("", "We hire via an employer of record.") is True
        assert is_eor_supported("", "Payroll is handled through Deel.") is True

    def test_vendor_name_detected(self):
        assert is_eor_supported("", "We use Velocity Global for hiring.") is True
        assert is_eor_supported("", "Global payroll is handled for you.") is True

    def test_no_signal_returns_false(self):
        assert is_eor_supported("Austin, TX", "Join our team in Texas.") is False

    def test_eeo_boilerplate_is_not_an_eor_signal(self):
        """'canada' used to be an EOR signal, so any EEO statement matched."""
        boilerplate = "We are an equal opportunity employer in the US and Canada."
        assert is_eor_supported("Austin, TX", boilerplate) is False

    def test_a_country_name_alone_is_not_an_eor_signal(self):
        assert is_eor_supported("Canada Remote", "") is False

    def test_short_signal_is_word_boundary_matched(self):
        """'eor' must not fire on 'theory' or 'reorganization'."""
        assert is_eor_supported("", "Strong grounding in queueing theory.") is False
        assert is_eor_supported("", "Following a recent reorganization.") is False
        assert is_eor_supported("", "We offer EOR employment.") is True


# =============================================================================
# PROFILE-AWARE FILTERING TESTS
# =============================================================================
class TestProfileAwareRoleFiltering:
    """Test that is_target_role respects the supplied profile"""

    def test_pm_titles_pass_pm_profile_only(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert is_target_role("Senior Product Manager", "", p) is True
        assert is_target_role("Senior Product Manager", "", DEFAULT_PROFILE) is False

    def test_engineering_titles_fail_pm_profile(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert is_target_role("Senior React Engineer", "", p) is False

    def test_technical_and_platform_pm_titles_survive_exclusions(self):
        """'technical' and 'platform' must not be excluded wholesale"""
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert is_target_role("Technical Product Manager", "", p) is True
        assert is_target_role("Platform Product Manager", "", p) is True

    def test_pm_exclusions_rejected(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert is_target_role("Junior Product Manager", "", p) is False
        assert is_target_role("Director of Product Management", "", p) is False
        assert is_target_role("VP Product", "", p) is False

    def test_exclusions_are_word_boundary_matched(self):
        """'lead' as an exclusion must not match 'leadership'"""
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        # "vp" is excluded, but must not match inside another word
        assert is_target_role("Senior Product Manager, VPN Tools", "", p) is True

    def test_generic_product_title_requires_description(self):
        p = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        assert is_target_role("Product Strategist", "Own the roadmap", p) is True
        assert is_target_role("Product Strategist", "Manage our retail floor", p) is False


class TestRoleFocusScoring:
    """Test the primary/secondary role keyword scoring tiers"""

    def test_primary_scores_above_secondary(self):
        """Titles chosen to carry no premium/good signal terms, so only the
        role-focus tier differs between them."""
        content = "General engineering work"
        primary = calculate_job_quality_score("Frontend Engineer", content, "UNLISTED")
        secondary = calculate_job_quality_score("UI Engineer", content, "UNLISTED")
        assert primary - secondary == 3, "primary=15, secondary=12"

    def test_non_matching_title_scores_zero_role_focus(self):
        content = "General engineering work"
        primary = calculate_job_quality_score("Frontend Engineer", content, "UNLISTED")
        none = calculate_job_quality_score("Engineer", content, "UNLISTED")
        assert primary - none == 15


# =============================================================================
# SALARY EDGE CASES
# =============================================================================
class TestSalaryEdgeCases:
    """Cases that previously parsed wrongly or dropped a posting silently"""

    def test_hourly_rate_is_not_annualized(self):
        """'$75 - $95/hr' must not be read as $75,000."""
        meets, _, status = parse_salary_info("Pay: $75 - $95/hr")
        assert status == "HOURLY"
        assert meets is True

    def test_trailing_currency_is_detected(self):
        """Currency after the amount, not before. 130k clears the PM profile's
        CAD floor of 125k but not engineering's 200k, so the profile matters."""
        pm = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        meets, _, status = parse_salary_info("Range: 130,000 - 150,000 CAD", None, pm)
        assert status == "VERIFIED"
        assert meets is True

    def test_trailing_currency_below_threshold_is_rejected(self):
        pm = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        meets, _, status = parse_salary_info("Range: 110,000 - 120,000 CAD", None, pm)
        assert status == "BELOW_THRESHOLD"
        assert meets is False

    def test_threshold_is_currency_aware(self):
        """The same CAD figure passes one profile and fails the other."""
        pm = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        text = "Range: 130,000 - 150,000 CAD"
        assert parse_salary_info(text, None, pm)[2] == "VERIFIED"
        assert parse_salary_info(text, None, DEFAULT_PROFILE)[2] == "BELOW_THRESHOLD"

    def test_years_of_experience_is_not_a_salary(self):
        """A currency token is required, so '10-15 years' can't match."""
        meets, _, status = parse_salary_info("We want 10-15 years of experience")
        assert status == "UNLISTED"
        assert meets is True

    def test_unknown_currency_surfaces_rather_than_drops(self):
        """No GBP threshold is configured, so flag it for manual review."""
        comp = {
            "targetCompensationMin": 90000,
            "currency": "GBP",
            "interval": "yearly",
        }
        meets, text, status = parse_salary_info("", comp)
        assert status == "UNLISTED"
        assert meets is True
        assert "no GBP threshold set" in text

    def test_structured_hourly_interval_is_detected(self):
        comp = {
            "targetCompensationMin": 85,
            "targetCompensationMax": 110,
            "currency": "USD",
            "interval": "hourly",
        }
        _, _, status = parse_salary_info("", comp)
        assert status == "HOURLY"


# =============================================================================
# AGGREGATOR NORMALIZATION
# =============================================================================
class TestAggregatorNormalization:
    """The aggregator feeds are the only source for a profile with no boards"""

    def test_remoteok_zero_salary_is_not_treated_as_compensation(self):
        """Remote OK sends "0" for both bounds when pay is unknown."""
        job = track_jobs._normalize_remoteok({
            "id": "123",
            "position": "Senior Product Manager",
            "company": "Acme",
            "salary_min": "0",
            "salary_max": "0",
        })
        assert job["comp_data"] is None
        assert job["id"] == "remoteok_123"
        assert job["source"] == "remoteok"

    def test_remoteok_real_salary_is_mapped(self):
        job = track_jobs._normalize_remoteok({
            "id": "9", "position": "PM", "company": "Acme",
            "salary_min": "150000", "salary_max": "180000",
        })
        assert job["comp_data"]["targetCompensationMin"] == 150000
        assert job["comp_data"]["currency"] == "USD"

    def test_remoteok_posting_without_id_is_skipped(self):
        assert track_jobs._normalize_remoteok({"position": "PM"}) is None

    def test_himalayas_list_fields_do_not_crash(self):
        """seniority and categories arrive as lists, not strings."""
        job = track_jobs._normalize_himalayas({
            "guid": "abc",
            "title": "Product Manager",
            "companyName": "Acme",
            "seniority": ["Senior"],
            "categories": ["Product", "Management"],
            "locationRestrictions": ["Canada", "United States"],
            "description": "Own the roadmap",
        })
        assert job["location"] == "Canada, United States"
        assert "Senior" in job["content"]
        assert "Management" in job["content"]

    def test_himalayas_posting_without_guid_is_skipped(self):
        assert track_jobs._normalize_himalayas({"title": "PM"}) is None


# =============================================================================
# SOURCE DISPATCH
# =============================================================================
class TestSourceDispatch:
    def test_unknown_source_warns_and_is_skipped(self, capsys):
        import dataclasses
        profile = dataclasses.replace(DEFAULT_PROFILE, sources=["not-a-source"])
        assert collect_matches(set(), profile) == []
        assert "unknown source" in capsys.readouterr().out

    def test_every_default_source_is_registered(self):
        for source in DEFAULT_PROFILE.sources:
            assert source in SOURCE_FETCHERS

    def test_product_owner_sources_are_registered(self):
        profile = load_profile(str(PROFILES_DIR / "product-owner.yml"))
        for source in profile.sources:
            assert source in SOURCE_FETCHERS


# =============================================================================
# BOARD CONFIGURATION
# =============================================================================
class TestBoardConfiguration:
    """Structural invariants for the curated ATS board lists.

    A misfiled slug fails quietly: the board 404s, the fetcher skips it, and
    the company drops out of coverage without anything going red. These checks
    run offline, so they prove only internal consistency -- whether a slug is
    still live has to be confirmed against the APIs.
    """

    def test_slugs_are_well_formed(self):
        """Slugs go straight into a URL path, so no spaces, case or URLs."""
        for source, slugs in DEFAULT_PROFILE.boards.items():
            for slug in slugs:
                assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug), (
                    f"{source} slug {slug!r} is not a bare lowercase slug"
                )

    def test_no_slug_repeats_within_a_platform(self):
        """A duplicate costs a wasted request and double-counts the company."""
        for source, slugs in DEFAULT_PROFILE.boards.items():
            repeated = sorted(s for s, n in Counter(slugs).items() if n > 1)
            assert not repeated, f"{source} lists {repeated} more than once"

    def test_no_slug_is_shared_across_platforms(self):
        """A company uses one ATS; the copy filed under the other always 404s.

        This is the exact shape of the original bad config, where `figma`,
        `github`, `gitlab`, `notion`, `statsbomb` and `zapier` were each listed
        on two platforms and the wrong copy 404ed on every run.
        """
        owners: dict[str, list[str]] = {}
        for source, slugs in DEFAULT_PROFILE.boards.items():
            for slug in slugs:
                owners.setdefault(slug, []).append(source)

        shared = {s: p for s, p in owners.items() if len(p) > 1}
        assert not shared, f"slugs claimed by multiple platforms: {shared}"

    def test_every_platform_with_boards_is_an_enabled_source(self):
        """Boards under a source that is not enabled are never polled."""
        for source, slugs in DEFAULT_PROFILE.boards.items():
            if slugs:
                assert source in DEFAULT_PROFILE.sources, (
                    f"{source} has {len(slugs)} boards but is not in sources"
                )

    def test_every_board_platform_has_a_fetcher(self):
        for source in DEFAULT_PROFILE.boards:
            assert source in SOURCE_FETCHERS


# =============================================================================
# DEAD BOARD HANDLING
# =============================================================================
class _StubResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class TestDeadBoardHandling:
    """A dead board must be skipped, logged, and never abort the run.

    An earlier version returned `continue` on a non-200 without printing, so a
    board that had 404ed for months was indistinguishable from one with no
    matching roles.
    """

    @staticmethod
    def _ashby_payload():
        return {
            "jobs": [{
                "id": "job-1",
                "title": "Staff Frontend Engineer",
                "location": "Remote - Canada",
                "workplaceType": "Remote",
                "descriptionPlain": "React and TypeScript across the stack.",
                "jobUrl": "https://example.com/job",
            }]
        }

    @staticmethod
    def _profile():
        return dataclasses.replace(
            DEFAULT_PROFILE,
            boards={"ashby": ["deadboard", "liveboard"]},
            sources=["ashby"],
        )

    def test_dead_board_is_reported_not_swallowed(self, monkeypatch, capsys):
        monkeypatch.setattr(
            track_jobs.requests, "get",
            lambda url, **kwargs: _StubResponse(404),
        )
        assert collect_matches(set(), self._profile()) == []
        assert "Ashby board deadboard: HTTP 404" in capsys.readouterr().out

    def test_remaining_boards_are_polled_after_a_dead_one(self, monkeypatch):
        def fake_get(url, **kwargs):
            if "liveboard" in url:
                return _StubResponse(200, self._ashby_payload())
            return _StubResponse(404)

        monkeypatch.setattr(track_jobs.requests, "get", fake_get)
        matches = collect_matches(set(), self._profile())
        assert [m["company"] for m in matches] == ["Liveboard"]

    def test_live_board_with_no_postings_is_not_reported(
        self, monkeypatch, capsys
    ):
        """200 with zero postings is an ordinary empty result, not an error."""
        monkeypatch.setattr(
            track_jobs.requests, "get",
            lambda url, **kwargs: _StubResponse(200, {"jobs": []}),
        )
        assert collect_matches(set(), self._profile()) == []
        assert "HTTP" not in capsys.readouterr().out

    def test_network_error_does_not_abort_the_run(self, monkeypatch, capsys):
        def fake_get(url, **kwargs):
            if "liveboard" in url:
                return _StubResponse(200, self._ashby_payload())
            raise OSError("connection reset by peer")

        monkeypatch.setattr(track_jobs.requests, "get", fake_get)
        matches = collect_matches(set(), self._profile())
        assert [m["company"] for m in matches] == ["Liveboard"]
        assert "Error fetching Ashby board deadboard" in capsys.readouterr().out


# =============================================================================
# BOARD HEALTH CHECK
# =============================================================================
class TestBoardHealthClassification:
    """The health check must keep 'dead' and 'empty' apart.

    Conflating them is what hid the original problem: a 404 board is never
    polled and silently shrinks coverage, while a 200 board with no postings
    was polled correctly and simply had nothing open.
    """

    def test_dead_board_is_a_failure(self):
        outcome, detail = check_boards.classify(404, None)
        assert outcome == check_boards.DEAD
        assert "404" in detail

    def test_live_board_with_postings_is_healthy(self):
        outcome, _ = check_boards.classify(200, 12)
        assert outcome == check_boards.OK

    def test_live_board_with_no_postings_is_not_dead(self):
        outcome, _ = check_boards.classify(200, 0)
        assert outcome == check_boards.EMPTY

    def test_unreachable_board_is_distinct_from_dead(self):
        """A network fault says nothing about whether the slug is valid."""
        outcome, _ = check_boards.classify(None, None)
        assert outcome == check_boards.UNREACHABLE

    def test_malformed_slug_is_never_requested(self):
        """Slugs are interpolated into a URL path, so they are validated."""
        source, slug, outcome, _ = check_boards.probe("ashby", "../etc/passwd")
        assert (source, slug, outcome) == (
            "ashby", "../etc/passwd", check_boards.MALFORMED,
        )

    def test_every_configured_ats_has_an_endpoint(self):
        """The checker probes the same URLs the tracker polls."""
        for source in DEFAULT_PROFILE.boards:
            assert source in track_jobs.BOARD_ENDPOINTS


# =============================================================================
# ALERT EMBED
# =============================================================================
class TestJobEmbed:
    @staticmethod
    def _match(**overrides):
        match = {
            "id": "remoteok_12345",
            "title": "Senior Product Manager",
            "company": "Acme",
            "url": "https://example.com/job",
            "location": "Toronto",
            "work_mode": "remote",
            "quality_score": 80,
            "salary_text": "CAD 140,000",
            "salary_status": "VERIFIED",
            "key_tech": "Roadmap",
            "recruiter_url": "https://linkedin.com/search",
            "outreach_note": "Hi there",
            "source": "remoteok",
            "eor_detected": False,
        }
        match.update(overrides)
        return match

    def _field_names(self, match):
        return [f["name"] for f in build_job_embed(match, "now")["fields"]]

    def test_eor_field_absent_when_not_detected(self):
        """Absence means 'not stated', which must not be claimed as support."""
        assert not any("EOR" in n for n in self._field_names(self._match()))

    def test_eor_field_present_when_detected(self):
        names = self._field_names(self._match(eor_detected=True))
        assert any("EOR" in n for n in names)

    def test_aggregator_source_is_attributed_by_name(self):
        """Remote OK and Himalayas require attribution for free API access."""
        for source, expected in SOURCE_ATTRIBUTION.items():
            embed = build_job_embed(self._match(source=source), "now")
            assert expected in embed["footer"]["text"]




# =============================================================================
# REGION WILDCARDS
# =============================================================================
class TestRegionWildcards:
    """An unrestricted posting doesn't exclude the profile's regions"""

    @pytest.fixture
    def pm(self):
        return load_profile(str(PROFILES_DIR / "product-owner.yml"))

    def test_named_region_matches(self, pm):
        assert matches_region("Toronto, ON", "", pm) is True

    def test_unrestricted_remote_is_kept(self, pm):
        assert matches_region("Remote", "", pm) is True
        assert matches_region("Worldwide", "", pm) is True
        assert matches_region("", "", pm) is True

    def test_other_country_is_rejected(self, pm):
        assert matches_region("Germany", "", pm) is False
        assert matches_region("Melbourne", "", pm) is False

    def test_empty_regions_accepts_anything(self):
        assert matches_region("Germany", "", DEFAULT_PROFILE) is True


# =============================================================================
# SCORE BADGE DISPLAY TESTS
# =============================================================================
class TestScoreBadge:
    """Test quality score badge rendering with components and colored circles"""

    def test_fallback_badge_without_components(self):
        """Simple badge when components are None"""
        result = _score_badge(75)
        assert "✅" in result
        assert "75/100" in result
        assert "Strong match" in result
        # Should be single line
        assert "\n" not in result

    def test_fallback_badge_excellent_score(self):
        result = _score_badge(90)
        assert "⭐" in result
        assert "Excellent match" in result

    def test_fallback_badge_moderate_score(self):
        result = _score_badge(60)
        assert "🔶" in result
        assert "Moderate match" in result

    def test_fallback_badge_low_score(self):
        result = _score_badge(30)
        assert "🔹" in result
        assert "Low match" in result

    def test_component_breakdown_with_perfect_score(self):
        """All components at max should render correctly"""
        components = {
            "signal": 35,
            "level": 30,
            "salary": 20,
            "role": 15,
            "total": 100,
        }
        result = _score_badge(100, components)
        lines = result.split("\n")
        assert len(lines) == 6  # 4 components + separator + total
        # Check all components have full bars
        assert "████████████████████" in result  # 20 filled chars
        # Check all components show green (strong)
        assert result.count("🟢") == 4
        assert "⭐" in result  # Excellent emoji
        assert "100/100" in result

    def test_component_breakdown_with_mixed_strengths(self):
        """Components with varying strengths show correct color circles"""
        components = {
            "signal": 35,  # Strong (100%)
            "level": 20,   # Yellow (67%)
            "salary": 5,   # Red (25%)
            "role": 15,    # Strong (100%)
            "total": 75,
        }
        result = _score_badge(75, components)
        # Check correct count of color circles
        assert result.count("🟢") == 2  # Signal and Role strong
        assert result.count("🟡") == 1  # Level moderate
        assert result.count("🔴") == 1  # Salary weak
        assert "✅" in result  # Strong Match overall

    def test_bar_width_consistency(self):
        """All Unicode bars should be exactly 20 characters wide"""
        components = {
            "signal": 35,
            "level": 15,
            "salary": 10,
            "role": 7,
            "total": 67,
        }
        result = _score_badge(67, components)
        lines = result.split("\n")
        # Extract lines with bars (first 4 lines)
        for i in range(4):
            line = lines[i]
            # Find the bar portion (between first space run and the parenthesis)
            bar_start = line.index("█") if "█" in line else line.index("░")
            bar_end = bar_start + 20
            bar = line[bar_start:bar_end]
            # Bar should be exactly 20 chars of filled/empty
            assert len(bar) == 20, f"Line {i} bar width != 20: {bar}"
            assert all(c in "█░" for c in bar), f"Line {i} contains non-bar chars: {bar}"

    def test_component_values_displayed(self):
        """Component scores should be shown in parentheses"""
        components = {
            "signal": 25,
            "level": 20,
            "salary": 8,
            "role": 12,
            "total": 65,
        }
        result = _score_badge(65, components)
        assert "(25)" in result  # Signal value
        assert "(20)" in result  # Level value
        assert "(8)" in result   # Salary value
        assert "(12)" in result  # Role value

    def test_score_totals_label(self):
        """Bottom line should show score and quality label"""
        components = {
            "signal": 20,
            "level": 0,
            "salary": 5,
            "role": 12,
            "total": 37,
        }
        result = _score_badge(37, components)
        assert "🔹 **37/100** — Low Match" in result

    def test_zero_component_handling(self):
        """Components with zero values should show empty bar and red circle"""
        components = {
            "signal": 0,
            "level": 0,
            "salary": 0,
            "role": 0,
            "total": 0,
        }
        result = _score_badge(0, components)
        # All should be red (weak)
        assert result.count("🔴") == 4
        # All bars should be empty
        assert "░░░░░░░░░░░░░░░░░░░░" in result

    def test_single_strong_component(self):
        """When only one component is strong, others should be red"""
        components = {
            "signal": 35,  # Strong
            "level": 0,    # Weak
            "salary": 0,   # Weak
            "role": 0,     # Weak
            "total": 35,
        }
        result = _score_badge(35, components)
        assert "🟢" in result  # Signal is green
        assert result.count("🔴") == 3  # Level, Salary, Role are red

    def test_strength_emoji_boundaries(self):
        """Test emoji selection at boundary percentages"""
        # 70% boundary: signal max is 35, so 70% = 24.5
        components_strong = {
            "signal": 25,  # 71% -> green
            "level": 0,
            "salary": 0,
            "role": 0,
            "total": 25,
        }
        assert "🟢" in _score_badge(25, components_strong)

        # 30% boundary: salary max is 20, so 30% = 6
        components_boundary = {
            "signal": 0,
            "level": 0,
            "salary": 6,  # 30% -> yellow
            "role": 0,
            "total": 6,
        }
        assert "🟡" in _score_badge(6, components_boundary)

        components_weak = {
            "signal": 0,
            "level": 0,
            "salary": 5,  # 25% -> red
            "role": 0,
            "total": 5,
        }
        result = _score_badge(5, components_weak)
        assert "🔴" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
