from pathlib import Path
import unittest

import install_handy


class HandyTests(unittest.TestCase):
    def test_personal_loopback_auth_catalog_and_explicit_identity(self):
        root=Path('/private/profiles')
        text=install_handy.configuration(root,'https://nas.example','fixture-personal-key',
                                         '64d68b5c-9e62-4c3d-a0f1-cc4dd4d72c4d',8318)
        self.assertIn('bind 127.0.0.1',text)
        self.assertIn('header Authorization "Bearer fixture-personal-key"',text)
        self.assertIn('header_up Authorization "Bearer fixture-personal-key"',text)
        self.assertIn('/private/profiles/personal/catalogs',text)
        self.assertIn('header_up Session-Id 64d68b5c',text)
        self.assertIn('header_up -X-Openai-Subagent',text)
        self.assertIn('reverse_proxy https://nas.example',text)
        self.assertNotIn('tls_insecure_skip_verify',text)
        self.assertNotIn('/work/',text)

    def test_untrusted_endpoint_key_and_session_are_rejected(self):
        root=Path('/private/profiles');session='64d68b5c-9e62-4c3d-a0f1-cc4dd4d72c4d'
        for endpoint,key,identity,port in [('http://nas.example','fixture-personal-key',session,8318),
                                         ('https://nas.example','fixture-key\ninjected',session,8318),
                                         ('https://nas.example','fixture-personal-key','invalid',8318),
                                         ('https://nas.example','fixture-personal-key',session,80)]:
            with self.assertRaises(ValueError):install_handy.configuration(root,endpoint,key,identity,port)


if __name__ == '__main__':
    unittest.main()
