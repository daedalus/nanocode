"""Tests for nanocode.tools.lazy_deps."""

import os
from unittest.mock import MagicMock, patch

import pytest

from nanocode.tools.lazy_deps import (
    LAZY_DEPS,
    FeatureUnavailable,
    _allow_lazy_installs,
    _is_present,
    _is_satisfied,
    _pkg_name_from_spec,
    _spec_is_safe,
    _specifier_from_spec,
    _venv_pip_install,
    active_features,
    ensure,
    ensure_and_bind,
    feature_install_command,
    feature_missing,
    feature_specs,
    is_available,
    refresh_active_features,
)


class TestFeatureSpecs:
    def test_known_feature_returns_specs(self):
        specs = feature_specs("provider.anthropic")
        assert len(specs) >= 1
        assert "anthropic" in specs[0]

    def test_known_feature_tts_returns_correct(self):
        specs = feature_specs("tts.edge")
        assert "edge-tts" in specs[0]

    def test_unknown_feature_raises_key_error(self):
        with pytest.raises(KeyError):
            feature_specs("nonexistent.feature")

    def test_lazy_deps_has_expected_keys(self):
        expected_keys = {
            "provider.anthropic", "provider.bedrock", "provider.ollama",
            "search.exa", "search.firecrawl",
            "tts.edge", "tts.elevenlabs",
            "stt.faster_whisper",
            "image.fal",
            "platform.telegram", "platform.discord", "platform.slack",
            "tool.acp", "tool.dashboard",
        }
        actual = set(LAZY_DEPS.keys())
        for k in expected_keys:
            assert k in actual, f"Missing expected key: {k}"


class TestFeatureInstallCommand:
    def test_known_feature(self):
        cmd = feature_install_command("provider.anthropic")
        assert cmd is not None
        assert cmd.startswith("pip install")

    def test_unknown_feature_returns_none(self):
        assert feature_install_command("nonexistent") is None


class TestSpecSafety:
    def test_safe_spec_passes(self):
        assert _spec_is_safe("anthropic>=0.80.0")
        assert _spec_is_safe("simple-package[extra]>=1.0")
        assert _spec_is_safe("package_name")

    def test_unsafe_chars_rejected(self):
        assert not _spec_is_safe("pkg; rm -rf /")
        assert not _spec_is_safe("pkg|cat /etc/passwd")
        assert not _spec_is_safe("pkg&cat /etc/passwd")
        assert not _spec_is_safe("pkg`id`")
        assert not _spec_is_safe("pkg$HOME")
        assert not _spec_is_safe("pkg\npip install evil")

    def test_unsafe_paths_rejected(self):
        assert not _spec_is_safe("/absolute/path")
        assert not _spec_is_safe("./relative")
        assert not _spec_is_safe("../traversal")
        assert not _spec_is_safe("-e git+https://evil.com/pkg")
        assert not _spec_is_safe("git+https://evil.com/pkg")
        assert not _spec_is_safe("file:///tmp/evil")
        assert not _spec_is_safe("pkg@https://evil.com")

    def test_empty_or_too_long_rejected(self):
        assert not _spec_is_safe("")
        long_spec = "pkg" + "x" * 300
        assert not _spec_is_safe(long_spec)


class TestPkgNameFromSpec:
    def test_basic(self):
        assert _pkg_name_from_spec("anthropic>=0.80.0") == "anthropic"

    def test_with_extra(self):
        assert _pkg_name_from_spec("slack-bolt[webhooks]>=22.0") == "slack-bolt"

    def test_dashed_name(self):
        assert _pkg_name_from_spec("python-telegram-bot[webhooks]>=22.0") == "python-telegram-bot"

    def test_plain_name(self):
        assert _pkg_name_from_spec("boto3") == "boto3"


class TestSpecifierFromSpec:
    def test_version_specifier(self):
        assert ">=0.80.0" in _specifier_from_spec("anthropic>=0.80.0")

    def test_with_extra(self):
        tail = _specifier_from_spec("slack-bolt[webhooks]>=22.0")
        assert ">=22.0" in tail
        assert "[webhooks]" not in tail

    def test_no_specifier_returns_empty(self):
        assert _specifier_from_spec("boto3") == ""


