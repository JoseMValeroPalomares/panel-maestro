"""
Temas del Panel: paletas de color (una por tema). Las usan `scripts/themes.py` (genera static/css/themes.css)
y las plantillas (selector de tema en Ajustes). Catppuccin Mocha es el tema por defecto.
"""

TILES = ("notas", "inbox", "tareas", "baul", "grafo", "comidas", "estudio", "gestion", "backups", "buscar", "rutinas", "economia")

# nombre visible, oscuro?, colores. Las claves de tiles siguen el orden de TILES.
THEMES = {
    "mocha": dict(label="Catppuccin Mocha", dark=True,
        bg="#181825", elev="#1e1e2e", elev2="#262637", sunken="#11111b", neutral=(147, 153, 178), sep=(108, 112, 134),
        text="#cdd6f4", text2="#bac2de", text3="#a6adc8", accent="#89b4fa", accent_fill="#89b4fa", accent_hover="#b4befe",
        on_accent="#11111b", danger="#f38ba8", on_danger="#11111b", warning="#fab387", success="#a6e3a1",
        draft="#9399b2", index="#cba6f7", tile_fg="#11111b",
        tiles=("#b4befe", "#fab387", "#94e2d5", "#f9e2af", "#89b4fa", "#a6e3a1", "#cba6f7", "#9399b2", "#7f849c", "#74c7ec", "#f5c2e7", "#89dceb"),
        cats=("#b4befe", "#89b4fa", "#a6e3a1", "#fab387", "#cba6f7", "#94e2d5", "#f9e2af", "#f38ba8", "#74c7ec", "#f2cdcd")),
    "latte": dict(label="Catppuccin Latte", dark=False,
        bg="#e6e9ef", elev="#eff1f5", elev2="#e9ecf2", sunken="#dce0e8", neutral=(124, 127, 147), sep=(108, 111, 133),
        text="#4c4f69", text2="#5c5f77", text3="#5c5f77", accent="#1d5bd6", accent_fill="#1e66f5", accent_hover="#1a56d0",
        on_accent="#ffffff", danger="#d20f39", on_danger="#ffffff", warning="#b34700", success="#2b7a1d",
        draft="#6c6f85", index="#8839ef", tile_fg="#ffffff",
        tiles=("#7287fd", "#fe640b", "#179299", "#e64553", "#1e66f5", "#40a02b", "#8839ef", "#6c6f85", "#5c5f77", "#7c7f93", "#c0379a", "#0f7fa8"),
        cats=("#7287fd", "#1e66f5", "#40a02b", "#fe640b", "#8839ef", "#179299", "#df8e1d", "#d20f39", "#209fb5", "#dd7878")),
    "light": dict(label="Claro", dark=False,
        bg="#f2f2f5", elev="#ffffff", elev2="#f7f7f9", sunken="#e9e9ee", neutral=(118, 118, 128), sep=(60, 60, 67),
        text="#1d1d1f", text2="#5c5c63", text3="#66666d", accent="#0066cc", accent_fill="#0071e3", accent_hover="#0077ed",
        on_accent="#ffffff", danger="#c4271b", on_danger="#ffffff", warning="#a35200", success="#1c7c34",
        draft="#66666d", index="#5148c4", tile_fg="#ffffff",
        tiles=("#5856d6", "#d0480f", "#0e7c86", "#8e6a3e", "#0071e3", "#248a3d", "#8944ab", "#5f6368", "#3a3a3c", "#6e6e75", "#c2185b", "#0b7a99"),
        cats=("#5856d6", "#0071e3", "#248a3d", "#c93400", "#8944ab", "#0e7c86", "#a35200", "#d70015", "#5f6368", "#8e6a3e")),
    "dark": dict(label="Oscuro", dark=True,
        bg="#111113", elev="#1c1c1f", elev2="#242428", sunken="#0c0c0e", neutral=(118, 118, 128), sep=(84, 84, 88),
        text="#f5f5f7", text2="#b8b8bf", text3="#9d9da5", accent="#4aa3ff", accent_fill="#0a6fd6", accent_hover="#0a63c0",
        on_accent="#ffffff", danger="#ff6b61", on_danger="#1c1c1f", warning="#ffb340", success="#4cd964",
        draft="#9d9da5", index="#a19bff", tile_fg="#ffffff",
        tiles=("#5856d6", "#d0480f", "#0e7c86", "#8e6a3e", "#0071e3", "#248a3d", "#8944ab", "#5f6368", "#48484c", "#6e6e75", "#c2185b", "#0b7a99"),
        cats=("#7d7bff", "#4aa3ff", "#4cd964", "#ff8a4c", "#c77dff", "#40c8d0", "#ffb340", "#ff6b61", "#9d9da5", "#c9a06a")),
    "nord": dict(label="Nord", dark=True,
        bg="#2e3440", elev="#3b4252", elev2="#434c5e", sunken="#272c36", neutral=(136, 150, 175), sep=(97, 110, 136),
        text="#eceff4", text2="#e5e9f0", text3="#d8dee9", accent="#88c0d0", accent_fill="#88c0d0", accent_hover="#8fbcbb",
        on_accent="#2e3440", danger="#ec9aa1", on_danger="#2e3440", warning="#ebcb8b", success="#a3be8c",
        draft="#a5b1c6", index="#b48ead", tile_fg="#2e3440",
        tiles=("#81a1c1", "#d08770", "#8fbcbb", "#ebcb8b", "#88c0d0", "#a3be8c", "#b48ead", "#a5b1c6", "#8b97ad", "#a6b5cc", "#d8a7c7", "#9fd0d8"),
        cats=("#88c0d0", "#81a1c1", "#a3be8c", "#d08770", "#b48ead", "#8fbcbb", "#ebcb8b", "#ec9aa1", "#5e81ac", "#eceff4")),
    "dracula": dict(label="Dracula", dark=True,
        bg="#21222c", elev="#282a36", elev2="#343746", sunken="#191a21", neutral=(98, 114, 164), sep=(98, 114, 164),
        text="#f8f8f2", text2="#e2e2dc", text3="#b6b9d0", accent="#bd93f9", accent_fill="#bd93f9", accent_hover="#d6b4fc",
        on_accent="#21222c", danger="#ff6e6e", on_danger="#21222c", warning="#ffb86c", success="#50fa7b",
        draft="#9ea8c7", index="#ff79c6", tile_fg="#21222c",
        tiles=("#bd93f9", "#ffb86c", "#8be9fd", "#f1fa8c", "#a9b6e8", "#50fa7b", "#ff79c6", "#9ea8c7", "#8590b4", "#c3a5f9", "#ffb2e6", "#9580ff"),
        cats=("#bd93f9", "#8be9fd", "#50fa7b", "#ffb86c", "#ff79c6", "#f1fa8c", "#ff6e6e", "#a9b6e8", "#6272a4", "#f8f8f2")),
    "gruvbox": dict(label="Gruvbox", dark=True,
        bg="#1d2021", elev="#282828", elev2="#32302f", sunken="#141617", neutral=(168, 153, 132), sep=(146, 131, 116),
        text="#ebdbb2", text2="#d5c4a1", text3="#bdae93", accent="#83a598", accent_fill="#83a598", accent_hover="#8ec07c",
        on_accent="#1d2021", danger="#fb4934", on_danger="#1d2021", warning="#fe8019", success="#b8bb26",
        draft="#a89984", index="#d3869b", tile_fg="#1d2021",
        tiles=("#83a598", "#fe8019", "#8ec07c", "#fabd2f", "#7fa2a3", "#b8bb26", "#d3869b", "#a89984", "#928374", "#689d6a", "#ea6962", "#89b482"),
        cats=("#83a598", "#8ec07c", "#b8bb26", "#fe8019", "#d3869b", "#fabd2f", "#fb4934", "#689d6a", "#458588", "#ebdbb2")),
    "tokyo": dict(label="Tokyo Night", dark=True,
        bg="#16161e", elev="#1a1b26", elev2="#24283b", sunken="#101014", neutral=(169, 177, 214), sep=(86, 95, 137),
        text="#c0caf5", text2="#a9b1d6", text3="#9aa5ce", accent="#7aa2f7", accent_fill="#7aa2f7", accent_hover="#7dcfff",
        on_accent="#16161e", danger="#f7768e", on_danger="#16161e", warning="#ff9e64", success="#9ece6a",
        draft="#8a93b8", index="#bb9af7", tile_fg="#16161e",
        tiles=("#bb9af7", "#ff9e64", "#73daca", "#e0af68", "#7aa2f7", "#9ece6a", "#9d7cd8", "#8a93b8", "#737aa2", "#7dcfff", "#f7768e", "#2ac3de"),
        cats=("#7aa2f7", "#bb9af7", "#9ece6a", "#ff9e64", "#73daca", "#e0af68", "#f7768e", "#7dcfff", "#2ac3de", "#c0caf5")),
}
DEFAULT = "mocha"

# Para el selector: (clave, nombre visible); «Sistema» sigue al equipo (Claro u Oscuro)
CHOICES = [("system", "Sistema")] + [(k, t["label"]) for k, t in THEMES.items()]


def preview(name: str) -> dict:
    """Colores de la muestra del selector (Sistema se muestra mitad claro, mitad oscuro)."""
    t = THEMES.get(name)
    if not t:
        a, b = THEMES["light"], THEMES["dark"]
        return {"bg": f"linear-gradient(135deg, {a['bg']} 50%, {b['bg']} 50%)", "elev": a["elev"], "accent": a["accent_fill"], "text": a["text"]}
    return {"bg": t["bg"], "elev": t["elev"], "accent": t["accent_fill"], "text": t["text"]}
