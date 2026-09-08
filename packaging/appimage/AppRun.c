/* MusicSync MIT launcher: no shell, private environment confined to the app. */
#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char root[PATH_MAX], program[PATH_MAX], key[128];
    ssize_t n = readlink("/proc/self/exe", root, sizeof(root) - 1);
    if (n < 0 || n >= sizeof(root) - 1) { perror("MusicSync launcher"); return 1; }
    root[n] = 0;
    char *slash = strrchr(root, '/');
    if (!slash) return 1;
    *slash = 0;
    const char *vars[] = {"LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH",
        "PYTHONHOME", "PYTHONPATH", "GIO_MODULE_DIR", "GIO_EXTRA_MODULES",
        "GSETTINGS_SCHEMA_DIR", NULL};
    for (int i = 0; vars[i]; ++i) {
        snprintf(key, sizeof(key), "MUSICSYNC_HOST_%s", vars[i]);
        const char *value = getenv(vars[i]);
        if (value) setenv(key, value, 1); else unsetenv(key);
        unsetenv(vars[i]);
    }
    setenv("MUSICSYNC_HOST_ENV_SAVED", "1", 1);
    setenv("APPDIR", root, 1);
    // Confine loadable GIO code to the private GLib build. External user GTK,
    // Qt and XDG appearance settings remain inherited; no theme is selected here.
    if (snprintf(program, sizeof(program), "%s/usr/lib/musicsync/gio/modules", root) >= sizeof(program)) return 1;
    setenv("GIO_MODULE_DIR", program, 1);
    if (snprintf(program, sizeof(program), "%s/usr/share/musicsync/gtk-schemas", root) >= sizeof(program)) return 1;
    setenv("GSETTINGS_SCHEMA_DIR", program, 1);
    if (snprintf(program, sizeof(program), "%s/usr/lib/musicsync/musicsync.bin", root) >= sizeof(program)) return 1;
    argv[0] = program;
    execv(program, argv);
    perror("MusicSync standalone runtime");
    return 1;
}
