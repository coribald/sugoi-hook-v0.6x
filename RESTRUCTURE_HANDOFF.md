# Sugoi Hook restructure handoff

## Current state

- Branch: `restructure/sugoi-hook-gui`
- Head: `afcdc74 Finalize application composition root`
- Branch is 14 commits ahead of `origin/restructure/sugoi-hook-gui` and contains
  the complete planned Phase 0–10 restructure sequence below.
- Working tree was clean when this report was written.
- Source launcher remains unchanged:

  ```powershell
  python .\SugoiHook_gui.py
  python .\SugoiHook_gui.py --debug
  ```

  `SugoiHook_gui.py` is now intentionally the bootstrap/compatibility entrypoint;
  `sugoihook_app.py` owns `SugoiHookGUI`.

## Behavioral invariants preserved

- `plugin.app` continues to refer to the `SugoiHookGUI` coordinator.
- Luna command strings, Windows process flags, UTF-16 LE output decoding,
  hook parsing, attach/detach behavior, and stale-session protection remain in
  place.
- Hook output still records and routes into the output/plugin pipeline from the
  Luna reader thread. Only Tk mutations are dispatched to the UI thread.
- Plugin settings/profile mutations retain transactional persistence through the
  existing managers/stores; extracted views do not save configuration directly.
- UI labels, dimensions, widget ordering, modal behavior, and layout were
  preserved in the extracted dialogs/views.

## Phase-by-phase results

### Phase 0 — Characterization

Commit: `def81f4 Characterize GUI decomposition boundaries`

- Added `RESTRUCTURE_PLAN.md` and characterization coverage for runtime paths,
  UI dispatch, Luna output routing, process/profile behavior, plugin discovery,
  and hook registry behavior.
- Established incremental extraction rules and live/package gates.

### Phase 1 — Runtime context

Commit: `9c9dba3 Extract runtime path context`

- Added `runtime_context.py` as the immutable owner of source/frozen paths,
  user-data locations, plugin/config locations, Luna assets, and launcher data.
- Kept legacy GUI path helpers as compatibility delegates.

### Phase 2 — UI dispatcher

Commit: `c0d7a57 Extract UI thread dispatcher`

- Added `ui_dispatcher.py` with FIFO background-to-Tk dispatch, callback error
  isolation, and shutdown rejection.
- The user live-tested this phase successfully.

### Phase 3 — Plugin lifecycle

Commit: `0e1fe6e Extract plugin lifecycle manager`

- Added `plugin_manager.py`, moving plugin discovery/load/unload, activation,
  configuration persistence, and transactional settings behavior behind a
  manager while preserving coordinator-facing properties.

### Phase 4 — Plugin pipeline and concatenation regression

Commits:

- `91c8c70 Extract plugin pipeline coordinator`
- `df38fe5 Handle cumulative speaker prefixes`

- Added `plugin_pipeline.py` for output routing/pipeline coordination.
- Fixed real Hook Concatenation behavior discovered in live testing: a
  cumulative prefix such as `タイラミア` is now split into the existing prefix
  `タイラ` plus new speaker `ミア`, avoiding the invented speaker “Tairamia.”
- Added regression coverage. User live-tested the correction successfully.

### Phase 5 — Game profiles

Commit: `a1854b7 Extract game profile store`

- Added `game_profile_store.py` for game identity and profile persistence.
- Confirmed a deliberate current limitation: Hook Concatenation role assignments
  are plugin-global settings in `plugins_config.json`; they are not per-game
  profile fields. Normal selected/manual hooks remain profile-saveable.

### Phase 6 — Process discovery

Commit: `c44b3fb Extract process discovery service`

- Added `process_service.py` for process filtering, discovery, architecture,
  and safe executable launch behavior.
- User live-tested this phase successfully.

### Phase 7 — Hook registry

Commit: `92fb403 Extract thread-safe hook registry`

- Added `hook_registry.py` as the owner of hook records, snapshots, text
  history, and monotonic event-sequence markers.
- GUI compatibility properties (`hooks`, `hooks_lock`, and
  `hook_event_sequence`) continue to delegate to the registry.

### Phase 8 — Luna controller

Commit: `b1c1033 Extract Luna controller`

- Added `luna_controller.py` with pure Luna output-line parsing,
  generation-safe session ownership, stdout/stderr/watch workers,
  asynchronous detach, and UI-dispatched domain callbacks.
