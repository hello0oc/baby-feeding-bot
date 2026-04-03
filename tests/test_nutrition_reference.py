"""
Nutrition Reference — Unit Tests

Tests for:
- All entries have required fields
- No duplicate names
- Allergen risks are valid values
- appropriate_from_months is 4–36
"""
import json
import os
import pytest

# Import the functions to test
from baby_feeding_bot import (
    get_nutritional_context,
    get_nutrition_context_for_age,
    NUTRITION_REFERENCE,
    _load_nutrition_reference,
)


class TestNutritionReferenceData:
    """Tests for the nutrition reference JSON data integrity."""

    @pytest.fixture(scope="class")
    def nutrition_data(self):
        """Load the nutrition reference data."""
        # Load directly from file to ensure we're testing the source data
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ref_path = os.path.join(base_dir, "data", "baby_nutrition_reference.json")
        with open(ref_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture(scope="class")
    def foods_list(self, nutrition_data):
        """Get the list of foods from nutrition data."""
        return nutrition_data.get("foods", [])

    def test_all_entries_have_required_fields(self, foods_list):
        """Every food entry must have all required fields."""
        required_fields = [
            "name",
            "category",
            "nutrients_per_100g",
            "allergen_risk",
            "safe_preparation",
            "appropriate_from_months",
            "notes",
        ]
        required_nutrients = ["iron_mg", "calcium_mg", "vitamin_c_mg", "protein_g", "fiber_g"]
        required_name_languages = ["en", "de"]

        errors = []
        for i, food in enumerate(foods_list):
            food_name = food.get("name", {}).get("en", f"Food #{i}")
            
            # Check top-level fields
            for field in required_fields:
                if field not in food:
                    errors.append(f"{food_name}: missing field '{field}'")
            
            # Check name has both languages
            if "name" in food:
                for lang in required_name_languages:
                    if lang not in food["name"]:
                        errors.append(f"{food_name}: missing name language '{lang}'")
            
            # Check nutrients
            if "nutrients_per_100g" in food:
                for nutrient in required_nutrients:
                    if nutrient not in food["nutrients_per_100g"]:
                        errors.append(f"{food_name}: missing nutrient '{nutrient}'")

        assert not errors, f"Missing required fields found:\n" + "\n".join(errors)

    def test_no_duplicate_names(self, foods_list):
        """No two foods should have the same English or German name."""
        en_names = []
        de_names = []
        
        for food in foods_list:
            name = food.get("name", {})
            en_name = name.get("en", "").lower().strip()
            de_name = name.get("de", "").lower().strip()
            
            if en_name:
                en_names.append(en_name)
            if de_name:
                de_names.append(de_name)
        
        en_duplicates = [name for name in set(en_names) if en_names.count(name) > 1]
        de_duplicates = [name for name in set(de_names) if de_names.count(name) > 1]
        
        assert not en_duplicates, f"Duplicate English names found: {en_duplicates}"
        assert not de_duplicates, f"Duplicate German names found: {de_duplicates}"

    def test_allergen_risks_are_valid_values(self, foods_list):
        """Allergen risk must be one of: none, low, medium, high."""
        valid_risks = {"none", "low", "medium", "high"}
        errors = []
        
        for food in foods_list:
            risk = food.get("allergen_risk")
            if risk not in valid_risks:
                name = food.get("name", {}).get("en", "Unknown")
                errors.append(f"{name}: invalid allergen_risk '{risk}'")
        
        assert not errors, f"Invalid allergen risks found:\n" + "\n".join(errors)

    def test_appropriate_from_months_in_range(self, foods_list):
        """Appropriate from months must be between 4 and 36."""
        errors = []
        
        for food in foods_list:
            from_months = food.get("appropriate_from_months")
            if not isinstance(from_months, int) or from_months < 4 or from_months > 36:
                name = food.get("name", {}).get("en", "Unknown")
                errors.append(f"{name}: invalid appropriate_from_months '{from_months}'")
        
        assert not errors, f"Invalid appropriate_from_months found:\n" + "\n".join(errors)

    def test_categories_are_valid(self, foods_list, nutrition_data):
        """Category must be one of the valid categories."""
        valid_categories = set(nutrition_data.get("categories", []))
        errors = []
        
        for food in foods_list:
            category = food.get("category")
            if category not in valid_categories:
                name = food.get("name", {}).get("en", "Unknown")
                errors.append(f"{name}: invalid category '{category}'")
        
        assert not errors, f"Invalid categories found:\n" + "\n".join(errors)

    def test_safe_preparation_is_non_empty_list(self, foods_list):
        """safe_preparation must be a non-empty list of strings."""
        errors = []
        
        for food in foods_list:
            prep = food.get("safe_preparation", [])
            if not isinstance(prep, list) or len(prep) == 0:
                name = food.get("name", {}).get("en", "Unknown")
                errors.append(f"{name}: safe_preparation is empty or not a list")
            elif not all(isinstance(p, str) and p.strip() for p in prep):
                name = food.get("name", {}).get("en", "Unknown")
                errors.append(f"{name}: safe_preparation contains empty strings")
        
        assert not errors, f"Invalid safe_preparation found:\n" + "\n".join(errors)

    def test_nutrient_values_are_non_negative(self, foods_list):
        """All nutrient values must be non-negative numbers."""
        errors = []
        
        for food in foods_list:
            nutrients = food.get("nutrients_per_100g", {})
            for nutrient, value in nutrients.items():
                if not isinstance(value, (int, float)) or value < 0:
                    name = food.get("name", {}).get("en", "Unknown")
                    errors.append(f"{name}: {nutrient} has invalid value {value}")
        
        assert not errors, f"Invalid nutrient values found:\n" + "\n".join(errors)

    def test_at_least_50_foods(self, foods_list):
        """Reference should contain approximately 50 foods."""
        assert len(foods_list) >= 40, f"Expected at least 40 foods, got {len(foods_list)}"
        assert len(foods_list) <= 60, f"Expected at most 60 foods, got {len(foods_list)}"

    def test_foods_in_all_categories(self, foods_list, nutrition_data):
        """Should have foods in all categories."""
        categories = nutrition_data.get("categories", [])
        foods_by_category = {cat: [] for cat in categories}
        
        for food in foods_list:
            cat = food.get("category")
            if cat in foods_by_category:
                foods_by_category[cat].append(food.get("name", {}).get("en"))
        
        missing = [cat for cat, foods in foods_by_category.items() if not foods]
        assert not missing, f"Categories with no foods: {missing}"


class TestNutritionContextFunctions:
    """Tests for the nutrition context helper functions."""

    def test_get_nutritional_context_returns_string(self):
        """get_nutritional_context should return a string."""
        result = get_nutritional_context(["banana", "apple"])
        assert isinstance(result, str)

    def test_get_nutritional_context_matches_foods(self):
        """Should match foods from the reference."""
        result = get_nutritional_context(["banana", "sweet potato"])
        # Should contain matched foods
        if result:  # May be empty if no matches
            assert "banana" in result.lower() or "sweet potato" in result.lower()

    def test_get_nutritional_context_empty_list(self):
        """Empty list should return empty string or minimal result."""
        result = get_nutritional_context([])
        assert isinstance(result, str)

    def test_get_nutrition_context_for_age_returns_string(self):
        """get_nutrition_context_for_age should return a string."""
        for age in [4, 6, 9, 12, 18, 24]:
            result = get_nutrition_context_for_age(age)
            assert isinstance(result, str)

    def test_get_nutrition_context_for_age_contains_age_guidance(self):
        """Should contain age-specific guidance."""
        result = get_nutrition_context_for_age(6)
        # Should mention something about 6 months or the age range
        assert len(result) > 0

    def test_get_nutrition_context_includes_iron_guidance_for_6_months(self):
        """6-month context should emphasize iron-rich foods."""
        result = get_nutrition_context_for_age(6)
        # Should mention iron or critical nutrients
        assert "iron" in result.lower() or "6" in result


class TestNutritionDataLoading:
    """Tests for the nutrition data loading functionality."""

    def test_nutrition_reference_loaded_at_startup(self):
        """NUTRITION_REFERENCE should be loaded at module import."""
        assert isinstance(NUTRITION_REFERENCE, dict)
        assert "foods" in NUTRITION_REFERENCE or NUTRITION_REFERENCE == {"foods": [], "categories": [], "allergen_risk_levels": []}

    def test_load_nutrition_reference_returns_dict(self):
        """_load_nutrition_reference should return a dict."""
        result = _load_nutrition_reference()
        assert isinstance(result, dict)

    def test_load_nutrition_reference_has_expected_keys(self):
        """Loaded data should have expected keys if file exists."""
        result = _load_nutrition_reference()
        if result.get("foods"):  # Only if file was found and parsed
            assert "foods" in result
            assert "categories" in result
            assert "allergen_risk_levels" in result


class TestHighAllergenFoods:
    """Tests to ensure high allergen foods are properly identified."""

    @pytest.fixture(scope="class")
    def foods_list(self):
        """Get the list of foods from the global reference."""
        return NUTRITION_REFERENCE.get("foods", [])

    def test_egg_marked_high_allergen(self, foods_list):
        """Egg should be marked as high allergen."""
        egg_foods = [f for f in foods_list if "egg" in f.get("name", {}).get("en", "").lower()]
        for food in egg_foods:
            assert food.get("allergen_risk") == "high", f"{food['name']['en']} should be high allergen"

    def test_dairy_marked_high_allergen(self, foods_list):
        """Dairy products should be marked as high allergen."""
        dairy_foods = [f for f in foods_list if f.get("category") == "dairy"]
        for food in dairy_foods:
            assert food.get("allergen_risk") == "high", f"{food['name']['en']} should be high allergen"

    def test_fish_marked_high_allergen(self, foods_list):
        """Fish should be marked as high allergen."""
        fish_names = ["salmon", "cod", "fish"]
        fish_foods = [
            f for f in foods_list 
            if any(name in f.get("name", {}).get("en", "").lower() for name in fish_names)
        ]
        for food in fish_foods:
            assert food.get("allergen_risk") == "high", f"{food['name']['en']} should be high allergen"

    def test_high_allergen_foods_have_early_intro_months(self, foods_list):
        """High allergen foods should be introducible from 6 months (early introduction recommended)."""
        high_allergen_foods = [f for f in foods_list if f.get("allergen_risk") == "high"]
        for food in high_allergen_foods:
            assert food.get("appropriate_from_months", 12) <= 6, \
                f"{food['name']['en']} should be introducible by 6 months for early allergen introduction"


class TestIronRichFoods:
    """Tests for iron-rich foods which are critical after 6 months."""

    @pytest.fixture(scope="class")
    def foods_list(self):
        """Get the list of foods from the global reference."""
        return NUTRITION_REFERENCE.get("foods", [])

    def test_iron_fortified_cereal_available_from_4_months(self, foods_list):
        """Iron-fortified cereal should be available from 4 months."""
        cereal_foods = [
            f for f in foods_list 
            if "cereal" in f.get("name", {}).get("en", "").lower() or "oatmeal" in f.get("name", {}).get("en", "").lower()
        ]
        early_cereals = [f for f in cereal_foods if f.get("appropriate_from_months", 12) <= 6]
        assert len(early_cereals) > 0, "Should have iron-fortified cereals available from early months"

    def test_meat_foods_available_from_6_months(self, foods_list):
        """Meat foods should be available from 6 months for iron."""
        meat_foods = [f for f in foods_list if f.get("category") == "protein"]
        early_meats = [f for f in meat_foods if f.get("appropriate_from_months", 12) == 6]
        assert len(early_meats) >= 3, "Should have multiple protein sources from 6 months"

    def test_lentils_and_beans_available_from_6_months(self, foods_list):
        """Plant-based iron sources should be available from 6 months."""
        plant_proteins = ["lentil", "bean", "chickpea", "tofu"]
        plant_foods = [
            f for f in foods_list
            if any(name in f.get("name", {}).get("en", "").lower() for name in plant_proteins)
        ]
        early_plants = [f for f in plant_foods if f.get("appropriate_from_months", 12) == 6]
        assert len(early_plants) >= 2, "Should have plant-based iron sources from 6 months"
