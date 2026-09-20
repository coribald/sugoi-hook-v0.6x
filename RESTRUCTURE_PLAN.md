# Sugoi Hook GUI Restructure Plan

## Purpose

This document is the execution handoff for decomposing `SugoiHook_gui.py`
without changing observable application behavior. It is written so a new agent
can start from `main`, understand the current constraints, and implement the
work incrementally without needing the preceding chat history.

This is a migration plan, not permission for a ground-up rewrite. Each phase
must leave the application runnable and independently reversible.

## Baseline

- Platform: Windows 10/11.
- Python: 3.11+.
- Current branch at review time: `main`.
- Reviewed commit: `d52067a` (`Harden lifecycle error handling`).
- `origin/main` and local `main` both pointed to `d52067a` during this review.
- `SugoiHook_gui.py`: 5,139 lines, 156 methods on `SugoiHookGUI`.
- Existing regression suite: 53 tests across 10 test modules.
- Latest source behavior has been live-tested successfully.
- A release onefile build succeeded before the final dictionary and lifecycle
  commits. Phase 0 must build the current `main` once to establish the packaged
  baseline for the exact reviewed commit.
- The worktree was clean before this plan was added.

## Product and Behavior Context

Sugoi Hook is a Windows/Tkinter application that:

1. Lists and launches/attaches to game processes.
2. Starts the Luna CLI for the selected process.
3. Discovers text hooks and lets the user select or manually add one.
4. Runs hook events through ordered plugins.
5. Performs primarily Japanese-to-English translation through the OpenAI
   plugin, with Deep Translator as a lower-priority fallback.
6. Displays output, copies cleaned untranslated text, and optionally displays
   an overlay with native Jitendex lookup.

Important user preferences and established decisions:

- Runtime and timing correctness have priority over cleanup or elegance.
- OpenAI is the primary translation path; Deep Translator is secondary.
- The existing plaintext API-key setting in the gitignored
  `plugins_config.json` is accepted and is not part of this restructure.
- Development iteration is source-first. Build only at specified package
  gates rather than after every small extraction.
- The application and release build are Luna-only.
- No UI redesign is included. Visual layout and interaction semantics must
  remain stable unless the user separately requests changes.

Read `context.md` and `README.md` before implementing any phase. They document
the current hook timing, output pipeline, overlay, runtime path, and build
behavior.

## Review Findings

### 1. `SugoiHookGUI` owns too many unrelated responsibilities

The class currently owns:

- runtime path detection and application startup;
- Tk construction, themes, layout, dialogs, status, and tray behavior;
- a cross-thread UI callback queue;
- plugin discovery, dynamic module ownership, activation, settings, ordering,
  persistence, and pipeline orchestration;
- game-profile persistence and automatic hook recall;
- process discovery, filtering, architecture checks, icons, and launching;
- Luna process creation, commands, readers, exit handling, and detach;
- hook registry state, hook routing, and Hook Concatenation integration;
- output queuing, translation orchestration, rendering, clipboard, and stats;
- shutdown coordination.

The largest individual methods are UI/dialog builders, but the highest-risk
coupling is shared state between Luna, hooks, plugins, profiles, and Tk.

### 2. Several stable boundaries already exist

Do not fold these modules back into the GUI or redesign them during the
decomposition:

- `output_pipeline.py`: ordered stateful preprocessing plus latest-pending
  translation behavior and invalidation epochs.
- `luna_session.py`: generation-bound Luna process lifetime and serialized
  command writes.
- `json_persistence.py`: atomic JSON replacement and backup recovery.
- `dictionary_backend.py`: Jitendex indexing and lookup.

These modules are tested and should be treated as foundations.

### 3. `plugin.app` is a compatibility boundary

Every loaded plugin currently receives `plugin.app = self`, where `self` is
the `SugoiHookGUI` instance. Built-in plugins use the following host surface:

