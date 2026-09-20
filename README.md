# Sugoi Hook v0.6x

A fork of SugoiHook - a Windows GUI for attaching to game processes, selecting text hooks, processing extracted text through plugins, and optionally translating or displaying it in an overlay.

![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)

## Recent Changes

- Converted the app to a Luna-only hook engine build and removed Textractor packaging/runtime paths.
- Renamed the plugin base layer from `TextractorPlugin` to `HookPlugin` and cleaned up Luna-only app naming.
- Reworked the old Google plugin into a configurable `Deep Translator` plugin with reactive provider-specific settings.
- Moved the vendored translation package to top-level `deep_translator/` and removed the old `Translator/` wrapper folder.
- Added a native Jitendex-backed dictionary pane to the overlay window, including click/double-click lookup and common Japanese deinflection support.
- Updated the build scripts to match the current repo layout and preserve runtime `*_config.json` files across clean builds.
- Reworked the main UI layout: fixed header, better section collapsing, compact/full geometry restore, clearer hook/process flow, and split `Session Events` / `Session Output`.
- Improved plugin management with explicit controls, better defaults, and a live preview in the Overlay Window settings.
- Stabilized the text pipeline: shared pre-translation flow, clipboard alignment with translator input, lossless preprocessing with latest-pending translation, safer Hook Concatenation behavior, and less aggressive duplicate filtering.
- Expanded debugging and runtime logging, including console-visible pipeline tracing and sanitized outbound OpenAI payload logging.
- Added support for `gpt-4o` and `gpt-4o-mini` in the OpenAI translation plugin.
- Finalized the onefile release path, including persistent config/log files beside the exe and bundled plain/debug shortcuts.

## Contact

For support or discussion, join the **Sugoi Toolkit Discord Server**:

