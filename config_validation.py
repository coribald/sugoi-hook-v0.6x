def is_valid_plugins_config(config):
    return (
        isinstance(config.get('active_plugins', []), list)
        and all(isinstance(name, str) for name in config.get('active_plugins', []))
        and isinstance(config.get('plugin_order', []), list)
        and all(isinstance(name, str) for name in config.get('plugin_order', []))
        and isinstance(config.get('plugin_settings', {}), dict)
        and all(
            isinstance(name, str) and isinstance(settings, dict)
            for name, settings in config.get('plugin_settings', {}).items()
        )
        and (config.get('window_geometry') is None or isinstance(config.get('window_geometry'), str))
        and (config.get('compact_window_geometry') is None or isinstance(config.get('compact_window_geometry'), str))
    )


def is_valid_game_profiles(config):
    return all(
        isinstance(game_id, str) and isinstance(profile, dict)
        for game_id, profile in config.items()
    )