- `base_path`
- `user_data_dir`
- `report_config_issue(...)`
- `run_on_ui_thread(...)`
- `get_hooks_snapshot()`
- `mark_hook_event_processed(...)`
- `submit_output_processing(...)`
- `schedule_pipeline_callback(...)`
- `cancel_pipeline_callback(...)`

Hook Concatenation also has fallback reads of `app.hooks`.

Unknown user plugins may depend on more. Therefore:

- Keep assigning the application facade to `plugin.app` throughout this
  restructure.
- Keep the existing method names and important public fields available on that
  facade through delegation/properties.
- Do not replace `plugin.app` with a narrower host object in this project
  unless a separately scoped, versioned plugin API migration is approved.
- A `PluginHost` `Protocol` may document the supported built-in surface, but it
  must not change the runtime object yet.

### 4. Thread ownership is implicit

Current worker activity includes the output pipeline, Luna stdout/stderr/watch
threads, launch monitors, dictionary lookups, timers, and the tray thread.
Tk widgets must remain owned by the Tk main thread. The existing
`run_on_ui_thread` queue is the correct cross-thread route and should become an
explicit component before Luna or UI extraction.

### 5. Persistence is transactional but still coupled to UI state

Plugin config contains active filenames, ordering, per-plugin settings, and
main-window geometry. Game profiles have a separate file. Overlay config is
owned by the overlay plugin. Existing file names, JSON shapes, backup behavior,
and source/packaged locations are compatibility constraints.

### 6. Tests protect core timing, but construction seams are weak

The current tests cover output ordering, Hook Concatenation, Luna session
generation, persistence rollback, dynamic plugin modules, dictionary lookups,
launch quoting, builds, and shutdown. Many tests create
`SugoiHookGUI.__new__(SugoiHookGUI)` and manually inject fields. This is useful
characterization but also shows that services and state ownership are not yet
explicit.

Coverage gaps relevant to the restructure include:

- runtime path resolution across source, Nuitka, and frozen modes;
- Luna stdout parsing as a pure input-to-event operation;
- hook registry mutations independent of Tk widgets;
- game ID/profile matching independent of dialogs;
- process filtering independent of Treeview and ImageTk;
- UI dispatcher shutdown and callback ordering;
- plugin discovery failure while restoring an active plugin.

## Non-Negotiable Invariants

Every phase must preserve all of the following:

1. Every raw hook event reaches stateful preprocessing in arrival order.
2. At most one translation request is active; only the newest pending
   translation is retained.
3. A successful in-flight translation is delivered unless reset/detach
   invalidated its epoch.
4. Translator input and clipboard input remain aligned after shared
   preprocessing.
5. Hook Concatenation timing, internal hook markers, burst recovery, prefix
   timeout, and selector resolution do not change.
6. Stale Luna reader/exit threads cannot mutate a newer attachment.
7. Luna stdout and stderr continue to be drained.
8. Detach remains asynchronous from the Tk thread.
9. Background threads never read or mutate Tk widgets directly.
10. Plugin activation/settings/profile mutations retain their rollback behavior
    when persistence fails.
11. Plugin reload/shutdown calls `on_disable()` and removes only tracked dynamic
    modules.
12. Dictionary lookup remains off the UI thread and stale lookup results remain
    suppressed.
13. Existing config file names, locations, keys, and backup semantics remain
    compatible.
14. Source and packaged runtime paths remain distinct in the same way they are
    today.
15. `python SugoiHook_gui.py` and both build scripts remain valid entry paths.
16. The release remains Luna-only and includes all current runtime assets.

## Target Ownership

Prefer flat modules during this migration. The repository already uses that
layout, and avoiding a new package hierarchy reduces Nuitka and dynamic-import
risk. Names may be adjusted if implementation reveals a conflict, but ownership
must remain clear.

