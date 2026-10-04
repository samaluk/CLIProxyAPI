import copy
import json
import unittest
from model_labels import model_label
from standardize_model_names import transform, pi_overrides

ROUTE = 'work/claude-oauth/claude-3-5-haiku-20241022'

class PresentationContract(unittest.TestCase):
    def test_route_and_snapshot_identity_stay_distinct(self):
        self.assertEqual(model_label(ROUTE), 'W/CL · Haiku 3.5 20241022')
        self.assertNotEqual(model_label(ROUTE), model_label(ROUTE.replace('20241022', '20241023')))
        self.assertEqual(model_label('personal/gpt-6-sol'), 'P/CX · 6 Sol · alias')
        self.assertEqual(model_label('personal/codex-oauth/gpt-6-sol'), 'P/CX · 6 Sol')
        self.assertEqual(model_label('commandcode/gpt-5.6-sol'), 'P/CC · 5.6 Sol · alias')
        self.assertEqual(model_label('unknown/gpt-6-sol'), 'unknown/gpt-6-sol')

    def test_t3_string_and_object_preserve_capabilities_without_inventing_them(self):
        doc = {'providerInstances': {'claude_work': {'config': {'customModels': [ROUTE,
            {'slug': 'work/litellm/gpt-5.6-luna-pro', 'name': 'old', 'capabilities': {'optionDescriptors': []}},
            'native-untouched'], 'environment': {'secret': 'fixture'}}}}}
        original = copy.deepcopy(doc)
        result, changes = transform(doc, 't3')
        models = result['providerInstances']['claude_work']['config']['customModels']
        self.assertEqual(models[0], {'slug': ROUTE, 'name': model_label(ROUTE)})
        self.assertEqual(models[1]['capabilities'], {'optionDescriptors': []})
        self.assertEqual(models[2], 'native-untouched')
        self.assertEqual(doc, original)
        self.assertEqual(transform(result, 't3'), (result, []))
        self.assertEqual(len(changes), 2)

    def test_codex_changes_only_display_name_and_keeps_hidden_alias(self):
        model = {'slug': 'personal/gpt-6-sol', 'display_name': 'old', 'visibility': 'hide',
                 'model_messages': {'instructions_template': 'trusted'},
                 'supported_reasoning_levels': [{'effort': 'ultra', 'description': 'original'}]}
        doc = {'models': [model], 'version': 7}
        result, changes = transform(doc, 'codex')
        expected = copy.deepcopy(doc)
        expected['models'][0]['display_name'] = model_label(model['slug'])
        self.assertEqual(result, expected)
        self.assertEqual(transform(result, 'codex'), (result, []))

    def test_pi_name_overrides_preserve_limits_and_other_providers(self):
        doc = {'providers': {'cliproxyapi': {'modelOverrides': {ROUTE: {'maxTokens': 128000}}},
                             'other': {'modelOverrides': {ROUTE: {'name': 'leave'}}}}}
        result, changes = pi_overrides(doc, {'models': [{'id': ROUTE}]})
        self.assertEqual(result['providers']['cliproxyapi']['modelOverrides'][ROUTE],
                         {'maxTokens': 128000, 'name': model_label(ROUTE)})
        self.assertEqual(result['providers']['other'], doc['providers']['other'])
        self.assertEqual(pi_overrides(result, {'models': [{'id': ROUTE}]}), (result, []))

    def test_opencode_changes_only_cpa_names_and_keeps_saved_alias(self):
        route = 'commandcode/gpt-5.6-sol'
        doc = {'model': 'cpa-personal/' + route, 'provider': {
            'cpa-personal': {'options': {'apiKey': 'fixture'}, 'models': {
                route: {'name': 'old', 'variants': {'max': {'reasoningEffort': 'max'}}, 'limit': {'context': 10, 'output': 2}}}},
            'other': {'models': {route: {'name': 'leave'}}}}}
        result, changes = transform(doc, 'opencode')
        expected = copy.deepcopy(doc)
        expected['provider']['cpa-personal']['models'][route]['name'] = model_label(route)
        self.assertEqual(result, expected)
        self.assertEqual(transform(result, 'opencode'), (result, []))

if __name__ == '__main__':
    unittest.main()