class TestIsPresent:
    def test_installed_package(self):
        assert _is_present("httpx")

    def test_stdlib_not_found_by_metadata(self):
        assert not _is_present("json")

    def test_nonexistent_package(self):
        assert not _is_present("_nonexistent_pkg_xyz_")


class TestIsAvailable:
    def test_known_and_present(self):
        with patch("nanocode.tools.lazy_deps.feature_missing", return_value=()):
            assert is_available("provider.anthropic") is True

    def test_known_and_missing(self):
        with patch("nanocode.tools.lazy_deps.feature_missing", return_value=("somepkg",)):
            assert is_available("provider.anthropic") is False

    def test_unknown_feature(self):
        assert is_available("nonexistent") is False


class TestFeatureMissing:
    def test_known_feature(self):
        missing = feature_missing("provider.anthropic")
        assert isinstance(missing, tuple)

    def test_unknown_feature_raises(self):
        with pytest.raises(KeyError):
            feature_missing("nonexistent")


class TestActiveFeatures:
    def test_returns_list_of_strings(self):
        features = active_features()
        assert isinstance(features, list)
        for f in features:
            assert isinstance(f, str)
            assert f in LAZY_DEPS


class TestAllowLazyInstalls:
    def test_default_true(self):
        assert _allow_lazy_installs() is True

    def test_env_var_disables(self):
        with patch.dict(os.environ, {"NANOCODE_DISABLE_LAZY_INSTALLS": "1"}):
            assert _allow_lazy_installs() is False

    def test_config_disable(self):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = {"allow_lazy_installs": False}
        with patch("nanocode.config.get_config", return_value=mock_cfg):
            assert _allow_lazy_installs() is False

    def test_config_enable(self):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = {"allow_lazy_installs": True}
        with patch("nanocode.config.get_config", return_value=mock_cfg):
            assert _allow_lazy_installs() is True


class TestEnsure:
    def test_unknown_feature_raises(self):
        with pytest.raises(FeatureUnavailable) as exc:
            ensure("nonexistent.feature", prompt=False)
        assert "not in LAZY_DEPS" in str(exc.value)

    def test_already_satisfied_does_nothing(self):
        with patch("nanocode.tools.lazy_deps.feature_missing", return_value=()):
            ensure("provider.anthropic", prompt=False)

    def test_disabled_lazy_installs_raises(self):
        with (
            patch("nanocode.tools.lazy_deps.feature_missing", return_value=("somepkg>=1.0",)),
            patch("nanocode.tools.lazy_deps._allow_lazy_installs", return_value=False),
        ):
            with pytest.raises(FeatureUnavailable) as exc:
                ensure("provider.anthropic", prompt=False)
            assert "lazy installs disabled" in str(exc.value)

    def test_unsafe_spec_raises(self):
        unsafe_specs = ("pkg;rm -rf /",)
        with patch("nanocode.tools.lazy_deps.feature_missing", return_value=unsafe_specs):
            with pytest.raises(FeatureUnavailable) as exc:
                ensure("provider.anthropic", prompt=False)
            assert "refusing to install" in str(exc.value)

    def test_pip_success(self):
        with (
            patch("nanocode.tools.lazy_deps.feature_missing", side_effect=[
                ("somepkg>=1.0",),
                (),
            ]),
            patch("nanocode.tools.lazy_deps._venv_pip_install") as mock_install,
        ):
            mock_install.return_value = type("R", (), {"success": True, "stdout": "", "stderr": ""})()
            ensure("provider.anthropic", prompt=False)

    def test_pip_failure_raises(self):
        with (
            patch("nanocode.tools.lazy_deps.feature_missing", return_value=("somepkg>=1.0",)),
            patch("nanocode.tools.lazy_deps._venv_pip_install") as mock_install,
        ):
            mock_install.return_value = type("R", (), {
                "success": False, "stdout": "", "stderr": "ERROR: Could not install"
            })()
            with pytest.raises(FeatureUnavailable) as exc:
                ensure("provider.anthropic", prompt=False)
            assert "pip install failed" in str(exc.value)

    def test_user_declines_prompt(self):
        with (
            patch("nanocode.tools.lazy_deps.feature_missing", return_value=("somepkg>=1.0",)),
            patch("builtins.input", return_value="n"),
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
        ):
            with pytest.raises(FeatureUnavailable) as exc:
                ensure("provider.anthropic", prompt=True)
            assert "declined" in str(exc.value)

    def test_user_accepts_prompt(self):
        with (
            patch("nanocode.tools.lazy_deps.feature_missing", side_effect=[
                ("somepkg>=1.0",),
                (),
            ]),
            patch("nanocode.tools.lazy_deps._venv_pip_install") as mock_install,
            patch("builtins.input", return_value="y"),
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
        ):
            mock_install.return_value = type("R", (), {"success": True, "stdout": "", "stderr": ""})()
            ensure("provider.anthropic", prompt=True)