| Proposed module | Owns | Must not own |
| --- | --- | --- |
| `runtime_context.py` | Source/compiled path resolution and immutable runtime paths | Tk widgets, plugin state |
| `ui_dispatcher.py` | Thread-safe callback queue and Tk polling lifecycle | Domain state |
| `plugin_manager.py` | Plugin discovery, module identity, lifecycle, order, settings state, config persistence | Settings-dialog widgets, text transformation |
| `plugin_pipeline.py` | Pre/translation/post plugin orchestration and prepared output data | Worker queues, Tk rendering |
| `game_profile_store.py` | Profile validation, load/save/commit, pure game identity helpers | Profile-manager dialog, process launching |
| `process_service.py` | Process enumeration/filter metadata, architecture, direct launch | Treeview rows, `PhotoImage` objects |
| `hook_registry.py` | Thread-safe hook records, event sequence, snapshots, processed/submitted markers | Tk rows, Luna process lifetime |
| `luna_controller.py` | Luna session generation, CLI process/readers/watch/detach, line parsing, domain callbacks | Tk widgets, plugin execution |
| `main_window.py` | Main Tk widget construction and view-only operations | Persistence, subprocesses, plugin execution |
| `plugin_settings_dialog.py` | Plugin settings editor and overlay preview UI | Plugin discovery/lifecycle ownership |
| `profile_manager_dialog.py` | Profile manager UI | Profile persistence implementation |
| `sugoihook_app.py` | Composition root/coordinator and backward-compatible plugin host facade | Low-level implementations owned above |
| `SugoiHook_gui.py` | Thin compatibility entrypoint and exported `SugoiHookGUI` name | Domain implementation |

The final file names are less important than single ownership. Do not create
generic `utils.py`, `helpers.py`, or a catch-all controller.

## Migration Rules

- One phase per commit. Do not mix extraction with feature changes.
- Move behavior before improving it. Preserve method bodies initially, then
  simplify only after tests demonstrate equivalence.
- Keep compatibility delegates on `SugoiHookGUI` until all internal and plugin
  callers are migrated and a later cleanup is explicitly approved.
- Do not maintain two writable copies of the same state. When ownership moves,
  the old facade must delegate to the new owner rather than mirror it.
- Prefer constructor injection for paths, callbacks, clocks, process factories,
  and loggers so tests do not require Tk or real subprocesses.
- Domain modules must not import `tkinter`.
- UI modules must not call `subprocess.Popen`, access SQLite, perform HTTP, or
  mutate worker-owned state.
- Avoid broad renames. Preserve public method names during extraction.
- Do not change dependency versions or add third-party dependencies.
- Do not rewrite Hook Concatenation, `OutputPipeline`, `LunaProcessSession`, or
  dictionary algorithms as part of this work.
- Do not change styling, geometry defaults, text labels, shortcuts, config
  locations, or packaged asset layout.
- Never inspect or print the API key from local config.

## Execution Phases

### Phase 0 — Establish the exact baseline and characterization seams

Goal: prove the reviewed commit and package before structural edits.

Tasks:

1. Start a dedicated restructure branch from `main` at or after `d52067a`.
2. Confirm a clean worktree and record `git rev-parse HEAD` in the handoff notes.
3. Run the full tests, compile check, and `pip check` using the commands in the
   validation section below.
4. Run one release build from current `main` with `NO_PAUSE=1`. Confirm runtime
   configs are preserved and `SugoiHook_builds/SugoiHook.exe` exists.
5. Add characterization tests for:
   - source/compiled/frozen runtime path decisions;
   - UI dispatcher ordering, exception isolation, and shutdown rejection;
   - process exclusion rules;
   - game identity from executable path and size;
   - representative Luna stdout lines: console/status, new hook, and hook text;
   - active-plugin restoration failure during discovery.
6. Tests added here should describe current behavior. Do not “fix” unrelated
   behavior in this phase.

Done when:

- Current source and packaged builds are baselined.
- Characterization tests fail only if a later extraction changes behavior.

Suggested commit: `Characterize GUI decomposition boundaries`.

### Phase 1 — Extract runtime paths

Goal: remove environment/path decisions from the GUI constructor without
changing startup logging or build behavior.

