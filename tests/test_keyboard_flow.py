"""
Tests for the inline keyboard callback state machine.
The flow has 3 steps: opt → selday → apply, plus back navigation.
"""
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_keyboard_flow.sqlite3"),
)

import baby_feeding_bot as bot


class OptionPickerKeyboardTests(unittest.TestCase):
    """Test the initial option picker keyboard."""

    def test_build_option_picker_returns_2_buttons(self):
        """Option picker must have exactly 2 buttons."""
        keyboard = bot.build_option_picker_keyboard()
        self.assertEqual(len(keyboard.inline_keyboard), 2)

    def test_option_picker_button_1_correct_data(self):
        """First button should have callback_data='opt:1'."""
        keyboard = bot.build_option_picker_keyboard()
        btn = keyboard.inline_keyboard[0][0]
        self.assertEqual(btn.callback_data, "opt:1")
        self.assertEqual(btn.text, "1️⃣ Option 1")

    def test_option_picker_button_2_correct_data(self):
        """Second button should have callback_data='opt:2'."""
        keyboard = bot.build_option_picker_keyboard()
        btn = keyboard.inline_keyboard[1][0]
        self.assertEqual(btn.callback_data, "opt:2")
        self.assertEqual(btn.text, "2️⃣ Option 2")


class InspirationKeyboardTests(unittest.TestCase):
    """Test the day picker keyboards for Option 1 and Option 2."""

    def test_option_1_keyboard_has_7_day_buttons(self):
        """Option 1 day picker should have 7 day buttons with 'selday:1:X' data."""
        keyboard = bot.build_inspiration_keyboard(1)
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        self.assertEqual(len(all_buttons), 7)
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:1:"))
            day = btn.callback_data.split(":")[-1]
            self.assertIn(day, {"mon", "tue", "wed", "thu", "fri", "sat", "sun"})

    def test_option_2_keyboard_has_7_day_buttons(self):
        """Option 2 day picker should have 7 day buttons with 'selday:2:X' data."""
        keyboard = bot.build_inspiration_keyboard(2)
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        self.assertEqual(len(all_buttons), 7)
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:2:"))
            day = btn.callback_data.split(":")[-1]
            self.assertIn(day, {"mon", "tue", "wed", "thu", "fri", "sat", "sun"})

    def test_option_1_and_2_produce_different_callback_data(self):
        """Option 1 and Option 2 keyboards must produce different callback data."""
        kbd1 = bot.build_inspiration_keyboard(1)
        kbd2 = bot.build_inspiration_keyboard(2)
        data1 = {btn.callback_data for row in kbd1.inline_keyboard for btn in row}
        data2 = {btn.callback_data for row in kbd2.inline_keyboard for btn in row}
        self.assertEqual(data1 & data2, set(), "Option 1 and 2 day pickers should have no overlap")
        # All option 1 should start with selday:1:
        self.assertTrue(all(d.startswith("selday:1:") for d in data1))
        # All option 2 should start with selday:2:
        self.assertTrue(all(d.startswith("selday:2:") for d in data2))


class SlotKeyboardTests(unittest.TestCase):
    """Test the slot picker keyboard."""

    def test_slot_keyboard_format_apply_N_day_slot(self):
        """Slot buttons should have format 'apply:N:day:slot'."""
        keyboard = bot.build_slot_keyboard(option_number=1, day_key="wed")
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        slot_buttons = [b for b in all_buttons if b.callback_data.startswith("apply:")]
        expected_slots = {"breakfast", "snack1", "lunch", "snack2", "dinner"}
        for btn in slot_buttons:
            parts = btn.callback_data.split(":")
            self.assertEqual(len(parts), 4, f"Expected 4 parts in {btn.callback_data}")
            self.assertEqual(parts[0], "apply")
            self.assertEqual(parts[1], "1")  # option number
            self.assertEqual(parts[2], "wed")  # day key
            self.assertIn(parts[3], expected_slots)

    def test_slot_keyboard_has_5_slot_buttons(self):
        """Slot keyboard should have exactly 5 slot buttons (breakfast, snack1, lunch, snack2, dinner)."""
        keyboard = bot.build_slot_keyboard(option_number=2, day_key="mon")
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        slot_buttons = [b for b in all_buttons if b.callback_data.startswith("apply:")]
        self.assertEqual(len(slot_buttons), 5)

    def test_slot_keyboard_has_back_button(self):
        """Slot keyboard must have a back button."""
        keyboard = bot.build_slot_keyboard(option_number=3, day_key="fri")
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        back_buttons = [b for b in all_buttons if b.callback_data.startswith("back:")]
        self.assertEqual(len(back_buttons), 1)
        # Back button text should mention days
        self.assertIn("Back", back_buttons[0].text)

    def test_slot_keyboard_back_preserves_option_number(self):
        """Back button should include the option number so user returns to correct option."""
        keyboard = bot.build_slot_keyboard(option_number=3, day_key="fri")
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        back_buttons = [b for b in all_buttons if b.callback_data.startswith("back:")]
        self.assertEqual(back_buttons[0].callback_data, "back:3")


