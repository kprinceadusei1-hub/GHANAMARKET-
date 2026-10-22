import shutil
import tempfile

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class IsolatedMediaTestRunner(DiscoverRunner):
    """Run tests with uploads written to a throwaway MEDIA_ROOT instead of the real media folder."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media_root = tempfile.mkdtemp(prefix="marketplace-test-media-")
        # override_settings fires setting_changed, so default_storage picks up the new location.
        # A fast hasher keeps the suite quick; production keeps Django's default PBKDF2.
        self._settings_override = override_settings(
            MEDIA_ROOT=self._media_root,
            PRIVATE_MEDIA_ROOT=self._media_root + "/private",
            PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        )
        self._settings_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._settings_override.disable()
        shutil.rmtree(self._media_root, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