- Maintained reader-thread pipeline routing and UI-thread-only widget work.
- Added direct tests for parser behavior, stale sessions/exits, unexpected
  exits, and non-blocking detach.
- User completed the required live test successfully.

### Phase 9 — Dialog and main-window views

Commits:

- `55c17ed Extract plugin settings dialog`
- `a3b9602 Extract profile manager dialog`
- `0547c6c Extract hook help dialog`
- `74fa1d3 Extract main window view`

New modules:

- `plugin_settings_dialog.py`: settings form, dynamic providers, comboboxes,
  scroll routing, and overlay live preview. Includes helper tests.
- `profile_manager_dialog.py`: profile list, delete/clear confirmations, count
  updates, and launch callback. Process monitoring/auto-attach remains in the
  coordinator.
- `hook_help_dialog.py`: read-only Hook Code Syntax Help window.
- `main_window.py`: header, scrollable shell, scrollbar lifecycle, responsive
  selection row, and section placement. Section builders remain coordinator
  callbacks for now.

The initial main-window commit had a startup ordering bug: wheel routing ran
before `self.canvas` was published. It was fixed and the commit amended to
`74fa1d3`; source startup was then live-tested successfully.

The tray implementation was reviewed and intentionally left with the
coordinator: it is modest in size and tightly coupled to shutdown ownership,
so a separate adapter would not currently reduce risk.

### Phase 10 — Composition root

Commit: `afcdc74 Finalize application composition root`

- Moved the `SugoiHookGUI` class into `sugoihook_app.py`.
- Reduced `SugoiHook_gui.py` to bootstrap imports/constants/logging, a
  compatibility export, and `main()`.
- Preserved early source/packaged logging while making module ownership one-way:
  `SugoiHook_gui.py` imports the coordinator, and `sugoihook_app.py` now imports
  its dependencies explicitly without importing or copying bootstrap globals.
- Added compatibility regression tests asserting both direct coordinator import
  and `SugoiHook_gui.SugoiHookGUI is sugoihook_app.SugoiHookGUI`.
- Updated README file structure for the newly extracted modules.

An initial circular import appeared only when the launcher was run as a script
(`__main__`). The temporary bootstrap-global bridge was subsequently removed;
the application coordinator is now directly importable in either order, while
the compatibility launcher still reached “SugoiHookGUI constructed” and the Tk
main loop successfully in the source-launch smoke test.

## Validation status

Latest automated validation on `afcdc74`:

- `python -m unittest discover -s tests -v`: **74 tests passed**.
- Explicit top-level-module plus `plugins`, `deep_translator`, and `tests`
  compilation passed. (Do not use literal `*.py` with PowerShell;
  `compileall` reports it as a non-expandable path.)
- `python -m pip check`: passed.
- `git diff --check`: passed.
- Source startup smoke test: passed after the circular-import fix.

Expected test logging includes intentionally malformed persistence fixtures and
an intentionally invalid test plugin; these are expected regression-test logs,
not suite failures.

## Remaining gates before merge

The restructure code is complete, but the final plan gates have **not yet been
run after Phase 10**:

1. Full user source workflow:
   - normal and `--debug` launch;
   - compact/full geometry and every collapse section;
   - plugin toggle/reorder/configure/reload;
   - overlay and dictionary behavior;
   - launch/attach/manual hook;
   - Hook Concatenation + OpenAI;
   - detach/reattach/unexpected exit;
   - tray and clean shutdown.
2. Release onefile build and smoke test:

   ```powershell
   $env:NO_PAUSE = '1'
   .\build.bat
   ```

   Verify `SugoiHook_builds\SugoiHook.exe`, configs, dictionaries, shortcuts,
   runtime logging, and both shared/build-venv `pip check` results. A debug
   standalone build is only needed if diagnostics are required.
3. Commit this handoff report, then merge the branch to `main` only after the
   source and package gates pass.

## Known cleanup note

Several earlier extraction phases intentionally left renamed private
`*_legacy` GUI methods behind after routing production behavior through the
new module. They are unreachable compatibility residue, not active execution
paths. Do not delete them during a live/package gate; delete them only in a
separate, search-backed cleanup commit after confirming no compatibility caller
depends on them.