🔗 [Join Sugoi Toolkit Server](https://discord.gg/XFbWSjMHJh)

---

## Features

### Hook Engine

Sugoi Hook is currently packaged as a Luna-only build:

- **Luna Hook**
  - good compatibility with many modern games
  - the only bundled hook engine in the current app/builds

### Core Workflow

- attach to a running process
- inspect discovered hooks or enter a manual hook
- optionally combine hooks with Hook Concatenation
- run text through a configurable plugin chain
- view session events and session output separately
- auto-copy cleaned untranslated text to the clipboard if desired

### UI / Quality of Life

- fixed header outside the scroll region
- compact/expanded layout with remembered window geometry
- collapsible sections for process, hook, plugins, events, and output
- session status surfaced directly in the UI instead of only in logs
- improved plugin configuration dialogs, including overlay style preview
- system tray support

### Built-in Plugins

- **Hook Concatenation**
  - combines speaker/dialogue style split hooks
  - supports `dialogue_hook_id`, `prefix_hook_ids`, and a short timing window
- **Remove Duplicates**
  - filters immediate repeats instead of aggressively dropping broader matches
- **Remove Special Characters**
- **Minimum Length Filter**
  - now also handles empty / whitespace-only line removal
- **Fix Repeated Characters**
- **Deep Translator**
  - configurable `deep_translator` backend
  - includes Google, MyMemory, and optional API-backed services such as DeepL, Microsoft, LibreTranslate, Papago, QCRI, Baidu, Tencent, and Yandex
  - provider-specific settings update live inside the same configuration dialog
- **OpenAI Translate**
  - rolling original-line context
  - story / character context and instruction fields
  - support for `gpt-5-mini`, `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, and `gpt-4.1-mini`
- **Translation Proxy**
  - forwards extracted text to Translator++
- **Overlay Window**
  - on-screen text overlay with configurable fonts, colors, opacity, and saved position/size
  - optional right-side native dictionary pane backed by Jitendex
  - click or double-click overlay text to look up nearby Japanese terms

## Quick Start

### Prerequisites

- Windows 10/11
- Python 3.11+ if running from source or building from your own environment

### Run From Source

```powershell
git clone https://github.com/coribald/sugoi-hook-v0.6x.git
cd sugoi-hook-v0.6x
python SugoiHook_gui.py
```

For verbose runtime logging:

- `python SugoiHook_gui.py --debug`

### Build Executables

Release onefile build:

```powershell
build.bat
```

Debug standalone build:

```powershell
build_debug_standalone.bat
```

Current build behavior:

- uses repo-local pip and Nuitka caches
- includes the runtime asset folders used by the app:
  - `luna_builds/`
  - `deep_translator/`
  - `plugins/`
  - `dictionaries/`
- explicitly bundles `dictionary_backend.py` for the overlay dictionary system
- preserves runtime `*_config.json` files across clean builds
- release onefile output includes:
  - `SugoiHook.exe`
  - `SugoiHook v0.6x.lnk`
  - `SugoiHook v0.6x (debug).lnk`
- onefile runtime assets are bundled into the exe, while persistent files live beside it

## How to Use

### Basic Flow

1. **Select a process**
   - choose a process from `Select Process`
   - use the search box to narrow the list
   - attach using the action button

2. **Choose a hook source**
   - inspect hooks in `Select Hook`
   - select a discovered hook or enter a manual hook
   - if Hook Concatenation is active, it can become the effective source instead of a single selected hook

3. **Read the output**
   - `Session Events` shows attach / hook / pipeline status
   - `Session Output` shows the extracted / translated line flow

4. **Tune plugins as needed**
   - enable, disable, configure, and reorder plugins from the Plugins section

### Hook Concatenation

Hook Concatenation is designed for games where text is split across multiple hooks, commonly:

- one hook for the speaker name
- one hook for the dialogue text

Current behavior supports:

- `dialogue_hook_id`
- `prefix_hook_ids`
- `speaker_wait_ms`
- `clipboard_output_mode`
- `max_dialogue_length`
- burst suppression / post-burst recovery for skip-mode churn

For Luna, hook selectors can now be:

- numeric hook IDs like `1` or `2`
- Luna function labels like `EXBWX0@25C880`
- full Luna `context_info` values

The hook list context menu can also set Hook Concatenation roles directly:

- `Set as Dialogue Hook`
- `Set as Prefix Hook`

That lets the plugin briefly wait for a late-arriving speaker line without stalling forever when narration or monologue has no speaker hook at all.

### Translation Plugins

The app now uses a shared pre-translation pipeline so the translator input and clipboard input stay aligned.

Important behavior:

- translation plugins receive the cleaned untranslated line
- clipboard gets that same untranslated translator input
- configurable via concat plugin to include prefix or just clip dialogue-only
- rolling original-line context can be sent to OpenAI for continuity
- output processing preserves every hook event for stateful plugins, delivers the active translation, and keeps only the newest pending translation so rapid advancement cannot create an unbounded backlog

### Plugin Management

Current plugin controls support:

- toggle active state
- open settings
- move up / move down
- drag reordering if preferred
- refresh the plugin directory

Many plugin settings are persisted through `plugins_config.json`.

For `Deep Translator`, the visible settings are conditional on the selected provider.

### Overlay Window

The overlay plugin:

- remembers its size and position
- supports separate translation/original/warning fonts and colors
- supports a native right-side dictionary pane with configurable width and typography
- now includes a live preview in its settings dialog so style changes can be seen before saving

### Overlay Dictionary

The overlay dictionary is a native Sugoi Hook feature built into the Overlay Window plugin.

Current behavior:

- uses the bundled Jitendex dictionary from `dictionaries/jitendex`
- builds a persistent local SQLite cache on first use
- supports single-click / double-click lookup from overlay text
- prefers the longest match around the clicked position
- includes common Japanese deinflection and contraction handling
- shows up to 3 match candidates for the chosen span

Current limitations:

- dictionary styling is configurable from the Overlay Window plugin settings
- dictionary preview is not shown in the plugin settings dialog

## Runtime Files

Useful local state files:

- `plugins_config.json`
  - plugin settings, active plugins, main window geometry
  - plugin file names are the config keys, so renaming a plugin file creates a fresh config entry
- `overlay_config.json`
  - overlay appearance and geometry
- `dictionary_cache/`
  - persistent local cache built from the bundled Jitendex data
- `game_profiles.json`
  - saved per-game hook profile data used for engine recall and auto-hooking
- `sugoihook-runtime.log`
  - runtime log file

For the onefile release build, these files live beside `SugoiHook.exe`.

## Logging and Debugging

The app has expanded runtime tracing intended for source-mode debugging.

Current traces include:

- hook line arrival
- pre-translation plugin results / drops
- Hook Concatenation timing and emits
- translation request / response logging
- clipboard and final output decisions

OpenAI logging only emits when the app itself is running in debug mode, and the plugin now supports `minimal`, `debug`, and `noisy` logging levels.

## File Structure

```text
sugoi-hook/
├── SugoiHook_gui.py
├── dictionary_backend.py
├── dictionaries/
├── plugins/
├── luna_builds/
├── deep_translator/
├── build.bat
├── build_debug_standalone.bat
├── plugins_config.json
├── overlay_config.json
├── game_profiles.json
└── README.md
```

## Acknowledgments

Sugoi Hook builds on several open-source projects and community contributions.

### Hooking Engine

#### Luna Hook

Sugoi Hook integrates Luna Hook assets sourced from the [LunaTranslator](https://github.com/HIllya51/LunaTranslator) project.

- **Luna Hook DLLs**: based on work from [LunaTranslator](https://github.com/HIllya51/LunaTranslator)
- **LunaHostCLI**: CLI integration work by Team Sugoi Toolkit

## License

This project is licensed under the GPL-3.0 License. See `LICENSE` for details.

This tool is intended for legitimate translation-assistance and accessibility workflows. Please respect software licenses and terms of service when using text extraction tools.