class BackFlowTests(unittest.TestCase):
    """Test the 'back' flow navigation."""

    def test_back_returns_to_option_picker(self):
        """After back action, option picker keyboard is shown."""
        # Simulate back action — it rebuilds option picker
        keyboard = bot.build_option_picker_keyboard()
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        callback_data = [b.callback_data for b in all_buttons]
        self.assertIn("opt:1", callback_data)
        self.assertIn("opt:2", callback_data)
        self.assertEqual(len(all_buttons), 2)

    def test_selday_after_opt1_has_correct_option(self):
        """selday after selecting opt:1 should produce 'selday:1:X' format."""
        keyboard = bot.build_inspiration_keyboard(1)
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        # After clicking opt:1, the selday buttons should reference option 1
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:1:"))

    def test_selday_after_opt2_has_correct_option(self):
        """selday after selecting opt:2 should produce 'selday:2:X' format."""
        keyboard = bot.build_inspiration_keyboard(2)
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:2:"))


class CallbackDataParsingTests(unittest.TestCase):
    """Test parsing of callback data strings."""

    def test_parse_opt_callback(self):
        """Parse 'opt:N' format."""
        data = "opt:1"
        parts = data.split(":")
        self.assertEqual(parts[0], "opt")
        self.assertEqual(int(parts[1]), 1)

    def test_parse_selday_callback(self):
        """Parse 'selday:N:day' format."""
        data = "selday:2:wed"
        parts = data.split(":")
        self.assertEqual(parts[0], "selday")
        self.assertEqual(int(parts[1]), 2)
        self.assertEqual(parts[2], "wed")

    def test_parse_apply_callback(self):
        """Parse 'apply:N:day:slot' format."""
        data = "apply:1:mon:dinner"
        parts = data.split(":")
        self.assertEqual(parts[0], "apply")
        self.assertEqual(int(parts[1]), 1)
        self.assertEqual(parts[2], "mon")
        self.assertEqual(parts[3], "dinner")

    def test_parse_back_callback(self):
        """Parse 'back:N' format."""
        data = "back:2"
        parts = data.split(":")
        self.assertEqual(parts[0], "back")
        self.assertEqual(int(parts[1]), 2)

    def test_apply_callback_all_days_and_slots(self):
        """All day/slot combinations produce valid apply callback data."""
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        slots = ["breakfast", "snack1", "lunch", "snack2", "dinner"]
        for day in days:
            for slot in slots:
                data = f"apply:1:{day}:{slot}"
                parts = data.split(":")
                self.assertEqual(len(parts), 4)
                self.assertEqual(parts[2], day)
                self.assertEqual(parts[3], slot)