Tasks:

1. Add an immutable `RuntimeContext`/`RuntimePaths` dataclass containing at
   least launcher, bundle base, user-data directory, bundled/user plugin
   directories, Luna x86/x64 executables, and logo path.
2. Make resolution functions accept injectable `argv`, executable, module path,
   and frozen/compiled flags for deterministic tests.
3. Keep the existing functions in `SugoiHook_gui.py` as temporary delegates if
   tests or plugins import them.
4. Inject the resolved context into `SugoiHookGUI`; do not let later services
   rediscover paths independently.
5. Leave early stream redirection/log initialization behavior unchanged in this
   phase. It has import-time/package implications and should move only at the
   final composition phase.

Package gate: run a release build because Nuitka/source paths are affected.

Suggested commit: `Extract runtime path context`.

### Phase 2 — Extract the UI dispatcher

Goal: make thread-to-Tk ownership explicit before moving controllers.

Tasks:

1. Add `UIThreadDispatcher` with:
   - `dispatch(callback, *args)`;
   - a lock-protected FIFO queue;
   - a Tk-thread `drain()` poll scheduled with `root.after`;
   - `stop()` that rejects new callbacks and clears pending work;
   - per-callback exception logging without stopping later callbacks.
2. `SugoiHookGUI.run_on_ui_thread` remains as a delegate for plugins and old
   callers.
3. Replace direct ownership of `ui_callback_lock`, `ui_callback_queue`, and
   `ui_callback_shutdown` with the dispatcher.
4. Preserve immediate execution when dispatch is called on the main thread.
5. Integrate dispatcher shutdown before root destruction.

Done when no non-UI module needs to know about Tk’s polling mechanism.

Suggested commit: `Extract UI thread dispatcher`.

### Phase 3 — Extract plugin lifecycle and persistence

Goal: establish one owner for plugin instances and configuration while leaving
all plugin UI in place.

Tasks:

1. Add `PluginManager` owning:
   - `plugins`;
   - `active_plugins`;
   - `plugin_order`;
   - `plugin_settings`;
   - plugin file paths and dynamic module names;
   - discovery/load/unload/reload;
   - enable/disable rollback;
   - setting application/rollback;
   - plugin-config load/save.
2. Inject paths, the application host facade, output-processing lock, config
   issue reporter, and user notification callback.
3. Keep dynamic modules under `sugoihook_dynamic_plugins` and preserve the
   current path-hashed module naming.
4. Preserve filename-based config keys and built-in/user plugin precedence.
5. Add compatibility properties/delegates on `SugoiHookGUI`. Do not use aliased
   mutable lists that can silently diverge when one side rebinds a list.
6. Leave `configure_selected_plugin`, plugin Treeview operations, and dialog
   construction in the GUI for now.
7. Keep `plugin.app` pointing at the application facade.

Tests:

- Move/expand plugin loading and persistence tests to target `PluginManager`
  directly.
- Retain at least one facade test proving old GUI method/property access reaches
  the manager.
- Cover failed startup activation, failed enable/disable compensation, reload,
  replacement by filename, and dynamic module cleanup.

Live gate:

- Toggle, reorder, configure, reload, and replace a plugin.
- Confirm overlay enable/disable does not leave a stale window.

Suggested commit: `Extract plugin lifecycle manager`.

### Phase 4 — Extract plugin pipeline orchestration

Goal: separate text transformation policy from the GUI and from the worker
queue in `output_pipeline.py`.

Tasks:

1. Add `PluginPipeline`/`PluginPipelineCoordinator` owning:
   - pre-translation plugin execution;
   - translation eligibility and execution;
   - post-translation plugins;
   - clipboard/display alignment;
   - translation-context remembrance;
   - pipeline diagnostics.
2. Inject the `PluginManager`/read-only registry view and logging callback.
3. Preserve the current prepared-output dictionary shape initially. A dataclass
   conversion is optional only after equivalence tests pass and must be a
   separate commit.
