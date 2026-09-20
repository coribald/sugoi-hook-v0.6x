"""Runtime path resolution shared by source and packaged launches.

The resolver deliberately has no Tk or application imports so it can be
characterized independently and injected into future services.
"""

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Sequence


@dataclass(frozen=True)
class RuntimeContext:
    """Immutable paths and launch-mode decisions for one application run."""

    launcher_path: Path
    runtime_bundle_base_path: Path
    asset_base_path: Path
    user_data_dir: Path
    bundled_plugins_dir: Path
    user_plugins_dir: Path
    plugins_config_path: Path
    game_profiles_path: Path
    luna_x86_path: Path
    luna_x64_path: Path
    logo_path: Path
    is_frozen: bool
    is_compiled: bool


def resolve_runtime_context(
    *,
    argv: Sequence[str] | None = None,
    executable: str | Path | None = None,
    module_path: str | Path | None = None,
    frozen: bool | None = None,
    compiled: bool | None = None,
    meipass: str | Path | None = None,
) -> RuntimeContext:
    """Resolve the current runtime paths without constructing the GUI.

    Arguments default to interpreter state but are injectable for tests and
    package-launch diagnostics.  The decisions preserve the legacy GUI path
    behavior, including PyInstaller's separate asset directory.
    """
    resolved_module_path = Path(module_path or __file__).resolve()
    resolved_executable = Path(executable if executable is not None else sys.executable).resolve()
    resolved_argv = tuple(argv if argv is not None else sys.argv)
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    explicitly_compiled = bool(getattr(sys, "__compiled__", False) if compiled is None else compiled)

    if is_frozen:
        launcher_path = resolved_executable
    else:
        argv0 = Path(resolved_argv[0]).resolve() if resolved_argv and resolved_argv[0] else None
        if argv0 and argv0.suffix.lower() == ".exe" and argv0 != resolved_executable:
            launcher_path = argv0
        elif resolved_executable.suffix.lower() == ".exe" and "python" not in resolved_executable.name.lower():
            launcher_path = resolved_executable
        else:
            launcher_path = resolved_module_path

    runtime_bundle_base_path = (
        resolved_executable.parent
        if is_frozen or explicitly_compiled
        else resolved_module_path.parent
    )
    is_compiled = is_frozen or explicitly_compiled or (
        launcher_path.suffix.lower() == ".exe" and launcher_path != resolved_module_path
    )
    asset_base_path = (
        Path(meipass if meipass is not None else getattr(sys, "_MEIPASS", resolved_executable.parent))
        if is_frozen
        else runtime_bundle_base_path
    )
    user_data_dir = launcher_path.parent

    return RuntimeContext(
        launcher_path=launcher_path,
        runtime_bundle_base_path=runtime_bundle_base_path,
        asset_base_path=asset_base_path,
        user_data_dir=user_data_dir,
        bundled_plugins_dir=asset_base_path / "plugins",
        user_plugins_dir=user_data_dir / "plugins",
        plugins_config_path=user_data_dir / "plugins_config.json",
        game_profiles_path=user_data_dir / "game_profiles.json",
        luna_x86_path=asset_base_path / "luna_builds" / "LunaHostCLI32.exe",
        luna_x64_path=asset_base_path / "luna_builds" / "LunaHostCLI64.exe",
        logo_path=asset_base_path / "logo.webp",
        is_frozen=is_frozen,
        is_compiled=is_compiled,
    )