class TestFeatureUnavailable:
    def test_exception_message(self):
        exc = FeatureUnavailable("test.feature", ("pkg1",), "some reason")
        msg = str(exc)
        assert "test.feature" in msg
        assert "pkg1" in msg
        assert "some reason" in msg

    def test_exception_attributes(self):
        exc = FeatureUnavailable("test.feature", ("pkg1", "pkg2"), "reason")
        assert exc.feature == "test.feature"
        assert exc.missing == ("pkg1", "pkg2")
        assert exc.reason == "reason"


class TestVenvPipInstall:
    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_uv_used_when_available(self, mock_run, mock_which):
        mock_which.return_value = "/usr/bin/uv"
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = _venv_pip_install(("anthropic>=0.80.0",))
        assert result.success
        mock_run.assert_called_once()
        assert "uv" in str(mock_run.call_args[0][0])

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_pip_when_uv_unavailable(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = _venv_pip_install(("anthropic>=0.80.0",))
        assert result.success

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_empty_specs_returns_success(self, mock_run, mock_which):
        result = _venv_pip_install(())
        assert result.success
        mock_run.assert_not_called()

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_pip_install_failure(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = _venv_pip_install(("somepkg",))
        assert not result.success
        assert "error" in result.stderr


class TestRefreshActiveFeatures:
    def test_returns_dict_with_status(self):
        results = refresh_active_features(prompt=False)
        assert isinstance(results, dict)
        for feature, status in results.items():
            assert isinstance(feature, str)
            assert isinstance(status, str)

    def test_refresh_current_features(self):
        with patch("nanocode.tools.lazy_deps.active_features", return_value=["provider.anthropic"]):
            with patch("nanocode.tools.lazy_deps.feature_missing", return_value=()):
                results = refresh_active_features(prompt=False)
                assert results["provider.anthropic"] == "current"


class TestEnsureAndBind:
    def test_successful_bind(self):
        def importer():
            return {"MY_VAR": 42}
        target = {}
        result = ensure_and_bind("provider.anthropic", importer, target, prompt=False)
        assert result
        assert target["MY_VAR"] == 42

    def test_failed_ensure_returns_false(self):
        def importer():
            return {"MY_VAR": 42}
        target = {}
        with patch("nanocode.tools.lazy_deps.ensure", side_effect=FeatureUnavailable("x", ("y",), "z")):
            result = ensure_and_bind("provider.anthropic", importer, target, prompt=False)
            assert not result
            assert "MY_VAR" not in target

    def test_failed_import_returns_false(self):
        def broken_importer():
            raise ImportError("nope")
        target = {}
        result = ensure_and_bind("provider.anthropic", broken_importer, target, prompt=False)
        assert not result


class TestSpecSatisfied:
    def test_is_satisfied_with_installed(self):
        result = _is_satisfied("httpx")
        assert result

    def test_not_satisfied_for_nonexistent(self):
        result = _is_satisfied("_nonexistent_pkg_xyz_>=1.0")
        assert not result


class TestEdgeCases:
    def test_lazy_deps_immutable(self):
        import copy
        og = copy.deepcopy(LAZY_DEPS)
        assert LAZY_DEPS == og

    def test_feature_specs_returns_copy(self):
        specs = feature_specs("provider.anthropic")
        assert isinstance(specs, tuple)

    def test_all_specs_are_safe(self):
        for name, spec_tuple in LAZY_DEPS.items():
            for spec in spec_tuple:
                assert _spec_is_safe(spec), f"Unsafe spec {spec!r} in {name!r}"

    def test_active_features_only_known_keys(self):
        features = active_features()
        for f in features:
            assert f in LAZY_DEPS, f"Unknown feature key in active: {f}"