4. Keep `OutputPipeline` unchanged as the worker/ordering primitive.
5. Keep the old GUI pipeline method names as delegates because existing tests
   and possibly plugins may call them.
6. Keep Hook Concatenation’s callback scheduling and front-of-queue emit
   semantics unchanged.

Tests:

- Port all `test_gui_pipeline.py` cases to the new coordinator.
- Add exceptions for pre-, translation-, and post-stage plugins.
- Retain a facade integration test with `OutputPipeline`.

Live gate:

- Rapidly advance dialogue with OpenAI enabled.
- Confirm display, clipboard, rolling context, and concatenated speaker/dialogue
  behavior match the baseline logs.

Suggested commit: `Extract plugin pipeline coordinator`.

### Phase 5 — Extract game-profile storage

Goal: isolate durable profile state without moving profile dialogs or auto-hook
timers yet.

Tasks:

1. Add `GameProfileStore` owning validation, load, save, atomic commit, and the
   in-memory profile dictionary.
2. Extract a pure identity helper based on normalized executable path and file
   size. Keep the exact current ID format so existing profiles still match.
3. Inject the profile path and issue reporter.
4. Keep auto-hook selection/orchestration on the application facade during this
   phase; it should consume the store rather than own persistence.
5. Leave the profile manager dialog in the GUI until the UI phase.

Tests:

- Existing profile rollback test should target the store.
- Add compatibility tests for an existing profile fixture and malformed backup
  recovery.

Suggested commit: `Extract game profile store`.

### Phase 6 — Extract process services

Goal: separate process/domain operations from Treeview and ImageTk rendering.

Tasks:

1. Add a plain `ProcessInfo` dataclass and `ProcessService` for:
   - process iteration and accessible metadata;
   - exclusion/filter rules;
   - visible-window checks;
   - architecture detection;
   - direct executable launch using `Popen([path])`.
2. Return plain data only. Keep icon-to-`PhotoImage` conversion and Treeview
   insertion on the UI side because Tk image objects are UI-thread-owned.
3. Inject psutil/Win32 adapters or callable seams for unit tests.
4. Preserve current fail-open/fail-closed decisions for inaccessible processes.
5. Do not broaden executable launch semantics or reintroduce a shell.

Tests:

- Keep the path-with-spaces launch test.
- Add exclusion and architecture fallback cases without querying real system
  processes.

Suggested commit: `Extract process discovery service`.

### Phase 7 — Extract the hook registry

Goal: establish one thread-safe owner for hook records before moving Luna I/O.

Tasks:

1. Add `HookRegistry` owning:
   - hook dictionary and lock;
   - global event sequence;
   - add/update text samples;
   - immutable/safe snapshots;
   - submitted/processed event sequence markers;
   - clear/reset.
2. Keep hook selection as application/UI state, not registry state.
3. Preserve the current hook record keys used by GUI and Hook Concatenation,
   including function/context information, text samples, and pipeline markers.
4. Keep `SugoiHookGUI.get_hooks_snapshot`, `mark_hook_event_submitted`, and
   `mark_hook_event_processed` as delegates for plugin compatibility.
5. Remove direct dictionary mutations only after every call site uses the
   registry.

Tests:

- Snapshot isolation.
- Concurrent-safe add/update/clear behavior.
- Event sequence ordering and processed/submitted markers.
- Existing Hook Concatenation integration through the facade.

Suggested commit: `Extract thread-safe hook registry`.

### Phase 8 — Extract the Luna controller

Goal: make one non-Tk component own Luna process/session lifetime and parsing.
This is the highest-risk non-UI phase.

Tasks:

1. Add typed/domain events for at least:
   - console/status output;
   - hook discovered/metadata updated;
   - hook text received;
   - session exited;
   - attach failed.
2. Extract Luna stdout parsing into a pure parser covered by Phase 0 fixtures.
3. Add `LunaController` owning:
   - generation and current `LunaProcessSession`;
   - CLI creation and command sending;
   - stdout/stderr/watch threads;
   - expected versus unexpected exit;
   - asynchronous detach/termination;
   - exit callbacks.
