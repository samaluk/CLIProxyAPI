import unittest
from codex_account_tiers import route_tiers, apply, provider_capabilities, verified_routes


class AccountTierTests(unittest.TestCase):
    def test_discovery_follows_account_response_without_plan_rules(self):
        credentials = [{'account_id': 'account-a', 'prefix': 'personal',
                        'model_aliases': [{'name': 'gpt-example', 'alias': 'codex-oauth/gpt-example'}]},
                       {'account_id': 'account-b', 'prefix': 'work',
                        'model_aliases': [{'name': 'gpt-example', 'alias': 'codex-oauth/gpt-example'}]}]
        for speeds in [[], ['fast'], ['fast', 'ultrafast']]:
            result = route_tiers(credentials, 'account-a', [{'slug': 'gpt-example',
                'additional_speed_tiers': speeds, 'service_tiers': [{'id': 'priority', 'description': 'untrusted'}]}])
            self.assertEqual(list(result), ['personal/codex-oauth/gpt-example'])
            self.assertEqual(result['personal/codex-oauth/gpt-example']['additional_speed_tiers'], speeds)
            self.assertNotIn('untrusted', str(result))

    def test_missing_or_disabled_accounts_do_not_claim_entitlement(self):
        auth = {'account_id': 'a', 'prefix': 'personal', 'disabled': True,
                'model_aliases': [{'name': 'm', 'alias': 'codex-oauth/m'}]}
        self.assertEqual(route_tiers([auth], 'a', [{'slug': 'm', 'additional_speed_tiers':['ultrafast']}]), {})
        auth['disabled'] = False
        self.assertEqual(route_tiers([auth], 'b', [{'slug': 'm'}]), {})
        self.assertEqual(route_tiers([auth], 'a', []), {})

    def test_overrides_cannot_add_routes_or_change_prompts(self):
        live = {'p': {'base_instructions': 'trusted', 'context_window': 1000}}
        apply(live, {'p': {'additional_speed_tiers':['fast']}, 'q': {'additional_speed_tiers':[]}})
        self.assertEqual(live, {'p': {'base_instructions': 'trusted', 'context_window':1000, 'additional_speed_tiers':['fast']}})


class ProviderCapabilityTests(unittest.TestCase):
    def test_provider_values_override_generic_aliases_without_prompt_import(self):
        fields = provider_capabilities({'context_window': 200000, 'max_output_tokens': 16000,
            'input_modalities': ['text'], 'output_modalities': ['text'],
            'supported_reasoning_levels': [{'effort': 'low', 'description': 'untrusted'}],
            'default_reasoning_level': 'low', 'base_instructions': 'untrusted'})
        live = {'r': {'context_window': 100000, 'max_tokens': 4000,
            'supported_input_modalities': ['text', 'image'], 'base_instructions': 'trusted'}}
        apply(live, {'r': fields})
        self.assertEqual(live['r']['context_window'], 200000)
        self.assertEqual(live['r']['max_tokens'], 16000)
        self.assertEqual(live['r']['supported_input_modalities'], ['text'])
        self.assertEqual(live['r']['supported_reasoning_levels'], [{'effort': 'low', 'description': 'low'}])
        self.assertEqual(live['r']['base_instructions'], 'trusted')
        self.assertNotIn('untrusted', str(live))

    def test_invalid_limits_are_not_claimed_and_empty_modalities_remain_explicit(self):
        self.assertEqual(provider_capabilities({'context_window': True, 'max_tokens': -1,
            'max_context_window': 0, 'input_modalities': [], 'output_modalities': 'text'}),
            {'input_modalities': []})

    def test_reasoning_restriction_clears_an_unsupported_generic_default(self):
        for levels in ([], [{'effort': 'low'}]):
            live = {'r': {'default_reasoning_level': 'high'}}
            apply(live, {'r': provider_capabilities({'supported_reasoning_levels': levels})})
            self.assertIsNone(live['r']['default_reasoning_level'])
        self.assertIsNone(provider_capabilities({'default_reasoning_level': None})['default_reasoning_level'])

    def test_unverified_routes_are_deferred_only_in_the_requested_scope(self):
        live = {'personal/codex-oauth/new': {}, 'work/litellm/m': {}}
        self.assertEqual(verified_routes(live, {}, 'work'), [])
        self.assertEqual(verified_routes(live, {}, 'personal'), ['personal/codex-oauth/new'])
        self.assertEqual(live, {'work/litellm/m': {}})

    def test_authoritative_service_tiers_replace_stale_generic_speed_alias(self):
        live = {'r': {'additional_speed_tiers': ['ultrafast']}}
        apply(live, {'r': {'service_tiers': [{'id': 'priority'}]}})
        self.assertEqual(live['r']['additional_speed_tiers'], ['fast'])
