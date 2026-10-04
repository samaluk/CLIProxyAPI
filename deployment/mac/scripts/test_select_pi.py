import unittest

from select_pi import select


class SelectTests(unittest.TestCase):
    def test_explicit_scope_preserves_arguments_and_overrides_parent(self):
        self.assertEqual(select(['work', '--resume', 'a session'], 'personal', False),
                         ('work', ['--resume', 'a session']))

    def test_child_inherits_profile_without_prompt(self):
        self.assertEqual(select(['--print', 'hello'], 'personal', False),
                         ('personal', ['--print', 'hello']))

    def test_noninteractive_and_unknown_profiles_never_default(self):
        for inherited in (None, 'invalid'):
            with self.assertRaises(ValueError):
                select(['--print', 'hello'], inherited, False)

    def test_interactive_choice_and_cancellation(self):
        self.assertEqual(select([], None, True, lambda _: ' W '), ('work', []))
        with self.assertRaises(ValueError):
            select([], None, True, lambda _: '')