4. Inject the process factory, executable paths, `HookRegistry`, logger, and
   event callbacks.
5. Emit domain callbacks through `UIThreadDispatcher` before any UI mutation.
6. Keep hook routing into `OutputPipeline` in the application coordinator. The
   controller reports hook text; it does not execute plugins.
7. Remove `cli_process` as independent writable state. If compatibility needs
   it temporarily, expose it as a read-only property of the current session.
8. Preserve command strings, creation flags, encodings, line interpretation,
   delays, and user-facing messages.

Tests:

- Port all Luna session/generation tests to the controller.
- Parser fixtures for real representative output lines.
- Stale stdout, stderr, and exit events cannot affect a newer session.
- Detach returns immediately to the caller and completion is dispatched once.
- Attach failure cannot leave a half-current session.

Mandatory live/package gate:

- Attach, discover hooks, select/manual hook, detach, reattach, unexpected Luna
  exit, and application quit.
- Repeat with Hook Concatenation and OpenAI enabled.
- Produce a debug standalone build if logs are needed, followed by release.

Suggested commit: `Extract Luna controller`.

### Phase 9 — Split dialogs and the main view

Goal: remove Tk construction from the application coordinator without changing
the UI.

Order:

1. `plugin_settings_dialog.py` (currently the largest single method).
2. `profile_manager_dialog.py`.
3. Hook help/context dialogs.
4. Main section/card construction and geometry/layout handling in
   `main_window.py`.
5. Tray view adapter if it remains large enough to justify a separate module.

Rules:

- Preserve widget labels, bindings, geometry, fonts, colors, and ordering.
- Views receive callbacks and state snapshots; they do not reach into service
  dictionaries or persist config directly.
- Keep widget objects owned by the view. The coordinator may expose temporary
  compatibility properties during migration.
- Extract one dialog/section per commit. Do not move all 2,000+ UI lines in one
  diff.
- Do not introduce a UI framework, declarative toolkit, or theme redesign.

Tests/live gates:

- Unit-test conversion/validation helpers separated from widgets.
- Source-run every dialog after its extraction.
- Verify mouse-wheel routing, combobox behavior, live overlay preview, compact
  geometry, and section collapse behavior.
- Run the complete user workflow after main-view extraction.

Suggested commits:

- `Extract plugin settings dialog`
- `Extract profile manager dialog`
- `Extract main window view`

### Phase 10 — Finalize the composition root and compatibility entrypoint

Goal: make ownership obvious while preserving all launch/build entrypoints.

Tasks:

1. Move the application coordinator to `sugoihook_app.py`.
2. Keep the name `SugoiHookGUI` available from `SugoiHook_gui.py` for existing
   imports/tests. It may be a direct re-export.
3. Reduce `SugoiHook_gui.py` to early bootstrap/logging, imports, `main()`, and
   the compatibility export.
4. Move early logging only if it can still capture failures before Tk and heavy
   Windows imports. Preserve source console tee and packaged log behavior.
5. Update build compile checks and README file structure for every new module.
6. Remove compatibility delegates only when repository searches prove no
   internal caller uses them, and retain the plugin host surface listed above.
7. Delete no legacy code until the equivalent service/view is wired and tested.

Final gates:

- Full automated validation.
- Full source live checklist.
- Debug standalone build if diagnostics are needed.
- Release onefile build and live smoke test.
- Confirm configs, dictionary cache, shortcuts, logs, and assets are in the
  expected locations.

Suggested commit: `Finalize application composition root`.

## Validation Commands

