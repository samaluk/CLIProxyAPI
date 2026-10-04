import copy
import unittest

import refresh_scoped_catalogs as refresh

ROUTE = 'personal/codex-oauth/gpt-6-astra'


class ServiceTierRefreshTests(unittest.TestCase):
    def test_new_speed_tier_reaches_codex_without_changing_reasoning_or_prompts(self):
        before = {'models': [{'slug': ROUTE, 'base_instructions': 'local prompt',
                              'default_reasoning_level': 'high',
                              'service_tiers': [{'id': 'priority', 'name': 'Fast'}],
                              'additional_speed_tiers': ['fast']}]}
        original = copy.deepcopy(before)
        live = refresh.safe_model({'slug': ROUTE, 'service_tiers': [
            {'id': 'priority', 'name': 'remote prose'},
            {'id': 'ultrafast', 'description': 'remote instructions'}]})
        result, _ = refresh.codex_update(before, {ROUTE: live}, 'personal')
        model = result['models'][0]
        self.assertEqual([t['id'] for t in model['service_tiers']], ['priority', 'ultrafast'])
        self.assertEqual(model['service_tiers'][1]['name'], 'Ultrafast')
        self.assertEqual(model['service_tiers'][1]['description'], 'Ultrafast service tier')
        self.assertEqual(model['additional_speed_tiers'], ['fast', 'ultrafast'])
        self.assertEqual(model['default_reasoning_level'], 'high')
        self.assertEqual(model['base_instructions'], 'local prompt')
        self.assertNotIn('remote', str(result))
        self.assertEqual(before, original)
        self.assertEqual(refresh.change_report(before, result, 'codex', 'personal')['updated'][0]['fields'],
                         ['additional_speed_tiers', 'service_tiers'])
        self.assertEqual(refresh.codex_update(result, {ROUTE: live}, 'personal')[0], result)

    def test_missing_tiers_preserve_existing_but_explicit_empty_removes(self):
        before = {'models': [{'slug': ROUTE, 'service_tiers': [{'id': 'priority', 'name': 'Fast'}],
                              'additional_speed_tiers': ['fast']}]}
        result, _ = refresh.codex_update(before, {ROUTE: {'slug': ROUTE}}, 'personal')
        self.assertEqual(result, before)
        result, _ = refresh.codex_update(before, {ROUTE: {'slug': ROUTE, 'service_tiers': []}}, 'personal')
        self.assertEqual(result['models'][0]['service_tiers'], [])
        self.assertEqual(result['models'][0]['additional_speed_tiers'], [])

    def test_fast_only_never_invents_ultrafast(self):
        live = refresh.safe_model({'slug': ROUTE, 'service_tiers': [{'id': 'priority'}]})
        result, _ = refresh.codex_update({'models': [{'slug': ROUTE}]}, {ROUTE: live}, 'personal')
        self.assertEqual(result['models'][0]['additional_speed_tiers'], ['fast'])
        self.assertNotIn('ultrafast', str(result))

    def test_tiers_on_a_different_scope_are_untouched(self):
        before = {'models': [{'slug': ROUTE, 'service_tiers': []}]}
        result, _ = refresh.codex_update(before, {ROUTE: {'slug': ROUTE, 'service_tiers': [{'id': 'ultrafast'}]}}, 'work')
        self.assertEqual(before, result)


if __name__ == '__main__':
    unittest.main()
