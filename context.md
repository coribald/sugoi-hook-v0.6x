# Sugoi Hook Context

## What This App Is

Sugoi Hook is a Windows/Tkinter GUI for attaching to a running game process, selecting text hooks, running extracted text through a plugin pipeline, and showing/copying the results. The main moving parts are:

- `SugoiHook_gui.py`
  - main window
  - process/hook attach flow
  - plugin loading, config UI, lifecycle, and pipeline orchestration
  - session event log, session output, clipboard handling, config persistence
- `plugins/`
  - text-processing plugins
  - translation plugins
  - overlay display plugin
  - all built-in plugins now inherit from `HookPlugin`
- `deep_translator/`
  - vendored translation backend package used by the `Deep Translator` plugin
- `dictionary_backend.py`
  - native Jitendex-backed lookup/index/search backend used by the overlay dictionary pane
- `dictionaries/`
  - bundled Jitendex dictionary data used by the native overlay dictionary feature
- `plugins_config.json`
  - active plugins
  - plugin settings
  - main window geometry
- `overlay_config.json`
  - overlay window geometry and styling
- `game_profiles.json`
  - saved per-game hook profiles
  - remembers a saved hook/manual hook for auto-selection
  - does not currently store full per-game plugin/app configuration

## Current Architecture Notes

- Process/hook/output flow is source-first during iteration. We are mostly running from the `.py` path, not rebuilding constantly.
- The plugin pipeline now has a shared pre-translation stage so translator input and clipboard input can stay aligned.
- The overlay window now has an optional native right-side dictionary pane backed by Jitendex.
- Output processing is asynchronous with lossless stateful preprocessing and a latest-pending translation slot:
  - every raw hook event reaches stateful plugins in arrival order
  - only one translation request runs at a time, while newer pending lines replace older pending work
  - an in-flight successful translation is still delivered before the newest pending line, while reset/detach-invalidated results are discarded
- Hook Concatenation is stateful and timing-sensitive. It should be treated carefully because many downstream behaviors depend on its output.
- Translation plugins are expected to receive the cleaned untranslated line, not raw hook text.
- The app now logs a lot of pipeline detail to both `sugoihook-runtime.log` and the source-run console.
- The native dictionary backend is stdlib-only; no new pip dependencies were added for it.

## UI State

- The main window has a fixed header outside the main scroll region.
- The outer scrollbar exists as a fallback, but section-local scrolling should own the mouse wheel where appropriate.
- `Select Process` and `Select Hook` are a responsive pair:
  - stacked full-width when either is expanded
  - side-by-side when both are collapsed
- Compact mode is active when `Select Process`, `Select Hook`, and `Plugins` are all collapsed.
- The app stores separate full and compact geometries and auto-switches between them.
- Plugins start collapsed by default.

## Translation / Hook Pipeline State

- Source runs now assume a system-installed Python 3.11+ environment.
- Clipboard now gets the same untranslated line that is sent to translation plugins.
- `deep_translator.py` is now the configurable multi-provider translation plugin.
- Its settings UI is provider-reactive:
  - changing provider in the dialog rebuilds the visible provider-specific fields immediately
- Hook Concatenation currently supports:
  - `dialogue_hook_id`
  - `prefix_hook_ids`
  - `speaker_wait_ms`
- Hook Concatenation also now supports:
  - Luna function-label selectors like `EXBWX0@25C880`
  - full Luna `context_info` selectors
  - `clipboard_output_mode`
  - `max_dialogue_length`
  - burst suppression and post-burst recovery
- Prefix-only lines now flush after the same timeout instead of disappearing.
- Hook list context menu can:
  - copy hook ID
  - copy Luna context info
  - copy hook function label
  - set a hook directly as concat dialogue/prefix
- `remove_duplicates.py` was rewritten to suppress only immediate repeats rather than broad substring/seen-before matches.

## Logging / Debugging State

- `SugoiHook_gui.py` emits `[PIPELINE] ...` logs for:
  - hook arrival
  - pre-translation plugin flow
  - translation result/empty result
  - post-translation flow
  - final display/clipboard decisions
- `plugins/hook_concatenation.py` emits `[HOOK CONCAT] ...` logs for buffered prefixes/dialogue, waits, and emits.
- `plugins/min_length_filter.py`, `plugins/fix_repeated_chars.py`, and `plugins/remove_duplicates.py` now log their in/out behavior.
- `plugins/openai_translate.py` now prints a sanitized outbound payload plus raw API responses to the console.
  - only when the app is running in global debug mode
  - actual verbosity is controlled by the plugin `logging_level` setting:
    - `minimal`
    - `debug`
    - `noisy`