Run after every phase:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q SugoiHook_gui.py *.py plugins deep_translator tests
python -m pip check
git diff --check
git status --short --branch
```

If PowerShell does not expand `*.py` as expected for `compileall`, list the new
top-level modules explicitly. A successful check must not contain “Can't list”.

At package gates:

```powershell
$env:NO_PAUSE = "1"
.\build.bat
```

Confirm:

- `SugoiHook_builds/SugoiHook.exe` exists;
- `plugins_config.json` and `overlay_config.json` were preserved without
  printing their contents;
- dictionaries are beside the onefile build as expected;
- normal/debug shortcuts point at the new executable;
- shared Python still passes `python -m pip check`;
- `.build-venv\Scripts\python.exe -m pip check` also passes.

## Live Test Checklist

Use source mode first:

1. Launch normally and with `--debug`.
2. Expand/collapse process, hook, and plugin sections; verify compact/full
   geometry restoration.
3. Toggle, reorder, configure, and reload plugins.
4. Enable the overlay; modify previewable settings; hide/show/disable it.
5. Use dictionary single- and double-click lookup; click rapidly and confirm an
   older result cannot replace a newer result.
6. Launch an executable whose path contains spaces or attach to an existing
   process.
7. Discover hooks, select a hook, and attach a manual hook.
8. Configure Hook Concatenation using numeric, function-label, and context-info
   selectors where available.
9. Advance text rapidly with OpenAI enabled; compare translator input,
   displayed output, and clipboard content.
10. Clear output and confirm stateful plugins reset.
11. Save and restore a game profile; exercise auto-hook retry/failure behavior.
12. Detach, reattach, force/observe an unexpected Luna exit if practical, then
    quit through both the main window and tray.
13. Inspect `sugoihook-runtime.log` for new exceptions or stale-generation
    activity. Do not include API keys in reports.

## Risk and Stop Conditions

Stop the current phase and fix or revert it before proceeding if any of these
occur:

- a worker thread calls Tk directly;
- duplicate writable state exists in both facade and service;
- a compatibility delegate changes timing or acquires locks in a new order;
- Hook Concatenation output order/timing changes;
- translator and clipboard inputs diverge;
- detach or quit blocks the UI;
- stale session/output/dictionary work reaches the UI;
- config is rewritten with missing keys or at a different path;
- dynamic plugin modules leak or collide with vendored packages;
- a build depends on globally installed packages;
- a phase requires changing plugin API, config schema, or UI design to finish.

The last case requires rescoping with the user rather than quietly broadening
the restructure.

## Definition of Done

The restructure is complete when:

- each mutable domain state has one documented owner;
- non-UI modules do not import Tkinter;
- all worker-to-UI traffic uses `UIThreadDispatcher`;
- `SugoiHookGUI` is a coordinator/compatibility facade rather than the
  implementation site for every subsystem;
- `SugoiHook_gui.py` is a thin launch/compatibility module;
- the built-in plugin host surface remains available;
- all prior and new regression tests pass;
- the complete source live checklist passes;
- release packaging succeeds from the isolated build environment;
- README/context/build metadata reflect the final module layout;
- commits remain phase-sized and can be reverted independently.

Do not use line count as the sole success metric. Clear ownership, stable
behavior, testability, and safe rollback are the actual goals.

## Terra Handoff Instructions

When handing this work to Terra, provide this exact starting scope:

> Work from `main` and read `RESTRUCTURE_PLAN.md`, `context.md`, and `README.md`
> completely before editing. Confirm the current commit and clean worktree.
> Execute the restructure one numbered phase at a time, beginning with Phase 0.
> Keep each phase in a separate commit and run the required validation before
> starting the next phase. Preserve all non-negotiable invariants and the
> `plugin.app` compatibility facade. Do not combine extraction with feature,
> UI, dependency, config-schema, or timing changes. At every mandatory live or
> package gate, stop and report the exact commit, tests, risks, and manual checks
> needed rather than assuming the gate passed. If implementation requires a
> scope change, document why and request direction before proceeding.

Terra should report after each phase:

- commit hash and summary;
- files added/moved and new state owner;
- compatibility delegates retained;
- automated validation results;
- live/package checks completed or awaiting the user;
- remaining risks and the next phase.

