#!/usr/bin/env python3
"""
Unit tests for high-risk logic in track_jobs.py
Tests: quality score calculation, role filtering, salary parsing
"""

import pytest
from track_jobs import (
    calculate_job_quality_score,
    is_target_role,
    parse_salary_info,
)


# =============================================================================
# QUALITY SCORE TESTS
# =============================================================================
class TestQualityScore:
    """Test job quality score calculation"""

    def test_perfect_score_all_factors(self):
        """Near-perfect score with all positive factors"""
        title = "Staff React TypeScript Engineer"
        content = "React, TypeScript, Next.js, GraphQL, PostgreSQL"
        score = calculate_job_quality_score(title, content, "USD $185,000", "VERIFIED")
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
        score = calculate_job_quality_score(title, content, "Unlisted", "UNLISTED")
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
        score = calculate_job_quality_score(title, content, "Unlisted", "UNLISTED")
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
        
        score_verified = calculate_job_quality_score(title1, content, "USD $150,000", "VERIFIED")
        score_unlisted = calculate_job_quality_score(title1, content, "Unlisted", "UNLISTED")
        
        diff = score_verified - score_unlisted
        assert diff == 15, f"Verified should be +15 more (20 vs 5), got diff={diff}"

    def test_fullstack_title_bonus(self):
        """Fullstack in title adds 15 role points"""
        title_fullstack = "Full Stack Engineer"
        title_generic = "Engineer"
        content = "React"
        
        score_fs = calculate_job_quality_score(title_fullstack, content, "Unlisted", "UNLISTED")
        score_gen = calculate_job_quality_score(title_generic, content, "Unlisted", "UNLISTED")
        
        diff = score_fs - score_gen
        assert diff == 15, f"Fullstack title should add 15 points, got diff={diff}"


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