## OpenAI Plugin State

- Supported models now include:
  - `gpt-5-mini`
  - `gpt-4o`
  - `gpt-4o-mini`
  - `gpt-4.1`
  - `gpt-4.1-mini`
- `reasoning` is only sent for `gpt-5*` models.
- For `gpt-4o` / `gpt-4o-mini`, requested `low` verbosity is automatically raised to `medium`.
- There is a no-op safeguard: if the model returns the source text unchanged, it is treated as no translation.
- Rolling original-line context is enabled and was fixed so it actually reaches the translator path.
- Long-idle stale HTTP sessions are retried once by resetting the `requests.Session()`.

## Prompt / Config State

The OpenAI translation config currently centers on:

- faithful translation over paraphrase
- preserving ambiguity when the source is genuinely ambiguous
- avoiding guessed gender/pronouns when context is insufficient

If behavior looks wrong, inspect:

- `plugins_config.json`
- the sanitized outbound payload log from `openai_translate.py`

## Overlay Window State

- The overlay plugin remembers its own size and position through `overlay_config.json`.
- The plugin settings dialog now has a live preview for overlay fonts/colors/styles.
- The overlay plugin now also exposes dictionary settings:
  - enable/disable dictionary pane
  - dictionary width
  - font/size/color controls for dictionary headword, definitions, meta, and JP/EN examples
- Those dictionary settings save/persist/apply correctly, but there is intentionally no dictionary live preview in the plugin settings dialog right now.
- Overlay dictionary lookup is built around:
  - bundled `dictionaries/jitendex`
  - persistent SQLite cache under `dictionary_cache/`
  - longest-match lookup around the clicked position
  - common Japanese deinflection / contraction handling
  - up to 3 candidates shown per chosen span
- The settings dialog scrollbar was adjusted to avoid stealing the mouse wheel from selector/editor widgets, though this may still be worth rechecking if combobox popup behavior feels off in practice.

## Lifecycle / Stability Notes

- Plugin reload and app shutdown now call plugin `on_disable()` and remove plugin modules from `sys.modules`.
- Luna subprocesses use generation-bound sessions so stale readers and exits cannot affect a newer attachment.
- Luna stdout/stderr are drained by session-specific workers, detach is asynchronous, and unexpected process exit resets the UI state.
- This cleaned up stale sessions/windows/timers and made reload/close behavior more intentional.
- We deliberately did not pursue some lower-value branching behavior in the clipboard path to avoid destabilizing the now-stable pipeline.

## Good Next Starting Points

- If translation behavior drifts:
  - inspect the outbound OpenAI payload in console
  - compare translator input vs clipboard
  - check `[HOOK CONCAT]` and `[PIPELINE]` logs together
- If UI work resumes:
  - keep using source-run iteration first
  - avoid rebuilding unless validating packaged behavior
- If packaged behavior is revisited:
  - remember earlier fixes around Tk packaging, logging, and elevation heuristics
  - current packaged builds are Luna-only
  - current onefile builds store persistent config/log files beside `SugoiHook.exe`, while bundled runtime assets are extracted to the temporary onefile runtime folder
  - current builds must bundle:
    - `luna_builds/`
    - `deep_translator/`
    - `plugins/`
    - `dictionaries/`
    - `dictionary_backend.py`

## Today’s High-Level Changelog

- stabilized source-run behavior and removed unwanted auto-elevation behavior
- improved main window usability and layout, including compact/full geometry behavior
- moved more status into explicit UI instead of hidden output/log-only behavior
- added overlay settings live preview
- added native Jitendex dictionary lookup inside the overlay window
- repaired rolling OpenAI context so previous lines actually reach the prompt
- aligned clipboard with translator input
- fixed Hook Concatenation timing/output edge cases
- added latest-wins async output processing
- added Luna selector support and direct concat role assignment from the hook list
- fixed duplicate suppression so valid concatenated lines are not dropped
- expanded pipeline debugging across the full text flow
- added `gpt-4o` and `gpt-4o-mini` to the OpenAI plugin
- adjusted 4o verbosity behavior to avoid invalid low-verbosity requests
