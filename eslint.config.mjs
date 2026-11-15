// ESLint plano (C-1): solo errores reales (no-undef, no-unused-vars), nada de estilo.
// El front son scripts clásicos sin módulos: lo que un archivo declara en su nivel superior (function, const, let,
// class, var) o cuelga de window es global para los demás. En vez de una lista a mano que se queda vieja, se leen
// esas declaraciones de los propios archivos; un nombre que nadie declara sigue siendo un error de no-undef.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import globals from "globals";

const TOP_LEVEL = /^(?:async\s+)?(?:function\*?\s+([A-Za-z_$][\w$]*)|(?:const|let|var|class)\s+([A-Za-z_$][\w$]*))/gm;
const ON_WINDOW = /\b(?:window|self)\.([A-Za-z_$][\w$]*)\s*=(?!=)/g; // la extensión usa self.Panel
const ASSIGN_WINDOW = /Object\.assign\(window,\s*\{([^}]*)\}\s*\)/g; // ui.js: Object.assign(window, { icon, api, ... })

function declaredGlobals(dirs) {
    const names = {};
    for (const dir of dirs) {
        for (const file of readdirSync(dir).filter((f) => f.endsWith(".js") && f !== "sw.js")) {
            const src = readFileSync(join(dir, file), "utf8");
            for (const m of src.matchAll(TOP_LEVEL)) names[m[1] || m[2]] = "writable";
            for (const m of src.matchAll(ON_WINDOW)) names[m[1]] = "writable";
            for (const m of src.matchAll(ASSIGN_WINDOW)) {
                for (const key of m[1].split(",").map((k) => k.split(":")[0].trim()).filter(Boolean)) names[key] = "writable";
            }
        }
    }
    return names;
}

// Librerías de static/vendor que se cargan con <script> (las define cada una en window)
const VENDOR = { marked: "readonly", DOMPurify: "readonly", vis: "readonly", katex: "readonly",
    renderMathInElement: "readonly", hljs: "readonly" };

const FRONT = ["static/js", "comidas/static/js", "estudio/static"];

const ERRORS_ONLY = {
    "no-undef": "error",
    // Lo de nivel superior lo usan otros archivos o las plantillas (data-call): solo se miran las variables locales
    "no-unused-vars": ["error", { vars: "local", args: "none", caughtErrors: "none" }],
};

export default [
    { ignores: ["static/vendor/**", "node_modules/**", "venv/**", "dist/**", "backups/**", "data/**"] },
    {
        files: FRONT.map((d) => `${d}/**/*.js`),
        ignores: ["static/js/sw.js"],
        languageOptions: {
            ecmaVersion: 2024,
            sourceType: "script",
            globals: { ...globals.browser, ...VENDOR, ...declaredGlobals(FRONT) },
        },
        rules: ERRORS_ONLY,
    },
    {
        files: ["static/js/sw.js"],
        // __VERSION__ y __PRECACHE__ los sustituye core/pwa.py al servir el archivo
        languageOptions: { ecmaVersion: 2024, sourceType: "script",
            globals: { ...globals.serviceworker, __VERSION__: "readonly", __PRECACHE__: "readonly" } },
        rules: ERRORS_ONLY,
    },
    {
        files: ["EXTENSION PANEL/**/*.js"],
        languageOptions: {
            ecmaVersion: 2024,
            sourceType: "script",
            // content y cloneInto: API de los content scripts de Firefox (autologin.js)
            globals: { ...globals.browser, ...globals.webextensions, content: "readonly", cloneInto: "readonly", ...declaredGlobals(["EXTENSION PANEL", "EXTENSION PANEL/lib"]) },
        },
        rules: ERRORS_ONLY,
    },
    {
        files: ["scripts/**/*.mjs", "eslint.config.mjs"],
        languageOptions: { ecmaVersion: 2024, sourceType: "module", globals: globals.node },
        rules: ERRORS_ONLY,
    },
];
