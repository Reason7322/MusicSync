[app]
title = MusicSync
project_dir = /work/project
input_file = /work/project/main.py
exec_directory = /work/frozen
project_file =
icon = /work/project/musicsync/icons/io.github.reason7322.MusicSync.svg

[python]
python_path = /opt/build-python/bin/python
packages = Nuitka==4.2.1

[qt]
qml_files =
excluded_qml_plugins =
modules = Core,Gui,Widgets,Svg
plugins = platforms,imageformats,iconengines,platformthemes,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration

[nuitka]
mode = standalone
extra_args = --noinclude-qt-translations --include-package=musicsync --include-package-data=musicsync --output-filename=musicsync.bin --report=/work/nuitka-report.xml --jobs=8 --assume-yes-for-downloads --file-reference-choice=runtime --lto=no