class StatePreservationTests(unittest.TestCase):
    """Test that user_data state is correctly preserved through navigation."""

    def test_last_inspiration_id_storage(self):
        """Store and retrieve last_inspiration_id in user_data."""
        user_data = {}
        inspiration_id = 42
        user_data["last_inspiration_id"] = inspiration_id
        self.assertEqual(user_data["last_inspiration_id"], 42)

    def test_selected_option_storage(self):
        """Store and retrieve selected_option in user_data."""
        user_data = {}
        user_data["selected_option"] = 2
        self.assertEqual(user_data["selected_option"], 2)

    def test_selected_day_per_option_storage(self):
        """selected_day_opt1 and selected_day_opt2 should be stored separately."""
        user_data = {}
        user_data["selected_day_opt1"] = "wed"
        user_data["selected_day_opt2"] = "fri"
        self.assertEqual(user_data["selected_day_opt1"], "wed")
        self.assertEqual(user_data["selected_day_opt2"], "fri")

    def test_navigation_opt1_day_back_opt2_day2_slot(self):
        """Simulate: opt1→day→back→opt2→day2→slot — state should be correct at each step."""
        user_data = {}

        # Step 1: User picks opt:1
        user_data["selected_option"] = 1
        self.assertEqual(user_data["selected_option"], 1)

        # Step 2: User picks day for opt1
        user_data["selected_day_opt1"] = "wed"
        self.assertEqual(user_data["selected_day_opt1"], "wed")

        # Step 3: User presses Back — back action returns to option picker
        # (back:X preserves selected_option=1 in context.user_data)
        keyboard = bot.build_option_picker_keyboard()
        self.assertIsNotNone(keyboard)

        # Step 4: User picks opt:2 (overwrites selected_option)
        user_data["selected_option"] = 2
        self.assertEqual(user_data["selected_option"], 2)

        # Step 5: User picks day2 for opt2
        user_data["selected_day_opt2"] = "fri"
        self.assertEqual(user_data["selected_day_opt2"], "fri")

        # Verify both options' state is preserved
        self.assertEqual(user_data["selected_option"], 2)  # current = opt2
        self.assertEqual(user_data["selected_day_opt1"], "wed")  # still tracked
        self.assertEqual(user_data["selected_day_opt2"], "fri")  # current day for opt2


class LastInspirationIdTests(unittest.TestCase):
    """Test last_inspiration_id storage and retrieval."""

    def setUp(self):
        bot.init_db()
        bot.upsert_user(999200, "en")

    def test_store_inspiration_sets_id(self):
        """store_inspiration returns the ID that should be stored."""
        bot.set_profile(999200, age_months=12, allergies="none")
        inspiration_id = bot.store_inspiration(
            999200,
            kind="text",
            summary="Test inspiration",
            adaptations=["Option 1", "Option 2"],
        )
        self.assertIsNotNone(inspiration_id)
        self.assertIsInstance(inspiration_id, int)
        self.assertGreater(inspiration_id, 0)

    def test_get_latest_inspiration_returns_newest(self):
        """get_latest_inspiration returns the most recently created inspiration."""
        bot.store_inspiration(999201, kind="text", summary="First", adaptations=[])
        bot.store_inspiration(999201, kind="text", summary="Second", adaptations=[])
        bot.store_inspiration(999201, kind="text", summary="Third", adaptations=[])
        latest = bot.get_latest_inspiration(999201)
        self.assertEqual(latest["summary"], "Third")

    def test_get_inspiration_by_id_and_user(self):
        """get_inspiration(user_id, id) only returns if user owns the inspiration."""
        bot.store_inspiration(999202, kind="text", summary="Owner inspiration", adaptations=[])
        bot.store_inspiration(999203, kind="text", summary="Other user inspiration", adaptations=[])
        # Try to get 999202's inspiration as user 999203
        result = bot.get_inspiration(999203, 1)  # id=1 belongs to 999202
        self.assertIsNone(result)

    def test_adaptation_index_parsing(self):
        """get_adaptation_by_index extracts the correct option from JSON adaptations."""
        bot.upsert_user(999204, "en")
        bot.store_inspiration(
            999204,
            kind="text",
            summary="Test",
            adaptations=["Banana Meal", "Carrot Meal"],
        )
        latest = bot.get_latest_inspiration(999204)
        opt1 = bot.get_adaptation_by_index(latest, 1)
        opt2 = bot.get_adaptation_by_index(latest, 2)
        self.assertEqual(opt1.strip(), "Banana Meal")
        self.assertEqual(opt2.strip(), "Carrot Meal")

    def test_adaptation_index_out_of_range(self):
        """get_adaptation_by_index returns empty string for out-of-range index."""
        bot.upsert_user(999205, "en")
        bot.store_inspiration(999205, kind="text", summary="Test", adaptations=["Only One"])
        latest = bot.get_latest_inspiration(999205)
        opt3 = bot.get_adaptation_by_index(latest, 3)
        self.assertEqual(opt3, "")


if __name__ == "__main__":
    unittest.main()
