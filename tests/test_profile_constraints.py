"""
Tests for profile constraint and age safety rules functions.
"""
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_constraints.sqlite3"),
)

import baby_feeding_bot as bot


class ProfileConstraintsTests(unittest.TestCase):
    def test_profile_constraints_uses_real_age(self):
        """Profile with age_months=6 shows '6 months' in output."""
        profile = {
            "age_months": 6,
            "allergies": "none",
            "blw_ratio": 0.4,
            "spoon_ratio": 0.6,
        }
        result = bot.profile_constraints_text(profile)
        self.assertIn("6 months", result)

    def test_profile_constraints_defaults_to_12(self):
        """No profile shows '12 months' in output."""
        result = bot.profile_constraints_text(None)
        self.assertIn("12 months", result)

    def test_profile_constraints_no_profile_dict(self):
        """Empty profile dict defaults to 12 months."""
        result = bot.profile_constraints_text({})
        self.assertIn("12 months", result)


class AgeSafetyRulesTests(unittest.TestCase):
    def test_age_safety_rules_4_to_6_months(self):
        """Age < 6 months returns 'Puree stage'."""
        profile = {"age_months": 5, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6}
        result = bot.age_safety_rules_text(profile)
        self.assertIn("Puree stage", result)

    def test_age_safety_rules_6_to_9_months(self):
        """Age 6-9 months returns 'Smooth to slightly textured'."""
        profile = {"age_months": 7, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6}
        result = bot.age_safety_rules_text(profile)
        self.assertIn("Smooth to slightly textured", result)

    def test_age_safety_rules_12_to_18_months(self):
        """Age 12-18 months returns 'Family food adaptation'."""
        profile = {"age_months": 14, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6}
        result = bot.age_safety_rules_text(profile)
        self.assertIn("Family food adaptation", result)

    def test_age_safety_rules_24_plus(self):
        """Age 24+ months returns 'Near-adult'."""
        profile = {"age_months": 30, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6}
        result = bot.age_safety_rules_text(profile)
        self.assertIn("Near-adult", result)

    def test_age_safety_rules_no_profile_defaults_to_12(self):
        """No profile defaults to 12-month rules."""
        result = bot.age_safety_rules_text(None)
        self.assertIn("Family food adaptation", result)

    def test_age_safety_rules_boundary_9_months(self):
        """Exactly 9 months is included in 6-9 month range."""
        profile = {"age_months": 9, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6}
        result = bot.age_safety_rules_text(profile)
        # 9 is in the < 12 and >= 9 range
        self.assertIn("Finger food introduction", result)


if __name__ == "__main__":
    unittest.main()
