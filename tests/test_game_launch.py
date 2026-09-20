import unittest
from pathlib import Path
from unittest.mock import patch

import SugoiHook_gui as gui


class GameLaunchTests(unittest.TestCase):
    def test_launch_executable_passes_space_containing_path_without_shell(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        executable = Path(r"C:\Games\Visual Novel\game.exe")

        with patch.object(gui.subprocess, "Popen") as popen:
            app.launch_executable(executable)

        popen.assert_called_once_with([str(executable)])


if __name__ == "__main__":
    unittest.main()
